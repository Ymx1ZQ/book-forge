import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_style_pending", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClosedStylePendingTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[], style_preset="plain-concrete")
        self.book = self.bf.add_book(self.project, "Book")["id"]
        self.reviews = self.project / f"books/{self.book}/reviews/CH-0001"
        self.reviews.mkdir(parents=True)

    def test_a_style_file_from_any_model_counts_as_reviewed(self):
        (self.reviews / "style-grok-4-6.json").write_text(json.dumps({"findings": []}))
        self.assertFalse(self.bf._closed_style_pending(self.project, self.book, "CH-0001"))

    def test_no_style_file_leaves_the_chapter_pending(self):
        self.assertTrue(self.bf._closed_style_pending(self.project, self.book, "CH-0001"))


if __name__ == "__main__":
    unittest.main()
