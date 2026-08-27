import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_argv", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module




class RunnerArgvTests(unittest.TestCase):
    """`opencode run` declares `-f, --file` as a yargs array, so it consumes every
    following non-flag token. With the prompt after it the call died with
    `File not found: Process the attached envelope...` before reaching a provider."""

    def setUp(self):
        self.bf = load_module()
        self.prompt = self.bf.WIRE_PROMPT
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.attempt_dir = self.project / ".book-forge" / "runs" / "RUN-0001" / "attempts" / "ATT-0001"
        self.attempt_dir.mkdir(parents=True)
        self.envelope = {"bytes": b'{"schema":1}\n', "hash": "abc", "estimated_input_tokens": 10}

    def _argv(self, role="writer"):
        captured = []

        def fake_run(args, **kwargs):
            captured.append(list(args))
            if "debug" in args:
                model_id, variant = self.bf._expected_pin(role)
                payload = {"name": role, "model": {"providerID": "openrouter", "modelID": model_id}, "variant": variant}
                return mock.Mock(stdout=json.dumps(payload), stderr="", returncode=0)
            return mock.Mock(stdout=json.dumps({"parts": []}), stderr="", returncode=0)

        with mock.patch.object(self.bf.subprocess, "run", side_effect=fake_run):
            try:
                self.bf.run_opencode_role(role, self.envelope, self.attempt_dir)
            except Exception:
                pass
        return next(args for args in captured if "run" in args)

    def test_the_prompt_comes_before_the_file_flag(self):
        argv = self._argv()
        self.assertIn(self.prompt, argv)
        self.assertIn("--file", argv)
        self.assertLess(argv.index(self.prompt), argv.index("--file"), "the prompt must not sit inside the --file array")

    def test_the_file_flag_is_followed_only_by_the_envelope_path(self):
        argv = self._argv()
        after_file = argv[argv.index("--file") + 1:]
        self.assertEqual(len(after_file), 1)
        self.assertTrue(after_file[0].endswith("envelope.wire.json"))

    def test_every_option_still_precedes_the_prompt(self):
        argv = self._argv()
        prompt_at = argv.index(self.prompt)
        for flag in ("--dir", "--agent", "--format", "--title"):
            self.assertLess(argv.index(flag), prompt_at, flag)


if __name__ == "__main__":
    unittest.main()
