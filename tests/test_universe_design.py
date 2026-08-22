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
        "eras": [{"id": "ERA-0001", "name": "Afterlight", "order": 1}],
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
        self.assertEqual(result["calls"], 2)
        self.assertEqual(provider.calls, ["designer", "canon-auditor"])
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


if __name__ == "__main__":
    unittest.main()
