import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_retry_backoff", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WhatEachFailureNeedsTests(unittest.TestCase):
    """Every retry here was immediate, which is right for one of the two ways a
    provider fails and wrong for the other. Two writer calls went quiet for 900
    seconds each while the identical envelope answered in 340, and a critic
    produced no text twice in a row and read the same chapter on the next
    command. Both times a person restarted it."""

    def setUp(self):
        self.bf = load_module()
        self.slept = []
        self.bf.time.sleep = self.slept.append

    def wait(self, exc, attempt=1):
        return self.bf._wait_before_retry("writer", "CH-0001", attempt, exc, self.bf.run_opencode_role)

    def test_an_unusable_answer_is_asked_again_with_no_wait(self):
        """It was heard and answered badly: what it needs is the feedback, now."""
        self.assertEqual(self.wait(self.bf.BookForgeError("Model output is not contract JSON")), 0.0)
        self.assertEqual(self.slept, [])

    def test_a_timeout_with_nothing_on_the_wire_is_waited_out(self):
        self.assertEqual(self.wait(self.bf.ProviderProducedNothing("no result in 900s")), 60.0)
        self.assertEqual(self.slept, [60.0])

    def test_an_accepted_call_that_produced_no_text_is_silence_too(self):
        """CH-0003's critic: a session on the wire and nothing in it."""
        exc = self.bf.ProviderOutcomeUnknown("ses-1", "Accepted call produced no observable text")
        self.assertEqual(self.wait(exc), 60.0)

    def test_the_wait_grows_with_the_attempt_and_then_stops(self):
        silence = self.bf.ProviderProducedNothing("no result in 900s")
        self.assertEqual(self.wait(silence, attempt=1), 60.0)
        self.assertEqual(self.wait(silence, attempt=2), 180.0)
        self.assertEqual(self.wait(silence, attempt=3), 0.0, "a dead provider costs four minutes, not a night")

    def test_a_substituted_runner_is_never_waited_for(self):
        """A fake provider has no window to wait out; making the engine sleep for
        one turned a two-minute suite into a timeout."""
        silence = self.bf.ProviderProducedNothing("no result in 900s")
        self.assertEqual(self.bf._wait_before_retry("writer", "CH-0001", 1, silence, lambda *a: None), 0.0)
        self.assertEqual(self.slept, [])

    def test_silence_is_told_apart_from_an_answer_nobody_can_read(self):
        self.assertTrue(self.bf._is_silence(self.bf.ProviderProducedNothing("x")))
        self.assertTrue(self.bf._is_silence(self.bf.BookForgeError("OpenCode call for writer produced no result in 900s")))
        self.assertTrue(self.bf._is_silence(self.bf.BookForgeError("Accepted call produced no observable text")))
        self.assertFalse(self.bf._is_silence(self.bf.BookForgeError("Model output contains no JSON object")))
        self.assertFalse(self.bf._is_silence(self.bf.BookForgeError("Writer output word count 300 is outside 490..980")))

    def test_the_ladder_is_bounded_and_declared(self):
        self.assertEqual(sorted(self.bf.SILENCE_RETRY_DELAYS), [1, 2])
        self.assertEqual(self.bf.CRITIC_ATTEMPTS, 3)
        self.assertLessEqual(sum(self.bf.SILENCE_RETRY_DELAYS.values()), 300)


if __name__ == "__main__":
    unittest.main()
