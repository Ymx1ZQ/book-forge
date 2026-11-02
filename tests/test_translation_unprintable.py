import importlib.util
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_translation_unprintable", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TranslationUnprintableTests(unittest.TestCase):
    """M90. A translation that carries a character the print font cannot draw is refused.

    An Italian chapter came back with the Japanese corner brackets `「」` as
    dialogue marks and another with U+2212 MINUS SIGN. Both passed every gate and
    the PDF export then failed its font check hours later, so the refusal names
    each character with its code point and the sentence around it.
    """

    def setUp(self):
        self.bf = load_module()

    def test_corner_brackets_are_refused_with_their_code_points(self):
        source = "# Chapter\n\nHe said the words and left."
        translated = "# Capitolo\n\n«Va bene» — 「Va bene」."
        problem = self.bf._unprintable_problem(source, translated)
        self.assertIsNotNone(problem)
        self.assertIn("U+300C", problem)
        self.assertIn("U+300D", problem)
        self.assertIn("the print font has no glyph for", problem)
        self.assertIn("Va bene", problem)

    def test_a_minus_sign_is_refused_with_its_code_point(self):
        source = "# Chapter\n\nThe value fell by 3 minus 1."
        translated = "# Capitolo\n\nIl valore è calato di 3 − 1."
        problem = self.bf._unprintable_problem(source, translated)
        self.assertIsNotNone(problem)
        self.assertIn("U+2212", problem)
        self.assertIn("Il valore è calato", problem)

    def test_ordinary_typography_passes(self):
        source = "# Chapter\n\nThe café's price — the old one — was three euros…"
        translated = "# Capitolo\n\nIl prezzo del caffè — quello vecchio — era «tre euro»… € 3."
        self.assertIsNone(self.bf._unprintable_problem(source, translated))

    def test_a_character_the_source_carries_passes(self):
        source = "# Chapter\n\nHe wrote 「the word」 on the page."
        translated = "# Capitolo\n\nEgli scrisse 「the word」 sulla pagina."
        self.assertIsNone(self.bf._unprintable_problem(source, translated))

    def test_a_missing_fc_query_returns_none(self):
        source = "# Chapter\n\nHe said the words and left."
        translated = "# Capitolo\n\n「Va bene」."
        with mock.patch.object(self.bf, "_print_font_codepoints", return_value=None):
            self.assertIsNone(self.bf._unprintable_problem(source, translated))


if __name__ == "__main__":
    unittest.main()
