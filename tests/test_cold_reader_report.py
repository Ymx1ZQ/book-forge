import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from test_review import RoleProvider, prose


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_cold_reader_report", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ColdReaderReportTests(unittest.TestCase):
    """What the cold reader says happened, could not define and saw at stake."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        self.book = self.bf.add_book(self.project, "Book")["id"]
        chapter_dir = self.project / f"books/{self.book}/chapters"
        chapter_dir.mkdir()
        contract = {
            "schema": 1, "book": self.book, "id": "CH-0001", "order": 1,
            "pov": "CHR-0001", "beats": ["Find signal"], "plants": [], "reveals": [],
            "target_words": 700, "imports": ["UNI-0001#kernel"], "pivotal": None,
        }
        (chapter_dir / "CH-0001.json").write_text(json.dumps(contract))
        draft = {
            "prose_markdown": prose(), "beat_map": [{"beat": "Find signal", "evidence": "found"}],
            "consequences": [],
        }

        class DraftProvider:
            def __call__(inner_self, role, envelope, attempt_dir):
                return {
                    "text": json.dumps(draft), "provider": "openrouter",
                    "model": "openrouter/deepseek/deepseek-v4.1-flash-1017",
                    "variant": "low", "session_id": "ses-draft",
                    "tokens": {"input": 1000, "output": 800}, "cost": .001,
                    "latency_ms": 10, "finish": "stop",
                }

        self.bf.draft_chapter(self.project, self.book, "CH-0001", provider=DraftProvider())

    def answer(self, *, events=None, terms=0, stakes="Mara can lose the archive."):
        return {
            "findings": [],
            "events": ["Mara opens the archive."] if events is None else events,
            "undefined_terms": [
                {"term": f"term-{number}", "quote": f"quote-{number}"}
                for number in range(1, terms + 1)
            ],
            "stakes": stakes,
        }

    def set_cap(self, cap):
        path = self.project / "book-forge.yaml"
        config = json.loads(path.read_text())
        config["review"] = {"max_undefined_terms": cap}
        path.write_text(json.dumps(config))

    def engine_findings(self, value):
        self.bf._validate_cold_reader_result(value)
        return self.bf._cold_reader_engine_findings(self.project, value)

    def test_an_answer_without_events_is_refused(self):
        value = self.answer()
        del value["events"]

        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf._validate_cold_reader_result(value)

        self.assertIn("events", str(caught.exception))

    def test_no_events_yields_the_blocking_pacing_finding(self):
        findings = self.engine_findings(self.answer(events=[]))

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding["dimension"], "pacing")
        self.assertEqual(finding["severity"], "blocking")
        self.assertEqual(finding["source"], "engine")
        self.assertTrue(finding["fix_required"])
        self.assertEqual(finding["evidence"], [])
        self.assertIn("0", finding["issue"])
        self.assertIn(str(self.bf.COLD_READER_MAX_EVENTS), finding["issue"])

    def test_no_stakes_yields_the_blocking_pacing_finding(self):
        findings = self.engine_findings(self.answer(stakes=""))

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding["dimension"], "pacing")
        self.assertEqual(finding["severity"], "blocking")
        self.assertEqual(finding["source"], "engine")
        self.assertTrue(finding["fix_required"])
        self.assertIn("0", finding["issue"])
        self.assertIn("1", finding["issue"])

    def test_four_undefined_terms_are_blocking_at_the_default_cap_and_none_at_five(self):
        value = self.answer(terms=4)
        findings = self.engine_findings(value)

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding["dimension"], "clarity")
        self.assertEqual(finding["severity"], "blocking")
        self.assertEqual(finding["source"], "engine")
        self.assertTrue(finding["fix_required"])
        self.assertEqual([term["term"] for term in finding["evidence"]], [f"term-{n}" for n in range(1, 5)])
        self.assertIn("4", finding["issue"])
        self.assertIn(str(self.bf.REVIEW_MAX_UNDEFINED_TERMS_DEFAULT), finding["issue"])

        self.set_cap(5)

        self.assertEqual(self.engine_findings(value), [])

    def test_a_complete_answer_with_two_terms_adds_nothing(self):
        self.assertEqual(self.engine_findings(self.answer(terms=2)), [])

    def test_the_engine_findings_reach_the_cold_reader_result(self):
        provider = RoleProvider({
            "cold-reader": [self.answer(events=[])],
            "technical-editor": [{"findings": [], "consequences": []}],
        })
        contract = json.loads((self.project / f"books/{self.book}/chapters/CH-0001.json").read_text())
        draft = (self.project / f"books/{self.book}/work/CH-0001/draft.md").read_text()
        consequences = json.loads(
            (self.project / f"books/{self.book}/work/CH-0001/consequences.json").read_text()
        )
        self.bf._ensure_review_tasks(self.project, self.book, "CH-0001")

        cold, _, _ = self.bf._call_parallel_reviews(
            self.project, self.book, "CH-0001", contract, draft, consequences, provider,
        )

        self.assertEqual([finding["id"] for finding in cold["findings"]], ["F-ENG-0001"])
        self.assertEqual(cold["findings"][0]["dimension"], "pacing")
        self.assertEqual(cold["findings"][0]["source"], "engine")


if __name__ == "__main__":
    unittest.main()
