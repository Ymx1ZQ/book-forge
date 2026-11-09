import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_adopt", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdoptTests(unittest.TestCase):
    """A source chapter edited by hand is adopted by name, with the old and new
    hash on record, instead of failing every later reconcile."""

    def setUp(self):
        self.bf = load_module()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.root = self.bf._project_root(self.project)
        (self.root / "books").mkdir(exist_ok=True)
        self.source = self.root / "books" / "a.txt"
        self.source.write_text("alpha\n")
        derived = self.root / "books" / "derived.txt"
        derived.write_text("translated")
        self.bf.register_artifact(self.project, "SRC", "source-chapter", path=self.source)
        self.bf.register_artifact(self.project, "TRN", "translation-chapter", path=derived, dependencies=["SRC"])

    def registry(self):
        return json.loads((self.root / ".book-forge/artifact-deps.json").read_text())["artifacts"]

    def test_a_hand_edit_fails_reconcile_and_the_message_names_adopt(self):
        self.source.write_text("alpha, edited by hand\n")
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.reconcile_artifacts(self.project)
        self.assertIn("SRC", str(caught.exception))
        self.assertIn("adopt", str(caught.exception))

    def test_adopt_accepts_the_hash_records_it_and_marks_the_translation_stale(self):
        old = self.registry()["SRC"]["hash"]
        self.source.write_text("alpha, edited by hand\n")

        result = self.bf.adopt_artifact(self.project, "SRC", reason="Italian words pass")

        new = hashlib.sha256(b"alpha, edited by hand\n").hexdigest()
        self.assertEqual(result["old_hash"], old)
        self.assertEqual(result["new_hash"], new)
        self.assertEqual(self.registry()["SRC"]["hash"], new)
        self.assertEqual(self.bf.reconcile_artifacts(self.project), ["TRN"])
        journal = (self.root / ".book-forge/adopted.jsonl").read_text().strip().splitlines()
        row = json.loads(journal[-1])
        self.assertEqual((row["artifact"], row["old_hash"], row["new_hash"], row["reason"]), ("SRC", old, new, "Italian words pass"))

    def test_keep_translations_accepts_the_hash_and_leaves_the_translation_current(self):
        self.source.write_text("alpha, edited by hand\n")

        result = self.bf.adopt_artifact(self.project, "SRC", reason="wording only", keep_dependents=True)

        self.assertEqual(result["stale"], [])
        self.assertEqual(self.bf.reconcile_artifacts(self.project), [])
        row = json.loads((self.root / ".book-forge/adopted.jsonl").read_text().strip().splitlines()[-1])
        self.assertEqual(row["kept_dependents"], ["TRN"])

    def test_adopt_accepts_a_hand_edited_translation(self):
        (self.root / "books" / "derived.txt").write_text("hand-edited translation")
        result = self.bf.adopt_artifact(self.project, "TRN", reason="wording")
        self.assertNotEqual(result["old_hash"], result["new_hash"])
        self.assertEqual(self.bf.reconcile_artifacts(self.project), [])

    def test_adopt_refuses_an_artifact_of_another_kind(self):
        self.bf.register_artifact(self.project, "OTHER", "universe-block", path=self.source)
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.adopt_artifact(self.project, "OTHER")

    def test_adopt_refuses_an_unknown_artifact(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.adopt_artifact(self.project, "NOPE")

    def test_adopting_an_unchanged_file_changes_nothing(self):
        before = self.registry()["SRC"]["hash"]
        result = self.bf.adopt_artifact(self.project, "SRC")
        self.assertEqual(result["old_hash"], result["new_hash"])
        self.assertEqual(self.registry()["SRC"]["hash"], before)


class CarryTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.root = self.bf._project_root(self.project)
        (self.root / "books").mkdir(exist_ok=True)
        self.source = self.root / "books" / "a.txt"
        self.source.write_text("one\n\ntwo\n\nthree\n")
        derived = self.root / "books" / "BX-d.txt"
        derived.write_text("uno due tre")
        self.bf.register_artifact(self.project, "SRC", "source-chapter", path=self.source)
        self.bf.register_artifact(self.project, "TRANSLATION-BX-CH-0001-it", "translation-chapter", path=derived, dependencies=["SRC"])

    def test_keep_translations_records_the_changed_paragraphs_and_status_lists_them(self):
        self.source.write_text("one\n\n2\n\nthree\n")
        self.bf.adopt_artifact(self.project, "SRC", reason="r", keep_dependents=True)
        pending = self.bf.pending_carries(self.project)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["changes"], [{"old": "two", "new": "2"}])
        self.assertEqual(self.bf.status_project(self.project)["source_edits_not_confirmed"][0]["paragraphs"], 1)

    def test_confirm_carried_clears_the_pending_list(self):
        self.source.write_text("one\n\n2\n\nthree\n")
        self.bf.adopt_artifact(self.project, "SRC", reason="r", keep_dependents=True)
        done = self.bf.confirm_carried(self.project, "BX", "it", who="author")
        self.assertEqual(done, ["TRANSLATION-BX-CH-0001-it"])
        self.assertEqual(self.bf.pending_carries(self.project), [])
        self.assertNotIn("source_edits_not_confirmed", self.bf.status_project(self.project))

    def test_without_keep_translations_nothing_is_pending(self):
        self.source.write_text("one\n\n2\n\nthree\n")
        self.bf.adopt_artifact(self.project, "SRC", reason="r")
        self.assertEqual(self.bf.pending_carries(self.project), [])


class ShallowReaderTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def guard(self, preset, effort):
        self.bf._project_config = lambda root: {"style": {"preset": preset}}
        self.bf._role_ladder = lambda root, role: (effort, ["low", "medium", "high", "max"])
        self.bf._refuse_shallow_reader(Path("."))

    def test_an_explicit_preset_refuses_a_reader_below_the_default(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.guard("erotic-romance", "low")

    def test_the_default_effort_passes(self):
        self.guard("erotic-romance", "medium")

    def test_another_preset_may_read_at_low(self):
        self.guard("neutral", "low")


class TranslateLockTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]
        self.root = self.bf._project_root(self.project)

    def test_a_second_translate_run_is_refused_and_names_the_holder(self):
        lock = self.bf._advance_lock_path(self.root, self.book)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("1\n")  # pid 1 is always alive
        with self.assertRaises(self.bf.AdvanceBusy) as caught:
            self.bf.run_translate_locked(self.project, self.book, "it", run_all=True)
        self.assertIn("pid 1", str(caught.exception))

    def test_retry_dead_resumes_the_unknown_tasks_of_this_book_and_locale_only(self):
        seen = {}
        self.bf.recover_run = lambda root: None
        self.bf._load_plan = lambda root: {"tasks": [{"id": "TRANSLATE-B-CH-0001-it", "state": "outcome_unknown"}, {"id": "TRANSLATE-B-CH-0002-it", "state": "running"}]}
        self.bf.resume_run = lambda root, resolutions=None, **k: seen.update(resolutions or {})
        self.assertEqual(self.bf._retry_dead_translate_tasks(self.root, "B", "it"), ["TRANSLATE-B-CH-0001-it"])
        self.assertEqual(seen, {"TRANSLATE-B-CH-0001-it": "retry"})

    def test_retry_dead_leaves_another_locales_unknown_task_alone(self):
        self.bf.recover_run = lambda root: None
        self.bf._load_plan = lambda root: {"tasks": [{"id": "TRANSLATE-B-CH-0001-de", "state": "outcome_unknown"}]}
        self.bf.resume_run = lambda *a, **k: self.fail("must not resume")
        self.assertEqual(self.bf._retry_dead_translate_tasks(self.root, "B", "it"), [])

    def test_a_dead_holder_is_taken_over(self):
        lock = self.bf._advance_lock_path(self.root, self.book)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("999999999\n")
        calls = []
        self.bf.translate_next = lambda *a, **k: calls.append((a, k)) or {"ok": True}
        self.assertEqual(self.bf.run_translate_locked(self.project, self.book, "it", run_all=True), {"ok": True})
        self.assertEqual(len(calls), 1)
        self.assertFalse(lock.exists())


class RegisterBeforeReconcileTests(unittest.TestCase):
    def test_registration_runs_even_when_reconcile_raises(self):
        bf = load_module()
        calls = []
        bf._ensure_translation_artifacts = lambda *a, **k: calls.append("register") or []

        def boom(root):
            calls.append("reconcile")
            raise bf.BookForgeError("Derived artifact was edited directly: X")

        bf.reconcile_artifacts = boom
        with self.assertRaises(bf.BookForgeError):
            bf._register_then_reconcile(Path("."), "B", "it", ["CH-0001"])
        self.assertEqual(calls, ["register", "reconcile"])


if __name__ == "__main__":
    unittest.main()
