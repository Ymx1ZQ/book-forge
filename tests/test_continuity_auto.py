import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_continuity_auto", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AutoLedgerTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.root = self.bf._project_root(self.project)
        self.passes = []
        self.bf._ledger_pass = lambda root, book, runner: self.passes.append(book) or {"new_flags": ["CF-1"], "open_flags": 1}

    def test_the_real_runner_runs_the_ledger_and_reports_new_flags(self):
        report = self.bf._auto_ledger(self.root, "B", None, "closing CH-0001")
        self.assertEqual(self.passes, ["B"])
        self.assertEqual(report["new_flags"], ["CF-1"])

    def test_a_substituted_runner_is_left_alone(self):
        self.assertIsNone(self.bf._auto_ledger(self.root, "B", lambda *a: {}, "closing CH-0001"))
        self.assertEqual(self.passes, [])

    def test_it_can_be_switched_off_in_the_project_config(self):
        path = self.root / "book-forge.yaml"
        config = json.loads(path.read_text())
        config["continuity"] = {"auto": False}
        path.write_text(json.dumps(config))
        self.assertIsNone(self.bf._auto_ledger(self.root, "B", None, "x"))
        self.assertEqual(self.passes, [])

    def test_a_failing_ledger_never_stops_the_work(self):
        def boom(root, book, runner):
            raise self.bf.BookForgeError("B has no closed chapter to read")
        self.bf._ledger_pass = boom
        self.assertIsNone(self.bf._auto_ledger(self.root, "B", None, "x"))

    def test_translate_reads_the_ledger_before_it_picks_a_chapter(self):
        calls = []
        book = self.bf.add_book(self.project, "A")["id"]
        locale_root = self.root / "books" / book / "translations" / "it"
        locale_root.mkdir(parents=True)
        (locale_root / "locale.yaml").write_text("{}")
        self.bf._require_locale_style = lambda *a, **k: None
        self.bf._ensure_locale_artifacts = lambda *a, **k: None
        self.bf._auto_ledger = lambda root, book_id, provider, why: calls.append(why)
        try:
            self.bf.translate_next(self.project, book, "it", run_all=True)
        except Exception:
            pass
        self.assertEqual(len(calls), 1)

    def test_closing_a_chapter_reads_the_ledger(self):
        source = MODULE_PATH.read_text()
        close = source[source.index("def review_and_close_chapter("):source.index("def produce_pivotal_chapter(")]
        self.assertIn('_auto_ledger(root, book_id, provider, f"closing {chapter_id}")', close)


if __name__ == "__main__":
    unittest.main()
