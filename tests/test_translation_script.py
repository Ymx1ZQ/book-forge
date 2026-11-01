import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_translation_script", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TranslationScriptTests(unittest.TestCase):
    """M84. A translation that carries letters of a foreign script is refused.

    A Ukrainian chapter came back with three CJK ideographs inside one word
    (`к原作者кладав`), passed every gate, and then broke the PDF export's font
    check. The refusal names the characters and the sentence around them so the
    repair ask can fix the word, while a name kept in Latin or Cyrillic as a
    whole word still passes.
    """

    SOURCE = (
        "# Chapter\n\nHe knocked to close the report, and before the rails carried him to "
        "Rue du Refuge he had already put all of it there, laying the rest of the week's "
        "wrongness aside."
    )

    def setUp(self):
        self.bf = load_module()

    def value(self, translated):
        return {"translated_markdown": translated, "glossary_updates": [], "boundary": "Він стукнув."}

    def script_problems(self, source, translated):
        return [
            p
            for p in self.bf._translation_validation(source, self.value(translated))
            if p.startswith("letters of a script the source does not use")
        ]

    def test_cjk_inside_a_ukrainian_sentence_is_refused_with_the_characters_and_sentence(self):
        translated = (
            "# Розділ\n\nВін стукнув звіт зачинити, а до того, як рейки винесли його на рю дю "
            "Рефюж, він уже поклав усе це туди, к原作者кладав решту тижневого неправильного."
        )
        problems = self.script_problems(self.SOURCE, translated)
        self.assertTrue(problems)
        self.assertIn("原", problems[0])
        self.assertIn("Він стукнув звіт зачинити", problems[0])

    def test_a_ukrainian_paragraph_with_a_latin_name_passes(self):
        translated = (
            "# Розділ\n\nВін стукнув звіт зачинити, а до того, як рейки винесли його на рю дю "
            "Рефюж, він уже поклав усе це туди, поклавши решту тижневого неправильного на рахунок "
            "Vent Systems."
        )
        self.assertFalse(self.script_problems(self.SOURCE, translated))

    def test_a_german_paragraph_passes(self):
        source = "# Chapter\n\nThe Field recorded the cycle and the wall held through the night."
        translated = (
            "# Kapitel\n\nDas Feld registrierte den Zyklus, und die Wand hielt die ganze Nacht."
        )
        self.assertFalse(self.script_problems(source, translated))

    def test_a_source_with_cjk_allows_the_same_cjk_in_the_translation(self):
        source = "# 章\n\n他敲了敲门，然后走进屋子，把一切放在了那里。"
        translated = "# Розділ\n\nВін постукав у двері, увійшов до хати 原作者 і поклав усе туди."
        self.assertFalse(self.script_problems(source, translated))

    def test_a_hyphen_compound_with_each_part_in_one_alphabet_passes(self):
        # «міні-PC» and «PC-шний» are Cyrillic part + Latin part — each part
        # sits in a single alphabet, so the compound is not a homoglyph glitch.
        for compound in ("міні-PC", "PC-шний"):
            translated = (
                "# Розділ\n\nВін стукнув звіт зачинити, а до того, як рейки винесли його на рю дю "
                f"Рефюж, він уже поклав усе це туди, {compound} решту тижневого неправильного."
            )
            self.assertFalse(self.script_problems(self.SOURCE, translated), compound)

    def test_an_apostrophe_compound_with_each_part_in_one_alphabet_passes(self):
        # «Dr.-Іван» — the hyphen separates a Latin part from a Cyrillic part.
        translated = (
            "# Розділ\n\nВін стукнув звіт зачинити, а до того, як рейки винесли його на рю дю "
            "Рефюж, він уже поклав усе це туди, Dr.-Іван решту тижневого неправильного."
        )
        self.assertFalse(self.script_problems(self.SOURCE, translated))

    def test_a_word_mixing_cyrillic_and_latin_letters_is_refused(self):
        # «кaладав» carries a Latin a between Cyrillic letters — a homoglyph glitch.
        translated = (
            "# Розділ\n\nВін стукнув звіт зачинити, а до того, як рейки винесли його на рю дю "
            "Рефюж, він уже кaладав усе це туди, решту тижневого неправильного."
        )
        problems = self.script_problems(self.SOURCE, translated)
        self.assertTrue(problems)
        self.assertIn("кaладав", problems[0])

    def test_more_than_three_hits_are_truncated_with_a_count(self):
        translated = (
            "# Розділ\n\nВін стукнув звіт зачинити 原. А до того 作. Рейки винесли його туди 者. "
            "Він уже поклав усе це туди, решту 韩 тижневого неправильного."
        )
        problems = self.script_problems(self.SOURCE, translated)
        self.assertTrue(problems)
        self.assertIn("and 1 more", problems[0])


if __name__ == "__main__":
    unittest.main()
