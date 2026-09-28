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
MODEL = "openrouter/deepseek/deepseek-v4.1-flash"


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

    def test_flagged_output_gets_the_repairs_the_engine_allows(self):
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
        broken = TranslationProvider([bad] * self.bf.TRANSLATION_ATTEMPTS)
        with self.assertRaises(self.bf.TranslationRefused):
            self.bf.translate_next(second, book, "it-IT", provider=broken)
        self.assertEqual(len(broken.calls), self.bf.TRANSLATION_ATTEMPTS)

    def test_one_refused_chapter_does_not_stop_the_ones_behind_it(self):
        """CH-0005 carried `i suoi occhi` twice and took thirteen chapters with it."""
        bad = {"translated_markdown": "# Capitolo\n\nManca il numero.", "glossary_updates": [], "boundary": ""}
        chapters = self.project / f"books/{self.book}/chapters"
        source = self.project / f"books/{self.book}/manuscript/chapters"
        for order in (2, 3):
            (chapters / f"CH-{order:04d}.json").write_text(json.dumps({
                "schema": 1, "book": self.book, "id": f"CH-{order:04d}", "order": order, "pov": "Mara",
                "beats": ["Find signal"], "target_words": 30, "imports": ["UNI-0001#kernel"], "pivotal": None,
            }))
            (source / f"CH-{order:04d}.md").write_text(
                f"# Chapter {order}\n\nMara finds signal {order} in the drowned city. "
                "Memory changes every choice, but her name remains Mara.")
        provider = TranslationProvider(
            [translated(1, 1)] + [bad] * self.bf.TRANSLATION_ATTEMPTS + [translated(3, 3)] * 3
        )
        result = self.bf.translate_next(self.project, self.book, "it-IT", provider=provider, run_all=True)
        self.assertEqual([str(r["chapter"]) for r in result["refused"]], ["CH-0002"])
        self.assertIn("CH-0003", result["chapters"], "the chapter behind the refused one is still translated")
        recorded = json.loads(
            (self.project / f"books/{self.book}/translations/it-IT/refused.json").read_text())
        self.assertEqual(recorded["refused"][0]["chapter"], "CH-0002")
        self.assertIsInstance(recorded["refused"][0]["when"], (int, float), "a refusal says when it happened")

    def test_a_chapter_refused_once_and_translated_next_time_stops_being_listed(self):
        """Landfall's record still named CH-0007 and CH-0010 while both were
        translated: the file was written when a chapter was set aside and never
        touched again when it later landed, so the one file a person opens after a
        refusal to see what needs redoing was naming chapters that did not."""
        bad = {"translated_markdown": "# Capitolo\n\nManca il numero.", "glossary_updates": [], "boundary": ""}
        chapters = self.project / f"books/{self.book}/chapters"
        source = self.project / f"books/{self.book}/manuscript/chapters"
        for order in (2,):
            (chapters / f"CH-{order:04d}.json").write_text(json.dumps({
                "schema": 1, "book": self.book, "id": f"CH-{order:04d}", "order": order, "pov": "Mara",
                "beats": ["Find signal"], "target_words": 30, "imports": ["UNI-0001#kernel"], "pivotal": None,
            }))
            (source / f"CH-{order:04d}.md").write_text(
                f"# Chapter {order}\n\nMara finds signal {order} in the drowned city. "
                "Memory changes every choice, but her name remains Mara.")
        record = self.project / f"books/{self.book}/translations/it-IT/refused.json"

        refusing = TranslationProvider([translated(1, 1)] + [bad] * self.bf.TRANSLATION_ATTEMPTS)
        self.bf.translate_next(self.project, self.book, "it-IT", provider=refusing, run_all=True)
        self.assertEqual([row["chapter"] for row in json.loads(record.read_text())["refused"]], ["CH-0002"])

        landing = TranslationProvider([translated(2, 2)] * 3)
        result = self.bf.translate_next(self.project, self.book, "it-IT", provider=landing, run_all=True)
        self.assertEqual(json.loads(record.read_text())["refused"], [], "the chapter landed and left the list")
        self.assertEqual(result["refused"], [])

    def test_nothing_refused_is_written_down_rather_than_left_to_be_inferred(self):
        provider = TranslationProvider([translated(1, 1), translated(2, 2)])
        self.bf.translate_next(self.project, self.book, "it-IT", provider=provider, run_all=True)
        record = self.project / f"books/{self.book}/translations/it-IT/refused.json"
        self.assertTrue(record.is_file(), "an empty list is stated, not inferred from a missing file")
        self.assertEqual(json.loads(record.read_text())["refused"], [])


