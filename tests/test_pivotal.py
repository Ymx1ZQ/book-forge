import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_pivotal", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prose(word):
    return "# Finale\n\n" + " ".join([word] * 700)


class PivotalProvider:
    def __init__(self):
        self.calls = []
        self.writer_count = 0
        self.lock = threading.Lock()

    def __call__(self, role, envelope, attempt_dir):
        with self.lock:
            self.calls.append(role)
            number = len(self.calls)
            if role == "writer":
                self.writer_count += 1
                payload = {"prose_markdown": prose("glass" if self.writer_count == 1 else "tide"), "beat_map": [{"beat": "Choose", "evidence": "chosen"}], "consequences": []}
            elif role == "judge":
                labels = sorted(envelope["payload"]["task"]["candidates"])
                payload = {"ranking": [labels[1], labels[0]], "evidence": [{"dimension": "causality", "winner": labels[1], "reason": "The choice lands."}]}
            elif role == "cold-reader":
                payload = {"findings": []}
            elif role == "technical-editor":
                payload = {"findings": [], "consequences": []}
            elif role == "reviser":
                payload = {"prose_markdown": prose("tide"), "beat_map": [{"beat": "Choose", "evidence": "chosen"}], "consequences": [], "dispositions": [], "reader_state": "The choice is made."}
            else:
                raise AssertionError(role)
        variants = {"writer": "low", "judge": "max", "cold-reader": "low", "technical-editor": "high", "reviser": "medium"}
        return {"text": json.dumps(payload), "provider": "openrouter", "model": MODEL, "variant": variants[role], "session_id": f"ses-{number}", "tokens": {"input": envelope["estimated_input_tokens"], "output": 300}, "cost": .001, "latency_ms": 10, "finish": "stop"}


class PivotalTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        self.book = self.bf.add_book(self.project, "Book")["id"]
        chapters = self.project / f"books/{self.book}/chapters"
        chapters.mkdir()
        (chapters / "CH-0001.json").write_text(json.dumps({
            "schema": 1, "book": self.book, "id": "CH-0001", "order": 1,
            "pov": "CHR-0001", "beats": ["Choose"], "plants": [], "reveals": [],
            "target_words": 700, "imports": ["UNI-0001#kernel"], "pivotal": "finale",
        }))

    def test_blind_selects_and_closes_in_six_calls(self):
        provider = PivotalProvider()
        result = self.bf.produce_pivotal_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(result["calls"], 6)
        self.assertEqual(provider.calls.count("writer"), 2)
        self.assertEqual(provider.calls.count("judge"), 1)
        variants = self.project / f"books/{self.book}/work/CH-0001/variants"
        self.assertTrue((variants / "A/draft.md").is_file())
        self.assertTrue((variants / "B/draft.md").is_file())
        decision = json.loads((self.project / f"books/{self.book}/reviews/CH-0001/judgement.json").read_text())
        self.assertNotIn("A", json.dumps(decision["anonymous_candidates"]))
        self.assertLessEqual(len(decision["anchors"]), 2)
        self.assertTrue((self.project / f"books/{self.book}/manuscript/chapters/CH-0001.md").is_file())

    def test_rejects_unmarked_chapter(self):
        contract_path = self.project / f"books/{self.book}/chapters/CH-0001.json"
        contract = json.loads(contract_path.read_text())
        contract["pivotal"] = None
        contract_path.write_text(json.dumps(contract))
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.produce_pivotal_chapter(self.project, self.book, "CH-0001", provider=PivotalProvider())


if __name__ == "__main__":
    unittest.main()
