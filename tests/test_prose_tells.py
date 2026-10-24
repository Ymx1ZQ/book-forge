"""The negated contrast and the row of negated fragments, found by pattern in narration."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
PROMPTS = Path(__file__).parents[1] / "assets" / "prompts"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_tells", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProseTellScannerTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def kinds(self, text):
        return [hit["kind"] for hit in self.bf.prose_tells(text)["hits"]]

    def test_the_split_contrast_is_found(self):
        hits = self.bf.prose_tells("# T\n\nShe read the letter twice. It was not a warning. It was an invitation.")["hits"]
        self.assertEqual([hit["kind"] for hit in hits], ["negated-contrast"])
        self.assertEqual(hits[0]["paragraph"], 2)
        self.assertIn("It was an invitation", hits[0]["quote"])

    def test_the_one_sentence_contrast_is_found_when_both_halves_match(self):
        self.assertEqual(self.kinds("He stayed, not for the money but for the silence after."), ["negated-contrast"])
        self.assertEqual(self.kinds("She came not because of him, but because of the boat."), ["negated-contrast"])

    def test_a_but_that_opens_a_new_clause_is_not_the_contrast(self):
        self.assertEqual(self.kinds("The tea was not supper, but his hands had already reached for the cup."), [])

    def test_a_row_of_negated_fragments_is_found(self):
        self.assertEqual(self.kinds("She counted what was left. Not the house. Not the debt."), ["negated-row"])

    def test_dialogue_is_counted_and_not_listed(self):
        result = self.bf.prose_tells('# T\n\n"It was not a warning. It was an invitation," Ana said.')
        self.assertEqual(result["hits"], [])
        self.assertEqual(result["dialogue_hits"], 1)

    def test_plain_narration_yields_nothing(self):
        text = "# T\n\nBinta packed the chalk against her teeth. The tide had gone out. She did not look back at the tower."
        self.assertEqual(self.bf.prose_tells(text), {"hits": [], "dialogue_hits": 0})


class StyleCapsuleTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]
        config_path = self.project / "book-forge.yaml"
        config = json.loads(config_path.read_text())
        config["chorus"] = {"enabled": True, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER,
                            "style_review": {"enabled": True, "default_models": ["openrouter/z-ai/glm-5.3-flash"]}}
        config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.contract = {"id": "CH-0001", "book": self.book, "pov": "CHR-0001", "target_words": 900,
                         "beats": ["Mara opens the log"], "imports": []}
        self.capsules = []

    def provider(self, role, envelope, attempt_dir):
        self.capsules.append(json.loads(envelope["bytes"])["task"])
        return {"text": json.dumps({"findings": []}), "provider": "openrouter",
                "model": "openrouter/z-ai/glm-5.3-flash", "variant": "high", "session_id": "ses-1",
                "tokens": {"input": 10, "output": 10}, "cost": 0.0, "latency_ms": 1, "finish": "stop"}

    def review(self, draft):
        self.bf._call_style_review(self.bf._project_root(self.project), self.book, "CH-0001",
                                   self.contract, draft, self.provider)
        self.assertEqual(len(self.capsules), 1)
        return self.capsules[0]

    def test_the_reviewer_receives_the_located_hits(self):
        capsule = self.review("# T\n\nMara read the log. It was not a list. It was a confession.")
        self.assertEqual([hit["kind"] for hit in capsule["prose_tells"]], ["negated-contrast"])
        self.assertEqual(capsule["prose_tells"][0]["paragraph"], 2)

    def test_a_chapter_without_hits_carries_no_key(self):
        self.assertNotIn("prose_tells", self.review("# T\n\nMara read the log and closed it."))


class PromptTests(unittest.TestCase):
    def test_the_style_prompt_names_the_capsule_key(self):
        self.assertIn("`prose_tells`", (PROMPTS / "style-review.md").read_text(encoding="utf-8"))

    def test_the_writer_is_told_about_the_negated_contrast(self):
        self.assertIn("Say what a thing is without first saying what it is not", (PROMPTS / "writer.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
