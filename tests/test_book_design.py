import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_book_design", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


class BookDesignTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")

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


if __name__ == "__main__":
    unittest.main()
