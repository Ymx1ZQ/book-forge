import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_plan", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")

    def test_stable_frontier_and_separate_execution_promotion(self):
        self.bf.add_task(self.project, "TASK-B", "writer", priority=20, book_order=1, chapter_order=2)
        self.bf.add_task(self.project, "TASK-A", "designer", priority=10, book_order=1, chapter_order=1)
        self.bf.add_task(self.project, "TASK-C", "reviser", deps=["TASK-A"], priority=1)
        self.assertEqual([task["id"] for task in self.bf.ready_frontier(self.project)], ["TASK-A", "TASK-B"])

        a = self.bf.claim_task(self.project, "TASK-A", request_hash="a" * 64)
        b = self.bf.claim_task(self.project, "TASK-B", request_hash="b" * 64)
        self.assertNotEqual(a["attempt"], b["attempt"])
        self.bf.record_execution(self.project, a["attempt"], a["fence"], output_hash="1" * 64)
        plan = json.loads((self.project / ".book-forge/plan.json").read_text())
        task_a = next(task for task in plan["tasks"] if task["id"] == "TASK-A")
        self.assertEqual(task_a["state"], "promotion_pending")
        self.assertNotIn("promotion_receipt", task_a)

        self.bf.promote_task(self.project, a["attempt"], a["fence"])
        self.assertEqual([task["id"] for task in self.bf.ready_frontier(self.project)], ["TASK-C"])
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.promote_task(self.project, a["attempt"], a["fence"])

    def test_rejects_direct_plan_edit_and_stale_fence(self):
        self.bf.add_task(self.project, "TASK-A", "writer")
        claim = self.bf.claim_task(self.project, "TASK-A", request_hash="a" * 64)
        plan_path = self.project / ".book-forge/plan.json"
        plan = json.loads(plan_path.read_text())
        plan["tasks"][0]["state"] = "succeeded"
        plan_path.write_text(json.dumps(plan))
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.ready_frontier(self.project)

        self.bf.repair_plan_view(self.project, restore_canonical=True)
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.record_execution(self.project, claim["attempt"], claim["fence"] - 1, output_hash="1" * 64)

    def test_renders_human_view_with_tamper_hash(self):
        self.bf.add_task(self.project, "TASK-A", "writer")
        rendered = self.bf.render_plan(self.project)
        self.assertIn("TASK-A", rendered)
        self.assertIn("book-forge-plan-hash:", rendered)
        self.assertEqual((self.project / "DEVPLAN.md").read_text(), rendered)


if __name__ == "__main__":
    unittest.main()
