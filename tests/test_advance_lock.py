import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_lock", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdvanceLockTests(unittest.TestCase):
    """Two drivers on one book contend for the same claims: one orphans the other's
    attempt and both pay for work that is discarded."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]
        self.root = self.bf._project_root(self.project)

    def lock_path(self):
        return self.bf._advance_lock_path(self.root, self.book)

    def test_a_live_holder_refuses_a_second_driver_and_names_it(self):
        self.lock_path().parent.mkdir(parents=True, exist_ok=True)
        self.lock_path().write_text("1\n", encoding="utf-8")  # pid 1 is always alive
        with self.assertRaises(self.bf.AdvanceBusy) as caught:
            with self.bf._advance_lock(self.root, self.book):
                pass
        self.assertIn("pid 1", str(caught.exception))
        self.assertIn(self.book, str(caught.exception))

    def test_a_lock_left_by_a_dead_process_is_taken_over(self):
        self.lock_path().parent.mkdir(parents=True, exist_ok=True)
        dead = 2 ** 22 - 1
        self.lock_path().write_text(f"{dead}\n", encoding="utf-8")
        with self.bf._advance_lock(self.root, self.book):
            self.assertEqual(self.lock_path().read_text().strip(), str(os.getpid()))

    def test_a_corrupt_lock_does_not_block_a_run(self):
        self.lock_path().parent.mkdir(parents=True, exist_ok=True)
        self.lock_path().write_text("not a pid\n", encoding="utf-8")
        with self.bf._advance_lock(self.root, self.book):
            pass
        self.assertFalse(self.lock_path().exists())

    def test_the_lock_is_released_when_the_driver_finishes(self):
        with self.bf._advance_lock(self.root, self.book):
            self.assertTrue(self.lock_path().is_file())
        self.assertFalse(self.lock_path().exists())

    def test_the_lock_is_released_when_the_driver_fails(self):
        with self.assertRaises(ValueError):
            with self.bf._advance_lock(self.root, self.book):
                raise ValueError("boom")
        self.assertFalse(self.lock_path().exists())


class AdvanceReceiptTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]
        self.root = self.bf._project_root(self.project)

    def test_an_empty_book_is_reported_as_not_ready(self):
        receipt = self.bf._advance_receipt(self.root, self.book)
        self.assertEqual(receipt["outline_chapters"], 0)
        self.assertFalse(receipt["ready_to_write"])

    def test_a_blocking_design_audit_keeps_the_book_not_ready(self):
        self._design(2)
        self.bf._write_json(
            self.root / "books" / self.book / "design-audit.json",
            {"schema": 1, "state": "blocked", "findings": [
                {"id": "F-0001", "severity": "blocking", "issue": "The drowned person changes gender across chapters.", "repair_scope": ["CH-0001"]},
                {"id": "F-0002", "severity": "warning", "issue": "A minor clash."},
            ]},
        )
        receipt = self.bf._advance_receipt(self.root, self.book)
        self.assertFalse(receipt["ready_to_write"])
        self.assertEqual(receipt["design_audit"], {"state": "blocked", "blocking": 1})
        self.assertEqual([row["id"] for row in receipt["blocked_by"]], ["F-0001"])

    def test_warnings_alone_do_not_hold_the_book_back(self):
        self._design(2)
        self.bf._write_json(
            self.root / "books" / self.book / "design-audit.json",
            {"schema": 1, "state": "design_clean", "findings": [{"id": "F-0002", "severity": "warning", "issue": "A minor clash."}]},
        )
        receipt = self.bf._advance_receipt(self.root, self.book)
        self.assertTrue(receipt["ready_to_write"])
        self.assertNotIn("blocked_by", receipt)

    def _design(self, count):
        chapters = [{"id": f"CH-{i:04d}", "order": i, "pov": "CHR-0001", "beats": ["b"], "target_words": 900} for i in range(1, count + 1)]
        self.bf._write_json(self.root / "books" / self.book / "outline.yaml", {"schema": 1, "chapters": chapters})
        for chapter in chapters:
            self.bf._write_json(self.root / "books" / self.book / "chapters" / f"{chapter['id']}.json", chapter)
        self.bf.add_task(self.project, f"DESIGN-{self.book}", "designer", deps=[], priority=50, outputs=[])
        plan = self.bf._load_plan(self.root)
        next(row for row in plan["tasks"] if row["id"] == f"DESIGN-{self.book}")["state"] = "succeeded"
        self.bf._save_plan(self.root, plan)

    def test_a_designed_book_is_reported_as_ready(self):
        chapters = [{"id": f"CH-{i:04d}", "order": i, "pov": "CHR-0001", "beats": ["b"], "target_words": 900} for i in (1, 2)]
        self.bf._write_json(self.root / "books" / self.book / "outline.yaml", {"schema": 1, "chapters": chapters})
        for chapter in chapters:
            self.bf._write_json(self.root / "books" / self.book / "chapters" / f"{chapter['id']}.json", chapter)
        self.bf.add_task(self.project, f"DESIGN-{self.book}", "designer", deps=[], priority=50, outputs=[])
        plan = self.bf._load_plan(self.root)
        next(row for row in plan["tasks"] if row["id"] == f"DESIGN-{self.book}")["state"] = "succeeded"
        self.bf._save_plan(self.root, plan)

        receipt = self.bf._advance_receipt(self.root, self.book)

        self.assertEqual(receipt["outline_chapters"], 2)
        self.assertEqual(receipt["chapter_contracts"], 2)
        self.assertEqual(receipt["manuscript_chapters"], 0)
        self.assertTrue(receipt["ready_to_write"])


if __name__ == "__main__":
    unittest.main()


class DeadDriverResumeTests(unittest.TestCase):
    """An OOM kill leaves the run marked running with an accepted attempt whose
    lease has expired. One command must clear that."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.root = self.bf._project_root(self.project)
        self.bf.add_task(self.project, "DESIGN-BOOK-0001", "designer", deps=[], priority=50, outputs=[])
        self.bf.start_run(self.root)

    def _stale_accepted_attempt(self, lease):
        plan = self.bf._load_plan(self.root)
        task = next(row for row in plan["tasks"] if row["id"] == "DESIGN-BOOK-0001")
        task["state"] = "running"
        task["attempt"] = "ATT-9001"
        plan["attempts"].append({
            "id": "ATT-9001", "task": "DESIGN-BOOK-0001", "role": "designer", "state": "running",
            "provider_accepted": True, "lease_expires_at": lease, "run": "RUN-0001",
        })
        self.bf._save_plan(self.root, plan)

    def test_resume_clears_what_a_killed_driver_left_behind(self):
        self._stale_accepted_attempt(lease=1.0)

        self.bf.resume_run(self.project, resolutions={"DESIGN-BOOK-0001": "retry"})

        plan = self.bf._load_plan(self.root)
        task = next(row for row in plan["tasks"] if row["id"] == "DESIGN-BOOK-0001")
        self.assertEqual(task["state"], "pending")

    def test_a_run_with_a_live_lease_still_refuses(self):
        self._stale_accepted_attempt(lease=2 ** 40)
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.resume_run(self.project, resolutions={"DESIGN-BOOK-0001": "retry"})
        self.assertIn("Run cannot resume while running", str(caught.exception))

    def test_the_refusal_says_what_to_do_instead(self):
        self._stale_accepted_attempt(lease=2 ** 40)
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.resume_run(self.project, resolutions={})
        self.assertIn("pause", str(caught.exception))
