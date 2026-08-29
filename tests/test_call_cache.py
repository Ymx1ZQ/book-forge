import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_call_cache", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROLE_VARIANTS = {name: spec[1] for name, spec in load_module().ROLE_SPECS.items()}


class CountingProvider:
    """Answers the whole design and counts what it was actually asked."""

    def __init__(self, bf, chapter_count=9, fail_on=None):
        self.bf = bf
        self.chapter_count = chapter_count
        self.fail_on = fail_on
        self.calls = []

    def _ok(self, envelope, payload, role):
        return {
            "text": json.dumps(payload), "provider": "openrouter", "model": MODEL,
            "variant": ROLE_VARIANTS.get(role, "high"), "session_id": f"ses-{len(self.calls)}",
            "tokens": {"input": 100, "output": 200}, "cost": 0.01, "latency_ms": 5, "finish": "stop",
        }

    def __call__(self, role, envelope, attempt_dir):
        task = envelope["payload"]["task"]
        chunk = task.get("chunk") or {}
        slug = self.bf._chunk_slug(chunk) if chunk else role
        self.calls.append(slug)
        if slug == self.fail_on:
            raise RuntimeError(f"the machine died during {slug}")
        if role == "canon-auditor":
            payload = {"findings": []}
            if "neighbourhood_digest" not in task["design_scope"]:
                payload["open_promises"] = []
            return self._ok(envelope, payload, role)
        if chunk.get("category") == "spine":
            return self._ok(envelope, {
                "premise": "A warden decides.", "entry_state": {"CHR-0001": "here"},
                "arc": ["refusal", "cost", "choice"], "exit_boundary": {"CHR-0001": "gone"},
                "chapter_count": self.chapter_count,
            }, role)
        first, last = int(chunk["first_order"]), int(chunk["last_order"])
        if chunk.get("category") == "outline":
            return self._ok(envelope, {"chapter_outline": [
                {"id": f"CH-{i:04d}", "order": i, "title": "The Dawn Warden", "pov": "CHR-0001", "summary": "s"}
                for i in range(first, last + 1)
            ]}, role)
        return self._ok(envelope, {"chapters": [
            {
                "id": f"CH-{i:04d}", "order": i, "title": "The Dawn Warden", "pov": "CHR-0001",
                "beats": ["She counts the light and the ledger is short"], "plants": [], "reveals": [],
                "target_words": 900, "imports": ["UNI-0001#kernel"], "obligations": [], "pivotal": None,
            }
            for i in range(first, last + 1)
        ]}, role)

    def designer_calls(self):
        return [slug for slug in self.calls if slug not in {"canon-auditor"}]


