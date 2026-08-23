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
        # Neither the opening agent nor the catalogue is narrowed: the roles carry their own pins.
        self.assertNotIn("default_agent", config)
        self.assertNotIn("whitelist", config["provider"]["openrouter"])
        model = config["provider"]["openrouter"]["models"]["deepseek/deepseek-v4-flash-0731"]
        self.assertEqual(model["options"]["reasoningEffort"], "high")
        self.assertFalse(model["options"]["provider"]["allow_fallbacks"])
        self.assertEqual(model["variants"], {
            "low": {"reasoningEffort": "low"},
            "high": {"reasoningEffort": "high"},
            "max": {"reasoningEffort": "max"},
        })

        expected = {
            "book-forge-orchestrator": ("primary", "max"),
            "designer": ("all", "max"),
            "writer": ("all", "low"),
            "cold-reader": ("all", "low"),
            "technical-editor": ("all", "high"),
            "reviser": ("all", "high"),
            "canon-auditor": ("all", "max"),
            "translator": ("all", "low"),
            "judge": ("all", "max"),
            "book-forge-smoke": ("primary", "low"),
        }
        files = {path.stem: path.read_text() for path in (self.project / ".opencode/agents").glob("*.md")}
        # Primary roles must be present with exact pins; chorus advisors are additive.
        self.assertTrue(set(expected) <= set(files), f"missing primary roles: {set(expected) - set(files)}")
        expected_chorus = {self.bf._chorus_advisor_name(m) for m in self.bf.CHORUS_DEFAULT_MODELS} | {self.bf.CHORUS_SYNTHESIZER_AGENT}
        self.assertTrue(expected_chorus <= set(files), f"missing chorus agents: {expected_chorus - set(files)}")
        self.assertEqual(set(files), set(expected) | expected_chorus)
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
        # Chorus advisors carry their own model pin and variant from CHORUS_MODEL_CONFIGS.
        for advisor in expected_chorus:
            body = files[advisor]
            self.assertIn("mode: all", body)
            self.assertIn('"*": deny', body)
            self.assertNotIn("bash:", body)
        # Opencode config must expose the full chorus catalog (default 7 models).
        self.assertEqual(set(config["provider"]["openrouter"]["models"]), {m.split("/", 1)[1] for m in self.bf.CHORUS_DEFAULT_MODELS})

    def test_local_runtime_has_required_model_and_json_sessions(self):
        report = self.bf.verify_runtime(self.project)
        self.assertEqual(report["model"], MODEL)
        self.assertTrue(report["json_events"])
        self.assertTrue(report["session_resume"])
        self.assertEqual(set(report["variants"]), {"low", "high", "max"})


class ChorusPinResolutionTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")

    def test_project_root_from_resolves_run_and_chorus_depths(self):
        run_attempt = self.project / ".book-forge" / "runs" / "RUN-0001" / "attempts" / "ATT-0001"
        run_attempt.mkdir(parents=True)
        self.assertEqual(self.bf._project_root_from(run_attempt), self.project)
        chorus_tmp = self.project / ".book-forge" / "chorus" / ".tmp" / ".chorus-grok-4-6-ab12"
        chorus_tmp.mkdir(parents=True)
        self.assertEqual(self.bf._project_root_from(chorus_tmp), self.project)

    def test_project_root_from_raises_on_orphan(self):
        orphan = Path(self.temp.name) / "orphan" / "deep"
        orphan.mkdir(parents=True)
        with self.assertRaises(self.bf.BookForgeError):
            self.bf._project_root_from(orphan)

    def test_expected_pin_matches_written_agents(self):
        self.assertEqual(self.bf._expected_pin("designer"), ("deepseek/deepseek-v4-flash-0731", "max"))
        self.assertEqual(self.bf._expected_pin("writer"), ("deepseek/deepseek-v4-flash-0731", "low"))
        self.assertEqual(self.bf._expected_pin("advisor-qwen-qwen3-8-max"), ("qwen/qwen3.8-max", "xhigh"))
        self.assertEqual(self.bf._expected_pin("advisor-openai-gpt-5-6-luna"), ("openai/gpt-5.6-luna", "high"))
        pro_id = self.bf.CHORUS_SYNTHESIZER.split("/", 1)[1]
        cfg = self.bf.CHORUS_MODEL_CONFIGS.get(self.bf.CHORUS_SYNTHESIZER, {})
        variant = str(cfg.get("default_effort", "max"))
        self.assertEqual(self.bf._expected_pin(self.bf.CHORUS_SYNTHESIZER_AGENT), (pro_id, variant))
        with self.assertRaises(self.bf.BookForgeError):
            self.bf._expected_pin("no-such-role")


if __name__ == "__main__":
    unittest.main()
