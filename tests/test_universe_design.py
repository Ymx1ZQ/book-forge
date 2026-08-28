import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_universe_design", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROLE_VARIANTS = {name: spec[1] for name, spec in load_module().ROLE_SPECS.items()}


def clean_proposal():
    return {
        "kernel": [{"id": "LAW-0001", "summary": "Memory cannot be manufactured."}],
        "eras": [{"id": "ERA-0001", "name": "Afterlight", "order": 1, "when": "2087", "material": ["archive skiffs on the canals", "no radio below the waterline", "credit is a favour owed"]}],
        "events": [{"id": "EVT-0001", "era": "ERA-0001", "order": 1, "summary": "The archive opens."}],
        "places": [{"id": "PLC-0001", "name": "Glass Harbor", "summary": "A tidal archive."}],
        "factions": [{"id": "FAC-0001", "name": "Keepers", "summary": "Guard inherited memories."}],
        "characters": [{"id": "CHR-0001", "name": "Mara", "summary": "A skeptical diver.", "voice": "Precise and dry."}],
        "themes": ["memory and consent"],
        "style": {"tense": "past", "person": "third-limited"},
        "continuity_material": {"CNT-0001": ["EVT-0001"]},
        "book_local": {},
        "unresolved_questions": ["Who first sealed the archive?"],
    }


class DesignProvider:
    def __init__(self, proposal, audit=None):
        self.proposal = proposal
        self.audit = audit if audit is not None else {"findings": []}
        self.calls = []

    def __call__(self, role, envelope, attempt_dir):
        self.calls.append(role)
        if role.startswith("advisor-") or role == "chorus-synthesizer":
            # Chorus advisory — return empty findings for deterministic tests.
            variant = "high"
            return {
                "text": json.dumps({"findings": [], "suggestions": []}),
                "provider": "openrouter",
                "model": MODEL,
                "variant": variant,
                "session_id": f"ses-{len(self.calls)}",
                "tokens": {"input": envelope["estimated_input_tokens"], "output": 100},
                "cost": 0.001,
                "latency_ms": 5,
                "finish": "stop",
            }
        value = self.proposal if role == "designer" else self.audit
        variant = ROLE_VARIANTS[role]
        return {
            "text": json.dumps(value),
            "provider": "openrouter",
            "model": MODEL,
            "variant": variant,
            "session_id": f"ses-{len(self.calls)}",
            "tokens": {"input": envelope["estimated_input_tokens"], "output": 300},
            "cost": 0.001,
            "latency_ms": 5,
            "finish": "stop",
        }


class UniverseDesignTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        # Disable chorus for deterministic design-audit tests (M33).
        import json
        cfg = json.loads((self.project / "book-forge.yaml").read_text())
        cfg["chorus"] = {"enabled": False, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER}
        (self.project / "book-forge.yaml").write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n")

    def test_schedules_two_bounded_roles_and_promotes_clean_design(self):
        tasks = self.bf.schedule_universe_design(self.project, guided_answers={"tone": "hopeful"})
        self.assertEqual([(task["role"], task["deps"]) for task in tasks], [("designer", []), ("canon-auditor", ["DESIGN-UNI-0001"])])

        report = self.bf.apply_universe_design(self.project, clean_proposal())
        self.assertEqual(report["state"], "design_clean")
        self.assertTrue((self.project / "universe/canon/characters/CHR-0001.md").is_file())
        index = self.bf.rebuild_indexes(self.project)
        self.assertIn("CHR-0001#voice", index["blocks"])
        self.assertIn("LAW-0001#summary", index["blocks"])
        audit = json.loads((self.project / "universe/design-audit.json").read_text())
        self.assertEqual(audit["blocking"], [])

    def test_rejects_contradiction_without_mutating_design(self):
        proposal = clean_proposal()
        proposal["events"].append({"id": "EVT-0002", "era": "ERA-9999", "order": 1, "summary": "Impossible"})
        before = (self.project / "universe/kernel.md").read_bytes()
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.apply_universe_design(self.project, proposal)
        self.assertEqual((self.project / "universe/kernel.md").read_bytes(), before)
        self.assertFalse((self.project / "universe/design.json").exists())

    def test_executes_designer_and_independent_auditor_with_receipts(self):
        provider = DesignProvider(clean_proposal())
        result = self.bf.execute_universe_design(self.project, provider=provider)
        self.assertEqual(result["state"], "design_clean")
        self.assertEqual(result["calls"], len(self.bf.UNIVERSE_DESIGN_CHUNKS) + 1)
        self.assertEqual(provider.calls, ["designer"] * len(self.bf.UNIVERSE_DESIGN_CHUNKS) + ["canon-auditor"])
        report = self.bf.telemetry_report(self.project, strict=True)
        self.assertEqual(report["calls"]["with_receipts"], 2)

    def test_binds_audit_evidence_to_helper_computed_hashes(self):
        provider = DesignProvider(
            clean_proposal(),
            audit={"findings": [{
                "id": "F-0001",
                "severity": "note",
                "issue": "Seeded note.",
                "evidence": [
                    {"location": "proposal.places.PLC-0001", "hash": "0" * 64},
                    {"location": "proposal.eras.ERA-0001"},
                ],
                "repair_scope": ["PLC-0001"],
            }]},
        )
        result = self.bf.execute_universe_design(self.project, provider=provider)
        self.assertEqual(result["state"], "design_clean")
        audit = json.loads((self.project / "universe/design-audit.json").read_text())
        evidence = audit["findings"][0]["evidence"]
        place = self.project / "universe/canon/places/PLC-0001.md"
        eras = self.project / "universe/timeline/eras.yaml"
        self.assertEqual(evidence[0]["hash"], self.bf._file_hash(place))
        self.assertEqual(evidence[0]["location"], "proposal.places.PLC-0001")
        self.assertEqual(evidence[1]["hash"], self.bf._file_hash(eras))

    def test_unresolvable_audit_evidence_blocks_the_design(self):
        provider = DesignProvider(
            clean_proposal(),
            audit={"findings": [{
                "id": "F-0001",
                "severity": "note",
                "issue": "Seeded note.",
                "evidence": [{"location": "nowhere/not-a-file.md"}],
                "repair_scope": ["PLC-0001"],
            }]},
        )
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.execute_universe_design(self.project, provider=provider)

    def test_resumes_audit_alone_when_design_already_promoted(self):
        bad = DesignProvider(
            clean_proposal(),
            audit={"findings": [{
                "id": "F-0001",
                "severity": "note",
                "issue": "Seeded note.",
                "evidence": [{"location": "nowhere/not-a-file.md"}],
                "repair_scope": ["PLC-0001"],
            }]},
        )
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.execute_universe_design(self.project, provider=bad)
        plan = self.bf._load_plan(self.project)
        design_task = next(row for row in plan["tasks"] if row["id"] == "DESIGN-UNI-0001")
        self.assertEqual(design_task["state"], "succeeded")

        self.bf.resume_run(self.project, blocked_resolutions={"AUDIT-UNI-0001": "retry"})
        rerun = DesignProvider(clean_proposal(), audit={"findings": []})
        result = self.bf.execute_universe_design(self.project, provider=rerun)
        self.assertEqual(result["state"], "design_clean")
        self.assertEqual(rerun.calls, ["canon-auditor"])


    def test_promotes_designer_row_keys_into_summary_blocks(self):
        proposal = clean_proposal()
        proposal["kernel"] = [{"id": "LAW-0001", "name": "Salt Law", "law": "The salt preserves every secret."}]
        proposal["places"] = [{"id": "PLC-0001", "name": "Glass Harbor", "invariant": "A tidal archive."}]
        proposal["characters"] = [{"id": "CHR-0001", "name": "Mara", "invariant": "A skeptical diver.", "voice": "Precise and dry."}]
        report = self.bf.apply_universe_design(self.project, proposal)
        self.assertEqual(report["state"], "design_clean")
        law = (self.project / "universe/canon/topics/LAW-0001.md").read_text()
        place = (self.project / "universe/canon/places/PLC-0001.md").read_text()
        character = (self.project / "universe/canon/characters/CHR-0001.md").read_text()
        self.assertIn("The salt preserves every secret.", law)
        self.assertIn("A tidal archive.", place)
        self.assertIn("A skeptical diver.", character)
        self.assertIn("Precise and dry.", character)
        self.assertNotRegex(law + place + character, r"<!-- bf:block summary -->\s*\n\s*\n")

    def test_summary_key_wins_over_fallback_keys(self):
        row = {"id": "PLC-0001", "name": "Glass Harbor", "summary": "Explicit summary.", "invariant": "Fallback invariant.", "law": "Fallback law."}
        markdown = self.bf._canon_markdown(row, continuity="CNT-0001")
        self.assertIn("Explicit summary.", markdown)
        self.assertNotIn("Fallback invariant.", markdown)
        self.assertNotIn("Fallback law.", markdown)

    def test_blocks_contentless_canon_rows(self):
        proposal = clean_proposal()
        proposal["characters"].append({"id": "CHR-0002", "name": "Hollow"})
        before = (self.project / "universe/kernel.md").read_bytes()
        with self.assertRaises(self.bf.BookForgeError) as raised:
            self.bf.apply_universe_design(self.project, proposal)
        self.assertIn("canon-row.content-missing", str(raised.exception))
        self.assertEqual((self.project / "universe/kernel.md").read_bytes(), before)
        self.assertFalse((self.project / "universe/design.json").exists())

    def test_normalizes_id_keyed_dict_proposal_shapes(self):
        proposal = {
            "kernel": {"LAW-0001": "The salt preserves every secret."},
            "eras": {"ERA-0001": {"name": "Afterlight", "order": 1, "when": "2087", "material": ["skiffs", "no radio", "credit is a favour"]}},
            "events": {"EVT-0001": {"era": "ERA-0001", "order": 1, "name": "The archive opens.", "invariant": "The archive opens."}},
            "places": {"PLC-0001": {"name": "Glass Harbor", "invariant": "A tidal archive."}},
            "factions": {"FAC-0001": {"name": "Keepers", "invariant": "Guard inherited memories."}},
            "characters": {"CHR-0001": {"label": "Mara", "role": "Diver", "fact": "A skeptical diver.", "invariant": "Never trusts the archive."}},
            "themes": ["memory and consent"],
            "style": {"tense": "past", "person": "third-limited"},
            "continuity_material": {"CNT-0001": ["LAW-0001"]},
            "book_local": {},
            "unresolved_questions": [],
        }
        normalized = self.bf._normalize_universe_proposal(proposal)
        self.assertEqual(normalized["kernel"], [{"id": "LAW-0001", "summary": "The salt preserves every secret."}])
        self.assertEqual(normalized["characters"][0]["id"], "CHR-0001")
        self.assertEqual(normalized["characters"][0]["name"], "Mara")
        report = self.bf.apply_universe_design(self.project, normalized)
        self.assertEqual(report["state"], "design_clean")
        law = (self.project / "universe/canon/topics/LAW-0001.md").read_text()
        character = (self.project / "universe/canon/characters/CHR-0001.md").read_text()
        self.assertIn("The salt preserves every secret.", law)
        self.assertIn("# Mara", character)
        self.assertIn("A skeptical diver. Never trusts the archive.", character)

    def test_row_summary_joins_fact_invariant_law_in_order(self):
        row = {"fact": "Fact text.", "invariant": "Invariant text.", "law": "Law text."}
        self.assertEqual(self.bf._row_summary(row), "Fact text. Invariant text. Law text.")
        self.assertEqual(self.bf._row_summary({"summary": "Explicit.", "fact": "Dropped."}), "Explicit.")
        self.assertEqual(self.bf._row_summary({"invariant": "Only invariant."}), "Only invariant.")
        self.assertEqual(self.bf._row_summary({}), "")

    def test_row_summary_accepts_statement_and_description_keys(self):
        self.assertEqual(self.bf._row_summary({"statement": "Statement text."}), "Statement text.")
        self.assertEqual(self.bf._row_summary({"description": "Description text."}), "Description text.")
        self.assertEqual(
            self.bf._row_summary({"fact": "Fact.", "description": "Description.", "statement": "Statement."}),
            "Fact. Description. Statement.",
        )

    def test_envelope_pins_row_shape_for_the_designer(self):
        provider = DesignProvider(clean_proposal())
        self.bf.execute_universe_design(self.project, provider=provider)
        import glob
        envelopes = sorted(glob.glob(str(self.project / ".book-forge/runs/*/attempts/ATT-*/envelope-*.json")))
        designer = next(json.loads(Path(path).read_text()) for path in reversed(envelopes) if json.loads(Path(path).read_text())["role"] == "designer")
        required = designer["task"]["required_output"]
        self.assertEqual(required["kernel"], "LAW-#### rows: {id, name, summary}")
        self.assertIn("CHR-#### rows: {id, name, tier, summary", required["characters"])
        self.assertIn("tiered cast (M4)", required["characters"])
        self.assertIn("total named characters >= 22", required["characters"])
        self.assertIn("tier", required["places"])
        self.assertIn("EVT-#### rows: {id, name, summary, era, order}", required["events"])
        self.assertIn("stable ERA-#### id", required["events"])

    def test_promotes_detail_blocks_from_canon_rows(self):
        proposal = clean_proposal()
        proposal["characters"][0]["voice"] = "Precise and dry."
        proposal["characters"][0]["appearance"] = "Pale, dark-haired, salt-stained jacket."
        proposal["characters"][0]["past"] = "Left Hamburg after a broken engagement."
        proposal["places"][0]["sensory"] = "Salt glare, gull cries, diesel from the boats."
        self.bf.apply_universe_design(self.project, proposal)
        character = (self.project / "universe/canon/characters/CHR-0001.md").read_text()
        place = (self.project / "universe/canon/places/PLC-0001.md").read_text()
        for expected in ("<!-- bf:block voice -->\nPrecise and dry.", "<!-- bf:block appearance -->\nPale, dark-haired, salt-stained jacket.", "<!-- bf:block past -->\nLeft Hamburg after a broken engagement."):
            self.assertIn(expected, character)
        self.assertIn("<!-- bf:block sensory -->\nSalt glare, gull cries, diesel from the boats.", place)
        index = self.bf.rebuild_indexes(self.project)
        for block in ("CHR-0001#voice", "CHR-0001#appearance", "CHR-0001#past", "PLC-0001#sensory"):
            self.assertIn(block, index["blocks"])

    def test_refresh_re_runs_design_cycle_and_sweeps_orphaned_canon(self):
        first = DesignProvider(clean_proposal())
        self.bf.execute_universe_design(self.project, provider=first)
        self.assertTrue((self.project / "universe/canon/places/PLC-0001.md").is_file())
        self.assertEqual(first.calls, ["designer"] * len(self.bf.UNIVERSE_DESIGN_CHUNKS) + ["canon-auditor"])

        enriched = clean_proposal()
        enriched["characters"].append({"id": "CHR-0002", "name": "Serafina", "summary": "The bar owner who sees everything.", "voice": "Rapid Barese dialect, warm and cutting."})
        enriched["places"].pop(0)
        second = DesignProvider(enriched)
        result = self.bf.execute_universe_design(self.project, provider=second, refresh=True)
        self.assertEqual(result["state"], "design_clean")
        self.assertEqual(result["calls"], len(self.bf.UNIVERSE_DESIGN_CHUNKS) + 1)
        self.assertTrue((self.project / "universe/canon/characters/CHR-0002.md").is_file())
        self.assertFalse((self.project / "universe/canon/places/PLC-0001.md").exists())
        kept = (self.project / "universe/canon/characters/CHR-0001.md").read_text()
        self.assertIn("A skeptical diver.", kept)
        plan = self.bf._load_plan(self.project)
        for task_id in ("DESIGN-UNI-0001", "AUDIT-UNI-0001"):
            task = next(row for row in plan["tasks"] if row["id"] == task_id)
            self.assertEqual(task["state"], "succeeded")
        for attempt in plan["attempts"]:
            if attempt["state"] == "orphaned":
                self.assertEqual(attempt["resolution"], "refresh")

    def test_refresh_refused_once_books_exist(self):
        self.bf.add_book(self.project, "First Novel")
        with self.assertRaises(self.bf.BookForgeError) as raised:
            self.bf.execute_universe_design(self.project, provider=DesignProvider(clean_proposal()), refresh=True)
        self.assertIn("books exist", str(raised.exception))

    def test_plain_design_still_short_circuits_when_clean(self):
        first = DesignProvider(clean_proposal())
        self.bf.execute_universe_design(self.project, provider=first)
        again = DesignProvider(clean_proposal())
        result = self.bf.execute_universe_design(self.project, provider=again)
        self.assertEqual(result["calls"], 0)
        self.assertEqual(again.calls, [])

    def test_retry_capsule_carries_validation_failure_as_repair(self):
        # A validation-blocked attempt must feed the failure back into the
        # designer's retry capsule so the model can tighten word counts/tiers.
        bad = clean_proposal()
        bad["kernel"] = [{"id": "LAW-0001"}]  # no summary -> canon-row.content-missing blocking
        provider = DesignProvider(bad)
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.execute_universe_design(self.project, provider=provider)
        self.bf.resume_run(self.project, blocked_resolutions={"DESIGN-UNI-0001": "retry"})
        retry = DesignProvider(clean_proposal())
        self.bf.execute_universe_design(self.project, provider=retry)
        import glob
        envelopes = sorted(glob.glob(str(self.project / ".book-forge/runs/*/attempts/ATT-*/envelope-*.json")))
        designer = next(json.loads(Path(path).read_text()) for path in reversed(envelopes) if json.loads(Path(path).read_text())["role"] == "designer")
        repair = designer["task"].get("repair")
        self.assertIsNotNone(repair, "retry envelope must carry repair context")
        self.assertIn("validation_error", repair)
        self.assertIn("kernel", str(repair["validation_error"]))


if __name__ == "__main__":
    unittest.main()
