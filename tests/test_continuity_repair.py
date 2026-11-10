import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_continuity_repair", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FLAG = {"id": "CF-B-0001", "chapter": "CH-0002", "earlier_chapter": "CH-0001", "reason": "two weeks against a month",
        "quotes": [{"chapter": "CH-0001", "quote": "two weeks"}, {"chapter": "CH-0002", "quote": "a month"}]}
TEXTS = {"CH-0001": "You've been here two weeks. Two weeks is nothing.", "CH-0002": "I have watched you for a month."}


class ValidatedEditsTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def edits(self, rows):
        return self.bf._validated_edits(FLAG, TEXTS, {"edits": rows})

    def test_an_exact_single_occurrence_edit_applies(self):
        rows = [{"chapter": "CH-0002", "old": "for a month", "new": "for weeks", "why": "x"}]
        self.assertEqual(self.edits(rows)[0]["new"], "for weeks")

    def test_text_that_is_not_in_the_chapter_is_refused(self):
        self.assertIsNone(self.edits([{"chapter": "CH-0002", "old": "for a year", "new": "for weeks"}]))

    def test_text_that_occurs_twice_is_refused(self):
        self.assertIsNone(self.edits([{"chapter": "CH-0001", "old": "wo weeks", "new": "wo days"}]))

    def test_a_chapter_the_flag_does_not_name_is_refused(self):
        self.assertIsNone(self.edits([{"chapter": "CH-0009", "old": "x", "new": "y"}]))

    def test_a_rewrite_far_longer_than_the_text_it_replaces_is_refused(self):
        self.assertIsNone(self.edits([{"chapter": "CH-0002", "old": "a month", "new": "z" * 400}]))

    def test_an_empty_or_unchanged_edit_is_refused(self):
        self.assertIsNone(self.edits([]))
        self.assertIsNone(self.edits([{"chapter": "CH-0002", "old": "a month", "new": "a month"}]))

    def test_one_bad_edit_discards_the_whole_answer(self):
        rows = [{"chapter": "CH-0002", "old": "for a month", "new": "for weeks"}, {"chapter": "CH-0002", "old": "absent", "new": "y"}]
        self.assertIsNone(self.edits(rows))


class RepairLoopTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        manuscript = self.root / "books" / "B" / "manuscript" / "chapters"
        manuscript.mkdir(parents=True)
        for name, text in TEXTS.items():
            (manuscript / f"{name}.md").write_text(text, encoding="utf-8")
        self.flags = [dict(FLAG, book="B", state="open")]
        self.bf._open_flags = lambda root, book=None: list(self.flags)
        self.reads = 0

        def read(root, book, runner):
            self.reads += 1
            text = (manuscript / "CH-0002.md").read_text()
            self.flags = [] if "weeks" in text else self.flags
            return {}

        self.bf._ledger_pass = read
        self.adopted = []
        self.bf.adopt_artifact = lambda root, artifact, reason="": self.adopted.append(artifact) or {"stale": ["TRANSLATION-B-CH-0002-it"]}
        self.asked = []

    def ledger_call(self, answer):
        def call(root, task_id, role, capsule, runner):
            self.asked.append((role, capsule))
            return answer
        return call

    def test_an_edit_is_applied_journalled_adopted_and_the_book_read_again(self):
        self.bf._ledger_call = self.ledger_call({"edits": [{"chapter": "CH-0002", "old": "for a month", "new": "for weeks", "why": "two weeks in CH-0001"}]})
        outcome = self.bf._repair_continuity(self.root, "B", None)
        self.assertEqual((self.root / "books/B/manuscript/chapters/CH-0002.md").read_text(), "I have watched you for weeks.")
        self.assertEqual(outcome, {"repaired": ["CF-B-0001"], "open_flags": 0, "stale": ["TRANSLATION-B-CH-0002-it"]})
        self.assertEqual(self.adopted, ["SOURCE-B-CH-0002"])
        row = json.loads((self.root / ".book-forge/continuity-repairs.jsonl").read_text().splitlines()[0])
        self.assertEqual((row["flag"], row["old"], row["new"]), ("CF-B-0001", "for a month", "for weeks"))
        self.assertEqual(self.reads, 1)
        self.assertEqual(self.asked[0][0], "continuity-reviser")
        self.assertEqual(sorted(self.asked[0][1]["chapters"]), ["CH-0001", "CH-0002"])

    def test_an_unsafe_answer_leaves_the_flag_open_and_stops_after_one_round(self):
        self.bf._ledger_call = self.ledger_call({"edits": [{"chapter": "CH-0002", "old": "absent", "new": "weeks"}]})
        outcome = self.bf._repair_continuity(self.root, "B", None)
        self.assertEqual(outcome["open_flags"], 1)
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.reads, 0)
        self.assertFalse((self.root / ".book-forge/continuity-repairs.jsonl").exists())

    def test_rounds_are_bounded_when_the_flag_survives_the_edit(self):
        self.bf._ledger_pass = lambda root, book, runner: {}
        answers = iter([
            {"edits": [{"chapter": "CH-0002", "old": "for a month", "new": "for a while"}]},
            {"edits": [{"chapter": "CH-0002", "old": "for a while", "new": "for ages"}]},
            {"edits": [{"chapter": "CH-0002", "old": "for ages", "new": "for years"}]},
        ])
        self.bf._ledger_call = lambda root, task_id, role, capsule, runner: next(answers)
        self.bf._repair_continuity(self.root, "B", None)
        self.assertEqual((self.root / "books/B/manuscript/chapters/CH-0002.md").read_text(), "I have watched you for ages.")

    def test_a_failed_call_is_reported_and_the_work_goes_on(self):
        def boom(*args, **kwargs):
            raise self.bf.BookForgeError("empty")
        self.bf._ledger_call = boom
        self.assertEqual(self.bf._repair_continuity(self.root, "B", None)["repaired"], [])


class AutoRepairTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.root = self.bf._project_root(self.project)
        self.bf._ledger_pass = lambda root, book, runner: {"new_flags": ["CF-1"], "open_flags": 1}
        self.repairs = []
        self.bf._repair_continuity = lambda root, book, runner: self.repairs.append(book) or {"repaired": ["CF-1"], "open_flags": 0, "stale": []}

    def test_open_flags_after_a_pass_are_repaired_by_the_skill(self):
        report = self.bf._auto_ledger(self.root, "B", None, "closing CH-0001")
        self.assertEqual(self.repairs, ["B"])
        self.assertEqual(report["open_flags"], 0)

    def test_repair_can_be_switched_off(self):
        path = self.root / "book-forge.yaml"
        config = json.loads(path.read_text())
        config["continuity"] = {"repair": False}
        path.write_text(json.dumps(config))
        report = self.bf._auto_ledger(self.root, "B", None, "x")
        self.assertEqual(self.repairs, [])
        self.assertEqual(report["open_flags"], 1)

    def test_a_clean_pass_asks_for_no_repair(self):
        self.bf._ledger_pass = lambda root, book, runner: {"new_flags": [], "open_flags": 0}
        self.bf._auto_ledger(self.root, "B", None, "x")
        self.assertEqual(self.repairs, [])


if __name__ == "__main__":
    unittest.main()
