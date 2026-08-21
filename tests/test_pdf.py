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
