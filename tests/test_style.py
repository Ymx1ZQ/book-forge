import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_style", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StyleResolutionTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def test_a_project_with_no_style_key_gets_the_default_register(self):
        block = self.bf._style_block({})
        self.assertTrue(block.startswith("## Prose style"))
        self.assertIn("Use the common word", block)

    def test_a_named_preset_replaces_the_default(self):
        block = self.bf._style_block({"style": {"preset": "erotic-romance"}})
        self.assertIn("Desire runs on deferral", block)
        self.assertNotIn("Use the common word", block)

    def test_the_neutral_preset_adds_nothing(self):
        self.assertEqual(self.bf._style_block({"style": {"preset": "neutral"}}), "")

    def test_project_directives_are_appended_under_the_preset(self):
        block = self.bf._style_block({"style": {"preset": "neutral", "directives": ["Never name the season."]}})
        self.assertEqual(block, "## Prose style\n\n- Never name the season.")
        block = self.bf._style_block({"style": {"preset": "plain-concrete", "directives": ["Never name the season."]}})
        self.assertTrue(block.endswith("\n\n- Never name the season."))

    def test_an_unknown_preset_fails_instead_of_falling_back(self):
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf._style_block({"style": {"preset": "gothic"}})
        self.assertIn("plain-concrete", str(caught.exception))

    def test_a_malformed_style_block_fails(self):
        for config in ({"style": "plain-concrete"}, {"style": {"preset": ""}}, {"style": {"directives": "one"}}, {"style": {"directives": [1]}}):
            with self.assertRaises(self.bf.BookForgeError):
                self.bf._style_block(config)


class StyleEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "universe"
        self.bf.init_project(self.project, "Universe", "en", chorus_models=[], style_preset="erotic-romance")
        self.book = self.bf.add_book(self.project, "Book One")["id"]
        self.contract = {"id": "CH-0001", "book": self.book, "pov": "Mara", "target_words": 900, "beats": ["She asks."], "imports": []}

    def _role_prompt(self, role, prompt_role=None):
        envelope = self.bf.build_envelope(
            self.project,
            role=role,
            task_capsule=dict(self.contract),
            imports=[],
            state={},
            tools=[],
            max_output_tokens=1000,
            prompt_role=prompt_role,
        )
        return envelope["payload"]["role_prompt"]

    def test_the_writer_and_the_reviser_carry_the_project_register(self):
        for role in ("writer", "reviser"):
            self.assertIn("Desire runs on deferral", self._role_prompt(role))

    def test_the_style_pass_carries_it_under_its_own_lens(self):
        prompt = self._role_prompt("advisor-google-gemini-3-7-flash", prompt_role="style-review")
        self.assertIn("Desire runs on deferral", prompt)

    def test_roles_that_judge_facts_do_not_carry_it(self):
        for role in ("cold-reader", "technical-editor", "canon-auditor"):
            self.assertNotIn("Desire runs on deferral", self._role_prompt(role))

    def test_an_advisor_under_its_chorus_lens_does_not_carry_it(self):
        self.assertNotIn("Desire runs on deferral", self._role_prompt("advisor-google-gemini-3-7-flash"))

    def test_changing_the_register_changes_the_envelope_hash(self):
        before = self.bf.build_envelope(self.project, role="writer", task_capsule=dict(self.contract), imports=[], state={}, tools=[], max_output_tokens=1000)["hash"]
        config_path = self.project / "book-forge.yaml"
        config = json.loads(config_path.read_text())
        config["style"]["preset"] = "plain-concrete"
        config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        after = self.bf.build_envelope(self.project, role="writer", task_capsule=dict(self.contract), imports=[], state={}, tools=[], max_output_tokens=1000)["hash"]
        self.assertNotEqual(before, after)


class StyleInitTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_init_writes_the_default_preset(self):
        project = self.root / "one"
        self.bf.init_project(project, "One", "en", chorus_models=[])
        config = json.loads((project / "book-forge.yaml").read_text())
        self.assertEqual(config["style"], {"preset": "plain-concrete", "directives": []})

    def test_init_honours_a_chosen_preset(self):
        project = self.root / "two"
        self.bf.init_project(project, "Two", "en", chorus_models=[], style_preset="erotic-romance")
        config = json.loads((project / "book-forge.yaml").read_text())
        self.assertEqual(config["style"]["preset"], "erotic-romance")

    def test_init_refuses_a_preset_that_is_not_installed(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.init_project(self.root / "three", "Three", "en", chorus_models=[], style_preset="gothic")
        self.assertFalse((self.root / "three").exists())

    def test_the_installed_presets_are_the_shipped_ones(self):
        self.assertEqual(self.bf.available_style_presets(), ["erotic-romance", "neutral", "plain-concrete"])


if __name__ == "__main__":
    unittest.main()
