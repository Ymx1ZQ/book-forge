import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_reset", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResetFixture(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "universe"
        self.bf.init_project(self.project, "Universe", "en", chorus_models=[], style_preset="plain-concrete")
        self.book = self.bf.add_book(self.project, "Book One")["id"]
        root = self.project
        book = root / "books" / self.book

        (book / "book-brief.json").write_text(json.dumps({"premise": "A town keeps a ledger."}), encoding="utf-8")
        (book / "design-audit.json").write_text(json.dumps({"findings": []}), encoding="utf-8")
        self.bf._write_json(book / "outline.yaml", {"schema": 1, "chapters": [{"id": "CH-0001"}, {"id": "CH-0002"}]})
        (book / "design.md").write_text("---\nid: BOOK\n---\n\n# Book One\n\n<!-- bf:block premise -->\nA town.\n", encoding="utf-8")
        (book / "reader-state.md").write_text("# Reader State\n\nThe reader knows the ledger exists.\n", encoding="utf-8")
        for index in (1, 2):
            chapter = f"CH-{index:04d}"
            self.bf._write_json(book / "chapters" / f"{chapter}.json", {"id": chapter, "book": self.book, "target_words": 900})
            (book / "manuscript" / "chapters" / f"{chapter}.md").write_text(f"# {chapter}\n\nProse.\n", encoding="utf-8")
            (book / "reviews" / chapter).mkdir(parents=True, exist_ok=True)
            (book / "reviews" / chapter / "cold.json").write_text("{}", encoding="utf-8")
            translated = book / "translations" / "it" / "chapters"
            translated.mkdir(parents=True, exist_ok=True)
            (translated / f"{chapter}.md").write_text(f"# {chapter}\n\nProsa.\n", encoding="utf-8")
        (book / "translations" / "it" / "glossary.md").write_text("# Glossary\n", encoding="utf-8")
        self.bf._write_json(
            book / "translations" / "it" / "state.yaml",
            {"schema": 1, "locale": "it", "completed_chapters": ["CH-0001", "CH-0002"], "current": True, "boundary_hashes": {"CH-0001": "abc"}, "input_hashes": {"source": "def"}},
        )
        self.bf._write_json(book / "state.yaml", {"schema": 1, "closed_chapters": ["CH-0001", "CH-0002"], "consequences": [{"fact": "the ledger burned"}]})
        (root / "dist" / self.book / "en").mkdir(parents=True, exist_ok=True)
        (root / "dist" / self.book / "en" / "book-one-en.epub").write_text("edition", encoding="utf-8")
        (book / "work" / "CH-0001").mkdir(parents=True, exist_ok=True)
        (book / "work" / "CH-0001" / "variant.md").write_text("variant", encoding="utf-8")
        (book / "coldread-state").mkdir(exist_ok=True)
        (book / "coldread-state" / "CH-0001.json").write_text("{}", encoding="utf-8")

        for task_id, role in (
            (f"DESIGN-{self.book}", "designer"),
            (f"AUDIT-{self.book}", "canon-auditor"),
            ("AUDIT-UNI-0001", "canon-auditor"),
            (f"DRAFT-{self.book}-CH-0001", "writer"),
            (f"REVISE-{self.book}-CH-0001", "reviser"),
            (f"TRANSLATE-{self.book}-CH-0001-it", "translator"),
            (f"STYLE-{self.book}-CH-0001-glm-5-3-flash", "advisor-glm-5-3-flash"),
        ):
            self.bf.add_task(self.project, task_id, role, deps=[], priority=50, outputs=[])
        plan = self.bf._load_plan(root)
        for task in plan["tasks"]:
            task["state"] = "succeeded"
        self.bf._save_plan(root, plan)

        self.bf.register_artifact(self.project, f"SOURCE-{self.book}-CH-0001", "source-chapter", path=f"books/{self.book}/manuscript/chapters/CH-0001.md", dependencies=[])
        self.bf.register_artifact(self.project, f"TRANSLATION-{self.book}-CH-0001-it", "translation-chapter", path=f"books/{self.book}/translations/it/chapters/CH-0001.md", dependencies=[])
        self.bf.register_artifact(self.project, f"LOCALE-GLOSSARY-{self.book}-it", "locale-glossary", path=f"books/{self.book}/translations/it/glossary.md", dependencies=[])

    def task_ids(self):
        return sorted(str(task["id"]) for task in self.bf._load_plan(self.project)["tasks"])

    def artifact_ids(self):
        return sorted(json.loads((self.project / ".book-forge" / "artifact-deps.json").read_text())["artifacts"])


