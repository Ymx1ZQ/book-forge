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


class ChapterNumberingTests(EpubTests):
    def test_the_number_is_rendered_by_the_edition_and_absent_from_the_manuscript(self):
        result = self.bf.export_epub(self.base, self.book, "en")
        with zipfile.ZipFile(Path(result["path"])) as archive:
            nav = archive.read("OEBPS/nav.xhtml").decode()
            first = archive.read("OEBPS/chapter-0001.xhtml").decode()
            second = archive.read("OEBPS/chapter-0002.xhtml").decode()
            css = archive.read("OEBPS/styles/epub.css").decode()
        self.assertIn(">1. Chapter 1<", nav)
        self.assertIn(">2. Chapter 2<", nav)
        self.assertIn('<p class="chapter-number">1</p>', first)
        self.assertIn('<p class="chapter-number">2</p>', second)
        self.assertIn("p.chapter-number", css)
        # The prose never carries the element, so a reorder or a format change touches no manuscript.
        manuscript = (self.base / f"books/{self.book}/manuscript/chapters/CH-0001.md").read_text()
        self.assertNotIn("chapter-number", manuscript)
        self.assertEqual(manuscript.splitlines()[0], "# Chapter 1")

    def test_the_assembly_carries_the_contract_order(self):
        assembly = self.bf.assemble_edition(self.base, self.book, "en")
        self.assertEqual([chapter["number"] for chapter in assembly["chapters"]], [1, 2])


class NavigationTests(EpubTests):
    NCX = "{http://www.daisy.org/z3986/2005/ncx/}"

    def test_the_package_carries_both_navigations(self):
        """An EPUB 3 is valid with the XHTML nav alone; Adobe RMSDK readers are not."""
        result = self.bf.export_epub(self.base, self.book, "en")
        with zipfile.ZipFile(Path(result["path"])) as archive:
            opf = archive.read("OEBPS/content.opf").decode()
            ncx = archive.read("OEBPS/toc.ncx").decode()
        self.assertIn('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>', opf)
        self.assertIn('<spine toc="ncx">', opf)
        import xml.etree.ElementTree as ET
        points = ET.fromstring(ncx).findall(f".//{self.NCX}navPoint")
        self.assertEqual([p.find(f"{self.NCX}content").attrib["src"] for p in points], ["chapter-0001.xhtml", "chapter-0002.xhtml"])
        self.assertEqual([p.find(f"{self.NCX}navLabel/{self.NCX}text").text for p in points], ["1. Chapter 1", "2. Chapter 2"])

    def test_an_empty_author_does_not_become_an_empty_creator(self):
        result = self.bf.export_epub(self.base, self.book, "en")
        with zipfile.ZipFile(Path(result["path"])) as archive:
            self.assertNotIn("<dc:creator></dc:creator>", archive.read("OEBPS/content.opf").decode())
