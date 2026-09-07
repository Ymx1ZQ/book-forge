import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_provider_error", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def events(*rows):
    return "".join(json.dumps(row) + "\n" for row in rows)


KEY_LIMIT = {
    "type": "error",
    "sessionID": "ses_f86e81db",
    "error": {
        "name": "APIError",
        "data": {"message": "Key limit exceeded (daily limit). Manage it using https://openrouter.ai/workspaces/default/keys/64b8"},
    },
}


class WhatTheProviderSaidTests(unittest.TestCase):
    """landfall spent three stage attempts per task, a model swap and a memory
    lookup on `Key limit exceeded (daily limit)` — a message the engine had already
    written to `provider-events.jsonl` and then replaced, in what it showed the
    operator, with `OpenCode ended without a complete result`."""

    def setUp(self):
        self.bf = load_module()

    def test_the_providers_message_is_read_out_of_the_event_stream(self):
        said = self.bf._provider_errors_in([KEY_LIMIT])
        self.assertEqual(said, ["APIError: Key limit exceeded (daily limit). Manage it using https://openrouter.ai/workspaces/default/keys/64b8"])

    def test_an_error_without_data_still_gives_its_name(self):
        said = self.bf._provider_errors_in([{"type": "error", "error": {"name": "UnknownError"}}])
        self.assertEqual(said, ["UnknownError"])

    def test_rows_that_are_not_errors_say_nothing(self):
        self.assertEqual(self.bf._provider_errors_in([{"type": "step_finish", "part": {"reason": "stop"}}]), [])

    def test_a_spending_limit_is_recognised(self):
        self.assertTrue(self.bf._is_provider_limit(self.bf._provider_errors_in([KEY_LIMIT])))

    def test_an_ordinary_failure_is_not_called_a_limit(self):
        said = self.bf._provider_errors_in([
            {"type": "error", "error": {"name": "APIError", "data": {"message": "upstream connect timeout"}}},
        ])
        self.assertFalse(self.bf._is_provider_limit(said), "a transient failure must stay retryable")


class WhatTheOperatorIsToldTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.attempt_dir = self.project / ".book-forge" / "runs" / "RUN-0001" / "attempts" / "ATT-0001"
        self.attempt_dir.mkdir(parents=True)
        self.envelope = {"bytes": b'{"schema":1}\n', "hash": "abc", "estimated_input_tokens": 10}

    def _call(self, stdout, returncode=1, stderr="OpenCode ended without a complete result"):
        def fake_run(args, **kwargs):
            if "debug" in args:
                model_id, variant = self.bf._expected_pin("writer")
                return mock.Mock(
                    stdout=json.dumps({"name": "writer", "model": {"providerID": "openrouter", "modelID": model_id}, "variant": variant}),
                    stderr="", returncode=0,
                )
            return mock.Mock(stdout=stdout, stderr=stderr, returncode=returncode)

        with mock.patch.object(self.bf, "_verify_opencode_cli", lambda binary: None), \
             mock.patch.object(self.bf, "_run_opencode_process", side_effect=fake_run):
            return self.bf.run_opencode_role("writer", self.envelope, self.attempt_dir)

    def test_a_key_limit_is_raised_as_its_own_condition(self):
        with self.assertRaises(self.bf.ProviderLimitReached) as raised:
            self._call(events(KEY_LIMIT))
        self.assertIn("Key limit exceeded (daily limit)", str(raised.exception))

    def test_a_key_limit_is_not_reported_as_an_unknown_outcome(self):
        """`ProviderOutcomeUnknown` is what the stage retries. A refusal settled
        before the call was made spends three windows of latency for the same answer."""
        with self.assertRaises(self.bf.ProviderLimitReached):
            self._call(events(KEY_LIMIT))

    def test_an_ordinary_provider_error_still_quotes_the_provider(self):
        stream = events({
            "type": "error", "sessionID": "ses-1",
            "error": {"name": "APIError", "data": {"message": "upstream connect timeout"}},
        })
        with self.assertRaises(self.bf.ProviderOutcomeUnknown) as raised:
            self._call(stream)
        self.assertIn("upstream connect timeout", str(raised.exception))

    def test_a_stream_with_no_error_row_falls_back_to_stderr(self):
        stream = events({"type": "step_start", "sessionID": "ses-1"})
        with self.assertRaises(self.bf.ProviderOutcomeUnknown) as raised:
            self._call(stream, stderr="the CLI exited 1")
        self.assertIn("the CLI exited 1", str(raised.exception))


class WhatTheRunDoesWithItTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def test_the_stage_loop_lets_a_limit_through_instead_of_retrying(self):
        """The retry lives in `advance`'s `stage`, which catches `BookForgeError`.
        `ProviderLimitReached` is one, so it has to be named to escape."""
        source = MODULE_PATH.read_text(encoding="utf-8")
        body = source[source.index("    def stage(name: str, action) -> object:"):]
        body = body[:body.index("raise AdvanceHalted")]
        self.assertIn("except ProviderLimitReached:", body)
        self.assertLess(
            body.index("except ProviderLimitReached:"),
            body.index("except BookForgeError as exc:"),
            "a subclass caught after its base never fires",
        )


if __name__ == "__main__":
    unittest.main()