class CacheFixture(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["chorus"] = {"enabled": False, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.book = self.bf.add_book(self.project, "Landfall")["id"]
        self.write_brief("A warden decides.")

    def write_brief(self, premise):
        (self.project / f"books/{self.book}/book-brief.json").write_text(json.dumps({
            "schema": 1, "premise": premise, "characters": ["Binta"], "plot": ["walk"], "tone": "quiet",
        }))

    def design(self, provider):
        return self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)

    def reopen(self):
        self.bf._reopen_task(self.project, f"DESIGN-{self.book}")
        self.bf._reopen_task(self.project, f"AUDIT-{self.book}")


class AResumedRunPaysOnlyForWhatIsMissingTests(CacheFixture):
    """Landfall's design was killed at its twenty-seventh call and the other
    twenty-six were lost: the artifacts are written once, at the end."""

    def test_asking_the_same_design_again_makes_no_designer_call_at_all(self):
        first = CountingProvider(self.bf)
        self.design(first)
        self.assertTrue(first.designer_calls())
        self.reopen()
        second = CountingProvider(self.bf)
        self.design(second)
        self.assertEqual(second.designer_calls(), [])

    def test_a_design_that_died_halfway_calls_only_for_what_is_missing(self):
        broken = CountingProvider(self.bf, fail_on="chapters-1-8")
        with self.assertRaises(RuntimeError):
            self.design(broken)
        paid = [slug for slug in broken.designer_calls() if slug != "chapters-1-8"]
        self.assertIn("spine", paid)
        self.assertIn("outline-1-9", paid)
        self.reopen()
        resumed = CountingProvider(self.bf)
        self.design(resumed)
        for slug in paid:
            self.assertNotIn(slug, resumed.designer_calls(), f"{slug} was paid for once and asked again")
        self.assertIn("chapters-1-8", resumed.designer_calls())

    def test_the_chapters_are_the_same_whether_they_came_from_the_cache_or_the_call(self):
        self.design(CountingProvider(self.bf))
        first = (self.project / f"books/{self.book}/outline.yaml").read_text()
        self.reopen()
        self.design(CountingProvider(self.bf))
        self.assertEqual((self.project / f"books/{self.book}/outline.yaml").read_text(), first)


class TheCacheCannotServeAStaleAnswerTests(CacheFixture):
    def test_a_changed_brief_misses_it(self):
        self.design(CountingProvider(self.bf))
        self.reopen()
        self.write_brief("A warden refuses, which is a different book.")
        second = CountingProvider(self.bf)
        self.design(second)
        self.assertIn("spine", second.designer_calls())

    def test_a_truncation_is_never_remembered_so_the_retry_still_happens(self):
        envelope = {"hash": "abc123", "role": "designer"}
        self.bf._remember_call(self.project, "DESIGN-X", envelope, {"text": "{}", "finish": "length"})
        self.assertIsNone(self.bf._cached_call(self.project, "DESIGN-X", envelope))

    def test_an_empty_body_is_never_remembered(self):
        envelope = {"hash": "def456", "role": "designer"}
        self.bf._remember_call(self.project, "DESIGN-X", envelope, {"text": "   ", "finish": "stop"})
        self.assertIsNone(self.bf._cached_call(self.project, "DESIGN-X", envelope))

    def test_a_remembered_answer_costs_nothing_and_says_so(self):
        envelope = {"hash": "ghi789", "role": "designer"}
        self.bf._remember_call(self.project, "DESIGN-X", envelope, {"text": '{"a":1}', "finish": "stop", "cost": 0.42})
        cached = self.bf._cached_call(self.project, "DESIGN-X", envelope)
        self.assertEqual(cached["cost"], 0.0)
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["text"], '{"a":1}')


class TheCachingRunnerTests(CacheFixture):
    def calls_of(self, seen):
        def runner(role, envelope, attempt_dir):
            seen.append(role)
            return {"text": json.dumps({"findings": [], "suggestions": []}), "finish": "stop", "cost": 0.01,
                    "session_id": "ses-1", "tokens": {}, "model": MODEL, "variant": "high", "provider": "openrouter"}
        return self.bf._caching_runner(self.project, "DESIGN-X", runner)

    def envelope(self, role, digest):
        return {"hash": digest, "role": role, "payload": {"task": {}}}

    def test_two_advisors_never_share_an_entry(self):
        seen = []
        runner = self.calls_of(seen)
        runner("advisor-one", self.envelope("advisor-one", "hash-one"), self.project)
        runner("advisor-two", self.envelope("advisor-two", "hash-two"), self.project)
        self.assertEqual(seen, ["advisor-one", "advisor-two"])
        runner("advisor-one", self.envelope("advisor-one", "hash-one"), self.project)
        runner("advisor-two", self.envelope("advisor-two", "hash-two"), self.project)
        self.assertEqual(seen, ["advisor-one", "advisor-two"], "both were answered from the cache")

    def test_an_advisor_answer_that_does_not_parse_is_not_remembered(self):
        seen = []

        def runner(role, envelope, attempt_dir):
            seen.append(role)
            return {"text": "not json at all", "finish": "stop", "cost": 0.01, "session_id": "s",
                    "tokens": {}, "model": MODEL, "variant": "high", "provider": "openrouter"}

        caching = self.bf._caching_runner(self.project, "DESIGN-X", runner)
        caching("advisor-one", self.envelope("advisor-one", "hash-three"), self.project)
        caching("advisor-one", self.envelope("advisor-one", "hash-three"), self.project)
        self.assertEqual(len(seen), 2, "a bad answer must not be inherited by the next run")


if __name__ == "__main__":
    unittest.main()
