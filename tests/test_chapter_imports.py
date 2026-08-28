import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_imports", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ChapterImportTests(unittest.TestCase):
    """The writer, the technical editor and the reviser all build their envelope from
    the chapter's imports. A chapter that imports only the kernel is written and
    judged with no world in front of it."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]
        canon = self.project / "universe" / "canon"
        (canon / "characters" / "CHR-0001.md").write_text(
            "---\nid: CHR-0001\ncontinuity: CNT-0001\n---\n\n# Mara\n\n"
            "<!-- bf:block summary -->\nA diver who will not explain herself.\n\n"
            "<!-- bf:block voice -->\nShe answers questions with questions, and swears in German when tired.\n",
            encoding="utf-8",
        )
        (canon / "places" / "PLC-0001.md").write_text(
            "---\nid: PLC-0001\ncontinuity: CNT-0001\n---\n\n# The Archive\n\n"
            "<!-- bf:block summary -->\nA drowned reading room under the harbour.\n",
            encoding="utf-8",
        )
        self.bf.rebuild_indexes(self.project)

    def proposal(self, imports):
        return {
            "premise": "A diver must decide whether memory can be owned.",
            "entry_state": {"CHR-0001": "isolated"},
            "arc": ["refusal", "cost", "choice"],
            "exit_boundary": {"CHR-0001": "committed"},
            "chapters": [{
                "id": "CH-0001", "order": 1, "title": "The Ninth Tide", "pov": "CHR-0001",
                "beats": ["Mara wants the log and the warden will not open it"],
                "plants": [], "reveals": [], "target_words": 900,
                "imports": imports, "obligations": [], "pivotal": None,
            }],
        }

    def blocking(self, imports):
        return [row for row in self.bf.validate_book_design(self.project, self.book, self.proposal(imports))
                if row["severity"] == "blocking"]

    def test_a_chapter_importing_only_the_kernel_is_blocking(self):
        codes = {row["code"] for row in self.blocking(["UNI-0001#kernel"])}
        self.assertIn("chapter.import-pov", codes)
        self.assertIn("chapter.import-place", codes)

    def test_a_chapter_that_carries_its_world_validates(self):
        self.assertEqual(self.blocking(["UNI-0001#kernel", "CHR-0001#summary", "CHR-0001#voice", "PLC-0001#summary"]), [])

    def test_an_import_that_resolves_to_nothing_is_blocking(self):
        rows = self.blocking(["UNI-0001#kernel", "CHR-0001#summary", "CHR-0001#voice", "PLC-0001#summary", "CHR-9999#voice"])
        self.assertEqual([row["code"] for row in rows], ["chapter.import-unknown"])
        self.assertEqual(rows[0]["imports"], ["CHR-9999#voice"])

    def test_a_missing_voice_block_alone_is_named(self):
        rows = self.blocking(["UNI-0001#kernel", "CHR-0001#summary", "PLC-0001#summary"])
        self.assertEqual([row["code"] for row in rows], ["chapter.import-pov"])
        self.assertEqual(rows[0]["missing"], ["CHR-0001#voice"])

    def test_the_writer_envelope_carries_the_pov_voice(self):
        contract = {"id": "CH-0001", "book": self.book, "pov": "CHR-0001", "target_words": 900,
                    "beats": ["Mara wants the log"],
                    "imports": ["UNI-0001#kernel", "CHR-0001#summary", "CHR-0001#voice", "PLC-0001#summary"]}
        envelope = self.bf.build_envelope(self.project, role="writer", task_capsule=contract,
                                          imports=contract["imports"], state={}, tools=[], max_output_tokens=2000)
        blob = json.dumps(envelope["payload"]["context"], ensure_ascii=False)
        self.assertIn("swears in German when tired", blob)
        self.assertIn("drowned reading room", blob)

    def test_the_designer_is_told_what_imports_are_for(self):
        prompt = (Path(self.bf.__file__).resolve().parents[1] / "assets" / "prompts" / "designer.md").read_text()
        self.assertIn("written blind", prompt)
        self.assertIn("#voice", prompt)


if __name__ == "__main__":
    unittest.main()
