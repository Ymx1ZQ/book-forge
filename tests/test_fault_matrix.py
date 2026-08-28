import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_fault_matrix", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FaultMatrixTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")

    def add_claim(self, *, accepted=False, lease=5):
        self.bf.add_task(self.project, "TASK-A", "writer", outputs=["universe/fault.md"])
        claim = self.bf.claim_task(self.project, "TASK-A", request_hash="a" * 64, now=10, lease_seconds=lease)
        if accepted:
            self.bf.mark_provider_accepted(self.project, claim["attempt"], "ses-fault", now=11)
        return claim

    def test_dispatch_faults_have_one_explicit_recovery_state(self):
        claim = self.add_claim(accepted=False)
        recovered = self.bf.recover_run(self.project, now=16)
        self.assertEqual(recovered, {"orphaned": [claim["attempt"]], "outcome_unknown": []})
        self.assertEqual(self.bf.ready_frontier(self.project)[0]["id"], "TASK-A")

        second = Path(self.temp.name) / "accepted"
        self.bf.init_project(second, "Accepted")
        self.bf.add_task(second, "TASK-A", "writer")
        accepted = self.bf.claim_task(second, "TASK-A", request_hash="a" * 64, now=10, lease_seconds=5)
        self.bf.mark_provider_accepted(second, accepted["attempt"], "ses-accepted", now=11)
        # Answering renews the lease by the window the claim asked for, so the attempt
        # is stale only once it has been silent for that long.
        recovered = self.bf.recover_run(second, now=17)
        self.assertEqual(recovered, {"orphaned": [], "outcome_unknown": [accepted["attempt"]]})
        late = self.bf.record_late_result(second, accepted["attempt"], "9" * 64)
        self.assertEqual(late["state"], "orphaned")
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.cleanup_attempt(second, accepted["attempt"])

    def test_every_cli_route_crosses_transaction_recovery_barrier(self):
        claim = self.add_claim()
        self.bf.stage_outputs(self.project, claim["attempt"], {"universe/fault.md": "durable\n"})
        self.bf.record_execution(self.project, claim["attempt"], claim["fence"], output_hash="b" * 64)

        def crash(stage):
            if stage == "after_install:universe/fault.md":
                raise RuntimeError("injected crash")

        with self.assertRaises(RuntimeError):
            self.bf.promote_task(self.project, claim["attempt"], claim["fence"], fault_hook=crash)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.bf.main(["--project", str(self.project), "status"]), 0)
        journal = json.loads(next((self.project / ".book-forge/transactions").glob("TXN-*/journal.json")).read_text())
        self.assertEqual(journal["state"], "completed")
        self.assertEqual((self.project / "universe/fault.md").read_text(), "durable\n")

    def test_machine_state_replace_is_atomic_at_derived_write_boundary(self):
        target = self.project / ".book-forge/provider.json"
        before = target.read_bytes()
        real_replace = self.bf.os.replace

        def fail_replace(source, destination):
            if Path(destination) == target:
                raise RuntimeError("crash before atomic replace")
            return real_replace(source, destination)

        with mock.patch.object(self.bf.os, "replace", side_effect=fail_replace):
            with self.assertRaises(RuntimeError):
                self.bf.set_rate_limit(self.project, retry_after=90, now=10)
        self.assertEqual(target.read_bytes(), before)
        self.assertTrue(self.bf.provider_ready(self.project, now=11))

    def test_conflict_failed_sync_duplicate_resume_and_stale_fence_are_fail_closed(self):
        claim = self.add_claim(accepted=True)
        self.bf.stage_outputs(self.project, claim["attempt"], {"universe/fault.md": "candidate\n"})
        self.bf.record_execution(self.project, claim["attempt"], claim["fence"], output_hash="b" * 64)
        with mock.patch.object(self.bf, "_scoped_git_commit", return_value=(None, True)):
            receipt = self.bf.promote_task(self.project, claim["attempt"], claim["fence"])
        self.assertTrue(receipt["sync_pending"])
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.promote_task(self.project, claim["attempt"], claim["fence"])

        other = Path(self.temp.name) / "resume"
        self.bf.init_project(other, "Resume")
        self.bf.add_task(other, "TASK-A", "writer")
        pending = self.bf.claim_task(other, "TASK-A", request_hash="a" * 64)
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.record_execution(other, pending["attempt"], pending["fence"] + 1, output_hash="c" * 64)
        self.bf.mark_provider_accepted(other, pending["attempt"], "ses-resume")
        self.bf.pause_run(other, emergency=True)
        self.bf.resume_run(other, resolutions={"TASK-A": "retry"})
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.resume_run(other)


if __name__ == "__main__":
    unittest.main()
