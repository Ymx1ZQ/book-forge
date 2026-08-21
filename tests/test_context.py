import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_context", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        character = self.project / "universe/canon/characters/CHR-0001.md"
        character.write_text(
            "---\nid: CHR-0001\ncontinuity: CNT-0001\n---\n"
            "<!-- bf:block voice -->\n<!-- bf:import UNI-0001#kernel -->\nClipped voice.\n"
        )
        self.bf.rebuild_indexes(self.project)

    def test_envelope_is_stable_transitive_deduplicated_and_bounded(self):
        kwargs = dict(
            role="writer",
            task_capsule={"id": "CH-0001", "brief": "A quiet discovery"},
            imports=["CHR-0001#voice", "UNI-0001#kernel", "CHR-0001#voice"],
            state={"previous_boundary": "none"},
            tools=[],
            max_output_tokens=4000,
        )
        first = self.bf.build_envelope(self.project, **kwargs)
        second = self.bf.build_envelope(self.project, **kwargs)
        self.assertEqual(first["bytes"], second["bytes"])
        self.assertEqual(first["hash"], second["hash"])
        self.assertEqual([row["id"] for row in first["payload"]["context"]], ["CHR-0001#voice", "UNI-0001#kernel"])
        self.assertLessEqual(first["estimated_input_tokens"], 12000)
        self.assertEqual(first["estimator"], "deepseek-v4-flash-conservative-v1")

    def test_visibility_removes_canon_and_author_history(self):
        capsule = {"id": "CH-0001", "prose": "Text", "author_history": "secret deliberation"}
        reader = self.bf.build_envelope(
            self.project, role="cold-reader", task_capsule=capsule,
            imports=["CHR-0001#voice"], state={}, tools=[], max_output_tokens=1000,
        )
        self.assertEqual(reader["payload"]["context"], [])
        self.assertNotIn("author_history", reader["payload"]["task"])
        judge = self.bf.build_envelope(
            self.project, role="judge", task_capsule=capsule,
            imports=[], state={}, tools=[], max_output_tokens=1000,
        )
        self.assertNotIn("author_history", judge["payload"]["task"])

    def test_overflow_fails_with_ranked_contributors_without_truncation(self):
        with self.assertRaises(self.bf.ContextOverflowError) as caught:
            self.bf.build_envelope(
                self.project,
                role="writer",
                task_capsule={"id": "CH-0001", "brief": "x" * 50000},
                imports=[], state={"large": "y" * 50000}, tools=[], max_output_tokens=4000,
                input_budget=1000,
            )
        self.assertGreaterEqual(len(caught.exception.contributors), 2)
        self.assertEqual(caught.exception.contributors, sorted(caught.exception.contributors, key=lambda row: row["estimated_tokens"], reverse=True))


if __name__ == "__main__":
    unittest.main()