class ALocaleThatRefusedEverythingTests(unittest.TestCase):
    """Found while testing the chapter reset, on the path the refusal work left
    uncovered. `translate add` seeds a workspace without `status` — the key is first
    written when a chapter *completes* — so a locale whose every chapter was refused
    reached the end of the run having done the work correctly and died reporting it,
    with `KeyError: 'status'`. The chapters were set aside, `refused.json` was
    written, the names were printed, and the report took the run with it."""

    BAD = {"translated_markdown": "# Capitolo\n\nManca il numero.", "glossary_updates": [], "boundary": ""}

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        _isolate_translator(self.bf, self.project)
        self.book = self.bf.add_book(self.project, "Book")["id"]
        chapters = self.project / f"books/{self.book}/chapters"
        chapters.mkdir(exist_ok=True)
        manuscript = self.project / f"books/{self.book}/manuscript/chapters"
        for index in (1, 2):
            chapter = f"CH-{index:04d}"
            (chapters / f"{chapter}.json").write_text(json.dumps({
                "schema": 1, "book": self.book, "id": chapter, "order": index, "pov": "Mara",
                "beats": ["Find signal"], "target_words": 30, "imports": ["UNI-0001#kernel"], "pivotal": None,
            }))
            (manuscript / f"{chapter}.md").write_text(
                f"# Chapter {index}\n\nMara finds signal {index} in the drowned city. "
                "Memory changes every choice, but her name remains Mara.")
        self.bf.add_translation(self.project, self.book, "it-IT")
        _decide_locale_style(self.bf, self.project, self.book, "it-IT")

    def refuse_everything(self):
        provider = TranslationProvider([self.BAD] * (self.bf.TRANSLATION_ATTEMPTS * 2))
        return self.bf.translate_next(self.project, self.book, "it-IT", provider=provider, run_all=True)

    def test_a_run_that_completed_nothing_still_reports(self):
        result = self.refuse_everything()
        self.assertEqual([str(row["chapter"]) for row in result["refused"]], ["CH-0001", "CH-0002"])

    def test_the_state_says_the_locale_refused_rather_than_nothing(self):
        self.assertEqual(self.refuse_everything()["state"], "refused")

    def test_a_locale_with_nothing_to_do_is_not_the_same_answer(self):
        provider = TranslationProvider([translated(1, 1), translated(2, 2)])
        self.bf.translate_next(self.project, self.book, "it-IT", provider=provider, run_all=True)
        again = self.bf.translate_next(
            self.project, self.book, "it-IT", provider=TranslationProvider([]), run_all=True,
        )
        self.assertEqual(again["state"], "current")

    def test_the_seeded_workspace_really_has_no_status_to_read(self):
        """The test above passes for the right reason only if the key is absent."""
        state = json.loads(
            (self.project / f"books/{self.book}/translations/it-IT/state.yaml").read_text(encoding="utf-8")
        )
        self.assertNotIn("status", state)

    def test_a_locale_that_translated_one_chapter_reports_its_own_status(self):
        provider = TranslationProvider([translated(1, 1)] + [self.BAD] * self.bf.TRANSLATION_ATTEMPTS)
        result = self.bf.translate_next(self.project, self.book, "it-IT", provider=provider, run_all=True)
        self.assertEqual(result["state"], "in_progress")
        self.assertEqual([str(row["chapter"]) for row in result["refused"]], ["CH-0002"])


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
        self.assertFalse(any(p.startswith("numbers differ from source") for p in self.bf._translation_validation(self.SOURCE, self.value(italian))))

    def test_a_number_that_actually_changed_is_still_caught(self):
        wrong = "# Capitolo\n\nIl Campo ronzava a 5,9 hertz sotto 1,31 g, e l'esalato segnava 0,2% candela."
        self.assertTrue(any(p.startswith("numbers differ from source") for p in self.bf._translation_validation(self.SOURCE, self.value(wrong))))

    def test_an_integer_is_not_confused_with_a_decimal(self):
        wrong = "# Capitolo\n\nIl Campo ronzava a 58 hertz sotto 1,31 g, e l'esalato segnava 0,2% candela."
        self.assertTrue(any(p.startswith("numbers differ from source") for p in self.bf._translation_validation(self.SOURCE, self.value(wrong))))




