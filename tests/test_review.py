import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_review", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prose(words=700):
    return "# Chapter\n\n" + " ".join(["memory"] * words)


class RoleProvider:
    def __init__(self, responses):
        self.responses = {role: list(values) for role, values in responses.items()}
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, role, envelope, attempt_dir):
        with self.lock:
            text = self.responses[role].pop(0)
            number = len(self.calls) + 1
            self.calls.append(role)
        variants = {"cold-reader": "low", "technical-editor": "high", "reviser": "medium"}
        return {
            "text": json.dumps(text), "provider": "openrouter", "model": MODEL,
            "variant": variants[role], "session_id": f"ses-{number}",
            "tokens": {"input": envelope["estimated_input_tokens"], "output": 200},
            "cost": 0.001, "latency_ms": 10, "finish": "stop",
        }


class ReviewTests(unittest.TestCase):
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
                return {"text": json.dumps(draft), "provider": "openrouter", "model": MODEL, "variant": "low", "session_id": "ses-draft", "tokens": {"input": 1000, "output": 800}, "cost": .001, "latency_ms": 10, "finish": "stop"}
        self.bf.draft_chapter(self.project, self.book, "CH-0001", provider=DraftProvider())

    def reviser(self, consequences=None, dispositions=None):
        return {
            "prose_markdown": prose(),
            "beat_map": [{"beat": "Find signal", "evidence": "found"}],
            "consequences": consequences or [],
            "dispositions": dispositions or [],
            "reader_state": "The signal exists and Mara knows it.",
        }

    def test_closes_in_three_review_calls_and_updates_state(self):
        provider = RoleProvider({
            "cold-reader": [{"findings": []}],
            "technical-editor": [{"findings": [], "consequences": []}],
            "reviser": [self.reviser()],
        })
        result = self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(result["calls"], 3)
        self.assertEqual(set(provider.calls[:2]), {"cold-reader", "technical-editor"})
        self.assertEqual(provider.calls[-1], "reviser")
        self.assertTrue((self.project / f"books/{self.book}/manuscript/chapters/CH-0001.md").is_file())
        state = json.loads((self.project / f"books/{self.book}/state.yaml").read_text())
        self.assertEqual(state["closed_chapters"], ["CH-0001"])
        self.assertTrue(json.loads((self.project / ".book-forge/state.json").read_text())["source_locked"])
        config_path = self.project / "book-forge.yaml"
        config = json.loads(config_path.read_text())
        config["source_language"] = "fr"
        config_path.write_text(json.dumps(config))
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.status_project(self.project)

    def test_seeded_undisclosed_consequence_requires_repair_and_verification(self):
        finding = {"id": "F-STATE-1", "dimension": "state", "severity": "blocking", "objective": True, "evidence": "final paragraph", "issue": "Signal knowledge omitted", "fix_required": True}
        consequence = {"scope": "book", "fact": "Mara knows the signal.", "entities": ["CHR-0001"]}
        disposition = {"finding": "T-0001", "action": "repaired", "evidence": "final paragraph", "loss": "none", "supersedes": []}
        provider = RoleProvider({
            "cold-reader": [{"findings": []}],
            "technical-editor": [{"findings": [finding], "consequences": [consequence]}, {"verified": True, "findings": []}],
            "reviser": [self.reviser([consequence], [disposition])],
        })
        result = self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(result["calls"], 4)
        state = json.loads((self.project / f"books/{self.book}/state.yaml").read_text())
        self.assertEqual(state["consequences"][0]["fact"], "Mara knows the signal.")

        second = Path(self.temp.name) / "blocked"
        self.bf.init_project(second, "Blocked")
        book = self.bf.add_book(second, "Book")["id"]
        chapter_dir = second / f"books/{book}/chapters"
        chapter_dir.mkdir()
        contract = json.loads((self.project / f"books/{self.book}/chapters/CH-0001.json").read_text())
        contract["book"] = book
        (chapter_dir / "CH-0001.json").write_text(json.dumps(contract))
        class DraftProvider:
            def __call__(inner_self, role, envelope, attempt_dir):
                return {"text": json.dumps({"prose_markdown": prose(), "beat_map": [{"beat": "Find signal", "evidence": "found"}], "consequences": []}), "provider": "openrouter", "model": MODEL, "variant": "low", "session_id": "ses-d", "tokens": {}, "cost": 0, "latency_ms": 1, "finish": "stop"}
        self.bf.draft_chapter(second, book, "CH-0001", provider=DraftProvider())
        bad = RoleProvider({
            "cold-reader": [{"findings": []}],
            "technical-editor": [{"findings": [finding], "consequences": [consequence]}],
            "reviser": [self.reviser([], [{**disposition, "action": "dismissed"}])],
        })
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.review_and_close_chapter(second, book, "CH-0001", provider=bad)
        self.assertFalse((second / f"books/{book}/manuscript/chapters/CH-0001.md").exists())

    def test_duplicate_finding_ids_across_reviews_are_disambiguated_for_the_reviser(self):
        cold_finding = {"id": "F-0001", "dimension": "clarity", "severity": "warning", "evidence": "a span", "issue": "vague", "fix_required": True}
        tech_finding = {"id": "F-0001", "dimension": "state", "severity": "warning", "evidence": "another span", "issue": "missing consequence", "fix_required": True, "objective": False}
        provider = RoleProvider({
            "cold-reader": [{"findings": [cold_finding]}],
            "technical-editor": [{"findings": [tech_finding], "consequences": []}],
            "reviser": [self.reviser([], [
                {"finding": "F-0001", "action": "repaired", "evidence": "fixed", "loss": "none", "supersedes": []},
                {"finding": "T-0001", "action": "accepted-risk", "evidence": "kept", "loss": "none", "supersedes": []},
            ])],
        })
        result = self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(result["calls"], 3)
        dispositions = json.loads((self.project / f"books/{self.book}/reviews/CH-0001/dispositions.json").read_text())
        self.assertEqual([row["finding"] for row in dispositions["dispositions"]], ["F-0001", "F-0001"])
        self.assertEqual(
            [row["action"] for row in dispositions["dispositions"]],
            ["repaired", "accepted-risk"],
        )

    def test_resume_reuses_materialized_reviews_without_recalling_reviewers(self):
        cold_finding = {"id": "F-0001", "dimension": "clarity", "severity": "warning", "evidence": "a span", "issue": "vague", "fix_required": True}
        tech_finding = {"id": "F-0001", "dimension": "state", "severity": "warning", "evidence": "another span", "issue": "missing", "fix_required": True, "objective": False}
        provider = RoleProvider({
            "cold-reader": [{"findings": [cold_finding]}],
            "technical-editor": [{"findings": [tech_finding], "consequences": []}],
            "reviser": [self.reviser([], [
                {"finding": "F-0001", "action": "repaired", "evidence": "fixed", "loss": "none", "supersedes": []},
                {"finding": "T-0001", "action": "accepted-risk", "evidence": "kept", "loss": "none", "supersedes": []},
            ])],
        })
        self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(provider.calls.count("cold-reader"), 1)
        self.assertEqual(provider.calls.count("technical-editor"), 1)

        contract = json.loads((self.project / f"books/{self.book}/chapters/CH-0001.json").read_text())
        draft = (self.project / f"books/{self.book}/work/CH-0001/draft.md").read_text()
        writer_consequences = json.loads((self.project / f"books/{self.book}/work/CH-0001/consequences.json").read_text())
        only_reviser = RoleProvider({
            "reviser": [self.reviser([], [
                {"finding": "F-0001", "action": "repaired", "evidence": "fixed", "loss": "none", "supersedes": []},
                {"finding": "T-0001", "action": "accepted-risk", "evidence": "kept", "loss": "none", "supersedes": []},
            ])],
        })
        cold, technical, receipts = self.bf._call_parallel_reviews(
            self.project, self.book, "CH-0001", contract, draft, writer_consequences, only_reviser
        )
        self.assertEqual(only_reviser.calls, [])
        self.assertEqual([f["id"] for f in cold["findings"]], ["F-0001"])
        self.assertEqual([f["id"] for f in technical["findings"]], ["F-0001"])

    def test_revision_with_string_consequences_fails_with_clear_message(self):
        finding = {"id": "F-0001", "dimension": "state", "severity": "warning", "evidence": "span", "issue": "missing fact", "fix_required": True, "objective": False}
        consequence = {"scope": "book", "fact": "Mara knows the signal.", "entities": ["CHR-0001"]}
        provider = RoleProvider({
            "cold-reader": [{"findings": []}],
            "technical-editor": [{"findings": [finding], "consequences": [consequence]}],
            "reviser": [{
                "prose_markdown": prose(),
                "beat_map": [{"beat": "Find signal", "evidence": "found"}],
                "consequences": ["Mara knows the signal."],
                "dispositions": [{"finding": "T-0001", "action": "repaired", "evidence": "fixed", "loss": "none", "supersedes": []}],
                "reader_state": "Mara knows the signal.",
            }],
        })
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertIn("consequences must be a list of objects", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
