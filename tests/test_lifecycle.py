import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_lifecycle", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        self.bf.add_task(self.project, "TASK-A", "writer")

    def test_graceful_pause_finishes_accepted_work_then_pauses(self):
        claim = self.bf.claim_task(self.project, "TASK-A", request_hash="a" * 64, now=10)
        self.bf.mark_provider_accepted(self.project, claim["attempt"], "ses-1", now=11)
        paused = self.bf.pause_run(self.project, emergency=False)
        self.assertEqual(paused["state"], "pausing")
        self.assertEqual(self.bf.ready_frontier(self.project), [])

        self.bf.record_execution(self.project, claim["attempt"], claim["fence"], output_hash="1" * 64)
        self.bf.promote_task(self.project, claim["attempt"], claim["fence"])
        self.assertEqual(self.bf.status_project(self.project)["run"]["state"], "paused")

    def test_emergency_unknown_requires_explicit_resolution(self):
        claim = self.bf.claim_task(self.project, "TASK-A", request_hash="a" * 64, now=10)
        self.bf.mark_provider_accepted(self.project, claim["attempt"], "ses-1", now=11)
        halted = self.bf.pause_run(self.project, emergency=True)
        self.assertEqual(halted["state"], "blocked")
        self.assertEqual(self.bf.status_project(self.project)["tasks"]["outcome_unknown"], 1)
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.resume_run(self.project)

        resumed = self.bf.resume_run(self.project, resolutions={"TASK-A": "retry"})
        self.assertEqual(resumed["state"], "running")
        self.assertEqual([task["id"] for task in self.bf.ready_frontier(self.project)], ["TASK-A"])
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.cleanup_attempt(self.project, claim["attempt"])

    def test_rate_limit_and_expired_lease_are_durable(self):
        self.bf.set_rate_limit(self.project, retry_after=90, now=10)
        self.assertFalse(self.bf.provider_ready(self.project, now=99))
        self.assertTrue(self.bf.provider_ready(self.project, now=100))

        claim = self.bf.claim_task(self.project, "TASK-A", request_hash="a" * 64, now=100, lease_seconds=5)
        recovered = self.bf.recover_run(self.project, now=106)
        self.assertEqual(recovered["orphaned"], [claim["attempt"]])
        self.assertEqual([task["id"] for task in self.bf.ready_frontier(self.project)], ["TASK-A"])

    def test_abandon_blocks_descendants_and_late_result_becomes_orphan(self):
        self.bf.add_task(self.project, "TASK-B", "reviser", deps=["TASK-A"])
        claim = self.bf.claim_task(self.project, "TASK-A", request_hash="a" * 64)
        self.bf.mark_provider_accepted(self.project, claim["attempt"], "ses-1")
        self.bf.pause_run(self.project, emergency=True)
        self.bf.resume_run(self.project, resolutions={"TASK-A": "abandon"})
        status = self.bf.status_project(self.project)
        self.assertEqual(status["tasks"]["blocked"], 2)
        late = self.bf.record_late_result(self.project, claim["attempt"], "9" * 64)
        self.assertEqual(late["state"], "orphaned")

    def test_validation_blocked_task_requires_explicit_retry_resolution(self):
        claim = self.bf.claim_task(self.project, "TASK-A", request_hash="a" * 64)
        self.bf._set_attempt_failure(self.project, claim["attempt"], block=True, reason="creative-contract.incomplete")
        self.assertEqual(self.bf.status_project(self.project)["run"]["state"], "blocked")
        self.assertEqual(self.bf.status_project(self.project)["tasks"]["blocked"], 1)

        with self.assertRaises(self.bf.BookForgeError):
            self.bf.resume_run(self.project)
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.resume_run(self.project, blocked_resolutions={"TASK-A": "abandon"})

        resumed = self.bf.resume_run(self.project, blocked_resolutions={"TASK-A": "retry"})
        self.assertEqual(resumed["state"], "running")
        plan = self.bf._load_plan(self.project)
        task = next(row for row in plan["tasks"] if row["id"] == "TASK-A")
        self.assertEqual(task["state"], "pending")
        self.assertNotIn("attempt", task)
        attempt = self.bf._attempt(plan, claim["attempt"])
        self.assertEqual(attempt["state"], "orphaned")
        self.assertEqual(attempt["resolution"], "retry")
        self.assertEqual([row["id"] for row in self.bf.ready_frontier(self.project)], ["TASK-A"])
        self.assertEqual(self.bf.status_project(self.project)["telemetry"]["resolutions"], {claim["attempt"]: "retry"})

    def test_failed_length_blocked_task_requires_explicit_retry_resolution(self):
        claim = self.bf.claim_task(self.project, "TASK-A", request_hash="a" * 64)
        plan = self.bf._load_plan(self.project)
        attempt = self.bf._attempt(plan, claim["attempt"])
        attempt["state"] = "failed_length"
        attempt["failure"] = "finish_reason==length after retries"
        task = next(row for row in plan["tasks"] if row["id"] == "TASK-A")
        task["state"] = "blocked"
        task.pop("attempt", None)
        self.bf._save_plan(self.project, plan)
        self.bf.render_plan(self.project)
        self.assertEqual(self.bf.status_project(self.project)["tasks"]["blocked"], 1)

        with self.assertRaises(self.bf.BookForgeError):
            self.bf.resume_run(self.project)
        resumed = self.bf.resume_run(self.project, blocked_resolutions={"TASK-A": "retry"})
        self.assertEqual(resumed["state"], "running")
        plan = self.bf._load_plan(self.project)
        task = next(row for row in plan["tasks"] if row["id"] == "TASK-A")
        self.assertEqual(task["state"], "pending")
        attempt = self.bf._attempt(plan, claim["attempt"])
        self.assertEqual(attempt["state"], "orphaned")
        self.assertEqual(attempt["resolution"], "retry")

    def test_run_selector_is_validated_instead_of_silently_ignored(self):
        claim = self.bf.claim_task(self.project, "TASK-A", request_hash="a" * 64)
        active = self.bf.status_project(self.project)["run"]["id"]
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.pause_run(self.project, run_id="RUN-9999")
        self.assertEqual(self.bf.pause_run(self.project, run_id=active, emergency=True)["state"], "paused")
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.resume_run(self.project, run_id="RUN-9999")
        self.assertEqual(self.bf.resume_run(self.project, run_id=active)["state"], "running")
        self.assertEqual(self.bf._attempt(self.bf._load_plan(self.project), claim["attempt"])["state"], "orphaned")

    def test_status_scopes_book_run_and_locale_explicitly(self):
        book = self.bf.add_book(self.project, "Book")["id"]
        self.bf.add_translation(self.project, book, "it-IT")
        run = self.bf.claim_task(self.project, "TASK-A", request_hash="a" * 64)
        run_id = self.bf._attempt(self.bf._load_plan(self.project), run["attempt"])["run"]
        scoped = self.bf.status_project(self.project, book_id=book, run_id=run_id, locale="it-it")
        self.assertEqual(scoped["scope"]["book"], book)
        self.assertEqual(scoped["scope"]["run"], run_id)
        self.assertEqual(scoped["scope"]["locales"][0]["state"]["locale"], "it-IT")
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.status_project(self.project, run_id="RUN-9999")


if __name__ == "__main__":
    unittest.main()
