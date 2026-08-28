import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


def _decide_locale_style(bf, project, book, locale):
    """A project must decide how the book speaks before anything is translated."""
    path = bf._project_root(project) / "books" / book / "translations" / bf._canonical_locale(locale) / "style.md"
    path.write_text("---\nid: LOC\n---\n\n# Locale Style\n\n<!-- bf:block style -->\nFormal address throughout; guillemets for dialogue; past tense preserved.\n", encoding="utf-8")


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_translated_publication", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TranslatedPublicationTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        self.book = self.bf.add_book(self.project, "Glass Harbor")["id"]
        contracts = self.project / f"books/{self.book}/chapters"
        contracts.mkdir()
        manuscript = self.project / f"books/{self.book}/manuscript/chapters"
        for index in (1, 2):
            chapter = f"CH-{index:04d}"
            (contracts / f"{chapter}.json").write_text(json.dumps({
                "schema": 1,
                "book": self.book,
                "id": chapter,
                "order": index,
                "target_words": 10,
                "imports": [],
            }))
            (manuscript / f"{chapter}.md").write_text(f"# Chapter {index}\n\nMara sees signal {index}.")
        source_state = self.project / f"books/{self.book}/state.yaml"
        value = json.loads(source_state.read_text())
        value["closed_chapters"] = ["CH-0001", "CH-0002"]
        source_state.write_text(json.dumps(value))
        self.bf.add_translation(self.project, self.book, "it-IT")
        _decide_locale_style(self.bf, self.project, self.book, "it-IT")
        self.locale_root = self.project / f"books/{self.book}/translations/it-IT"
        for index in (1, 2):
            (self.locale_root / f"chapters/CH-{index:04d}.md").write_text(
                f"# Capitolo {index}\n\nMara vede il segnale {index}."
            )
        state = json.loads((self.locale_root / "state.yaml").read_text())
        state.update({
            "completed_chapters": ["CH-0001", "CH-0002"],
            "status": "current",
            "current": True,
            "stale_prose": [],
            "boundary_audit": [],
        })
        (self.locale_root / "state.yaml").write_text(json.dumps(state))
        metadata = json.loads((self.locale_root / "metadata.yaml").read_text())
        metadata["title"] = "Il porto di vetro"
        (self.locale_root / "metadata.yaml").write_text(json.dumps(metadata))

    def test_publishes_current_locale_to_both_formats_without_model_calls(self):
        epub = self.bf.export_epub(self.project, self.book, "it-it")
        pdf = self.bf.export_pdf(self.project, self.book, "it-IT")

        self.assertEqual(epub["model_calls"], 0)
        self.assertEqual(pdf["model_calls"], 0)
        self.assertEqual(Path(epub["path"]).parent.name, "it-IT")
        with zipfile.ZipFile(epub["path"]) as archive:
            opf = archive.read("OEBPS/content.opf").decode()
            self.assertIn("<dc:language>it-IT</dc:language>", opf)
            self.assertIn("Il porto di vetro", opf)
        self.assertEqual(json.loads(Path(pdf["manifest"]).read_text())["language"], "it-IT")
        registry = json.loads((self.project / ".book-forge/artifact-deps.json").read_text())
        epub_deps = registry["artifacts"][f"EDITION-{self.book}-it-IT-EPUB"]["dependencies"]
        self.assertEqual(epub_deps, [
            f"TRANSLATION-{self.book}-CH-0001-it-IT",
            f"TRANSLATION-{self.book}-CH-0002-it-IT",
        ])
        self.assertEqual(
            registry["artifacts"][f"EDITION-{self.book}-it-IT-EPUB-MANIFEST"]["dependencies"],
            [f"EDITION-{self.book}-it-IT-EPUB"],
        )
        self.assertEqual(
            registry["artifacts"][f"EDITION-{self.book}-it-IT-PDF-MANIFEST"]["dependencies"],
            [f"EDITION-{self.book}-it-IT-PDF"],
        )

    def test_refuses_every_noncurrent_or_mixed_locale_condition_before_rendering(self):
        state_path = self.locale_root / "state.yaml"
        metadata_path = self.locale_root / "metadata.yaml"
        clean_state = json.loads(state_path.read_text())
        clean_metadata = json.loads(metadata_path.read_text())
        cases = [
            ("stale", {**clean_state, "current": False, "status": "stale"}, clean_metadata),
            ("boundary", {**clean_state, "boundary_audit": ["CH-0002"]}, clean_metadata),
            ("missing", {**clean_state, "completed_chapters": ["CH-0001"]}, clean_metadata),
            ("mixed", clean_state, {**clean_metadata, "locale": "fr-FR"}),
        ]
        for label, state, metadata in cases:
            with self.subTest(label=label):
                state_path.write_text(json.dumps(state))
                metadata_path.write_text(json.dumps(metadata))
                with self.assertRaises(self.bf.BookForgeError):
                    self.bf.export_epub(self.project, self.book, "it-IT")
                self.assertFalse((self.project / f"dist/{self.book}/it-IT/{self.book}.epub").exists())
                state_path.write_text(json.dumps(clean_state))
                metadata_path.write_text(json.dumps(clean_metadata))


if __name__ == "__main__":
    unittest.main()
