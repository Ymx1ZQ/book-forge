import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_backfill", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Provider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, role, envelope, attempt_dir):
        with self.lock:
            response = self.responses.pop(0)
            self.calls.append(envelope["payload"])
            number = len(self.calls)
        return {"text": json.dumps(response), "provider": "openrouter", "model": MODEL, "variant": "low", "session_id": f"ses-{number}", "tokens": {"input": envelope["estimated_input_tokens"], "output": 200}, "cost": .001, "latency_ms": 5, "finish": "stop"}


def translated(chapter, number):
    return {
        "translated_markdown": f"# Capitolo {chapter}\n\nMara trova il segnale {number} nella città sommersa. La memoria cambia ogni scelta, ma il suo nome rimane Mara.",
        "glossary_updates": [{"source": "signal", "translation": "segnale", "note": "Use consistently"}],
        "boundary": f"Mara conosce il segnale {number}.",
    }


class TranslationFixture(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        self.book = self.bf.add_book(self.project, "Book")["id"]
        chapters = self.project / f"books/{self.book}/chapters"
        chapters.mkdir()
        manuscript = self.project / f"books/{self.book}/manuscript/chapters"
        for index in (1, 2):
            chapter = f"CH-{index:04d}"
            (chapters / f"{chapter}.json").write_text(json.dumps({"schema": 1, "book": self.book, "id": chapter, "order": index, "pov": "Mara", "beats": ["Find signal"], "target_words": 30, "imports": ["UNI-0001#kernel"], "pivotal": None}))
            (manuscript / f"{chapter}.md").write_text(f"# Chapter {index}\n\nMara finds signal {index} in the drowned city. Memory changes every choice, but her name remains Mara.")
        state = self.project / f"books/{self.book}/state.yaml"
        data = json.loads(state.read_text())
        data["closed_chapters"] = ["CH-0001", "CH-0002"]
        state.write_text(json.dumps(data))
        self.bf.add_translation(self.project, self.book, "it-IT")

    def registry(self):
        return json.loads((self.project / ".book-forge/artifact-deps.json").read_text())["artifacts"]

    def wipe_registry(self):
        """A project whose chapters were promoted before the registry tracked them."""
        path = self.project / ".book-forge/artifact-deps.json"
        value = json.loads(path.read_text())
        value["artifacts"] = {}
        value["edges"] = []
        path.write_text(json.dumps(value))


class BackfillTests(TranslationFixture):
    def test_translate_closes_a_chain_holed_before_the_registry_existed(self):
        self.bf.translate_next(self.project, self.book, "it-IT", provider=Provider([translated(1, 1)]))
        self.wipe_registry()

        self.bf.translate_next(self.project, self.book, "it-IT", provider=Provider([translated(2, 2)]))

        rows = self.registry()
        first = f"TRANSLATION-{self.book}-CH-0001-it-IT"
        second = f"TRANSLATION-{self.book}-CH-0002-it-IT"
        self.assertIn(first, rows)
        self.assertIn(second, rows)
        self.assertNotIn(first, rows[first]["dependencies"])
        self.assertIn(first, rows[second]["dependencies"])
        self.assertIn(f"SOURCE-{self.book}-CH-0002", rows[second]["dependencies"])

    def test_backfill_completes_a_row_registered_without_dependencies(self):
        self.bf.translate_next(self.project, self.book, "it-IT", provider=Provider([translated(1, 1)]))
        self.wipe_registry()
        source_id = f"SOURCE-{self.book}-CH-0001"
        self.bf.register_artifact(self.project, source_id, "source-chapter", path=self.project / f"books/{self.book}/manuscript/chapters/CH-0001.md")
        self.assertEqual(self.registry()[source_id]["dependencies"], [])

        result = self.bf.backfill_artifacts(self.project, book=self.book)

        self.assertIn(source_id, result["backfilled"])
        self.assertEqual(self.registry()[source_id]["dependencies"], ["UNI-0001#kernel"])
        self.assertEqual(self.registry()[source_id]["entities"], ["Mara"])
        self.assertIn(f"TRANSLATION-{self.book}-CH-0001-it-IT", self.registry())
        self.assertEqual(self.bf.backfill_artifacts(self.project, book=self.book)["count"], 0)

    def test_reconcile_and_export_stay_clean_after_backfill(self):
        self.bf.translate_next(self.project, self.book, "it-IT", provider=Provider([translated(1, 1), translated(2, 2)]), run_all=True)
        self.wipe_registry()
        self.bf.backfill_artifacts(self.project)
        self.assertEqual(self.bf.reconcile_artifacts(self.project), [])


class RepairEnvelopeTests(TranslationFixture):
    def set_translator_budget(self, budget):
        path = self.project / "book-forge.yaml"
        config = json.loads(path.read_text())
        config.setdefault("context", {})["translator_max_input_tokens"] = budget
        # Budgets are advisory by default; this suite is about what happens at the wall.
        config["context"]["enforce_budgets"] = True
        path.write_text(json.dumps(config))

    def bad_translation(self, filler):
        return {"translated_markdown": "# Capitolo\n\n" + ("parola " * filler), "glossary_updates": [], "boundary": ""}

    def test_repair_drops_the_previous_output_instead_of_overflowing(self):
        provider = Provider([self.bad_translation(4000), translated(1, 1)])
        self.set_translator_budget(3000)

        result = self.bf.translate_next(self.project, self.book, "it-IT", provider=provider)

        self.assertEqual(result["calls"], 2)
        repair = provider.calls[1]["task"]["repair"]
        self.assertTrue(repair["previous_output_omitted"])
        self.assertNotIn("previous_output", repair)

    def test_a_real_overflow_still_raises(self):
        provider = Provider([self.bad_translation(4000), translated(1, 1)])
        self.set_translator_budget(200)
        with self.assertRaises(self.bf.ContextOverflowError):
            self.bf.translate_next(self.project, self.book, "it-IT", provider=provider)


if __name__ == "__main__":
    unittest.main()