class ProseResetTests(ResetFixture):
    def test_the_prose_and_everything_derived_from_it_is_removed(self):
        self.bf.reset_book(self.project, self.book, confirm=True)
        book = self.project / "books" / self.book
        self.assertEqual(list(book.glob("manuscript/chapters/*.md")), [])
        self.assertEqual(list(book.glob("translations/it/chapters/*.md")), [])
        self.assertEqual(list((book / "reviews").glob("*")), [])
        self.assertEqual(list((book / "work").glob("*")), [])
        self.assertEqual(list((book / "coldread-state").glob("*")), [])
        self.assertEqual(list((self.project / "dist" / self.book).glob("*")), [])

    def test_the_plan_stops_claiming_the_chapter_work_succeeded(self):
        self.bf.reset_book(self.project, self.book, confirm=True)
        self.assertEqual(self.task_ids(), [f"AUDIT-{self.book}", "AUDIT-UNI-0001", f"DESIGN-{self.book}"])

    def test_the_book_state_and_the_translation_workspace_are_reseeded(self):
        self.bf.reset_book(self.project, self.book, confirm=True)
        book = self.project / "books" / self.book
        self.assertEqual(json.loads((book / "state.yaml").read_text()), {"schema": 1, "closed_chapters": []})
        state = json.loads((book / "translations" / "it" / "state.yaml").read_text())
        self.assertEqual(state["completed_chapters"], [])
        self.assertEqual(state["boundary_hashes"], {})
        self.assertNotIn("input_hashes", state)

    def test_the_artifact_registry_drops_the_rows_whose_files_are_gone(self):
        self.bf.reset_book(self.project, self.book, confirm=True)
        self.assertEqual(self.artifact_ids(), [f"LOCALE-GLOSSARY-{self.book}-it"])

    def test_the_design_and_the_inputs_survive(self):
        self.bf.reset_book(self.project, self.book, confirm=True)
        book = self.project / "books" / self.book
        self.assertEqual(len(list(book.glob("chapters/*.json"))), 2)
        self.assertIn("A town.", (book / "design.md").read_text())
        self.assertIn("the ledger exists", (book / "reader-state.md").read_text())
        self.assertTrue((book / "book-brief.json").is_file())
        self.assertTrue((book / "book.yaml").is_file())
        self.assertTrue((book / "continuity.yaml").is_file())
        self.assertTrue((book / "translations" / "it" / "glossary.md").is_file())
        self.assertTrue((self.project / "universe" / "kernel.md").is_file())

    def test_the_rendered_plan_view_agrees_with_the_plan(self):
        self.bf.reset_book(self.project, self.book, confirm=True)
        rendered = (self.project / "DEVPLAN.md").read_text()
        self.assertNotIn(f"DRAFT-{self.book}-CH-0001", rendered)
        self.assertIn(f"DESIGN-{self.book}", rendered)
        control = json.loads((self.project / ".book-forge" / "control.json").read_text())
        self.assertIn(control["plan_hash"], rendered)


class DesignResetTests(ResetFixture):
    def test_the_beats_and_the_design_go_too(self):
        self.bf.reset_book(self.project, self.book, scope="design", confirm=True)
        book = self.project / "books" / self.book
        self.assertEqual(list(book.glob("chapters/*.json")), [])
        self.assertEqual(json.loads((book / "outline.yaml").read_text())["chapters"], [])
        self.assertNotIn("A town.", (book / "design.md").read_text())
        self.assertEqual((book / "reader-state.md").read_text(), "# Reader State\n")
        self.assertFalse((book / "design-audit.json").exists())

    def test_the_design_tasks_are_dropped_but_the_universe_audit_is_not(self):
        self.bf.reset_book(self.project, self.book, scope="design", confirm=True)
        self.assertEqual(self.task_ids(), ["AUDIT-UNI-0001"])

    def test_the_brief_and_the_canon_still_survive(self):
        self.bf.reset_book(self.project, self.book, scope="design", confirm=True)
        book = self.project / "books" / self.book
        self.assertTrue((book / "book-brief.json").is_file())
        self.assertTrue((book / "book.yaml").is_file())
        self.assertTrue((self.project / "universe" / "kernel.md").is_file())


