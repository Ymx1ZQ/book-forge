import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_cold_reader_stranger", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ColdReaderStrangerTests(unittest.TestCase):
    """The cold reader receives prose, not the book's private notes."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        self.book = self.bf.add_book(self.project, "Book")["id"]
        self.manuscript = self.project / f"books/{self.book}/manuscript/chapters"
        self.manuscript.mkdir(parents=True, exist_ok=True)

    def write(self, chapter, text):
        (self.manuscript / f"{chapter}.md").write_text(text, encoding="utf-8")

    def contract(self, chapter):
        return {
            "schema": 1,
            "book": self.book,
            "id": chapter,
            "order": int(chapter.split("-")[1]),
            "title": f"Title of {chapter}",
            "pov": "CHR-0001",
            "beats": [f"BEAT-{chapter}-the choice opens the conflict"],
            "plants": [f"PLANT-{chapter}-the sky hums"],
            "reveals": [f"REVEAL-{chapter}-the arrival is told"],
            "imports": [f"IMPORT-{chapter}-the kernel"],
            "target_words": 700,
            "pivotal": None,
        }

    def capsule(self, chapter, draft=None):
        return self.bf._cold_reader_capsule(
            self.project,
            self.book,
            chapter,
            self.contract(chapter),
            draft or f"# Title of {chapter}\n\nProse of {chapter}.",
        )

    def test_chapter_three_holds_the_two_chapters_before_it_and_no_contract(self):
        for chapter in ("CH-0001", "CH-0002", "CH-0003"):
            self.write(chapter, f"# Title of {chapter}\n\nProse of {chapter}.\n")
        state_dir = self.project / f"books/{self.book}/coldread-state"
        state_dir.mkdir()
        (state_dir / "CH-0001.md").write_text("COLDREAD-STATE-CH-0001", encoding="utf-8")
        (self.project / f"books/{self.book}/reader-state.md").write_text(
            "READER-STATE-FALLBACK", encoding="utf-8"
        )

        capsule = self.capsule("CH-0003")

        self.assertEqual(
            [row["chapter"] for row in capsule["prior_chapters"]],
            ["CH-0001", "CH-0002"],
        )
        self.assertEqual(
            capsule["prior_chapters"][0]["prose"],
            "# Title of CH-0001\n\nProse of CH-0001.\n",
        )
        self.assertNotIn("contract", capsule)
        self.assertNotIn("previous_synthetic", capsule)
        serialized = json.dumps(capsule)
        for marker in ("BEAT-", "PLANT-", "REVEAL-", "IMPORT-", "COLDREAD-STATE-", "READER-STATE-"):
            self.assertNotIn(marker, serialized)

    def test_chapter_one_reads_with_no_prior_text(self):
        self.write("CH-0001", "# Title of CH-0001\n\nProse of CH-0001.\n")

        capsule = self.capsule("CH-0001")

        self.assertEqual(capsule["prior_chapters"], [])

    def test_only_the_last_three_previous_chapters_are_carried(self):
        for number in range(1, 7):
            chapter = f"CH-{number:04d}"
            self.write(chapter, f"# Title of {chapter}\n\nProse of {chapter}.\n")

        capsule = self.capsule("CH-0006")

        self.assertEqual(
            [row["chapter"] for row in capsule["prior_chapters"]],
            ["CH-0003", "CH-0004", "CH-0005"],
        )


if __name__ == "__main__":
    unittest.main()
