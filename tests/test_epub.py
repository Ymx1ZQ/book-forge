import importlib.util
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_epub", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EpubTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name) / "base"
        self.bf.init_project(base, "World")
        self.book = self.bf.add_book(base, "Glass & Tide")["id"]
        contracts = base / f"books/{self.book}/chapters"
        contracts.mkdir()
        manuscript = base / f"books/{self.book}/manuscript/chapters"
        for index in (1, 2):
            chapter = f"CH-{index:04d}"
            (contracts / f"{chapter}.json").write_text(json.dumps({"schema": 1, "book": self.book, "id": chapter, "order": index, "target_words": 10, "imports": []}))
            (manuscript / f"{chapter}.md").write_text(f"# Chapter {index}\n\nMara crosses the glass harbor.\n\n***\n\nThe tide answers {index}.")
        state_path = base / f"books/{self.book}/state.yaml"
        state = json.loads(state_path.read_text())
        state["closed_chapters"] = ["CH-0001", "CH-0002"]
        state_path.write_text(json.dumps(state))
        self.base = base

    def test_rebuilds_identically_across_absolute_roots(self):
        first = Path(self.temp.name) / "first"
        second = Path(self.temp.name) / "second"
        shutil.copytree(self.base, first)
        shutil.copytree(self.base, second)

        a = self.bf.export_epub(first, self.book, "en")
        b = self.bf.export_epub(second, self.book, "en")
        self.assertEqual(Path(a["path"]).read_bytes(), Path(b["path"]).read_bytes())
        self.assertEqual(a["sha256"], b["sha256"])
        self.assertTrue(self.bf.validate_epub(Path(a["path"]), expected_chapters=2)["valid"])
        manifest = json.loads(Path(a["manifest"]).read_text())
        self.assertEqual(manifest["output_sha256"], a["sha256"])
        self.assertNotIn(str(first), json.dumps(manifest))

        with zipfile.ZipFile(a["path"]) as archive:
            infos = archive.infolist()
            self.assertEqual(infos[0].filename, "mimetype")
            self.assertEqual(infos[0].compress_type, zipfile.ZIP_STORED)
            self.assertEqual({info.date_time for info in infos}, {(2000, 1, 1, 0, 0, 0)})
            self.assertIn("Glass &amp; Tide", archive.read("OEBPS/content.opf").decode())

    def test_refuses_incomplete_or_mixed_language_source(self):
        state_path = self.base / f"books/{self.book}/state.yaml"
        state = json.loads(state_path.read_text())
        state["closed_chapters"] = ["CH-0001"]
        state_path.write_text(json.dumps(state))
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.export_epub(self.base, self.book, "en")
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.export_epub(self.base, self.book, "it-IT")


if __name__ == "__main__":
    unittest.main()
