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



class BlockCatalogueTests(unittest.TestCase):
    """Validation demanded CHR-0001#voice from a designer whose 62 context rows were
    all summaries: it had no way to learn the block existed."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        config_path = self.project / "book-forge.yaml"
        config = json.loads(config_path.read_text())
        config["chorus"] = {"enabled": False, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER}
        config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.book = self.bf.add_book(self.project, "A")["id"]
        (self.project / f"books/{self.book}/book-brief.json").write_text(
            json.dumps({"schema": 1, "premise": "A diver decides.", "characters": ["Mara"], "plot": ["dive"], "tone": "quiet"})
        )
        canon = self.project / "universe" / "canon"
        (canon / "characters" / "CHR-0001.md").write_text(
            "---\nid: CHR-0001\ncontinuity: CNT-0001\n---\n\n# Mara\n\n"
            "<!-- bf:block summary -->\nA diver.\n\n<!-- bf:block voice -->\nShe deflects.\n", encoding="utf-8")
        (canon / "eras").mkdir(parents=True, exist_ok=True)
        (canon / "eras" / "ERA-0001.md").write_text(
            "---\nid: ERA-0001\ncontinuity: CNT-0001\n---\n\n# Now\n\n"
            "<!-- bf:block summary -->\nThe present.\n\n<!-- bf:block when -->\n2026\n", encoding="utf-8")
        self.bf.rebuild_indexes(self.project)

    def test_the_capsule_lists_the_blocks_the_validator_can_demand(self):
        seen = {}
        original = self.bf.build_envelope

        def spy(project, **kwargs):
            envelope = original(project, **kwargs)
            if kwargs.get("role") == "designer" and not seen:
                seen.update(envelope["payload"]["task"])
            return envelope

        self.bf.build_envelope = spy
        try:
            self.bf.execute_book_design(self.project, self.book, provider=self.provider, no_chorus=True, no_post_chorus=True)
        except Exception:
            pass
        finally:
            self.bf.build_envelope = original
        catalogue = seen.get("available_blocks") or []
        self.assertIn("CHR-0001#voice", catalogue)
        self.assertIn("ERA-0001#when", catalogue)
        self.assertIn("UNI-0001#kernel", catalogue)

    def provider(self, role, envelope, attempt_dir):
        chunk = (envelope["payload"]["task"].get("chunk") or {})
        if chunk.get("category") == "spine":
            payload = {"premise": "p", "entry_state": {}, "arc": ["a", "b", "c"], "exit_boundary": {},
                       "chapter_outline": [{"id": "CH-0001", "order": 1, "title": "T", "pov": "CHR-0001", "summary": "s"}]}
        else:
            payload = {"chapters": [{"id": "CH-0001", "order": 1, "title": "T", "pov": "CHR-0001",
                                     "beats": ["b"], "plants": [], "reveals": [], "target_words": 900,
                                     "imports": ["UNI-0001#kernel"], "obligations": [], "pivotal": None}]}
        return {"text": json.dumps(payload), "provider": "openrouter",
                "model": "openrouter/deepseek/deepseek-v4-flash-0731", "variant": "medium",
                "session_id": "s", "tokens": {"input": 1, "output": 1}, "cost": 0.0, "latency_ms": 1, "finish": "stop"}

    def test_the_repair_hint_names_the_catalogue_when_imports_fail(self):
        source = Path(self.bf.__file__).read_text()
        self.assertIn('is_import_error = any("chapter.import"', source)
        self.assertIn("the ids from available_blocks rather than assuming which blocks exist", source)


if __name__ == "__main__":
    unittest.main()
