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

    def test_a_book_names_its_own_author_over_the_project_s(self):
        """A universe can hold books by different hands. Four editions shipped from
        this engine with no author at all, because the project-level field was the
        only one and nobody had a reason to set it for a whole universe."""
        config = json.loads((self.base / "book-forge.yaml").read_text())
        config["author"] = "The Universe's Hand"
        (self.base / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.assertEqual(self.bf.assemble_edition(self.base, self.book, "en")["author"], "The Universe's Hand")

        book_path = self.base / "books" / self.book / "book.yaml"
        book = json.loads(book_path.read_text())
        book["author"] = "This Book's Hand"
        book_path.write_text(json.dumps(book, indent=2, sort_keys=True) + "\n")
        self.assertEqual(self.bf.assemble_edition(self.base, self.book, "en")["author"], "This Book's Hand")

    def test_add_book_records_an_author_when_given_one_and_omits_the_key_otherwise(self):
        named = self.bf.add_book(self.base, "Named", author="A Hand")
        self.assertEqual(named["author"], "A Hand")
        self.assertNotIn("author", self.bf.add_book(self.base, "Unnamed"))


class ASourceDraftPublishesInTheBookSOrderTests(EpubTests):
    """The same gate on the branch that reads `closed_chapters`, which was left as it
    was. Publishing landfall's English after its first three chapters were rewritten
    failed with `closed chapters out of order`: the log read `CH-0004 … CH-0017,
    CH-0001, CH-0002, CH-0003`, because a rewritten chapter closes last.
    `reset --chapter` makes that the ordinary case."""

    def close_in_order(self, order):
        chapters = sorted(p.stem for p in (self.base / f"books/{self.book}/manuscript/chapters").glob("CH-*.md"))
        state_path = self.base / f"books/{self.book}/state.yaml"
        state = json.loads(state_path.read_text())
        state["closed_chapters"] = order(list(chapters))
        state_path.write_text(json.dumps(state))
        return chapters

    def test_a_closed_log_out_of_order_still_publishes_in_the_books_order(self):
        chapters = self.close_in_order(lambda c: list(reversed(c)))
        assembly = self.bf.assemble_edition(self.base, self.book, "en", draft=True)
        got = [str(row.get("id") or row.get("chapter")) for row in assembly["chapters"]]
        self.assertEqual(got, list(chapters), "the reader gets the book's order, not the log's")

    def test_a_closed_chapter_the_book_does_not_have_is_still_refused(self):
        self.close_in_order(lambda c: c + ["CH-9999"])
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.assemble_edition(self.base, self.book, "en", draft=True)
        self.assertIn("unknown chapter", str(caught.exception))


class ADraftPublishesInTheBookSOrderTests(EpubTests):
    """Landfall's Italian was refused with `completed chapters out of order`: the log
    read `… CH-0009, CH-0011, CH-0007, CH-0010 …` because CH-0007 and CH-0010 were
    refused once and retried, which is what setting a chapter aside and carrying on
    was built to allow. The gate was rejecting a state its sibling produces."""

    def locale_with_log(self, order):
        self.bf.add_translation(self.base, self.book, "it")
        root = self.base / f"books/{self.book}/translations/it"
        (root / "style.md").write_text(
            "---\nid: S\n---\n\n<!-- bf:block style -->\nImperfetto.\n", encoding="utf-8")
        chapters = sorted(p.stem for p in (self.base / f"books/{self.book}/manuscript/chapters").glob("CH-*.md"))
        for ch in chapters:
            (root / "chapters" / f"{ch}.md").write_text(f"# Capitolo\n\nTesto di {ch}.\n", encoding="utf-8")
        state = json.loads((root / "state.yaml").read_text())
        state["completed_chapters"] = order(list(chapters))
        (root / "state.yaml").write_text(json.dumps(state))
        meta_path = root / "metadata.yaml"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text())
            meta.setdefault("title", "La candela perduta")
            meta_path.write_text(json.dumps(meta))
        return chapters

    def test_a_log_out_of_order_still_publishes_in_the_books_order(self):
        chapters = self.locale_with_log(lambda c: c[2:] + c[:2] if len(c) > 2 else c)
        assembly = self.bf.assemble_edition(self.base, self.book, "it", draft=True)
        got = [str(row.get("id") or row.get("chapter")) for row in assembly["chapters"]]
        self.assertEqual(got, list(chapters), "the reader gets the book's order, not the log's")

    def test_a_completed_chapter_the_book_does_not_have_is_still_refused(self):
        self.locale_with_log(lambda c: c + ["CH-9999"])
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.assemble_edition(self.base, self.book, "it", draft=True)
        self.assertIn("unknown chapter", str(caught.exception))
