import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_pdf", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PdfTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name) / "base"
        self.bf.init_project(base, "World")
        self.book = self.bf.add_book(base, "Glass Tide")["id"]
        contracts = base / f"books/{self.book}/chapters"
        contracts.mkdir()
        manuscript = base / f"books/{self.book}/manuscript/chapters"
        for index in (1, 2):
            chapter = f"CH-{index:04d}"
            (contracts / f"{chapter}.json").write_text(json.dumps({"schema": 1, "book": self.book, "id": chapter, "order": index, "target_words": 10, "imports": []}))
            (manuscript / f"{chapter}.md").write_text(f"# Chapter {index}\n\nMara crosses the harbor. The tide answers {index}.")
        state_path = base / f"books/{self.book}/state.yaml"
        state = json.loads(state_path.read_text())
        state["closed_chapters"] = ["CH-0001", "CH-0002"]
        state_path.write_text(json.dumps(state))
        self.base = base

    def test_rebuilds_identically_with_a5_and_embedded_noto(self):
        first = Path(self.temp.name) / "first"
        second = Path(self.temp.name) / "second"
        shutil.copytree(self.base, first)
        shutil.copytree(self.base, second)
        a = self.bf.export_pdf(first, self.book, "en")
        b = self.bf.export_pdf(second, self.book, "en")
        self.assertEqual(Path(a["path"]).read_bytes(), Path(b["path"]).read_bytes())
        self.assertEqual(a["sha256"], b["sha256"])
        report = self.bf.validate_pdf(Path(a["path"]), expected_titles=["Chapter 1", "Chapter 2"])
        self.assertTrue(report["valid"])
        info = subprocess.run(["pdfinfo", "-box", a["path"]], capture_output=True, text=True, check=True).stdout
        self.assertIn("419.528 x 595.276", info)
        fonts = subprocess.run(["pdffonts", a["path"]], capture_output=True, text=True, check=True).stdout
        self.assertIn("Book-Forge-Serif", fonts)
        self.assertNotIn(" no ", "\n".join(fonts.splitlines()[2:]))

    def test_fails_closed_on_font_toolchain_drift(self):
        wrong = Path(self.temp.name) / "wrong.ttf"
        wrong.write_bytes(b"not a font")
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.export_pdf(self.base, self.book, "en", font_paths={"regular": wrong, "bold": wrong})


if __name__ == "__main__":
    unittest.main()


class PdfTitleValidationTests(unittest.TestCase):
    """A rendered title that wraps or carries a ligature is present, not missing."""

    LONG_TITLE = "The Voice Interrogates the Offering at the Counting Floor"

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        self.book = self.bf.add_book(self.project, "Glass Tide")["id"]
        contracts = self.project / f"books/{self.book}/chapters"
        contracts.mkdir()
        manuscript = self.project / f"books/{self.book}/manuscript/chapters"
        (contracts / "CH-0001.json").write_text(json.dumps({"schema": 1, "book": self.book, "id": "CH-0001", "order": 1, "target_words": 10, "imports": []}))
        (manuscript / "CH-0001.md").write_text(f"# {self.LONG_TITLE}\n\nMara crosses the harbor. The tide answers once.")
        state_path = self.project / f"books/{self.book}/state.yaml"
        state = json.loads(state_path.read_text())
        state["closed_chapters"] = ["CH-0001"]
        state_path.write_text(json.dumps(state))

    def test_a_wrapped_title_with_a_ligature_validates(self):
        result = self.bf.export_pdf(self.project, self.book, "en")
        raw = subprocess.run(["pdftotext", str(result["path"]), "-"], capture_output=True, text=True, check=False).stdout
        # The regression this guards: the title is rendered but not extractable verbatim.
        self.assertNotIn(self.LONG_TITLE, raw)
        self.assertTrue(self.bf.validate_pdf(Path(result["path"]), expected_titles=[self.LONG_TITLE])["valid"])

    def test_a_title_that_is_really_absent_fails_and_is_named(self):
        result = self.bf.export_pdf(self.project, self.book, "en")
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.validate_pdf(Path(result["path"]), expected_titles=["A Chapter Never Written"])
        self.assertIn("A Chapter Never Written", str(caught.exception))


class PdfChapterNumberTests(PdfTests):
    def test_the_number_opens_the_chapter_without_costing_a_blank_page(self):
        result = self.bf.export_pdf(self.base, self.book, "en")
        text = subprocess.run(["pdftotext", str(result["path"]), "-"], capture_output=True, text=True, check=False).stdout
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        # Each chapter opens on its number, with the title on the next line.
        self.assertEqual(lines[0], "1")
        self.assertEqual(lines[1], "Chapter 1")
        self.assertIn("2", lines)
        self.assertEqual(lines[lines.index("2") + 1], "Chapter 2")
        pages = int(subprocess.run(["pdfinfo", str(result["path"])], capture_output=True, text=True, check=False).stdout.split("Pages:")[1].split()[0])
        self.assertEqual(pages, 2)
