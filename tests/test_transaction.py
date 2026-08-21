import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_transaction", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TransactionTests(unittest.TestCase):
    def make_claim(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        project = Path(temp.name) / "world"
        self.bf.init_project(project, "World")
        self.bf.add_task(project, "TASK-A", "writer", outputs=["universe/a.md", "universe/b.md"])
        claim = self.bf.claim_task(project, "TASK-A", request_hash="a" * 64)
        self.bf.stage_outputs(project, claim["attempt"], {"universe/a.md": "alpha\n", "universe/b.md": "beta\n"})
        self.bf.record_execution(project, claim["attempt"], claim["fence"], output_hash="1" * 64)
        return project, claim

    def setUp(self):
        self.bf = load_module()

    def test_recovers_every_promotion_boundary_to_same_hashes(self):
        stages = ["after_prepare", "after_install:universe/a.md", "after_install:universe/b.md", "after_commit", "after_receipt"]
        results = []
        for crash_stage in stages:
            with self.subTest(crash_stage=crash_stage):
                project, claim = self.make_claim()

                def crash(stage):
                    if stage == crash_stage:
                        raise RuntimeError("injected crash")

                with self.assertRaises(RuntimeError):
                    self.bf.promote_task(project, claim["attempt"], claim["fence"], fault_hook=crash)
                self.bf.recover_transactions(project)
                results.append(((project / "universe/a.md").read_bytes(), (project / "universe/b.md").read_bytes()))
                self.assertEqual(self.bf.status_project(project)["tasks"]["succeeded"], 1)
        self.assertEqual(len(set(results)), 1)

    def test_rejects_unsafe_or_changed_targets_and_preserves_stage(self):
        project, claim = self.make_claim()
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.stage_outputs(project, claim["attempt"], {"../escape.md": "bad"})

        (project / "universe/a.md").write_text("external\n")
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.promote_task(project, claim["attempt"], claim["fence"])
        staged = project / ".book-forge/runs/RUN-0001/attempts" / claim["attempt"] / "staged/universe/a.md"
        self.assertEqual(staged.read_text(), "alpha\n")

    def test_rejects_symlink_escape(self):
        project, claim = self.make_claim()
        outside = project.parent / "outside"
        outside.mkdir()
        (project / "universe/link").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.stage_outputs(project, claim["attempt"], {"universe/link/escape.md": "bad"})


if __name__ == "__main__":
    unittest.main()
