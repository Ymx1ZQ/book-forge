import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_migrate", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")

    def make_v0(self):
        paths = [
            "book-forge.yaml",
            "universe/universe.yaml",
            "universe/continuities.yaml",
            "universe/collections.yaml",
            "universe/relations.yaml",
        ]
        for relative in paths:
            path = self.project / relative
            data = json.loads(path.read_text())
            data["schema"] = 0
            path.write_text(json.dumps(data, sort_keys=True) + "\n")
        return paths

    def test_dry_run_apply_and_rollback_preserve_authored_prose(self):
        paths = self.make_v0()
        kernel = self.project / "universe/kernel.md"
        prose = kernel.read_bytes()
        before = {relative: (self.project / relative).read_bytes() for relative in paths}

        report = self.bf.migrate_project(self.project, "dry-run")
        self.assertEqual(report["from"], 0)
        self.assertTrue(report["changes"])
        self.assertEqual({relative: (self.project / relative).read_bytes() for relative in paths}, before)

        applied = self.bf.migrate_project(self.project, "apply")
        self.assertEqual(applied["to"], 1)
        self.assertEqual(kernel.read_bytes(), prose)
        self.assertEqual(json.loads((self.project / "book-forge.yaml").read_text())["schema"], 1)

        rolled_back = self.bf.migrate_project(self.project, "rollback")
        self.assertTrue(rolled_back["rolled_back"])
        self.assertEqual({relative: (self.project / relative).read_bytes() for relative in paths}, before)
        self.assertEqual(kernel.read_bytes(), prose)

    def test_interrupted_apply_restores_original_bytes(self):
        paths = self.make_v0()
        before = {relative: (self.project / relative).read_bytes() for relative in paths}

        def fail(stage):
            if stage == "after_first_install":
                raise RuntimeError("crash")

        with self.assertRaises(RuntimeError):
            self.bf.migrate_project(self.project, "apply", fault_hook=fail)
        self.assertEqual({relative: (self.project / relative).read_bytes() for relative in paths}, before)

    def test_rejects_unsupported_and_machine_state_tampering(self):
        config = self.project / "book-forge.yaml"
        data = json.loads(config.read_text())
        data["schema"] = 99
        config.write_text(json.dumps(data))
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.migrate_project(self.project, "check")

        data["schema"] = 1
        config.write_text(json.dumps(data))
        machine = self.project / ".book-forge/project.json"
        state = json.loads(machine.read_text())
        state["source_language"] = "fr"
        machine.write_text(json.dumps(state))
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.migrate_project(self.project, "check")


if __name__ == "__main__":
    unittest.main()
