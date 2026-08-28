import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _decide_locale_style(bf, project, book, locale):
    """A project must decide how the book speaks before anything is translated."""
    path = bf._project_root(project) / "books" / book / "translations" / bf._canonical_locale(locale) / "style.md"
    path.write_text("---\nid: LOC\n---\n\n# Locale Style\n\n<!-- bf:block style -->\nFormal address throughout; guillemets for dialogue; past tense preserved.\n", encoding="utf-8")


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_translation_workspace", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TranslationWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", "en")
        self.book = self.bf.add_book(self.project, "Book")["id"]

    def test_is_absent_until_requested_and_canonicalizes_distinct_locales(self):
        translations = self.project / f"books/{self.book}/translations"
        self.assertFalse(translations.exists())

        italian = self.bf.add_translation(self.project, self.book, "it-it")
        self.assertEqual(italian["locale"], "it-IT")
        self.assertTrue((translations / "it-IT/chapters").is_dir())
        self.assertEqual(list((translations / "it-IT/chapters").iterdir()), [])
        self.assertTrue((translations / "it-IT/style.md").is_file())
        self.assertTrue((translations / "it-IT/glossary.md").is_file())
        self.assertEqual(self.bf.add_translation(self.project, self.book, "it-IT")["created"], False)

        portuguese = self.bf.add_translation(self.project, self.book, "pt-br")
        self.assertEqual(portuguese["locale"], "pt-BR")
        self.assertNotEqual(italian["id"], portuguese["id"])
        self.assertEqual(list((self.project / f"books/{self.book}/manuscript/chapters").glob("*.md")), [])

    def test_rejects_source_alias_and_unsafe_tags_without_side_effects(self):
        for locale in ("en", "iw", "../it", "it/../../x", "x"):
            with self.subTest(locale=locale):
                with self.assertRaises(self.bf.BookForgeError):
                    self.bf.add_translation(self.project, self.book, locale)
                    _decide_locale_style(self.bf, self.project, self.book, locale)
        translations = self.project / f"books/{self.book}/translations"
        self.assertFalse(translations.exists())

    def test_locale_state_is_isolated(self):
        self.bf.add_translation(self.project, self.book, "fr-FR")
        _decide_locale_style(self.bf, self.project, self.book, "fr-FR")
        self.bf.add_translation(self.project, self.book, "de-DE")
        fr = self.project / f"books/{self.book}/translations/fr-FR/state.yaml"
        data = json.loads(fr.read_text())
        data["boundary"] = "French only"
        fr.write_text(json.dumps(data))
        de = json.loads((self.project / f"books/{self.book}/translations/de-DE/state.yaml").read_text())
        self.assertNotIn("boundary", de)


if __name__ == "__main__":
    unittest.main()
