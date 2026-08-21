import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_roles", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RoleTopologyTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")

    def test_generates_exact_pins_and_fail_closed_roles(self):
        config = json.loads((self.project / "opencode.json").read_text())
        self.assertEqual(config["model"], MODEL)
        self.assertEqual(config["small_model"], MODEL)
        self.assertEqual(config["default_agent"], "book-forge-orchestrator")
        model = config["provider"]["openrouter"]["models"]["deepseek/deepseek-v4-flash-0731"]
        self.assertEqual(model["options"]["reasoningEffort"], "medium")
        self.assertFalse(model["options"]["provider"]["allow_fallbacks"])
        self.assertEqual(set(model["variants"]), {"low", "mid", "high", "xhigh"})

        expected = {
            "book-forge-orchestrator": ("primary", "high"),
            "designer": ("subagent", "high"),
            "writer": ("subagent", "low"),
            "cold-reader": ("subagent", "low"),
            "technical-editor": ("subagent", "mid"),
            "reviser": ("subagent", "mid"),
            "canon-auditor": ("subagent", "high"),
            "translator": ("subagent", "low"),
            "judge": ("subagent", "high"),
            "book-forge-smoke": ("primary", "low"),
        }
        files = {path.stem: path.read_text() for path in (self.project / ".opencode/agents").glob("*.md")}
        self.assertEqual(set(files), set(expected))
        for name, (mode, variant) in expected.items():
            body = files[name]
            self.assertIn(f"mode: {mode}", body)
            self.assertIn(f"model: {MODEL}", body)
            self.assertIn(f"variant: {variant}", body)
            self.assertIn('"*": deny', body)
            if name != "book-forge-orchestrator":
                self.assertNotIn("bash:", body)
                self.assertNotIn("write:", body)
                self.assertNotIn("task:", body)
        self.assertIn("book-forge: allow", files["book-forge-smoke"])

    def test_local_runtime_has_required_model_and_json_sessions(self):
        report = self.bf.verify_runtime(self.project)
        self.assertEqual(report["model"], MODEL)
        self.assertTrue(report["json_events"])
        self.assertTrue(report["session_resume"])
        self.assertEqual(set(report["variants"]), {"low", "mid", "high", "xhigh"})


if __name__ == "__main__":
    unittest.main()
