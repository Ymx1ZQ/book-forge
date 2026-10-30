import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_import_names", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ImportNameTests(unittest.TestCase):
    """A canon entity's name lives in the file heading, outside every block. An
    imported block without it leaves the writer inventing a name for the entity."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]
        self.character = self.project / "universe" / "canon" / "characters" / "CHR-0003.md"

    def write_summary(self, body):
        self.character.write_text(
            "---\nid: CHR-0003\ncontinuity: CNT-0001\n---\n\n# Ren Chen-Silva\n\n"
            f"<!-- bf:block summary -->\n{body}\n",
            encoding="utf-8",
        )
        self.bf.rebuild_indexes(self.project)

    def envelope_context(self):
        envelope = self.bf.build_envelope(
            self.project,
            role="writer",
            task_capsule={"id": "CH-0001", "book": self.book, "pov": "CHR-0003"},
            imports=["CHR-0003#summary"],
            state={},
            tools=[],
            max_output_tokens=2000,
        )
        return envelope["payload"]["context"]

    def test_an_imported_block_carries_the_entity_name(self):
        self.write_summary("Heretical Reader; felt the Arc slip.")
        blob = json.dumps(self.envelope_context(), ensure_ascii=False)
        self.assertIn("Ren Chen-Silva", blob)

    def test_a_block_that_already_starts_with_the_name_is_not_prefixed_twice(self):
        self.write_summary("Ren Chen-Silva, Heretical Reader, felt the Arc slip.")
        content = next(row["content"] for row in self.envelope_context() if row["id"] == "CHR-0003#summary")
        self.assertTrue(content.startswith("Ren Chen-Silva"))
        self.assertEqual(content.count("Ren Chen-Silva"), 1)

    def test_the_prompts_carry_the_name_rule(self):
        prompts = Path(self.bf.__file__).resolve().parents[1] / "assets" / "prompts"
        reviser = (prompts / "reviser.md").read_text(encoding="utf-8")
        editor = (prompts / "technical-editor.md").read_text(encoding="utf-8")
        self.assertIn("never changes the name of a canon entity", reviser)
        self.assertIn("is `repaired` in the prose", reviser)
        self.assertIn("differs from the canon name is `blocking` and `objective`", editor)


if __name__ == "__main__":
    unittest.main()
