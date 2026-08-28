import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_requirement", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELP = " ".join(f"{flag} <value>" for flag in ("--agent", "--file", "--format", "--variant", "--dir", "--session"))


class OpenCodeRequirementTests(unittest.TestCase):
    """A CLI that cannot do what the engine calls used to fail as something else:
    an argv whose --file swallowed the prompt reported "File not found: Process the
    attached envelope"."""

    def setUp(self):
        self.bf = load_module()

    def runner(self, *, version="1.18.23", help_text=HELP, debug_ok=True):
        def fake(args, **kwargs):
            if "--version" in args:
                return mock.Mock(stdout=version, stderr="", returncode=0)
            if "run" in args and "--help" in args:
                return mock.Mock(stdout=help_text, stderr="", returncode=0)
            if "debug" in args:
                return mock.Mock(stdout="", stderr="", returncode=0 if debug_ok else 1)
            return mock.Mock(stdout="", stderr="", returncode=0)
        return fake

    def check(self, **kwargs):
        self.bf._OPENCODE_CHECKED.clear()
        with mock.patch.object(self.bf.subprocess, "run", side_effect=self.runner(**kwargs)):
            self.bf._verify_opencode_cli("/usr/bin/opencode")

    def test_a_capable_cli_passes(self):
        self.check()

    def test_a_missing_run_flag_is_named(self):
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.check(help_text=HELP.replace("--file <value>", ""))
        self.assertIn("--file", str(caught.exception))
        self.assertIn("cannot run without them", str(caught.exception))

    def test_a_cli_that_is_too_old_says_the_minimum(self):
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.check(version="1.18.17")
        self.assertIn("1.18.18", str(caught.exception))
        self.assertIn("1.18.17", str(caught.exception))

    def test_a_cli_without_debug_agent_is_refused(self):
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.check(debug_ok=False)
        self.assertIn("debug agent", str(caught.exception))

    def test_the_check_runs_once_per_binary(self):
        self.bf._OPENCODE_CHECKED.clear()
        calls = []

        def counting(args, **kwargs):
            calls.append(args)
            return self.runner()(args, **kwargs)

        with mock.patch.object(self.bf.subprocess, "run", side_effect=counting):
            self.bf._verify_opencode_cli("/usr/bin/opencode")
            self.bf._verify_opencode_cli("/usr/bin/opencode")
        self.assertEqual(len([a for a in calls if "--version" in a]), 1)

    def test_the_skill_declares_the_requirement_where_a_reader_meets_it(self):
        skill = (MODULE_PATH.parents[1] / "SKILL.md").read_text()
        self.assertIn("OpenCode 1.18.18 or newer", skill)
        self.assertIn("debug agent", skill)

    def test_the_installer_refuses_without_opencode(self):
        script = (MODULE_PATH.parents[1] / "install.sh").read_text()
        self.assertIn("requires OpenCode on PATH", script)
        self.assertIn("1.18.18", script)


if __name__ == "__main__":
    unittest.main()
