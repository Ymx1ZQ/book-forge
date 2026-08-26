import importlib.util
import json
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_titles", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContractHeadingTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.contract = {"id": "CH-0002", "title": "The Mistimed Dawn"}

    def test_a_model_invented_prefix_is_replaced_by_the_contract_title(self):
        prose = "# Chapter Two — The Mistimed Dawn\n\nThe fog came in wrong that morning."
        result = self.bf._with_contract_heading(prose, self.contract)
        self.assertEqual(result.splitlines()[0], "# The Mistimed Dawn")
        self.assertEqual(result.splitlines()[2], "The fog came in wrong that morning.")

    def test_a_matching_heading_is_left_alone(self):
        prose = "# The Mistimed Dawn\n\nThe fog came in wrong."
        self.assertEqual(self.bf._with_contract_heading(prose, self.contract), prose)

    def test_prose_is_untouched_without_a_contract_title_or_a_heading(self):
        prose = "# Whatever The Writer Chose\n\nBody."
        self.assertEqual(self.bf._with_contract_heading(prose, {"id": "CH-0002"}), prose)
        self.assertEqual(self.bf._with_contract_heading("No heading here.", self.contract), "No heading here.")


class BeatTitleTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def test_the_opening_words_of_a_beat_are_not_a_title(self):
        chapter = {
            "id": "CH-0005",
            "title": "At the counting the floor is",
            "beats": ["At the Counting the floor is read: lamps fail in public, riots follow."],
        }
        self.assertTrue(self.bf._title_is_beat_prefix(chapter))

    def test_a_real_title_survives(self):
        chapter = {
            "id": "CH-0001",
            "title": "The Word Under the Glass",
            "beats": ["Binta reads the undercrypt telemetry and finds a word that should not be there."],
        }
        self.assertFalse(self.bf._title_is_beat_prefix(chapter))

    def test_a_short_title_coinciding_with_the_beat_opening_is_not_caught(self):
        chapter = {"id": "CH-0003", "title": "Six Spoke", "beats": ["Six Spoke, and the sky screamed over Port Cradle."]}
        self.assertFalse(self.bf._title_is_beat_prefix(chapter))


if __name__ == "__main__":
    unittest.main()


class InventedTitleTests(unittest.TestCase):
    """With no contract title there is nothing downstream to repair the heading."""

    BEAT = "At the Counting the floor is read: lamps fail in public, riots follow."

    def setUp(self):
        self.bf = load_module()

    def output(self, heading):
        body = " ".join(["word"] * 28)
        return json.dumps({
            "prose_markdown": f"# {heading}\n\n{body}",
            "beat_map": [{"beat": self.BEAT, "evidence": "line 3"}],
            "consequences": [],
        })

    def contract(self, title=None):
        value = {"id": "CH-0005", "target_words": 30, "beats": [self.BEAT]}
        if title:
            value["title"] = title
        return value

    def test_a_heading_repeating_a_beat_opening_is_rejected(self):
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.validate_writer_output(self.contract(), self.output("At the counting the floor is"))
        self.assertIn("repeats the opening of a beat", str(caught.exception))

    def test_a_numbering_prefix_is_rejected(self):
        for heading in ("Chapter Two — The Mistimed Dawn", "III — Six Spoke, and the Sky Screamed", "4. The Signed Misread"):
            with self.subTest(heading=heading):
                with self.assertRaises(self.bf.BookForgeError) as caught:
                    self.bf.validate_writer_output(self.contract(), self.output(heading))
                self.assertIn("numbering prefix", str(caught.exception))

    def test_a_real_title_passes_even_when_it_opens_with_a_number_word(self):
        for heading in ("The Arithmetic of Grace", "Six Spoke, and the Sky Screamed"):
            with self.subTest(heading=heading):
                value = self.bf.validate_writer_output(self.contract(), self.output(heading))
                self.assertEqual(value["prose_markdown"].splitlines()[0], f"# {heading}")

    def test_a_contract_that_names_a_title_is_not_second_guessed(self):
        # _with_contract_heading overwrites the heading at promote, so there is nothing to check.
        value = self.bf.validate_writer_output(self.contract("The Arithmetic of Grace"), self.output("Chapter Two — Whatever"))
        self.assertIn("prose_markdown", value)
