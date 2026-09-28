import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


def _project_catalogue(bf):
    """What a generated project carries: the models its own config names, no more.

    A default project names the default chorus, the default style reviewers, the
    default synthesizer and the default role pins, and every one of them is in the
    default fleet. grok is not: it used to be appended to every project (M52).
    """
    models = list(bf.CHORUS_DEFAULT_MODELS)
    for extra in list(bf.STYLE_REVIEW_MODELS) + [bf.CHORUS_SYNTHESIZER]:
        if extra not in models:
            models.append(extra)
    return models


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4.1-flash"


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
        model = config["provider"]["openrouter"]["models"]["deepseek/deepseek-v4.1-flash"]
        model["options"]["reasoning"]["effort"] = "medium"
        model["variants"] = {
            "low": {"reasoning": {"effort": "low"}},
            "mid": {"reasoning": {"effort": "medium"}},
            "high": {"reasoning": {"effort": "high"}},
            "xhigh": {"reasoning": {"effort": "xhigh"}},
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
        model = config["provider"]["openrouter"]["models"]["deepseek/deepseek-v4.1-flash"]
        self.assertEqual(model["options"]["reasoning"]["effort"], "high")
        self.assertEqual(set(model["variants"]), {"low", "medium", "high", "max"})
        # Chorus catalog is restored as well (7 models by default).
        self.assertEqual(set(config["provider"]["openrouter"]["models"]), {m.split("/", 1)[1] for m in _project_catalogue(self.bf)})

        agents = self.project / ".opencode" / "agents"
        expected_agents = (
            set(self.bf.ROLE_SPECS)
            | {self.bf._chorus_advisor_name(m) for m in _project_catalogue(self.bf)}
            | {self.bf._writer_candidate_name(m) for m in _project_catalogue(self.bf)}
            | {self.bf._translator_candidate_name(m) for m in _project_catalogue(self.bf)}
            | {self.bf._reviser_candidate_name(m) for m in _project_catalogue(self.bf)}
            | {self.bf.CHORUS_SYNTHESIZER_AGENT}
        )
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
        self.assertEqual(set(config["provider"]["openrouter"]["models"]), {m.split("/", 1)[1] for m in _project_catalogue(self.bf)})


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
        self.assertEqual(entry["options"]["reasoning"]["effort"], "high")
        self.assertEqual(sorted(entry["variants"]), ["high", "low", "max", "medium"])
        self.assertEqual(entry["limit"]["context"], 1048576)

    def test_a_model_the_skill_does_not_know_gets_no_borrowed_provider_pin(self):
        config = self.bf._opencode_config(["openrouter/newvendor/newmodel-1"])
        entry = config["provider"]["openrouter"]["models"]["newvendor/newmodel-1"]
        self.assertNotIn("provider", entry["options"])
        self.assertEqual(entry["options"]["reasoning"]["effort"], self.bf.DEFAULT_EFFORT)

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

    def test_style_review_runs_on_glm_flash_and_grok_stays_out_of_the_fleet(self):
        """grok answers the spicy rule, not the style pass and not the default chorus."""
        self.assertIn("openrouter/z-ai/glm-5.3-flash", self.bf.STYLE_REVIEW_MODELS)
        self.assertNotIn("openrouter/x-ai/grok-4.6", self.bf.STYLE_REVIEW_MODELS)
        self.assertNotIn("openrouter/x-ai/grok-4.6", self.bf.CHORUS_DEFAULT_MODELS)
        self.assertIn("openrouter/x-ai/grok-4.6", self.bf.CHORUS_MODEL_CONFIGS)

    def test_a_configured_model_outside_the_default_fleet_still_resolves(self):
        """chorus.models accepts any configured model, so its advisor must be runnable."""
        for model in ("openrouter/x-ai/grok-4.6",):
            with self.subTest(model=model):
                advisor = self.bf._chorus_advisor_name(model)
                self.assertNotIn(model, self.bf.CHORUS_DEFAULT_MODELS)
                self.assertIn(advisor, self.bf.ROLE_BUDGETS)
                self.assertEqual(self.bf._expected_pin(advisor)[0], model.split("/", 1)[1])


class TheProjectDecidesWhichModelsItsRuntimeCanCallTests(unittest.TestCase):
    """M52. The Ground Truth pilot's `runtime sync` wrote grok-4.6 into opencode.json
    and four grok agents although the project declared no grok model, and left
    `chorus-synthesizer.md` on gemini-3.8-flash although the project named
    deepseek-v4.1-flash as its synthesizer."""

    GROK = "openrouter/x-ai/grok-4.6"
    DEEPSEEK = "openrouter/deepseek/deepseek-v4.1-flash"
    GLM = "openrouter/z-ai/glm-5.3-flash"
    QWEN = "openrouter/qwen/qwen3.8-flash"
    GEMINI = "openrouter/google/gemini-3.8-flash"

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")

    def configure(self, **chorus):
        path = self.project / "book-forge.yaml"
        config = json.loads(path.read_text())
        config["chorus"] = {"enabled": True, "post_enabled": True, **chorus}
        path.write_text(json.dumps(config))
        return self.bf.sync_runtime(self.project)

    def catalogue(self):
        return set(json.loads((self.project / "opencode.json").read_text())["provider"]["openrouter"]["models"])

    def agents(self):
        return {path.stem: path.read_text() for path in (self.project / ".opencode" / "agents").glob("*.md")}

    def test_the_pilot_config_writes_no_grok_file(self):
        self.configure(
            models=[self.DEEPSEEK, self.GLM, self.QWEN],
            style_review={"default_models": [self.GLM, self.QWEN, self.GEMINI]},
            synthesizer=self.DEEPSEEK,
        )
        self.assertNotIn("x-ai/grok-4.6", self.catalogue())
        grok = [name for name, body in self.agents().items() if "grok" in name or "grok" in body]
        self.assertEqual(grok, [])

    def test_a_project_naming_grok_still_gets_it(self):
        self.configure(models=[self.DEEPSEEK, self.GROK])
        self.assertIn("x-ai/grok-4.6", self.catalogue())
        self.assertIn(self.bf._chorus_advisor_name(self.GROK), self.agents())

    def test_a_style_rule_naming_grok_is_a_declaration(self):
        self.configure(models=[self.DEEPSEEK], style_review={"rules": [{"tags": ["spicy"], "reviewer": self.GROK}]})
        self.assertIn("x-ai/grok-4.6", self.catalogue())
        self.assertIn(self.bf._chorus_advisor_name(self.GROK), self.agents())

    def test_candidate_agents_exist_only_for_configured_models(self):
        self.configure(models=[self.DEEPSEEK], style_review={"enabled": False})
        runtime = set(self.bf._runtime_models(json.loads((self.project / "book-forge.yaml").read_text())))
        self.assertNotIn(self.GLM, runtime)
        self.assertNotIn(self.QWEN, runtime)
        agents = self.agents()
        for model in (self.GLM, self.QWEN, self.GROK):
            for namer in (self.bf._writer_candidate_name, self.bf._translator_candidate_name,
                          self.bf._reviser_candidate_name, self.bf._chorus_advisor_name):
                self.assertNotIn(namer(model), agents)
        self.assertEqual({model.split("/", 1)[1] for model in runtime}, self.catalogue())

    def test_style_review_models_are_written_while_style_review_is_on(self):
        self.configure(models=[self.DEEPSEEK])
        for model in self.bf.STYLE_REVIEW_MODELS:
            self.assertIn(self.bf._chorus_advisor_name(model), self.agents())

    def test_the_configured_synthesizer_is_written_reported_and_dispatched(self):
        report = self.configure(models=[self.DEEPSEEK, self.GLM], synthesizer=self.DEEPSEEK)
        synthesizer = self.agents()[self.bf.CHORUS_SYNTHESIZER_AGENT]
        self.assertIn(f"model: {self.DEEPSEEK}\n", synthesizer)
        self.assertEqual(report["chorus_synthesizer"], self.DEEPSEEK)
        config = json.loads((self.project / "book-forge.yaml").read_text())
        self.assertEqual(self.bf._role_pin(config, self.bf.CHORUS_SYNTHESIZER_AGENT)[0], self.DEEPSEEK)
        seen = []

        def runner(role, envelope, attempt_dir):
            seen.append((role, envelope["payload"]["model"]))
            return {"text": json.dumps({"patches": []}), "provider": "openrouter", "model": "deepseek/deepseek-v4.1-flash",
                    "variant": "high", "session_id": "s", "tokens": {}, "cost": 0, "latency_ms": 1, "finish": "stop"}

        chorus = self.project / ".book-forge" / "chorus" / "universe" / "RUN-1"
        chorus.mkdir(parents=True)
        (chorus / "advisor-a.json").write_text(json.dumps({"findings": [{"id": "F-1", "severity": "note", "issue": "x"}]}))
        synthesis = self.bf.chorus_synthesize(self.project, provider=runner)
        self.assertEqual(seen and seen[0][0], self.bf.CHORUS_SYNTHESIZER_AGENT)
        self.assertIn(self.DEEPSEEK.split("/", 1)[1], seen[0][1])
        self.assertEqual(synthesis["synthesizer"], self.DEEPSEEK)

    def test_an_unset_synthesizer_is_the_default(self):
        self.configure(models=[self.DEEPSEEK])
        self.assertIn(f"model: {self.bf.CHORUS_SYNTHESIZER}\n", self.agents()[self.bf.CHORUS_SYNTHESIZER_AGENT])

    def test_qwen_sends_opencode_s_reasoning_budget_and_no_effort(self):
        """OpenCode 1.18.32 gives qwen3.8-flash a `high` variant of its own,
        `reasoning: {max_tokens}`, because the model offers a budget and no effort.
        An effort beside it made OpenRouter answer HTTP 400, "Only one of
        reasoning.effort and reasoning.max_tokens can be specified"."""
        self.configure(models=[self.DEEPSEEK, self.QWEN])
        entry = json.loads((self.project / "opencode.json").read_text())["provider"]["openrouter"]["models"]["qwen/qwen3.8-flash"]
        self.assertNotIn("reasoning", entry["options"])
        self.assertEqual(entry["variants"], {"high": {}})
        self.assertIn("variant: high", self.agents()[self.bf._chorus_advisor_name(self.QWEN)])
        other = json.loads((self.project / "opencode.json").read_text())["provider"]["openrouter"]["models"]["deepseek/deepseek-v4.1-flash"]
        self.assertEqual(other["options"]["reasoning"], {"effort": "high"})
