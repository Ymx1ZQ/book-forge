import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
PROMPTS = Path(__file__).parents[1] / "assets" / "prompts"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_translation_prompts", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TranslationPromptRuleTests(unittest.TestCase):
    """The translator, the passage translator, the locale reviser and reader
    carry the rules that keep references and localize punctuation."""

    @classmethod
    def setUpClass(cls):
        cls.bf = load_module()

    def prompt(self, name):
        return (PROMPTS / name).read_text(encoding="utf-8")

    def test_translator_carries_the_three_rules(self):
        text = self.prompt("translator.md")
        for phrase in (
            "never the source's marks",
            "name the subject of any sentence that follows an exchange",
            "not turned into a definite article",
        ):
            self.assertIn(phrase, text)

    def test_passage_translator_points_at_the_three_rules(self):
        text = self.prompt("passage-translator.md")
        for phrase in (
            "never the source's marks",
            "name the subject of a sentence that follows an exchange",
            "not turned into a definite article",
        ):
            self.assertIn(phrase, text)

    def test_locale_reviser_catches_the_two_defects(self):
        text = self.prompt("locale-reviser.md")
        for phrase in (
            "a subject the reader cannot attribute",
            "a definite article or a demonstrative on a noun",
            "follows the house style file",
        ):
            self.assertIn(phrase, text)

    def test_locale_reader_grades_the_two_defects_at_least_warning(self):
        text = self.prompt("locale-reader.md")
        self.assertIn("A subject the reader cannot attribute", text)
        self.assertIn("a definite noun the text never introduced", text)
        self.assertIn("are at least this too", text)

    def test_forbidden_pattern_refuses_a_dash_before_a_closing_quote(self):
        checks = {"forbidden": [{"pattern": "—[»”\"]", "reason": "r"}]}
        self.assertEqual(len(self.bf._forbidden_form_problems("«Come—» disse.", checks)), 1)
        self.assertEqual(self.bf._forbidden_form_problems("«Come… » disse.", checks), [])
        self.assertEqual(self.bf._forbidden_form_problems("Lei — disse — rise.", checks), [])


if __name__ == "__main__":
    unittest.main()
