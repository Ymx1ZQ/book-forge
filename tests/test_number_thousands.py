import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_number_thousands", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NO_BREAK_SPACE = "\u00a0"
NARROW_NO_BREAK_SPACE = "\u202f"


class NumberThousandsTests(unittest.TestCase):
    """M83. A source integer written with thousands separators survives localization.

    «Cycle 7,714» may be rendered «Цикл 7714», «Цикл 7 714» (no-break space) or
    German «7.714» without the number check refusing the chapter.
    """

    SOURCE = "# Chapter\n\nThe Field recorded Cycle 7,714, and 1,000,000 drones fell silent."

    def setUp(self):
        self.bf = load_module()

    def value(self, translated):
        return {"translated_markdown": translated, "glossary_updates": [], "boundary": "Mara sa."}

    def has_number_problem(self, source, translated):
        return any(
            p.startswith("numbers differ from source")
            for p in self.bf._translation_validation(source, self.value(translated))
        )

    def test_plain_regrouping_passes(self):
        translated = "# Розділ\n\nПоле зафіксувало Цикл 7714, і 1000000 дронів замовкли."
        self.assertFalse(self.has_number_problem(self.SOURCE, translated))

    def test_no_break_space_separator_passes(self):
        translated = (
            "# Розділ\n\nПоле зафіксувало Цикл 7"
            + NO_BREAK_SPACE
            + "714, і 1"
            + NO_BREAK_SPACE
            + "000"
            + NO_BREAK_SPACE
            + "000 дронів замовкли."
        )
        self.assertFalse(self.has_number_problem(self.SOURCE, translated))

    def test_narrow_no_break_space_separator_passes(self):
        translated = (
            "# Розділ\n\nПоле зафіксувало Цикл 7"
            + NARROW_NO_BREAK_SPACE
            + "714, і 1"
            + NARROW_NO_BREAK_SPACE
            + "000"
            + NARROW_NO_BREAK_SPACE
            + "000 дронів замовкли."
        )
        self.assertFalse(self.has_number_problem(self.SOURCE, translated))

    def test_regular_space_separator_passes(self):
        translated = "# Розділ\n\nПоле зафіксувало Цикл 7 714, і 1 000 000 дронів замовкли."
        self.assertFalse(self.has_number_problem(self.SOURCE, translated))

    def test_german_dot_separator_passes(self):
        translated = "# Kapitel\n\nDas Feld registrierte Zyklus 7.714, und 1.000.000 Drohnen verstummten."
        self.assertFalse(self.has_number_problem(self.SOURCE, translated))

    def test_a_truncated_number_still_fails(self):
        translated = "# Розділ\n\nПоле зафіксувало Цикл 7,71, і 1000000 дронів замовкли."
        self.assertTrue(self.has_number_problem(self.SOURCE, translated))

    def test_a_decimal_comma_localization_still_passes(self):
        source = "# Chapter\n\nThe exhale read 0.2% candela."
        translated = "# Capitolo\n\nL'esalato segnava 0,2% candela."
        self.assertFalse(self.has_number_problem(source, translated))

    def test_an_integer_is_not_read_as_a_regrouped_decimal(self):
        translated = "# Розділ\n\nПоле зафіксувало Цикл 1.31, і 1000000 дронів замовкли."
        self.assertTrue(self.has_number_problem(self.SOURCE, translated))

    def test_a_missing_number_still_fails(self):
        translated = "# Розділ\n\nПоле зафіксувало Цикл 7714, і дронів замовкли."
        self.assertTrue(self.has_number_problem(self.SOURCE, translated))

    def test_an_extra_number_still_fails(self):
        translated = "# Розділ\n\nПоле зафіксувало Цикл 7714, і 1000000 дронів та 5 вартових замовкли."
        self.assertTrue(self.has_number_problem(self.SOURCE, translated))

    def test_a_word_between_two_numbers_is_not_read_as_a_separator(self):
        source = "# Chapter\n\nThe gate held. Rows 7 and 714 were lost, and 1,000,000 drones fell silent."
        translated = "# Розділ\n\nВорота витримали. Ряди 7 і 714 було втрачено, і 1 000 000 дронів замовкли."
        self.assertFalse(self.has_number_problem(source, translated))

    def test_a_space_before_more_than_three_digits_does_not_join(self):
        translated = "# Розділ\n\nПоле зафіксувало Цикл 7 7145, і 1 000 000 дронів замовкли."
        self.assertTrue(self.has_number_problem(self.SOURCE, translated))

    def test_a_translation_that_keeps_the_source_comma_still_passes(self):
        translated = "# Розділ\n\nПоле зафіксувало Цикл 7,714, і 1,000,000 дронів замовкли."
        self.assertFalse(self.has_number_problem(self.SOURCE, translated))


if __name__ == "__main__":
    unittest.main()
