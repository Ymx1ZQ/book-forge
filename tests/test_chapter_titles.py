import importlib.util
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
