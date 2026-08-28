import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
PROMPTS = MODULE_PATH.parents[1] / "assets" / "prompts"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"
CHAPTER_COUNT = 40


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_audit_slices", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROLE_VARIANTS = {name: spec[1] for name, spec in load_module().ROLE_SPECS.items()}


def chapter(index):
    return {
        "id": f"CH-{index:04d}", "order": index, "title": f"The Ninth Tide {index}",
        "pov": "CHR-0001", "beats": ["She wants the log and the warden will not open it"],
        "plants": [f"the warden keeps a key for {index}"], "reveals": [f"the key opens door {index}"],
        "target_words": 3000, "imports": ["UNI-0001#kernel"], "obligations": [], "pivotal": None,
    }


class AuditProvider:
    """Answers the design in slices and the audit in passes, recording both."""

    def __init__(self, bf, chapter_count=CHAPTER_COUNT, schedule_ceiling=None):
        self.bf = bf
        self.chapter_count = chapter_count
        self.schedule_ceiling = schedule_ceiling
        self.audit_scopes = []
        self.calls = []

    def _ok(self, envelope, payload, role):
        return {
            "text": json.dumps(payload),
            "provider": "openrouter", "model": MODEL, "variant": ROLE_VARIANTS.get(role, "high"),
            "session_id": f"ses-{len(self.calls)}", "tokens": {"input": envelope["estimated_input_tokens"], "output": 800},
            "cost": 0.01, "latency_ms": 5, "finish": "stop",
        }

    def _truncated(self, envelope, role):
        return {
            "text": '{"findings":[{"id":"F-001"',
            "provider": "openrouter", "model": MODEL, "variant": ROLE_VARIANTS.get(role, "high"),
            "session_id": f"ses-{len(self.calls)}", "tokens": {"input": envelope["estimated_input_tokens"], "output": 3000},
            "cost": 0.01, "latency_ms": 5, "finish": "length",
        }

    def __call__(self, role, envelope, attempt_dir):
        self.calls.append(role)
        if role.startswith("advisor-") or role == "chorus-synthesizer":
            return self._ok(envelope, {"findings": [], "suggestions": []}, role)
        task = envelope["payload"]["task"]
        if role == "canon-auditor":
            scope = task["design_scope"]
            self.audit_scopes.append(scope)
            rows = scope.get("proposal", {}).get("chapters", [])
            if self.schedule_ceiling is not None and "book_digest" not in scope and len(rows) > self.schedule_ceiling:
                return self._truncated(envelope, role)
            return self._ok(envelope, {"findings": [{
                "id": "F-001", "severity": "note", "issue": "Seeded note.",
                "evidence": [{"location": "UNI-0001#kernel"}], "repair_scope": ["BOOK-0001"],
            }]}, role)
        chunk = task.get("chunk") or {}
        if chunk.get("category") == "spine":
            return self._ok(envelope, {
                "premise": "A diver must decide whether memory can be owned.",
                "entry_state": {"CHR-0001": "isolated"},
                "arc": ["refusal", "cost", "choice"],
                "exit_boundary": {"CHR-0001": "committed"},
                "chapter_outline": [
                    {"id": f"CH-{i:04d}", "order": i, "title": f"The Ninth Tide {i}", "pov": "CHR-0001", "summary": "She goes down again."}
                    for i in range(1, self.chapter_count + 1)
                ],
            }, role)
        first, last = int(chunk["first_order"]), int(chunk["last_order"])
        return self._ok(envelope, {"chapters": [chapter(i) for i in range(first, last + 1)]}, role)


class PassBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def test_forty_chapters_become_eight_windows_and_one_schedule_pass(self):
        chunks = self.bf._book_audit_chunks(40)
        self.assertEqual([(c["category"], c["first_order"], c["last_order"]) for c in chunks], [
            ("window", 1, 5), ("window", 6, 10), ("window", 11, 15), ("window", 16, 20),
            ("window", 21, 25), ("window", 26, 30), ("window", 31, 35), ("window", 36, 40),
            ("schedule", 1, 40),
        ])

    def test_the_window_is_the_width_production_answers_at(self):
        """Ten chapters failed at 9508 tokens of input; five answered at 7638."""
        self.assertEqual(self.bf.BOOK_AUDIT_SLICE_SIZE, 5)

    def test_a_book_with_no_chapters_asks_nothing(self):
        self.assertEqual(self.bf._book_audit_chunks(0), [])

    def test_a_schedule_pass_can_be_halved_like_a_window(self):
        halves = self.bf._halve_chunk({"category": "schedule", "part": "1-40", "first_order": 1, "last_order": 40})
        self.assertEqual([(h["category"], h["first_order"], h["last_order"]) for h in halves], [
            ("schedule", 1, 20), ("schedule", 21, 40),
        ])

    def test_the_design_spine_still_cannot_be_halved(self):
        self.assertEqual(self.bf._halve_chunk({"category": "spine"}), [])


class PassScopeTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.scope = {
            "scope": "book", "book": "BOOK-0001",
            "proposal": {"premise": "p", "arc": ["a"], "chapters": [chapter(i) for i in range(1, 41)]},
        }

    def test_a_window_reads_its_own_chapters_in_full(self):
        sliced = self.bf._audit_chunk_scope(self.scope, {"category": "window", "part": "11-15", "first_order": 11, "last_order": 15})
        rows = sliced["proposal"]["chapters"]
        self.assertEqual([row["order"] for row in rows], list(range(11, 16)))
        self.assertIn("summary", rows[0].keys() | {"summary"})
        self.assertIn("plants", rows[0])
        self.assertIn("reveals", rows[0])

    def test_a_window_sees_the_rest_of_the_book_one_line_at_a_time(self):
        sliced = self.bf._audit_chunk_scope(self.scope, {"category": "window", "part": "1-5", "first_order": 1, "last_order": 5})
        digest = sliced["book_digest"]
        self.assertEqual(len(digest), 40)
        self.assertEqual(sorted(digest[0]), ["id", "order", "pov", "title"])

    def test_the_schedule_pass_reads_every_chapter_but_only_its_promises(self):
        sliced = self.bf._audit_chunk_scope(self.scope, {"category": "schedule", "part": "1-40", "first_order": 1, "last_order": 40})
        rows = sliced["proposal"]["chapters"]
        self.assertEqual(len(rows), 40)
        self.assertEqual(sorted(rows[0]), ["id", "order", "plants", "reveals", "title"])
        self.assertNotIn("book_digest", sliced)

    def test_the_spine_travels_with_every_pass(self):
        for chunk in self.bf._book_audit_chunks(40):
            sliced = self.bf._audit_chunk_scope(self.scope, chunk)
            self.assertEqual(sliced["proposal"]["arc"], ["a"], self.bf._chunk_slug(chunk))
            self.assertEqual(sliced["proposal"]["premise"], "p")

    def test_each_pass_is_told_what_it_is_reading(self):
        for chunk in self.bf._book_audit_chunks(40):
            self.assertIn("reading", self.bf._audit_chunk_scope(self.scope, chunk)["pass"])

    def test_the_prompt_describes_both_shapes(self):
        prompt = (PROMPTS / "canon-auditor.md").read_text()
        self.assertIn("design_scope.pass", prompt)
        self.assertIn("book_digest", prompt)


class AuditFixture(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["chorus"] = {"enabled": False, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.book = self.bf.add_book(self.project, "A")["id"]
        (self.project / f"books/{self.book}/book-brief.json").write_text(
            json.dumps({"schema": 1, "premise": "A diver must decide.", "characters": ["Mara"], "plot": ["dive"], "tone": "quiet", "length_notes": "40 chapters"})
        )


class SlicedAuditTests(AuditFixture):
    """The audit came back empty five times because it was one question over forty
    chapters: 34822 tokens of input, 32000 of reasoning, no output."""

    def test_a_long_book_is_audited_in_passes_and_the_verdict_is_one_record(self):
        provider = AuditProvider(self.bf)
        result = self.bf.execute_book_design(self.project, self.book, provider=provider)
        self.assertEqual(result["state"], "design_clean")
        self.assertEqual(provider.calls.count("canon-auditor"), 9)
        record = json.loads((self.project / f"books/{self.book}/design-audit.json").read_text())
        self.assertEqual(len(record["findings"]), 9)

    def test_no_pass_is_handed_the_staging_or_the_wiring(self):
        provider = AuditProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider)
        self.assertTrue(provider.audit_scopes)
        for scope in provider.audit_scopes:
            for row in scope["proposal"]["chapters"]:
                self.assertNotIn("beats", row)
                self.assertNotIn("imports", row)

    def test_findings_from_different_passes_keep_their_own_identifiers(self):
        provider = AuditProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider)
        record = json.loads((self.project / f"books/{self.book}/design-audit.json").read_text())
        ids = [row["id"] for row in record["findings"]]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertIn("A-window-1-5-F-001", ids)
        self.assertIn("A-schedule-1-40-F-001", ids)
        self.assertEqual({row["pass"] for row in record["findings"]}, {
            "window-1-5", "window-6-10", "window-11-15", "window-16-20",
            "window-21-25", "window-26-30", "window-31-35", "window-36-40", "schedule-1-40",
        })

    def test_a_pass_that_returns_no_answer_is_asked_for_half_as_much(self):
        provider = AuditProvider(self.bf, schedule_ceiling=20)
        result = self.bf.execute_book_design(self.project, self.book, provider=provider)
        self.assertEqual(result["state"], "design_clean")
        schedule = [len(s["proposal"]["chapters"]) for s in provider.audit_scopes if "book_digest" not in s]
        self.assertEqual(schedule, [40, 20, 20])


class ShortBookTests(AuditFixture):
    def test_a_book_that_fits_is_still_one_call(self):
        provider = AuditProvider(self.bf, chapter_count=4)
        self.bf.execute_book_design(self.project, self.book, provider=provider)
        self.assertEqual(provider.calls.count("canon-auditor"), 1)
        self.assertNotIn("pass", provider.audit_scopes[0])


if __name__ == "__main__":
    unittest.main()
