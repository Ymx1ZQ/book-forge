import json

from test_translation_review import GOOD_BODY, MODEL, ScriptedProvider, TranslationReviewFixture, translation


class Bench:
    """Answers the rewrite bake-off's two roles, refusing the calls a test names."""

    def __init__(self, invalid=()):
        self.invalid = set(invalid)
        self.reviser_calls = 0
        self.calls = []

    def __call__(self, role, envelope, attempt_dir):
        payload = envelope["payload"]
        self.calls.append(role)
        if role == "locale-reader":
            text = json.dumps({"summary": "letto", "followed": True, "stumbles": []})
        else:
            index = self.reviser_calls
            self.reviser_calls += 1
            if index in self.invalid:
                text = "this is not contract JSON"
            else:
                text = json.dumps({"revised_markdown": payload["task"]["chapter_markdown"], "changed": []})
        return {
            "text": text, "provider": "openrouter", "model": payload["model"],
            "variant": payload["variant"], "session_id": "ses",
            "tokens": {"input": envelope["estimated_input_tokens"], "output": 100},
            "cost": 0.001, "latency_ms": 10, "finish": "stop",
        }


class ARewriteBakeOffKeepsGoingTests(TranslationReviewFixture):
    """A passage that answers non-JSON used to leave its claim held, so the task stayed `outcome_unknown`, the run turned `blocked`, and every later dispatch of the project was refused."""

    def bake(self, invalid):
        self.translate(ScriptedProvider([translation(GOOD_BODY)]))
        bench = Bench(invalid)
        index = self.bf.rewrite_bakeoff(
            self.project, self.book, "CH-0001", "it", [MODEL], provider=bench,
        )
        return index, bench

    def assert_the_run_was_not_blocked(self):
        tasks = self.bf._load_plan(self.project)["tasks"]
        self.assertEqual([task for task in tasks if task["state"] == "outcome_unknown"], [])
        run = self.bf.status_project(self.project)["run"]
        self.assertIsNotNone(run)
        self.assertNotEqual(run["state"], "blocked")

    def test_a_bake_off_passage_that_answers_non_json_once_is_asked_again(self):
        index, bench = self.bake(invalid={0})
        self.assertEqual(index["candidates"][0]["state"], "written")
        self.assertEqual(bench.reviser_calls, 2, "the first passage must be asked once more")
        self.assert_the_run_was_not_blocked()

    def test_a_bake_off_whose_passages_never_parse_is_unusable_without_blocking(self):
        index, bench = self.bake(invalid={0, 1})
        self.assertEqual(index["candidates"][0]["state"], "unusable")
        self.assertEqual(bench.reviser_calls, 2, "the second failure must not buy a third call")
        self.assert_the_run_was_not_blocked()
