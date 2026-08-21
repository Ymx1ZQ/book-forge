import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_index", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        character = self.project / "universe/canon/characters/CHR-0012.md"
        character.write_text(
            "---\nid: CHR-0012\ncontinuity: CNT-0001\n---\n\n"
            "<!-- bf:block voice -->\nSpeaks in clipped clauses.\n"
            "<!-- bf:block secret -->\nFears the sea.\n"
        )

    def test_indexes_blocks_and_propagates_only_exact_consumers(self):
        index = self.bf.rebuild_indexes(self.project)
        self.assertIn("CHR-0012#voice", index["blocks"])
        self.assertIn("UNI-0001#kernel", index["blocks"])

        source = self.project / "universe/canon/characters/CHR-0012.md"
        derived_b = self.project / "books/derived-b.txt"
        derived_c = self.project / "books/derived-c.txt"
        unrelated = self.project / "books/unrelated.txt"
        derived_b.write_text("b")
        derived_c.write_text("c")
        unrelated.write_text("u")
        self.bf.register_artifact(self.project, "CANON-CHR", "canon", path=source, authored=True)
        self.bf.register_artifact(
            self.project, "ART-B", "chapter-state", path=derived_b,
            dependencies=["CHR-0012#voice"], entities=["CHR-0012"], events=["EVT-0001"],
        )
        self.bf.register_artifact(self.project, "ART-C", "translation", path=derived_c, dependencies=["ART-B"])
        self.bf.register_artifact(self.project, "ART-U", "future-type", path=unrelated, dependencies=[])

        source.write_text(source.read_text().replace("clipped", "measured"))
        stale = self.bf.reconcile_artifacts(self.project)
        self.assertEqual(stale, ["ART-B", "ART-C"])
        appearances = json.loads((self.project / ".book-forge/appearances.json").read_text())
        self.assertEqual(appearances["entities"]["CHR-0012"], ["ART-B"])

    def test_rejects_duplicate_blocks_dangling_imports_and_derived_edits(self):
        duplicate = self.project / "universe/canon/characters/CHR-0012-copy.md"
        duplicate.write_text("---\nid: CHR-0012\n---\n<!-- bf:block voice -->\nOther\n")
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.rebuild_indexes(self.project)
        duplicate.unlink()
        self.bf.rebuild_indexes(self.project)

        relations = self.project / "universe/relations.yaml"
        data = json.loads(relations.read_text())
        data["relations"].append({"id": "REL-9999", "type": "alternate_of", "endpoints": [], "imports": [{"block": "CHR-9999#missing", "hash": "0" * 64}], "obligations": []})
        relations.write_text(json.dumps(data))
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.rebuild_indexes(self.project)

        data["relations"] = []
        relations.write_text(json.dumps(data))
        path = self.project / "books/generated.txt"
        path.write_text("one")
        self.bf.register_artifact(self.project, "GEN", "generated", path=path)
        path.write_text("tampered")
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.reconcile_artifacts(self.project)


if __name__ == "__main__":
    unittest.main()
