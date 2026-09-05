import importlib.util
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_process", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DerivedConfigTests(unittest.TestCase):
    """Every call started the operator's ten MCP servers and waited for them; one
    stalled a run for two hours."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "opencode.json"
        self.config.write_text(json.dumps({
            "model": "openrouter/deepseek/deepseek-v4-flash-0731",
            "provider": {"openrouter": {"options": {}}},
            "permission": {"edit": "deny"},
            "mcp": {"airtable": {"command": ["npx", "airtable"]}, "linkedin": {"command": ["uvx", "scraper@latest"]}},
        }))
        self._restore = {key: os.environ.get(key) for key in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENROUTER_API_KEY")}
        os.environ["OPENCODE_CONFIG"] = str(self.config)
        os.environ["OPENROUTER_API_KEY"] = "sk-must-not-travel"
        self.addCleanup(self._put_back)

    def _put_back(self):
        for key, value in self._restore.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def derived(self):
        environment = self.bf._opencode_environment()
        return environment, json.loads(Path(environment["OPENCODE_CONFIG"]).read_text())

    def test_the_servers_are_gone(self):
        _, config = self.derived()
        self.assertNotIn("mcp", config)

    def test_the_model_pin_and_the_permissions_survive(self):
        _, config = self.derived()
        self.assertEqual(config["model"], "openrouter/deepseek/deepseek-v4-flash-0731")
        self.assertEqual(config["permission"], {"edit": "deny"})
        self.assertIn("openrouter", config["provider"])

    def test_the_provider_key_does_not_travel(self):
        environment, _ = self.derived()
        self.assertNotIn("OPENROUTER_API_KEY", environment)

    def test_opencode_is_pointed_at_the_derived_file_not_the_operator_s(self):
        environment, _ = self.derived()
        self.assertNotEqual(environment["OPENCODE_CONFIG"], str(self.config))

    def test_a_config_that_cannot_be_read_is_left_alone(self):
        self.config.write_text("{ not json")
        environment = self.bf._opencode_environment()
        self.assertEqual(environment.get("OPENCODE_CONFIG"), str(self.config))

    def test_no_config_at_all_is_not_an_error(self):
        os.environ.pop("OPENCODE_CONFIG")
        os.environ["OPENCODE_CONFIG_DIR"] = str(Path(self.temp.name) / "empty")
        self.assertNotIn("OPENCODE_CONFIG", self.bf._opencode_environment())


class WallClockTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def test_a_process_that_never_answers_is_killed_and_reported(self):
        started = time.monotonic()
        with self.assertRaises(self.bf.OpencodeTimeout) as caught:
            self.bf._run_opencode_process(
                ["sh", "-c", "sleep 60"], cwd=Path.cwd(), env=dict(os.environ), timeout=1.0, what="call for writer"
            )
        self.assertLess(time.monotonic() - started, 20)
        self.assertIn("call for writer", str(caught.exception))

    def test_a_process_that_answers_in_time_comes_back_whole(self):
        result = self.bf._run_opencode_process(
            ["sh", "-c", "echo hello"], cwd=Path.cwd(), env=dict(os.environ), timeout=30.0, what="probe"
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "hello")

    def test_what_the_process_wrote_before_the_clock_ran_out_is_kept(self):
        with self.assertRaises(self.bf.OpencodeTimeout) as caught:
            self.bf._run_opencode_process(
                ["sh", "-c", 'echo \'{"sessionID":"ses_1"}\'; sleep 60'],
                cwd=Path.cwd(), env=dict(os.environ), timeout=2.0, what="call for writer",
            )
        self.assertIn("ses_1", caught.exception.stdout)

    def test_the_whole_group_goes_not_just_the_child(self):
        marker = Path(tempfile.mkdtemp()) / "child-still-alive"
        with self.assertRaises(self.bf.OpencodeTimeout):
            self.bf._run_opencode_process(
                ["sh", "-c", f"(sleep 25; touch {marker}) & sleep 60"],
                cwd=Path.cwd(), env=dict(os.environ), timeout=1.0, what="call for writer",
            )
        time.sleep(3)
        self.assertFalse(marker.exists(), "a grandchild outlived the timeout")

    def test_a_session_id_is_found_in_a_partial_stream(self):
        stream = 'not json\n{"type":"step-start"}\n{"type":"text","sessionID":"ses_42"}\n'
        self.assertEqual(self.bf._session_id_in(stream), "ses_42")

    def test_an_empty_stream_names_no_session(self):
        self.assertIsNone(self.bf._session_id_in(""))
        self.assertIsNone(self.bf._session_id_in("Killed\n"))


class InheritedStdinTests(unittest.TestCase):
    """Seven calls launched from a background script produced zero provider events
    in 900s each, while five replays of the same argv, environment and envelope
    answered in 139-294s. opencode inherited the caller's stdin, and a live pipe
    there is something it waits on. The seventeen chapters written before it were
    protected only by having been launched with `nohup`."""

    def setUp(self):
        self.bf = load_module()

    def _with_a_live_pipe_on_fd_zero(self):
        """Put an open pipe on fd 0, the way a background launcher does."""
        read_end, write_end = os.pipe()
        saved = os.dup(0)
        os.dup2(read_end, 0)

        def restore():
            os.dup2(saved, 0)
            for handle in (saved, read_end, write_end):
                try:
                    os.close(handle)
                except OSError:
                    pass

        self.addCleanup(restore)

    def test_a_child_that_reads_stdin_is_not_left_waiting_on_the_caller_s_pipe(self):
        self._with_a_live_pipe_on_fd_zero()
        started = time.monotonic()
        result = self.bf._run_opencode_process(
            ["sh", "-c", "cat > /dev/null; echo answered"],
            cwd=Path.cwd(), env=dict(os.environ), timeout=20.0, what="call for writer",
        )
        self.assertEqual(result.stdout.strip(), "answered")
        self.assertLess(time.monotonic() - started, 10, "the child waited on a pipe nobody was going to write to")

    def test_the_probes_close_it_too(self):
        seen = []
        original = subprocess.run

        def record(argv, **kwargs):
            seen.append((list(argv), kwargs.get("stdin")))
            return original(["true"], capture_output=True, text=True)

        subprocess.run = record
        self.addCleanup(lambda: setattr(subprocess, "run", original))
        try:
            self.bf._opencode_version("opencode")
        except Exception:
            pass
        self.assertTrue(seen, "the version probe did not run")
        for argv, stdin in seen:
            self.assertEqual(stdin, subprocess.DEVNULL, f"{argv} left stdin inherited")


class TheDeclaredBudgetReachesTheProviderTests(unittest.TestCase):
    """`max_output_tokens` was a number written into the payload and read by the
    model as advice: the request asked the provider for 32000 whatever the role
    declared, so a model could spend the whole ceiling reasoning and have nothing
    left to write. The cap is shared between reasoning and completion — an override
    of 120 came back `output: 56, reasoning: 64` — so the budget cannot be a limit
    on what a role writes. It is made room reasoning cannot take instead."""

    def setUp(self):
        self.bf = load_module()

    def test_the_cap_is_the_providers_own_default_plus_the_role_s_budget(self):
        self.assertEqual(self.bf.OPENCODE_OUTPUT_TOKEN_MAX, 32000)
        for role, (_input, output) in self.bf.ROLE_BUDGETS.items():
            self.assertGreater(output, 0, role)
            self.assertGreater(
                self.bf.OPENCODE_OUTPUT_TOKEN_MAX + output, self.bf.OPENCODE_OUTPUT_TOKEN_MAX,
                f"{role} would be given no room its reasoning cannot take",
            )

    def test_the_override_is_the_variable_opencode_reads(self):
        # Read out of the binary and confirmed live before it was written down.
        self.assertEqual(self.bf.OPENCODE_OUTPUT_TOKEN_MAX_ENV, "OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX")

    def test_the_effort_ladder_uses_the_key_the_provider_reads(self):
        """`reasoningEffort` is not a key `@openrouter/ai-sdk-provider` knows: it
        travelled as an unknown field and was dropped, so every variant set no
        effort at all, which is why lowering it never helped any role."""
        config = self.bf._opencode_config()
        for model_id, entry in config["provider"]["openrouter"]["models"].items():
            self.assertIn("reasoning", entry["options"], model_id)
            self.assertIn("effort", entry["options"]["reasoning"], model_id)
            self.assertNotIn("reasoningEffort", entry["options"], model_id)
            for name, variant in entry.get("variants", {}).items():
                self.assertIn("effort", variant.get("reasoning", {}), f"{model_id}/{name}")
                self.assertNotIn("reasoningEffort", variant, f"{model_id}/{name}")


class TimeoutReportingTests(unittest.TestCase):
    """A timeout after the provider accepted the call may already have been paid
    for, and that is a judgement for a person, not a silent retry."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.attempt = self.project / ".book-forge" / "runs" / "RUN-0001" / "attempts" / "ATT-0001"
        self.attempt.mkdir(parents=True)
        self.bf._opencode_binary = lambda: "/bin/true"
        self.bf._verify_opencode_cli = lambda binary: None
        model, variant = self.bf._expected_pin("writer")
        self.probe = json.dumps({"name": "writer", "variant": variant, "model": {"providerID": "openrouter", "modelID": model}})
        self.envelope = self.bf.build_envelope(
            self.project, role="writer", task_capsule={"scope": "test"}, imports=[], state={}, tools=[], max_output_tokens=100
        )

    def _with_call_timing_out(self, stdout):
        calls = []

        def fake(argv, *, cwd, env, timeout, what):
            calls.append(what)
            if "agent probe" in what:
                return subprocess.CompletedProcess(argv, 0, self.probe, "")
            raise self.bf.OpencodeTimeout(what, timeout, stdout, "")

        self.bf._run_opencode_process = fake
        return calls

    def test_a_timeout_before_acceptance_is_retryable(self):
        self._with_call_timing_out("")
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.run_opencode_role("writer", self.envelope, self.attempt)
        self.assertNotIsInstance(caught.exception, self.bf.ProviderOutcomeUnknown)

    def test_a_timeout_after_acceptance_is_an_unknown_outcome(self):
        self._with_call_timing_out('{"type":"step-start","sessionID":"ses_paid"}\n')
        with self.assertRaises(self.bf.ProviderOutcomeUnknown) as caught:
            self.bf.run_opencode_role("writer", self.envelope, self.attempt)
        self.assertEqual(caught.exception.session_id, "ses_paid")

    def test_the_partial_transcript_is_kept_either_way(self):
        self._with_call_timing_out('{"type":"step-start","sessionID":"ses_paid"}\n')
        with self.assertRaises(self.bf.ProviderOutcomeUnknown):
            self.bf.run_opencode_role("writer", self.envelope, self.attempt)
        self.assertIn("ses_paid", (self.attempt / "provider-events.jsonl").read_text())


if __name__ == "__main__":
    unittest.main()
