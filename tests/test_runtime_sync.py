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
