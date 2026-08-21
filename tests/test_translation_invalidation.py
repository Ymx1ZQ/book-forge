import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_translation_invalidation", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Provider:
    def __init__(self):
        self.count = 0
    def __call__(self, role, envelope, attempt_dir):
        self.count += 1
        chapter = envelope["payload"]["task"]["chapter"]
        number = int(chapter[-4:])
        value = {"translated_markdown": f"# Capitolo {number}\n\nMara vede il segnale {number} e continua.", "glossary_updates": [], "boundary": f"confine-{number}"}
        return {"text": json.dumps(value), "provider": "openrouter", "model": MODEL, "variant": "low", "session_id": f"ses-{number}", "tokens": {}, "cost": 0, "latency_ms": 1, "finish": "stop"}


class TranslationInvalidationTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        self.book = self.bf.add_book(self.project, "Book")["id"]
        contracts = self.project / f"books/{self.book}/chapters"
        contracts.mkdir()
        manuscript = self.project / f"books/{self.book}/manuscript/chapters"
        for index in (1, 2, 3):
            chapter = f"CH-{index:04d}"
            (contracts / f"{chapter}.json").write_text(json.dumps({"schema": 1, "book": self.book, "id": chapter, "order": index, "pov": "Mara", "beats": ["signal"], "target_words": 20, "imports": ["UNI-0001#kernel"], "pivotal": None}))
            (manuscript / f"{chapter}.md").write_text(f"# Chapter {index}\n\nMara sees signal {index} and continues.")
        self.bf.add_translation(self.project, self.book, "it-IT")
        self.bf.translate_next(self.project, self.book, "it-IT", provider=Provider(), run_all=True)

    def test_source_edit_marks_direct_prose_and_boundary_audit_suffix(self):
        locale = self.project / f"books/{self.book}/translations/it-IT"
        before = {path.name: path.read_bytes() for path in (locale / "chapters").glob("*.md")}
        source = self.project / f"books/{self.book}/manuscript/chapters/CH-0002.md"
        source.write_text(source.read_text() + "\nA new fact.")

        impact = self.bf.translation_impact(self.project, self.book, "it-IT")
        self.assertEqual(impact["stale_prose"], ["CH-0002"])
        self.assertEqual(impact["boundary_audit"], ["CH-0003"])
        self.assertIn("source hash changed", impact["causes"]["CH-0002"])
        self.assertEqual({path.name: path.read_bytes() for path in (locale / "chapters").glob("*.md")}, before)

        state = json.loads((locale / "state.yaml").read_text())
        same = self.bf.converge_translation_boundaries(
            self.project, self.book, "it-IT", changed_chapter="CH-0002",
            recomputed={"CH-0002": state["boundary_hashes"]["CH-0002"]},
        )
        self.assertEqual(same["stale_prose"], ["CH-0002"])

    def test_changed_boundary_cascades_until_next_boundary_converges(self):
        result = self.bf.converge_translation_boundaries(
            self.project, self.book, "it-IT", changed_chapter="CH-0001",
            recomputed={"CH-0001": "new-1", "CH-0002": "new-2", "CH-0003": "same-3"},
        )
        self.assertEqual(result["stale_prose"], ["CH-0001", "CH-0002", "CH-0003"])

    def test_locale_style_edit_invalidates_every_direct_consumer(self):
        style = self.project / f"books/{self.book}/translations/it-IT/style.md"
        style.write_text(style.read_text() + "\nUse formal address.\n")
        impact = self.bf.translation_impact(self.project, self.book, "it-IT")
        self.assertEqual(impact["stale_prose"], ["CH-0001", "CH-0002", "CH-0003"])
        self.assertEqual(impact["boundary_audit"], [])


if __name__ == "__main__":
    unittest.main()