class ResetGuardTests(ResetFixture):
    def test_a_reset_without_confirmation_changes_nothing(self):
        before = sorted(str(path) for path in (self.project / "books").rglob("*"))
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.reset_book(self.project, self.book)
        self.assertEqual(sorted(str(path) for path in (self.project / "books").rglob("*")), before)
        self.assertIn(f"DRAFT-{self.book}-CH-0001", self.task_ids())

    def test_an_unknown_scope_or_book_fails(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.reset_book(self.project, self.book, scope="everything", confirm=True)
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.reset_book(self.project, "BOOK-9999", confirm=True)

    def test_the_receipt_names_what_went_and_what_stayed(self):
        receipt = self.bf.reset_book(self.project, self.book, confirm=True)
        self.assertEqual(receipt["scope"], "prose")
        self.assertIn(f"books/{self.book}/manuscript/chapters/CH-0001.md", receipt["removed_paths"])
        self.assertIn(f"DRAFT-{self.book}-CH-0001", receipt["dropped_tasks"])
        self.assertIn(f"SOURCE-{self.book}-CH-0001", receipt["dropped_artifacts"])
        self.assertEqual(receipt["reset_locales"], ["it"])
        self.assertTrue(receipt["kept"])


class TranslationResetTests(ResetFixture):
    """Landfall's Italian came back with the wrong tense rule and a translator on
    `low`. Both causes were fixed at the source, and then nothing could ask the
    question again: `translate run` skips a chapter whose file exists, and the
    only reset that revisited it deleted the English manuscript with it."""

    def setUp(self):
        super().setUp()
        book = self.project / "books" / self.book
        for locale in ("it", "fr"):
            workspace = book / "translations" / locale
            (workspace / "chapters").mkdir(parents=True, exist_ok=True)
            self.bf._write_json(workspace / "locale.yaml", {"schema": 1, "id": f"LOC-{locale.upper()}", "book": self.book, "locale": locale})
            (workspace / "chapters" / "CH-0001.md").write_text(f"# CH-0001\n\n{locale}\n", encoding="utf-8")
            if not (workspace / "state.yaml").is_file():
                self.bf._write_json(workspace / "state.yaml", {"schema": 1, "locale": locale, "completed_chapters": ["CH-0001"], "current": True, "boundary_hashes": {"CH-0001": "abc"}})
        (self.project / "dist" / self.book / "it").mkdir(parents=True, exist_ok=True)
        (self.project / "dist" / self.book / "it" / "book-one-it.epub").write_text("edizione", encoding="utf-8")

    def reset_it(self):
        return self.bf.reset_book(self.project, self.book, scope="translation", confirm=True, locale="it")

    def test_the_locale_loses_its_chapters_and_its_editions(self):
        receipt = self.reset_it()
        book = self.project / "books" / self.book
        self.assertEqual(list((book / "translations" / "it" / "chapters").glob("*.md")), [])
        self.assertFalse((self.project / "dist" / self.book / "it" / "book-one-it.epub").exists())
        self.assertTrue(receipt["removed_paths"])

    def test_the_prose_it_was_translated_from_is_untouched(self):
        book = self.project / "books" / self.book
        before = {path.name: path.read_bytes() for path in (book / "manuscript" / "chapters").glob("*.md")}
        self.reset_it()
        after = {path.name: path.read_bytes() for path in (book / "manuscript" / "chapters").glob("*.md")}
        self.assertEqual(before, after)
        self.assertTrue(before)
        self.assertTrue((book / "design-audit.json").is_file())
        self.assertTrue((book / "chapters" / "CH-0001.json").is_file())
        self.assertEqual(self.bf._read_json(book / "state.yaml")["closed_chapters"], ["CH-0001", "CH-0002"])

    def test_another_locale_keeps_its_own_translation(self):
        self.reset_it()
        book = self.project / "books" / self.book
        self.assertTrue((book / "translations" / "fr" / "chapters" / "CH-0001.md").is_file())
        self.assertEqual(self.bf._read_json(book / "translations" / "fr" / "state.yaml").get("locale", "fr"), "fr")

    def test_the_locale_state_forgets_what_it_had_completed(self):
        self.reset_it()
        state = self.bf._read_json(self.project / "books" / self.book / "translations" / "it" / "state.yaml")
        self.assertEqual(state["completed_chapters"], [])
        self.assertEqual(state["boundary_hashes"], {})
        self.assertTrue(state["current"])

    def test_only_that_locale_translate_task_is_dropped(self):
        self.bf.add_task(self.project, f"TRANSLATE-{self.book}-CH-0001-fr", "translator", deps=[], priority=50, outputs=[])
        self.reset_it()
        ids = {str(task["id"]) for task in self.bf._load_plan(self.project)["tasks"]}
        self.assertNotIn(f"TRANSLATE-{self.book}-CH-0001-it", ids)
        self.assertIn(f"TRANSLATE-{self.book}-CH-0001-fr", ids)
        self.assertIn(f"DRAFT-{self.book}-CH-0001", ids)
        self.assertIn(f"DESIGN-{self.book}", ids)

    def test_it_refuses_without_a_locale_and_names_the_ones_the_book_has(self):
        with self.assertRaises(self.bf.BookForgeError) as raised:
            self.bf.reset_book(self.project, self.book, scope="translation", confirm=True)
        self.assertIn("it", str(raised.exception))
        self.assertIn("fr", str(raised.exception))

    def test_it_refuses_a_locale_the_book_does_not_have(self):
        with self.assertRaises(self.bf.BookForgeError) as raised:
            self.bf.reset_book(self.project, self.book, scope="translation", confirm=True, locale="de")
        self.assertIn("de", str(raised.exception))
        self.assertTrue((self.project / "books" / self.book / "translations" / "it" / "chapters" / "CH-0001.md").is_file())

    def test_it_still_needs_confirmation(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.reset_book(self.project, self.book, scope="translation", locale="it")
        self.assertTrue((self.project / "books" / self.book / "translations" / "it" / "chapters" / "CH-0001.md").is_file())


class ChapterResetTests(ResetFixture):
    """The style preset gained three rules after seventeen chapters were written,
    and the chapters that needed rewriting were the ones written before them.
    `--scope prose` would have deleted sixteen good chapters and every translation
    of them to redo the first; deleting the file by hand leaves the plan reporting
    DRAFT as succeeded, which is the failure `reset_book` exists to prevent."""

    def setUp(self):
        super().setUp()
        book = self.project / "books" / self.book
        for locale in ("it", "fr"):
            workspace = book / "translations" / locale
            (workspace / "chapters").mkdir(parents=True, exist_ok=True)
            self.bf._write_json(workspace / "locale.yaml", {"schema": 1, "id": f"LOC-{locale.upper()}", "book": self.book, "locale": locale})
            for chapter in ("CH-0001", "CH-0002"):
                (workspace / "chapters" / f"{chapter}.md").write_text(f"# {chapter}\n\n{locale}\n", encoding="utf-8")
            self.bf._write_json(
                workspace / "state.yaml",
                {
                    "schema": 1, "locale": locale, "completed_chapters": ["CH-0001", "CH-0002"],
                    "current": True, "status": "current", "boundary": "the ledger is open",
                    "boundary_hashes": {"CH-0001": "abc", "CH-0002": "def"},
                    "input_hashes": {"source": {"CH-0001": "s1", "CH-0002": "s2"}, "canon": {"CH-0001": {}, "CH-0002": {}}, "global": {"style": "g"}},
                },
            )
        for chapter in ("CH-0001", "CH-0002"):
            (book / "reviews" / chapter).mkdir(parents=True, exist_ok=True)
            (book / "reviews" / chapter / "cold.json").write_text("{}", encoding="utf-8")
            (book / "work" / chapter).mkdir(parents=True, exist_ok=True)
            (book / "work" / chapter / "draft.md").write_text("draft", encoding="utf-8")
            (book / "coldread-state" / f"{chapter}.json").write_text("{}", encoding="utf-8")
        for task_id, role in (
            (f"DRAFT-{self.book}-CH-0002", "writer"),
            (f"REVISE-{self.book}-CH-0002", "reviser"),
            (f"TRANSLATE-{self.book}-CH-0002-it", "translator"),
            (f"STYLE-{self.book}-CH-0002-glm-5-3-flash", "advisor-glm-5-3-flash"),
        ):
            self.bf.add_task(self.project, task_id, role, deps=[], priority=50, outputs=[])
        plan = self.bf._load_plan(self.project)
        for task in plan["tasks"]:
            task["state"] = "succeeded"
        plan["attempts"] = [
            {"id": "ATT-0001", "task": f"DRAFT-{self.book}-CH-0001", "state": "promoted"},
            {"id": "ATT-0002", "task": f"DRAFT-{self.book}-CH-0002", "state": "promoted"},
        ]
        self.bf._save_plan(self.project, plan)
        state = self.bf._read_json(book / "state.yaml")
        state["previous_chapter_tail"] = "# CH-0002\n\nProse.\n"
        self.bf._write_json(book / "state.yaml", state)
        self.bf.register_artifact(self.project, f"SOURCE-{self.book}-CH-0002", "source-chapter", path=f"books/{self.book}/manuscript/chapters/CH-0002.md", dependencies=[])

    def reset_chapter(self, chapter="CH-0001", **kwargs):
        return self.bf.reset_book(self.project, self.book, confirm=True, chapter=chapter, **kwargs)

    def state(self):
        return self.bf._read_json(self.project / "books" / self.book / "state.yaml")

    def locale_state(self, locale):
        return self.bf._read_json(self.project / "books" / self.book / "translations" / locale / "state.yaml")

    def test_only_that_chapter_prose_work_and_reviews_go(self):
        self.reset_chapter()
        book = self.project / "books" / self.book
        self.assertFalse((book / "manuscript" / "chapters" / "CH-0001.md").exists())
        self.assertTrue((book / "manuscript" / "chapters" / "CH-0002.md").is_file())
        self.assertFalse((book / "reviews" / "CH-0001").exists())
        self.assertTrue((book / "reviews" / "CH-0002").is_dir())
        self.assertFalse((book / "work" / "CH-0001").exists())
        self.assertTrue((book / "work" / "CH-0002" / "draft.md").is_file())
        self.assertFalse((book / "coldread-state" / "CH-0001.json").exists())
        self.assertTrue((book / "coldread-state" / "CH-0002.json").is_file())

    def test_the_chapter_translation_goes_in_every_locale_and_the_others_stay(self):
        self.reset_chapter()
        book = self.project / "books" / self.book
        for locale in ("it", "fr"):
            self.assertFalse((book / "translations" / locale / "chapters" / "CH-0001.md").exists())
            self.assertTrue((book / "translations" / locale / "chapters" / "CH-0002.md").is_file())
            self.assertEqual(self.locale_state(locale)["completed_chapters"], ["CH-0002"])
            self.assertEqual(sorted(self.locale_state(locale)["boundary_hashes"]), ["CH-0002"])
            self.assertEqual(sorted(self.locale_state(locale)["input_hashes"]["source"]), ["CH-0002"])
            self.assertEqual(self.locale_state(locale)["status"], "in_progress")

    def test_the_chapter_leaves_the_closed_list_and_the_others_keep_their_place(self):
        self.reset_chapter()
        self.assertEqual(self.state()["closed_chapters"], ["CH-0002"])

    def test_the_consequences_the_other_chapters_are_written_against_survive(self):
        self.reset_chapter()
        self.assertEqual(self.state()["consequences"], [{"fact": "the ledger burned"}])

    def test_only_that_chapter_tasks_and_attempts_are_dropped(self):
        receipt = self.reset_chapter()
        ids = set(self.task_ids())
        self.assertNotIn(f"DRAFT-{self.book}-CH-0001", ids)
        self.assertNotIn(f"REVISE-{self.book}-CH-0001", ids)
        self.assertNotIn(f"TRANSLATE-{self.book}-CH-0001-it", ids)
        self.assertNotIn(f"STYLE-{self.book}-CH-0001-glm-5-3-flash", ids)
        self.assertIn(f"DRAFT-{self.book}-CH-0002", ids)
        self.assertIn(f"TRANSLATE-{self.book}-CH-0002-it", ids)
        self.assertIn(f"DESIGN-{self.book}", ids)
        self.assertIn(f"AUDIT-{self.book}", ids)
        attempts = [str(row["task"]) for row in self.bf._load_plan(self.project)["attempts"]]
        self.assertEqual(attempts, [f"DRAFT-{self.book}-CH-0002"])
        self.assertEqual(receipt["chapter"], "CH-0001")
        self.assertEqual(receipt["dropped_artifacts"], [f"SOURCE-{self.book}-CH-0001", f"TRANSLATION-{self.book}-CH-0001-it"])

    def test_the_tail_the_next_chapter_is_written_against_follows_the_last_survivor(self):
        self.reset_chapter("CH-0002")
        self.assertEqual(self.state()["closed_chapters"], ["CH-0001"])
        self.assertEqual(self.state()["previous_chapter_tail"], "# CH-0001\n\nProse.\n")
        for locale in ("it", "fr"):
            self.assertEqual(self.locale_state(locale)["boundary"], "")

    def test_resetting_a_chapter_in_the_middle_leaves_the_tail_where_it_was(self):
        self.reset_chapter("CH-0001")
        self.assertEqual(self.state()["previous_chapter_tail"], "# CH-0002\n\nProse.\n")
        self.assertEqual(self.locale_state("it")["boundary"], "the ledger is open")

    def test_a_locale_can_lose_one_chapter_without_the_prose_or_the_other_locale(self):
        self.bf.reset_book(self.project, self.book, scope="translation", confirm=True, locale="it", chapter="CH-0001")
        book = self.project / "books" / self.book
        self.assertTrue((book / "manuscript" / "chapters" / "CH-0001.md").is_file())
        self.assertFalse((book / "translations" / "it" / "chapters" / "CH-0001.md").exists())
        self.assertTrue((book / "translations" / "it" / "chapters" / "CH-0002.md").is_file())
        self.assertTrue((book / "translations" / "fr" / "chapters" / "CH-0001.md").is_file())
        self.assertEqual(self.locale_state("it")["completed_chapters"], ["CH-0002"])
        self.assertEqual(self.locale_state("fr")["completed_chapters"], ["CH-0001", "CH-0002"])
        self.assertEqual(self.state()["closed_chapters"], ["CH-0001", "CH-0002"])
        ids = set(self.task_ids())
        self.assertNotIn(f"TRANSLATE-{self.book}-CH-0001-it", ids)
        self.assertIn(f"TRANSLATE-{self.book}-CH-0002-it", ids)
        self.assertIn(f"DRAFT-{self.book}-CH-0001", ids)

    def test_the_editions_go_because_every_one_of_them_carries_the_chapter(self):
        self.reset_chapter()
        self.assertEqual(list((self.project / "dist" / self.book).glob("*")), [])

    def test_it_refuses_a_chapter_the_book_does_not_have(self):
        with self.assertRaises(self.bf.BookForgeError) as raised:
            self.reset_chapter("CH-0009")
        self.assertIn("CH-0009", str(raised.exception))
        self.assertIn("CH-0001", str(raised.exception))
        self.assertIn("CH-0002", str(raised.exception))
        self.assertTrue((self.project / "books" / self.book / "manuscript" / "chapters" / "CH-0001.md").is_file())

    def test_it_refuses_to_narrow_a_design_reset_to_one_chapter(self):
        with self.assertRaises(self.bf.BookForgeError) as raised:
            self.bf.reset_book(self.project, self.book, scope="design", confirm=True, chapter="CH-0001")
        self.assertIn("design", str(raised.exception))
        self.assertTrue((self.project / "books" / self.book / "chapters" / "CH-0001.json").is_file())

    def test_it_still_needs_confirmation(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.reset_book(self.project, self.book, chapter="CH-0001")
        self.assertTrue((self.project / "books" / self.book / "manuscript" / "chapters" / "CH-0001.md").is_file())

    def test_no_surviving_task_is_left_depending_on_a_dropped_one(self):
        self.bf.add_task(self.project, f"VERIFY-{self.book}-CH-0002", "judge", deps=[f"DRAFT-{self.book}-CH-0001"], priority=50, outputs=[])
        self.reset_chapter()
        survivor = next(row for row in self.bf._load_plan(self.project)["tasks"] if str(row["id"]) == f"VERIFY-{self.book}-CH-0002")
        self.assertEqual(survivor["deps"], [])

    def test_a_translation_leans_on_the_chapter_before_it_and_never_on_one_after(self):
        # After a reset of the first chapter the second is the last one completed.
        # Reading the last completed chapter made the first depend on the second
        # while the second still depended on the first, and the frontier recursed.
        self.assertEqual(
            self.bf._previous_translated_chapter(self.project, self.book, "CH-0001", ["CH-0002"]),
            None,
        )
        self.assertEqual(
            self.bf._previous_translated_chapter(self.project, self.book, "CH-0002", ["CH-0001"]),
            "CH-0001",
        )

    def test_a_chapter_the_locale_refused_is_stepped_over_rather_than_waited_for(self):
        self.bf._write_json(
            self.project / "books" / self.book / "outline.yaml",
            {"schema": 1, "chapters": [{"id": "CH-0001", "order": 1}, {"id": "CH-0002", "order": 2}, {"id": "CH-0003", "order": 3}]},
        )
        self.assertEqual(
            self.bf._previous_translated_chapter(self.project, self.book, "CH-0003", ["CH-0001"]),
            "CH-0001",
        )

    def test_the_cli_carries_the_chapter_through(self):
        parsed = self.bf.build_parser().parse_args(["reset", "--book", self.book, "--chapter", "CH-0001", "--yes"])
        self.assertEqual(parsed.chapter, "CH-0001")
        self.assertEqual(parsed.scope, "prose")


class AttemptIdTests(ResetFixture):
    """Landfall had 207 attempt directories against 69 planned attempts, and the
    first claim after a reset was handed an id whose directory already held a
    receipt. The immutability guard that protects the audit trail fired on honest
    work, and the translation died with the call already paid for."""

    def attempt_dir(self, run_id, attempt_id):
        path = self.project / ".book-forge" / "runs" / run_id / "attempts" / attempt_id
        path.mkdir(parents=True, exist_ok=True)
        (path / "execution-receipt.json").write_text("{}", encoding="utf-8")
        return path

    def test_an_id_whose_directory_exists_is_never_handed_out(self):
        for number in range(1, 12):
            self.attempt_dir("RUN-0001", f"ATT-{number:04d}")
        plan = self.bf._load_plan(self.project)
        plan["attempts"] = []
        self.bf._save_plan(self.project, plan)
        self.assertEqual(self.bf._next_attempt_id(self.project, plan), "ATT-0012")

    def test_the_plan_and_the_directories_are_counted_together(self):
        self.attempt_dir("RUN-0001", "ATT-0007")
        plan = self.bf._load_plan(self.project)
        plan["attempts"] = [{"id": "ATT-0001", "task": "x"}, {"id": "ATT-0002", "task": "x"}]
        self.assertEqual(self.bf._next_attempt_id(self.project, plan), "ATT-0003")
        for number in (3, 4, 5, 6):
            self.attempt_dir("RUN-0002", f"ATT-{number:04d}")
        self.assertEqual(self.bf._next_attempt_id(self.project, plan), "ATT-0008")

    def test_an_empty_project_starts_at_one(self):
        plan = self.bf._load_plan(self.project)
        plan["attempts"] = []
        for path in (self.project / ".book-forge" / "runs").glob("*"):
            shutil.rmtree(path)
        self.assertEqual(self.bf._next_attempt_id(self.project, plan), "ATT-0001")

    def test_the_receipt_of_the_earlier_attempt_survives_the_reset(self):
        self.bf._write_json(
            self.project / "books" / self.book / "translations" / "it" / "locale.yaml",
            {"schema": 1, "id": "LOC-IT", "book": self.book, "locale": "it"},
        )
        kept = self.attempt_dir("RUN-0001", "ATT-0003")
        self.bf.reset_book(self.project, self.book, scope="translation", confirm=True, locale="it")
        self.assertTrue((kept / "execution-receipt.json").is_file())
        plan = self.bf._load_plan(self.project)
        self.assertNotEqual(self.bf._next_attempt_id(self.project, plan), "ATT-0003")


if __name__ == "__main__":
    unittest.main()