class ActionableRefusalTests(unittest.TestCase):
    """M56. A refusal the translator cannot act on is asked three times for the same text.

    The Ground Truth pilot's CH-0003 wrote "Seven-F" in the source and "7-F" in the
    translation on every ask, told only that numbers differed.
    """

    def setUp(self):
        self.bf = load_module()

    def value(self, translated):
        return {"translated_markdown": translated, "glossary_updates": [], "boundary": "Mara sa."}

    def numbers_problem(self, source, translated):
        problems = [p for p in self.bf._translation_validation(source, self.value(translated)) if p.startswith("numbers differ from source")]
        self.assertEqual(len(problems), 1, problems)
        return problems[0]

    def test_a_number_the_translation_added_is_named_with_its_sentence(self):
        source = "# Chapter\n\nThe gate held. Seven-F had taken the same cut, and 12 crews went down."
        italian = "# Capitolo\n\nIl cancello resse. Il Settore 7-F aveva subito lo stesso taglio, e 12 squadre scesero."
        problem = self.numbers_problem(source, italian)
        self.assertIn("7", problem)
        self.assertIn("Il Settore 7-F aveva subito lo stesso taglio", problem)
        self.assertNotIn("12", problem.split(":", 1)[1].replace("12 squadre", ""), "a number that matches is not reported")

    def test_a_changed_number_names_the_source_number_and_its_sentence(self):
        source = "# Chapter\n\nThe Field hummed at 5.8 hertz. Nobody slept."
        italian = "# Capitolo\n\nIl Campo ronzava a 5,9 hertz. Nessuno dormiva."
        problem = self.numbers_problem(source, italian)
        self.assertIn("5.8", problem)
        self.assertIn("The Field hummed at 5.8 hertz", problem)
        self.assertIn("5,9", problem)

    def test_a_missing_number_names_the_source_sentence(self):
        source = "# Chapter\n\nShe counted 40 lamps. Then she left."
        italian = "# Capitolo\n\nContò le lampade. Poi se ne andò."
        problem = self.numbers_problem(source, italian)
        self.assertIn("40", problem)
        self.assertIn("She counted 40 lamps", problem)

    def test_the_retry_is_told_which_number_differs(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "world"
            self.bf.init_project(project, "World")
            _isolate_translator(self.bf, project)
            book = self.bf.add_book(project, "Book")["id"]
            chapters = project / f"books/{book}/chapters"
            chapters.mkdir()
            (chapters / "CH-0001.json").write_text(json.dumps({"schema": 1, "book": book, "id": "CH-0001", "order": 1, "pov": "Mara", "beats": ["x"], "target_words": 30, "imports": ["UNI-0001#kernel"], "pivotal": None}))
            (project / f"books/{book}/manuscript/chapters/CH-0001.md").write_text("# Chapter 1\n\nMara finds the signal in the drowned city. Seven-F had taken the same cut, and her name remains Mara.")
            state = project / f"books/{book}/state.yaml"
            data = json.loads(state.read_text())
            data["closed_chapters"] = ["CH-0001"]
            state.write_text(json.dumps(data))
            self.bf.add_translation(project, book, "it-IT")
            _decide_locale_style(self.bf, project, book, "it-IT")
            bad = {"translated_markdown": "# Capitolo 1\n\nMara trova il segnale nella città sommersa. Il Settore 7-F aveva subito lo stesso taglio, e il suo nome rimane Mara.", "glossary_updates": [], "boundary": "Mara sa."}
            good = {**bad, "translated_markdown": bad["translated_markdown"].replace("7-F", "Sette-F")}
            provider = TranslationProvider([bad, good])
            self.bf.translate_next(project, book, "it-IT", provider=provider)
            reason = provider.calls[1]["task"]["repair"]["reason"]
            self.assertIn("Il Settore 7-F aveva subito lo stesso taglio", reason)


class ForbiddenFormQuotingTests(unittest.TestCase):
    """M56. The Italian preposition rule matched "A lo" inside "Settore 7-A lo accolse"
    and the refusal quoted a single letter."""

    PATTERN = r"\b(in|a|da|di)\s+(il|lo)\b"

    def setUp(self):
        self.bf = load_module()

    def test_the_refusal_quotes_the_whole_match_its_context_and_the_pattern(self):
        text = "Il varco si aprì. Il Settore 7-A lo accolse senza una parola."
        problems = self.bf._forbidden_form_problems(text, {"forbidden": [{"pattern": self.PATTERN, "reason": "preposizione non articolata"}]})
        self.assertEqual(len(problems), 1, problems)
        problem = problems[0]
        self.assertIn("A lo", problem)
        self.assertIn("Settore 7-A lo accolse", problem)
        self.assertIn(self.PATTERN, problem)
        self.assertIn("case-insensitive", problem)
        self.assertIn("preposizione non articolata", problem)

    def test_patterns_ignore_case_by_default(self):
        """Existing locale rules rely on it: `stette` must also catch a sentence-initial `Stette`."""
        problems = self.bf._forbidden_form_problems("Stette zitta.", {"forbidden": [{"pattern": r"\bstette\b", "reason": "x"}]})
        self.assertEqual(len(problems), 1)

    def test_a_row_can_ask_for_case_sensitive_matching(self):
        checks = {"forbidden": [{"pattern": self.PATTERN, "reason": "x", "case_sensitive": True}]}
        self.assertEqual(self.bf._forbidden_form_problems("Il Settore 7-A lo accolse.", checks), [])
        problems = self.bf._forbidden_form_problems("Andò a lo sportello.", checks)
        self.assertEqual(len(problems), 1)
        self.assertIn("case-sensitive", problems[0])


class StaleTranslatorPinTests(unittest.TestCase):
    """M56. A pin changed without `runtime sync` stops the route before any call."""

    setUp = TranslateTests.setUp

    def test_translation_is_refused_before_the_provider_is_asked(self):
        path = self.project / "book-forge.yaml"
        config = json.loads(path.read_text())
        config["roles"] = {"translator": {"model": "openrouter/z-ai/glm-5.3-flash", "variant": "high"}}
        path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        provider = TranslationProvider([translated(1, 1)])
        with self.assertRaises(self.bf.StaleRuntime) as refused:
            self.bf.translate_next(self.project, self.book, "it-IT", provider=provider)
        self.assertIn("runtime sync", str(refused.exception))
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.bf._load_plan(self.project)["attempts"], [])
