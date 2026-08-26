import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_currentness", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ArtifactCurrentnessTests(unittest.TestCase):
    """A derived file the pipeline rewrites through a second promote must stay
    current in the artifact registry; only an out-of-band edit is tampering."""

    def setUp(self):
        self.bf = load_module()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name) / "world"
        self.bf.init_project(self.project, "World")

    def registry(self):
        return json.loads((self.project / ".book-forge/artifact-deps.json").read_text())["artifacts"]

    def promote(self, task_id, payload):
        self.bf.add_task(self.project, task_id, "writer", outputs=["books/a.txt"])
        claim = self.bf.claim_task(self.project, task_id, request_hash=hashlib.sha256(task_id.encode()).hexdigest())
        self.bf.stage_outputs(self.project, claim["attempt"], {"books/a.txt": payload})
        self.bf.record_execution(self.project, claim["attempt"], claim["fence"], output_hash="1" * 64)
        self.bf.promote_task(self.project, claim["attempt"], claim["fence"])

    def register_pair(self):
        dependent = self.project / "books/derived.txt"
        dependent.write_text("translated")
        self.bf.register_artifact(self.project, "SRC", "source-chapter", path=self.project / "books/a.txt")
        self.bf.register_artifact(self.project, "TRN", "translation-chapter", path=dependent, dependencies=["SRC"])

    def test_second_promote_refreshes_the_row_and_invalidates_dependents(self):
        self.promote("TASK-A", "alpha\n")
        self.register_pair()

        self.promote("TASK-B", "alpha revised by the style pass\n")

        expected = hashlib.sha256(b"alpha revised by the style pass\n").hexdigest()
        self.assertEqual(self.registry()["SRC"]["hash"], expected)
        stale = self.bf.reconcile_artifacts(self.project)
        self.assertEqual(stale, ["TRN"])

    def test_registry_desynced_by_an_earlier_promote_is_repaired(self):
        self.promote("TASK-A", "alpha\n")
        self.register_pair()
        self.promote("TASK-B", "alpha revised by the style pass\n")

        # Reproduce the pre-fix state: the row pinned to the first promote.
        registry_path = self.project / ".book-forge/artifact-deps.json"
        value = json.loads(registry_path.read_text())
        value["artifacts"]["SRC"]["hash"] = hashlib.sha256(b"alpha\n").hexdigest()
        registry_path.write_text(json.dumps(value))

        stale = self.bf.reconcile_artifacts(self.project)
        self.assertEqual(stale, ["TRN"])
        self.assertEqual(self.registry()["SRC"]["hash"], hashlib.sha256(b"alpha revised by the style pass\n").hexdigest())

    def test_out_of_band_edit_still_fails_the_guard(self):
        self.promote("TASK-A", "alpha\n")
        self.register_pair()
        self.promote("TASK-B", "alpha revised by the style pass\n")

        (self.project / "books/a.txt").write_text("hand edited outside the pipeline\n")
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.reconcile_artifacts(self.project)

    def test_reverting_to_an_older_promoted_hash_is_accepted(self):
        """Provenance is per (path, hash): any hash the pipeline installed at that
        path is legitimate, including a rollback to the previous one."""
        self.promote("TASK-A", "alpha\n")
        self.register_pair()
        self.promote("TASK-B", "alpha revised by the style pass\n")

        (self.project / "books/a.txt").write_text("alpha\n")
        self.bf.reconcile_artifacts(self.project)
        self.assertEqual(self.registry()["SRC"]["hash"], hashlib.sha256(b"alpha\n").hexdigest())


if __name__ == "__main__":
    unittest.main()
