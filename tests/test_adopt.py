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

    def test_adopt_refuses_an_artifact_that_is_not_a_source_chapter(self):
        (self.root / "books" / "derived.txt").write_text("hand-edited translation")
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.adopt_artifact(self.project, "TRN")

    def test_adopt_refuses_an_unknown_artifact(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.adopt_artifact(self.project, "NOPE")

    def test_adopting_an_unchanged_file_changes_nothing(self):
        before = self.registry()["SRC"]["hash"]
        result = self.bf.adopt_artifact(self.project, "SRC")
        self.assertEqual(result["old_hash"], result["new_hash"])
        self.assertEqual(self.registry()["SRC"]["hash"], before)


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

    def test_a_dead_holder_is_taken_over(self):
        lock = self.bf._advance_lock_path(self.root, self.book)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("999999999\n")
        calls = []
        self.bf.translate_next = lambda *a, **k: calls.append((a, k)) or {"ok": True}
        self.assertEqual(self.bf.run_translate_locked(self.project, self.book, "it", run_all=True), {"ok": True})
        self.assertEqual(len(calls), 1)
        self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
