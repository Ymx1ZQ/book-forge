import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InitProjectTests(unittest.TestCase):
    def setUp(self):
        self.book_forge = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_initializes_zero_book_universe_with_pinned_model(self):
        project = self.root / "story-world"

        result = self.book_forge.init_project(project, "Story World", "en")

        self.assertTrue(result["created"])
        config = json.loads((project / "book-forge.yaml").read_text())
        self.assertEqual(config["source_language"], "en")
        self.assertEqual(config["model"], "openrouter/deepseek/deepseek-v4-flash-0731")
        self.assertEqual(config["universe"], "UNI-0001")
        opencode = json.loads((project / "opencode.json").read_text())
        self.assertNotIn("enabled_providers", opencode)
        self.assertEqual(opencode["model"], config["model"])
        self.assertEqual(opencode["small_model"], config["model"])
        self.assertNotIn("whitelist", opencode["provider"]["openrouter"])
        self.assertNotIn("default_agent", opencode)
        self.assertEqual(list((project / "books").iterdir()), [])
        self.assertTrue((project / "universe" / "kernel.md").is_file())
        self.assertTrue((project / ".book-forge" / "project.json").is_file())
        self.assertTrue((project / ".git").is_dir())
        self.assertFalse((project / "CLAUDE.md").exists())
        self.assertEqual(list(project.glob("*.sh")), [])

    def test_rerun_is_idempotent(self):
        project = self.root / "story-world"
        self.book_forge.init_project(project, "Story World", "en")
        before = (project / "book-forge.yaml").read_bytes()

        result = self.book_forge.init_project(project, "Story World", "en")

        self.assertFalse(result["created"])
        self.assertEqual((project / "book-forge.yaml").read_bytes(), before)

    def test_collision_preserves_existing_files(self):
        project = self.root / "story-world"
        project.mkdir()
        marker = project / "notes.txt"
        marker.write_text("keep me")

        with self.assertRaises(self.book_forge.BookForgeError):
            self.book_forge.init_project(project, "Story World", "en")

        self.assertEqual(marker.read_text(), "keep me")
        self.assertEqual(sorted(p.name for p in project.iterdir()), ["notes.txt"])

    def test_injected_failure_leaves_no_partial_project(self):
        project = self.root / "story-world"

        def fail_before_promote(stage):
            if stage == "before_promote":
                raise RuntimeError("injected")

        with self.assertRaises(RuntimeError):
            self.book_forge.init_project(project, "Story World", "en", fault_hook=fail_before_promote)

        self.assertFalse(project.exists())


if __name__ == "__main__":
    unittest.main()
