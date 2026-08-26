import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_runtime_sync", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeSyncTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")

    def _decay(self):
        """Reproduce a project generated before the effort ladder was corrected."""
        config = json.loads((self.project / "opencode.json").read_text())
        model = config["provider"]["openrouter"]["models"]["deepseek/deepseek-v4-flash-0731"]
        model["options"]["reasoningEffort"] = "medium"
        model["variants"] = {
            "low": {"reasoningEffort": "low"},
            "mid": {"reasoningEffort": "medium"},
            "high": {"reasoningEffort": "high"},
            "xhigh": {"reasoningEffort": "xhigh"},
        }
        (self.project / "opencode.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        agents = self.project / ".opencode" / "agents"
        for name in ("technical-editor", "reviser"):
            path = agents / f"{name}.md"
            path.write_text(path.read_text().replace("variant: high", "variant: mid"))
        (agents / "retired-role.md").write_text("---\ndescription: stale.\n---\n")

    def test_sync_restores_the_pinned_configuration(self):
        self._decay()
        report = self.bf.sync_runtime(self.project)

        self.assertTrue(report["synced"])
        self.assertEqual(report["model"], MODEL)
        self.assertEqual(report["default_effort"], "high")
        self.assertEqual(set(report["variants"]), {"low", "medium", "high", "max"})

        config = json.loads((self.project / "opencode.json").read_text())
        self.assertEqual(config, self.bf._opencode_config())
        model = config["provider"]["openrouter"]["models"]["deepseek/deepseek-v4-flash-0731"]
        self.assertEqual(model["options"]["reasoningEffort"], "high")
        self.assertEqual(set(model["variants"]), {"low", "medium", "high", "max"})
        # Chorus catalog is restored as well (7 models by default).
        self.assertEqual(set(config["provider"]["openrouter"]["models"]), {m.split("/", 1)[1] for m in self.bf.CHORUS_DEFAULT_MODELS})

        agents = self.project / ".opencode" / "agents"
        expected_agents = set(self.bf.ROLE_SPECS) | {self.bf._chorus_advisor_name(m) for m in self.bf.CHORUS_DEFAULT_MODELS} | {self.bf.CHORUS_SYNTHESIZER_AGENT}
        self.assertEqual({path.stem for path in agents.glob("*.md")}, expected_agents)
        for name, (_, variant, _) in self.bf.ROLE_SPECS.items():
            self.assertIn(f"variant: {variant}", (agents / f"{name}.md").read_text())

    def test_every_pinned_variant_is_a_declared_effort(self):
        efforts = set(self.bf.VARIANT_EFFORTS)
        self.assertIn(self.bf.DEFAULT_EFFORT, self.bf.VARIANT_EFFORTS.values())
        for name, (_, variant, _) in self.bf.ROLE_SPECS.items():
            self.assertIn(variant, efforts, name)

    def test_sync_leaves_project_and_control_state_untouched(self):
        before = {
            path: path.read_bytes()
            for path in [self.project / "book-forge.yaml", *sorted((self.project / ".book-forge").rglob("*")) ]
            if path.is_file()
        }
        self._decay()
        self.bf.sync_runtime(self.project)
        after = {path: path.read_bytes() for path in before}
        self.assertEqual(before, after)

    def test_cli_exposes_runtime_sync(self):
        self._decay()
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(self.bf.main(["--project", str(self.project), "runtime", "sync"]), 0)
        self.assertTrue(json.loads(stream.getvalue())["synced"])
        config = json.loads((self.project / "opencode.json").read_text())
        self.assertEqual(config, self.bf._opencode_config())
        self.assertEqual(set(config["provider"]["openrouter"]["models"]), {m.split("/", 1)[1] for m in self.bf.CHORUS_DEFAULT_MODELS})


if __name__ == "__main__":
    unittest.main()


class ChorusCatalogTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def test_glm_flash_is_the_default_and_carries_its_own_pin_and_ladder(self):
        self.assertIn("openrouter/z-ai/glm-5.3-flash", self.bf.CHORUS_DEFAULT_MODELS)
        self.assertNotIn("openrouter/z-ai/glm-5.3", self.bf.CHORUS_DEFAULT_MODELS)
        entry = self.bf._opencode_config()["provider"]["openrouter"]["models"]["z-ai/glm-5.3-flash"]
        self.assertEqual(entry["options"]["provider"]["only"], ["z-ai"])
        self.assertEqual(entry["options"]["reasoningEffort"], "high")
        self.assertEqual(sorted(entry["variants"]), ["high", "low", "max", "medium"])
        self.assertEqual(entry["limit"]["context"], 1048576)

    def test_a_model_the_skill_does_not_know_gets_no_borrowed_provider_pin(self):
        config = self.bf._opencode_config(["openrouter/newvendor/newmodel-1"])
        entry = config["provider"]["openrouter"]["models"]["newvendor/newmodel-1"]
        self.assertNotIn("provider", entry["options"])
        self.assertEqual(entry["options"]["reasoningEffort"], self.bf.DEFAULT_EFFORT)

    def test_an_advisor_without_its_own_lens_falls_back_to_the_generic_prompt(self):
        import tempfile
        from pathlib import Path as _Path
        with tempfile.TemporaryDirectory() as temp:
            project = _Path(temp) / "world"
            self.bf.init_project(project, "World")
            self.bf.ROLE_BUDGETS["advisor-newvendor-newmodel-1"] = (16000, 3000)
            try:
                envelope = self.bf.build_envelope(project, role="advisor-newvendor-newmodel-1", task_capsule={}, imports=[], state={}, tools=[], max_output_tokens=100)
            finally:
                self.bf.ROLE_BUDGETS.pop("advisor-newvendor-newmodel-1", None)
            generic = (_Path(self.bf.__file__).parents[1] / "assets/prompts/chorus-advisor.md").read_text().strip()
            self.assertEqual(envelope["payload"]["role_prompt"], generic)

    def test_qwen_flash_is_the_default_and_declares_the_one_operating_point_it_has(self):
        self.assertIn("openrouter/qwen/qwen3.8-flash", self.bf.CHORUS_DEFAULT_MODELS)
        self.assertNotIn("openrouter/qwen/qwen3.8-max", self.bf.CHORUS_DEFAULT_MODELS)
        entry = self.bf._opencode_config()["provider"]["openrouter"]["models"]["qwen/qwen3.8-flash"]
        self.assertEqual(entry["options"]["provider"]["only"], ["alibaba"])
        # No reasoning_effort on this model: one variant, not a ladder that would be a fiction.
        self.assertEqual(list(entry["variants"]), ["high"])
        self.assertEqual(entry["limit"]["context"], 1000000)

    def test_style_review_runs_on_glm_flash_and_kimi_stays_in_the_chorus(self):
        self.assertIn("openrouter/z-ai/glm-5.3-flash", self.bf.STYLE_REVIEW_MODELS)
        self.assertNotIn("openrouter/moonshotai/kimi-k3", self.bf.STYLE_REVIEW_MODELS)
        self.assertIn("openrouter/moonshotai/kimi-k3", self.bf.CHORUS_DEFAULT_MODELS)

    def test_a_configured_model_outside_the_default_fleet_still_resolves(self):
        """chorus.models accepts any configured model, so its advisor must be runnable."""
        for model in ("openrouter/qwen/qwen3.8-max", "openrouter/z-ai/glm-5.3"):
            with self.subTest(model=model):
                advisor = self.bf._chorus_advisor_name(model)
                self.assertNotIn(model, self.bf.CHORUS_DEFAULT_MODELS)
                self.assertIn(advisor, self.bf.ROLE_BUDGETS)
                self.assertEqual(self.bf._expected_pin(advisor)[0], model.split("/", 1)[1])
