"""The reader-named shapes and the per-chapter limits that turn counts into findings."""
import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_shapes", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProseShapeTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def result(self, text, config=None):
        return self.bf.prose_tells(text, config)

    def kinds(self, text, config=None):
        return [hit["kind"] for hit in self.result(text, config)["hits"]]

    def test_an_inanimate_thing_that_acts_is_found(self):
        result = self.result("The paper came to the table.")
        self.assertEqual([hit["kind"] for hit in result["hits"]], ["personified"])
        self.assertEqual(result["counts"], {"personified": 1})

    def test_an_inanimate_thing_that_does_nothing_is_not_found(self):
        self.assertEqual(self.kinds("The clerk brought the paper."), [])

    def test_the_way_clause_is_a_simile(self):
        result = self.result("She read it the way a Counter reads a column.")
        self.assertEqual([hit["kind"] for hit in result["hits"]], ["simile"])
        self.assertEqual(result["counts"], {"simile": 1})

    def test_in_the_way_of_is_not_the_simile(self):
        self.assertEqual(self.kinds("She stood in the way of the door."), [])

    def test_as_if_is_a_simile(self):
        self.assertEqual(self.kinds("The paper moved as if a hand had touched it."), ["simile"])
        self.assertEqual(self.kinds("It was quiet as though the room held its breath."), ["simile"])

    def test_like_a_wall_is_a_simile(self):
        result = self.result("The sea stood like a wall.")
        self.assertEqual([hit["kind"] for hit in result["hits"]], ["simile"])
        self.assertEqual(result["counts"], {"simile": 1})

    def test_appearance_and_wish_with_like_are_not_similes(self):
        for text in ("It looked like rain.", "She would like tea.", "It felt like a stone."):
            self.assertEqual(self.kinds(text), [], text)

    def test_dialogue_shapes_are_counted_not_listed(self):
        result = self.result('"The paper came to the table," she said.')
        self.assertEqual(result["hits"], [])
        self.assertEqual(result["dialogue_hits"], 1)

    def test_the_negated_contrast_is_unchanged(self):
        self.assertEqual(self.kinds("It was not a warning. It was an invitation."), ["negated-contrast"])


class StyleLimitTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def similes(self, n):
        return "\n\n".join("She read it the way a Counter reads a column." for _ in range(n))

    def limits(self, **values):
        return {"style": {"limits": values}}

    def test_a_chapter_over_the_default_simile_limit_gets_one_finding(self):
        result = self.bf.prose_tells(self.similes(7))
        findings = self.bf.style_limit_findings(result["counts"], result["hits"], {})
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["kind"], "style-limit")
        self.assertEqual(findings[0]["of"], "simile")
        self.assertEqual(findings[0]["count"], 7)
        self.assertEqual(findings[0]["limit"], 6)
        self.assertEqual(len(findings[0]["quotes"]), 7)

    def test_a_configured_limit_above_the_count_yields_nothing(self):
        result = self.bf.prose_tells(self.similes(7))
        self.assertEqual(
            self.bf.style_limit_findings(result["counts"], result["hits"], self.limits(similes_per_chapter=8)),
            [],
        )

    def test_a_chapter_under_the_limit_yields_nothing(self):
        result = self.bf.prose_tells(self.similes(2))
        self.assertEqual(self.bf.style_limit_findings(result["counts"], result["hits"], {}), [])

    def test_motif_words_are_counted_by_whole_word_and_each_occurrence(self):
        config = self.limits(motif_words=["ash", "smoke"], motif_per_chapter=3)
        text = "Ash fell on the road. Smoke rose. The ash covered the road. ASH on the sill. The boat reached ashore."
        result = self.bf.prose_tells(text, config)
        self.assertEqual(result["counts"]["motif"], 4)
        findings = self.bf.style_limit_findings(result["counts"], result["hits"], config)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["of"], "motif")
        self.assertEqual(findings[0]["count"], 4)
        self.assertEqual(findings[0]["limit"], 3)

    def test_motif_under_the_limit_yields_nothing(self):
        config = self.limits(motif_words=["ash"], motif_per_chapter=3)
        result = self.bf.prose_tells("Ash fell. The ash covered the road.", config)
        self.assertEqual(self.bf.style_limit_findings(result["counts"], result["hits"], config), [])

    def test_personified_objects_get_a_finding_past_their_default_limit(self):
        result = self.bf.prose_tells("The paper came to the table. The pane woke. The candle gave its grain. The dark took them.")
        findings = self.bf.style_limit_findings(result["counts"], result["hits"], {})
        self.assertEqual([f["of"] for f in findings], ["personified"])
        self.assertEqual(findings[0]["count"], 4)
        self.assertEqual(findings[0]["limit"], 3)


if __name__ == "__main__":
    unittest.main()
