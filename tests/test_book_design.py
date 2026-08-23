import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_book_design", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROLE_VARIANTS = {name: spec[1] for name, spec in load_module().ROLE_SPECS.items()}


def proposal(obligation=None):
    chapters = [
        {"id": "CH-0001", "order": 1, "pov": "CHR-0001", "beats": ["A choice opens the conflict"], "plants": ["signal"], "reveals": [], "target_words": 1800, "imports": ["UNI-0001#kernel"], "pivotal": "opener"},
        {"id": "CH-0002", "order": 2, "pov": "CHR-0001", "beats": ["The choice costs an ally"], "plants": [], "reveals": ["signal"], "target_words": 2000, "imports": ["UNI-0001#kernel"], "pivotal": None},
        {"id": "CH-0003", "order": 3, "pov": "CHR-0001", "beats": ["Agency resolves the dilemma"], "plants": [], "reveals": [], "target_words": 2200, "imports": ["UNI-0001#kernel"], "pivotal": "finale"},
    ]
    if obligation:
        chapters[1]["obligations"] = [obligation]
    return {
        "premise": "A diver must decide whether memory can be owned.",
        "entry_state": {"CHR-0001": "isolated"},
        "arc": ["refusal", "cost", "choice"],
        "exit_boundary": {"CHR-0001": "committed"},
        "chapters": chapters,
    }


class DesignProvider:
    def __init__(self, value, audit=None):
        self.value = value
        self.audit = audit if audit is not None else {"findings": []}
        self.calls = []

    def __call__(self, role, envelope, attempt_dir):
        self.calls.append(role)
        if role.startswith("advisor-") or role == "chorus-synthesizer":
            return {
                "text": json.dumps({"findings": [], "suggestions": []}),
                "provider": "openrouter",
                "model": MODEL,
                "variant": "high",
                "session_id": f"ses-{len(self.calls)}",
                "tokens": {"input": envelope["estimated_input_tokens"], "output": 100},
                "cost": 0.001,
                "latency_ms": 5,
                "finish": "stop",
            }
        payload = self.value if role == "designer" else self.audit
        return {
            "text": json.dumps(payload),
            "provider": "openrouter",
            "model": MODEL,
            "variant": ROLE_VARIANTS[role],
            "session_id": f"ses-{len(self.calls)}",
            "tokens": {"input": envelope["estimated_input_tokens"], "output": 300},
            "cost": 0.001,
            "latency_ms": 5,
            "finish": "stop",
        }


class BookDesignTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        # Disable chorus for deterministic tests.
        import json as _json
        _cfg = _json.loads((self.project / "book-forge.yaml").read_text())
        _cfg["chorus"] = {"enabled": False, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER}
        (self.project / "book-forge.yaml").write_text(_json.dumps(_cfg, indent=2, sort_keys=True) + "\n")

    def brief(self, book):
        path = self.project / f"books/{book}/book-brief.json"
        path.write_text(json.dumps({"schema": 1, "premise": "A diver must decide.", "characters": ["Mara"], "plot": ["dive"], "tone": "quiet"}))
        return path

    def test_designs_unrelated_sequel_and_parallel_books_with_obligations(self):
        a = self.bf.add_book(self.project, "A")["id"]
        b = self.bf.add_book(self.project, "B")["id"]
        c = self.bf.add_book(self.project, "C")["id"]
        sequel = self.bf.add_relation(self.project, "sequel_of", [b, a], obligations=["Carry the signal"])
        parallel = self.bf.add_relation(self.project, "parallel_to", [a, c], obligations=["Share the eclipse"])

        self.assertEqual(self.bf.apply_book_design(self.project, b, proposal(sequel["obligations"][0]["id"]))["state"], "design_clean")
        self.assertEqual(self.bf.apply_book_design(self.project, c, proposal(parallel["obligations"][0]["id"]))["state"], "design_clean")
        unrelated = self.bf.add_book(self.project, "D")["id"]
        self.assertEqual(self.bf.apply_book_design(self.project, unrelated, proposal())["state"], "design_clean")

        outline = json.loads((self.project / f"books/{b}/outline.yaml").read_text())
        self.assertEqual([row["id"] for row in outline["chapters"]], ["CH-0001", "CH-0002", "CH-0003"])
        contract = json.loads((self.project / f"books/{b}/chapters/CH-0002.json").read_text())
        envelope = self.bf.build_envelope(
            self.project, role="writer", task_capsule=contract, imports=contract["imports"],
            state={}, tools=[], max_output_tokens=5000,
        )
        self.assertLessEqual(envelope["estimated_input_tokens"], 12000)

    def test_rejects_missing_relation_target_and_bad_chapter_order(self):
        a = self.bf.add_book(self.project, "A")["id"]
        b = self.bf.add_book(self.project, "B")["id"]
        relation = self.bf.add_relation(self.project, "sequel_of", [b, a], obligations=["Carry the signal"])
        bad = proposal()
        bad["chapters"][1]["order"] = 1
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.apply_book_design(self.project, b, bad)
        self.assertIn(relation["obligations"][0]["id"], str(caught.exception))
        self.assertFalse((self.project / f"books/{b}/chapters").exists())

    def test_executes_book_design_as_two_paid_receipted_calls(self):
        book = self.bf.add_book(self.project, "Agentic Book")["id"]
        self.brief(book)
        provider = DesignProvider(proposal())
        result = self.bf.execute_book_design(self.project, book, provider=provider)
        self.assertEqual(result["state"], "design_clean")
        self.assertEqual(result["calls"], 2)
        self.assertEqual(provider.calls, ["designer", "canon-auditor"])
        self.assertTrue((self.project / f"books/{book}/chapters/CH-0001.json").is_file())

    def test_binds_book_scoped_proposal_evidence_to_helper_hashes(self):
        book = self.bf.add_book(self.project, "Bound")["id"]
        self.brief(book)
        provider = DesignProvider(
            proposal(),
            audit={"findings": [{
                "id": "F-0001",
                "severity": "note",
                "issue": "Seeded note.",
                "evidence": [
                    {"location": f"{book}#proposal/turns/TURN-0001", "hash": "0" * 64},
                    {"location": f"{book}#proposal/chapters/CH-0001/beats/BEAT-0001"},
                    {"location": f"{book}#proposal/chapters/CH-0001"},
                ],
                "repair_scope": [book],
            }]},
        )
        result = self.bf.execute_book_design(self.project, book, provider=provider)
        self.assertEqual(result["state"], "design_clean")
        audit = json.loads((self.project / f"books/{book}/design-audit.json").read_text())
        evidence = audit["findings"][0]["evidence"]
        design_md = self.project / f"books/{book}/design.md"
        chapter = self.project / f"books/{book}/chapters/CH-0001.json"
        self.assertEqual(evidence[0]["hash"], self.bf._file_hash(design_md))
        self.assertEqual(evidence[0]["location"], f"{book}#proposal/turns/TURN-0001")
        self.assertEqual(evidence[1]["hash"], self.bf._file_hash(chapter))
        self.assertEqual(evidence[2]["hash"], self.bf._file_hash(chapter))

    def test_binds_kernel_block_evidence_to_its_file(self):
        book = self.bf.add_book(self.project, "KernelBound")["id"]
        self.brief(book)
        provider = DesignProvider(
            proposal(),
            audit={"findings": [{
                "id": "F-0001",
                "severity": "note",
                "issue": "Seeded note.",
                "evidence": [{"location": "UNI-0001#kernel"}],
                "repair_scope": [book],
            }]},
        )
        result = self.bf.execute_book_design(self.project, book, provider=provider)
        self.assertEqual(result["state"], "design_clean")
        audit = json.loads((self.project / f"books/{book}/design-audit.json").read_text())
        kernel = self.project / "universe/kernel.md"
        self.assertEqual(audit["findings"][0]["evidence"][0]["hash"], self.bf._file_hash(kernel))

    def test_binds_envelope_scope_evidence_locations(self):
        book = self.bf.add_book(self.project, "EnvelopeBound")["id"]
        self.brief(book)
        provider = DesignProvider(
            proposal(),
            audit={"findings": [{
                "id": "F-0001",
                "severity": "note",
                "issue": "Seeded note.",
                "evidence": [
                    {"location": "task.design_scope.proposal.premise"},
                    {"location": "task.design_scope.chapters.CH-0001.beats.BEAT-0001.cause"},
                    {"location": "task.design_scope.exit_boundary.sleeper"},
                ],
                "repair_scope": [book],
            }]},
        )
        result = self.bf.execute_book_design(self.project, book, provider=provider)
        self.assertEqual(result["state"], "design_clean")
        audit = json.loads((self.project / f"books/{book}/design-audit.json").read_text())
        evidence = audit["findings"][0]["evidence"]
        design_md = self.project / f"books/{book}/design.md"
        chapter = self.project / f"books/{book}/chapters/CH-0001.json"
        reader_state = self.project / f"books/{book}/reader-state.md"
        self.assertEqual(evidence[0]["hash"], self.bf._file_hash(design_md))
        self.assertEqual(evidence[1]["hash"], self.bf._file_hash(chapter))
        self.assertEqual(evidence[2]["hash"], self.bf._file_hash(reader_state))

    def test_foreign_book_scoped_evidence_still_fails_closed(self):
        book = self.bf.add_book(self.project, "Closed")["id"]
        self.brief(book)
        provider = DesignProvider(
            proposal(),
            audit={"findings": [{
                "id": "F-0001",
                "severity": "note",
                "issue": "Seeded note.",
                "evidence": [{"location": "BOOK-0009#proposal/turns/TURN-0001"}],
                "repair_scope": [book],
            }]},
        )
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.execute_book_design(self.project, book, provider=provider)

    def test_resumes_book_audit_alone_when_design_already_promoted(self):
        book = self.bf.add_book(self.project, "Resumed")["id"]
        self.brief(book)
        bad = DesignProvider(
            proposal(),
            audit={"findings": [{
                "id": "F-0001",
                "severity": "note",
                "issue": "Seeded note.",
                "evidence": [{"location": "nowhere/not-a-file.md"}],
                "repair_scope": [book],
            }]},
        )
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.execute_book_design(self.project, book, provider=bad)
        plan = self.bf._load_plan(self.project)
        design_task = next(row for row in plan["tasks"] if row["id"] == f"DESIGN-{book}")
        self.assertEqual(design_task["state"], "succeeded")

        self.bf.resume_run(self.project, blocked_resolutions={f"AUDIT-{book}": "retry"})
        rerun = DesignProvider(proposal(), audit={"findings": []})
        result = self.bf.execute_book_design(self.project, book, provider=rerun)
        self.assertEqual(result["state"], "design_clean")
        self.assertEqual(rerun.calls, ["canon-auditor"])
        audit = json.loads((self.project / f"books/{book}/design-audit.json").read_text())
        self.assertEqual(audit["findings"], [])


    def test_missing_author_brief_fails_closed_before_any_provider_call(self):
        book = self.bf.add_book(self.project, "NoBrief")["id"]
        provider = DesignProvider(proposal())
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.execute_book_design(self.project, book, provider=provider)
        self.assertIn("book-brief.json", str(caught.exception))
        self.assertEqual(provider.calls, [])

    def test_book_designer_envelope_carries_brief_and_full_canon_context(self):
        book = self.bf.add_book(self.project, "FullContext")["id"]
        self.brief(book)
        canon = self.project / "universe/canon/factions"
        canon.mkdir(parents=True, exist_ok=True)
        (canon / "FAC-0001.md").write_text("---\nid: FAC-0001\ncontinuity: CNT-0001\n---\n\n# Guild\n\n<!-- bf:block summary -->\nThe Guild meters memory in candles.\n")
        self.bf.rebuild_indexes(self.project)
        seen = {"capsule": None, "context": [], "worldbuilding": None}
        original = self.bf.build_envelope
        def spy(project, **kwargs):
            envelope = original(project, **kwargs)
            if kwargs.get("role") == "designer":
                payload = envelope["payload"]
                seen["capsule"] = payload["task"]
                seen["worldbuilding"] = payload["task"].get("worldbuilding")
                seen["context"] = [row["id"] for row in payload.get("context", [])]
            return envelope
        self.bf.build_envelope = spy
        try:
            self.bf.execute_book_design(self.project, book, provider=DesignProvider(proposal()))
        finally:
            self.bf.build_envelope = original
        self.assertIsNotNone(seen["capsule"])
        self.assertEqual(seen["capsule"]["brief"]["premise"], "A diver must decide.")
        self.assertIn("UNI-0001#kernel", seen["context"])
        self.assertIn("FAC-0001#summary", seen["context"])

    def test_no_mid_sentence_wrap_in_generated_design_artifacts(self):
        book = self.bf.add_book(self.project, "Nowrap")["id"]
        self.brief(book)
        self.bf.execute_book_design(self.project, book, provider=DesignProvider(proposal()))
        design = (self.project / f"books/{book}/design.md").read_text()
        wrapped = self.bf._wrapped_lines(self.project / f"books/{book}/design.md")
        self.assertEqual(wrapped, [])


if __name__ == "__main__":
    unittest.main()
