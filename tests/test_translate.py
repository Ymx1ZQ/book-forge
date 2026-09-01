import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path


def _decide_locale_style(bf, project, book, locale):
    """A project must decide how the book speaks before anything is translated."""
    path = bf._project_root(project) / "books" / book / "translations" / bf._canonical_locale(locale) / "style.md"
    path.write_text("---\nid: LOC\n---\n\n# Locale Style\n\n<!-- bf:block style -->\nFormal address throughout; guillemets for dialogue; past tense preserved.\n", encoding="utf-8")


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_translate", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _isolate_translator(bf, project):
    """These tests measure the translator, not the critic that now reads it back.

    The translation review is on by default, as the prose style review is, and it
    adds one call to every translation. A test that counts translator calls must
    say which of the two it is counting.
    """
    path = Path(project) / "book-forge.yaml"
    config = json.loads(path.read_text(encoding="utf-8"))
    config["translation"] = {"review": False}
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

class TranslationProvider:
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


class TranslateTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        _isolate_translator(self.bf, self.project)
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
        _decide_locale_style(self.bf, self.project, self.book, "it-IT")

    def test_translates_two_chapters_serially_one_call_each(self):
        provider = TranslationProvider([translated(1, 1), translated(2, 2)])
        result = self.bf.translate_next(self.project, self.book, "it-IT", provider=provider, run_all=True)
        self.assertEqual(result["calls"], 2)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.calls[1]["state"]["previous_boundary"], "Mara conosce il segnale 1.")
        locale = self.project / f"books/{self.book}/translations/it-IT"
        self.assertTrue((locale / "chapters/CH-0001.md").is_file())
        self.assertTrue((locale / "chapters/CH-0002.md").is_file())
        state = json.loads((locale / "state.yaml").read_text())
        self.assertEqual(state["completed_chapters"], ["CH-0001", "CH-0002"])
        self.assertEqual(state["status"], "current")

    def test_flagged_output_gets_one_repair_only(self):
        bad = {"translated_markdown": "# Capitolo\n\nManca il numero.", "glossary_updates": [], "boundary": ""}
        provider = TranslationProvider([bad, translated(1, 1)])
        result = self.bf.translate_next(self.project, self.book, "it-IT", provider=provider)
        self.assertEqual(result["calls"], 2)
        self.assertEqual(len(provider.calls), 2)

        second = Path(self.temp.name) / "blocked"
        self.bf.init_project(second, "Blocked")
        _isolate_translator(self.bf, second)
        book = self.bf.add_book(second, "Book")["id"]
        chapters = second / f"books/{book}/chapters"
        chapters.mkdir()
        (chapters / "CH-0001.json").write_text(json.dumps({"schema": 1, "book": book, "id": "CH-0001", "order": 1, "pov": "Mara", "beats": ["x"], "target_words": 20, "imports": ["UNI-0001#kernel"], "pivotal": None}))
        (second / f"books/{book}/manuscript/chapters/CH-0001.md").write_text("# Chapter 1\n\nMara sees number 42 and leaves.")
        self.bf.add_translation(second, book, "it-IT")
        _decide_locale_style(self.bf, second, book, "it-IT")
        broken = TranslationProvider([bad, bad])
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.translate_next(second, book, "it-IT", provider=broken)
        self.assertEqual(len(broken.calls), 2)


if __name__ == "__main__":
    unittest.main()


class NumberLocalizationTests(unittest.TestCase):
    """A locale may write its own decimal separator; a changed number must still fail."""

    SOURCE = "# Chapter\n\nThe Field hummed at 5.8 hertz under 1.31 g, and the exhale read 0.2% candela."

    def setUp(self):
        self.bf = load_module()

    def value(self, translated):
        return {"translated_markdown": translated, "glossary_updates": [], "boundary": "Mara sa."}

    def test_a_comma_localized_number_is_not_a_changed_number(self):
        italian = "# Capitolo\n\nIl Campo ronzava a 5,8 hertz sotto 1,31 g, e l'esalato segnava 0,2% candela."
        self.assertNotIn("numbers differ from source", self.bf._translation_validation(self.SOURCE, self.value(italian)))

    def test_a_number_that_actually_changed_is_still_caught(self):
        wrong = "# Capitolo\n\nIl Campo ronzava a 5,9 hertz sotto 1,31 g, e l'esalato segnava 0,2% candela."
        self.assertIn("numbers differ from source", self.bf._translation_validation(self.SOURCE, self.value(wrong)))

    def test_an_integer_is_not_confused_with_a_decimal(self):
        wrong = "# Capitolo\n\nIl Campo ronzava a 58 hertz sotto 1,31 g, e l'esalato segnava 0,2% candela."
        self.assertIn("numbers differ from source", self.bf._translation_validation(self.SOURCE, self.value(wrong)))
