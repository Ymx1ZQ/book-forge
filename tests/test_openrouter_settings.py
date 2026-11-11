import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_openrouter", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OpenRouterSettingsTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def provider(self, config):
        return self.bf._opencode_config([], config)["provider"]["openrouter"]

    def test_the_block_writes_key_file_reference_and_app_name(self):
        provider = self.provider({"openrouter": {"api_key_file": "~/keys/area", "app_name": "my-app"}})
        self.assertEqual(provider["options"], {"apiKey": "{file:~/keys/area}", "headers": {"X-Title": "my-app"}})

    def test_without_the_block_the_output_is_unchanged(self):
        self.assertNotIn("options", self.provider({}))

    def test_a_key_value_is_refused(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.provider({"openrouter": {"api_key_file": "sk-or-v1-abc"}})

    def test_init_writes_the_block_and_runtime_sync_keeps_it(self):
        project = self.dir / "w"
        self.bf.init_project(project, "W", chorus_models=[], style_preset="neutral",
                             openrouter_key_file="~/keys/area", openrouter_app_name="my-app")
        written = json.loads((project / "opencode.json").read_text())
        self.assertEqual(written["provider"]["openrouter"]["options"]["apiKey"], "{file:~/keys/area}")
        config = json.loads((project / "book-forge.yaml").read_text())
        self.assertEqual(config["openrouter"], {"api_key_file": "~/keys/area", "app_name": "my-app"})
        rebuilt = self.bf._opencode_config(self.bf._runtime_models(config), config)
        self.assertEqual(rebuilt["provider"]["openrouter"]["options"], written["provider"]["openrouter"]["options"])

    def test_init_refuses_a_key_value(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.init_project(self.dir / "x", "X", chorus_models=[], style_preset="neutral", openrouter_key_file="sk-abc")


if __name__ == "__main__":
    unittest.main()
