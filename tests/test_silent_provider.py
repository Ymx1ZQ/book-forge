import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_silent_provider", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def proposal(chapter_count=6):
    return {
        "premise": "A diver must decide whether memory can be owned.",
        "entry_state": {"CHR-0001": "isolated"},
        "arc": ["refusal", "cost", "choice"],
        "exit_boundary": {"CHR-0001": "committed"},
        "chapters": [
            {
                "id": f"CH-{order:04d}", "order": order, "title": f"Tide {order}", "pov": "CHR-0001",
                "beats": ["A choice opens the conflict"], "plants": [], "reveals": [],
                "target_words": 1800, "imports": ["UNI-0001#kernel"],
                "pivotal": "opener" if order == 1 else ("finale" if order == chapter_count else None),
            }
            for order in range(1, chapter_count + 1)
        ],
    }


class SilentOnSomeWindows:
    """A provider that goes quiet on named audit passes, the way a hung call does."""

    def __init__(self, bf, silent, forever=False):
        self.bf = bf
        self.silent = set(silent)
        self.forever = forever
        self.calls = []
        self.asked = []

    def _slug(self, envelope):
        """The range a pass covers. Named by range and not by kind, because the
        last-resort call about a chapter alone drops the neighbourhood and would
        otherwise read as a different pass than the one that went quiet."""
        task = envelope["payload"]["task"]
        scope = task.get("design_scope") or {}
        rows = scope.get("proposal", {}).get("chapters", [])
        if not rows:
            return ""
        return f"{rows[0]['order']}-{rows[-1]['order']}"

    def __call__(self, role, envelope, attempt_dir):
        self.calls.append(role)
        if role == "canon-auditor":
            slug = self._slug(envelope)
            self.asked.append(slug)
            if slug in self.silent:
                if not self.forever:
                    self.silent.discard(slug)
                raise self.bf.ProviderProducedNothing("OpenCode call for canon-auditor produced no result in 900s")
            value = {"findings": []}
            if "neighbourhood_digest" not in (envelope["payload"]["task"].get("design_scope") or {}):
                value.update({"paid": [], "added": []})
        elif role == "designer":
            chunk = envelope["payload"]["task"].get("chunk") or {}
            chapters = proposal()["chapters"]
            if chunk.get("category") == "spine":
                value = {
                    **{key: item for key, item in proposal().items() if key != "chapters"},
                    "chapter_outline": [{key: row[key] for key in ("id", "order", "pov")} for row in chapters],
                }
            elif chunk.get("category") == "chapters":
                first, last = int(chunk["first_order"]), int(chunk["last_order"])
                value = {"chapters": [row for row in chapters if first <= row["order"] <= last]}
            else:
                value = proposal()
        else:
            value = {"findings": [], "suggestions": []}
        return {
            "text": json.dumps(value),
            "provider": "openrouter",
            "model": MODEL,
            "variant": self.bf.ROLE_SPECS[role][1] if role in self.bf.ROLE_SPECS else "high",
            "session_id": f"ses-{len(self.calls)}",
            "tokens": {"input": envelope["estimated_input_tokens"], "output": 200},
            "cost": 0.001,
            "latency_ms": 5,
            "finish": "stop",
        }


class ACallThatNeverAnswersIsAPassToReAskTests(unittest.TestCase):
    """Landfall's re-audit ended on `produced no result in 900s` with six windows
    already answered. Nothing was accepted, so nothing was paid for, and the pass
    could simply have been asked again."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["chorus"] = {"enabled": False, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.book = self.bf.add_book(self.project, "A")["id"]
        (self.project / f"books/{self.book}/book-brief.json").write_text(json.dumps(
            {"schema": 1, "premise": "A diver must decide.", "characters": ["Mara"], "plot": ["dive"], "tone": "quiet"}
        ))

    def test_a_window_that_goes_quiet_once_is_split_and_the_audit_reaches_a_verdict(self):
        provider = SilentOnSomeWindows(self.bf, silent={"3-4"})
        record = self.bf.execute_book_design(self.project, self.book, provider=provider)
        self.assertEqual(record["state"], "design_clean")
        self.assertIn("3-3", provider.asked, "the silent window was halved and asked again")
        self.assertIn("4-4", provider.asked)

    def test_a_window_that_is_quiet_every_time_is_set_aside_and_the_rest_is_audited(self):
        """Ending the run here would throw away every pass that did answer."""
        provider = SilentOnSomeWindows(self.bf, silent={"3-4", "3-3", "4-4"}, forever=True)
        record = self.bf.execute_book_design(self.project, self.book, provider=provider)
        self.assertEqual(record["state"], "design_clean")
        unread = [row for row in record["unverifiable"] if str(row["id"]).endswith("unread")]
        self.assertTrue(unread, "the window that was never answered is recorded as unread")
        self.assertIn("5-6", provider.asked, "the audit went on to the windows after it")

    def test_an_accepted_call_that_goes_quiet_still_stops_for_a_person(self):
        """A session id on the wire means a retry may pay twice, which is not the
        engine's call to make."""
        self.assertTrue(issubclass(self.bf.ProviderProducedNothing, self.bf.BookForgeError))
        self.assertFalse(issubclass(self.bf.ProviderProducedNothing, self.bf.ProviderOutcomeUnknown))
        self.assertFalse(issubclass(self.bf.ProviderOutcomeUnknown, self.bf.ProviderProducedNothing))

    def test_a_timeout_with_a_session_id_is_reported_as_outcome_unknown(self):
        exc = self.bf.OpencodeTimeout("call for canon-auditor", 900, '{"sessionID":"ses-9"}', "")
        self.assertEqual(self.bf._session_id_in(exc.stdout), "ses-9")
        self.assertEqual(self.bf._session_id_in("nothing on the wire"), None)


class ADesignChunkThatGoesQuietTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def test_a_quiet_chunk_is_split_rather_than_ending_the_design(self):
        """The caller already splits on an answer that came back empty, and a call
        that never answered is the same event."""
        source = MODULE_PATH.read_text()
        self.assertIn("except ProviderProducedNothing as timeout:", source)
        self.assertIn("return None, envelope", source)


if __name__ == "__main__":
    unittest.main()
