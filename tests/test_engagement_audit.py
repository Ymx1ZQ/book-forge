import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_engagement_audit", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(index, beats, *, turn_kind="decision", want="Mara wants the log.", obstacle="The warden blocks her.", fields=True, **extra):
    value = {
        "id": f"CH-{index:04d}",
        "order": index,
        "title": f"The Ninth Tide {index}",
        "pov": "CHR-0001",
        "beats": beats,
        "plants": [],
        "reveals": [],
        "target_words": 900,
        "imports": [],
        "obligations": [],
        "pivotal": None,
    }
    if fields:
        value["want"] = want
        value["obstacle"] = obstacle
        value["turn"] = {"kind": turn_kind, "text": "She chooses the sea."}
    value.update(extra)
    return value


def faulty_book():
    return [
        row(1, ["She breaks the lock herself."], turn_kind="decision"),
        row(2, ["The warden refuses the ledger."], turn_kind="loss"),
        row(3, ["A gull drops a key."], turn_kind="danger"),
        row(4, ["The bell rings once."], turn_kind="decision"),
        row(5, ["A rope snaps in the dark."], turn_kind="decision"),
        row(6, ["The door opens inward."], turn_kind="decision"),
        row(7, ["The council meets again at dusk."], turn_kind="loss"),
        row(8, ["The council meets again without her."], turn_kind="danger"),
        row(9, ["The council meets again in secret."], turn_kind="question"),
        row(10, ["Mara wants the ledger and the clerk wants a bribe."], turn_kind="reveal"),
        row(11, ["Refs: ledger, chapter five"], turn_kind="loss"),
        row(12, ["The harbour freezes at noon."], fields=False),
    ]


def clean_book():
    return [
        row(
            1,
            ["Mara forces the harbour door."],
            turn_kind="decision",
            want="Mara wants the log before dawn.",
            new_terms=[
                {"term": "tide", "definition": "The sea's daily rise."},
                {"term": "warden", "definition": "The keeper of the harbour door."},
                {"term": "log", "definition": "The harbour's record of arrivals."},
            ],
        ),
        row(2, ["The warden counts the hours."], turn_kind="loss", obstacle="The tide turns in two hours."),
        row(3, ["A gull steals the key."], turn_kind="danger", obstacle="The vote closes at dusk."),
        row(4, ["The keeper lights the lamp."], turn_kind="question"),
    ]


class EngagementAuditTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]

    def write_book(self, rows):
        directory = self.project / "books" / self.book / "chapters"
        directory.mkdir(parents=True, exist_ok=True)
        for value in rows:
            (directory / f"{value['id']}.json").write_text(json.dumps(value), encoding="utf-8")

    def listing(self):
        base = self.project / ".book-forge"
        return sorted(str(path.relative_to(base)) for path in base.rglob("*"))

    def test_each_fault_is_reported_with_the_expected_codes(self):
        self.write_book(faulty_book())

        result = self.bf.audit_engagement(self.project, self.book)

        self.assertEqual(result["book"], self.book)
        self.assertEqual(result["kind"], "engagement")
        self.assertEqual([finding["code"] for finding in result["findings"]], [
            "engagement.no-clock",
            "engagement.turn-run",
            "engagement.repeated-opening",
            "engagement.wants-in-beats",
            "engagement.beat-shape",
            "engagement.missing-field",
            "engagement.missing-field",
            "engagement.missing-field",
        ])
        self.assertEqual(
            [finding["chapter"] for finding in result["findings"] if finding["code"] == "engagement.missing-field"],
            ["CH-0012", "CH-0012", "CH-0012"],
        )
        self.assertEqual(result["findings"][1]["message"], "CH-0004, CH-0005 and CH-0006 all turn on decision")
        self.assertEqual(result["summary"], {"blocking": 5, "warning": 3, "ok": 11, "exempt": 0, "invalid": 1})
        self.assertEqual(
            [(chapter["id"], chapter["status"], chapter["turn_kind"]) for chapter in result["chapters"][:3]],
            [("CH-0001", "ok", "decision"), ("CH-0002", "ok", "loss"), ("CH-0003", "ok", "danger")],
        )

    def test_a_clean_book_has_no_finding(self):
        self.write_book(clean_book())

        result = self.bf.audit_engagement(self.project, self.book)

        self.assertEqual(result["findings"], [])
        self.assertEqual(result["summary"], {"blocking": 0, "warning": 0, "ok": 4, "exempt": 0, "invalid": 0})

    def test_a_long_beat_is_reported_once_per_chapter_with_its_count(self):
        self.write_book([row(1, ["The storm " * 60, "A gull falls."])])

        result = self.bf.audit_engagement(self.project, self.book)

        codes = [finding["code"] for finding in result["findings"]]
        self.assertIn("engagement.long-beat", codes)
        finding = next(finding for finding in result["findings"] if finding["code"] == "engagement.long-beat")
        self.assertEqual(finding["severity"], "warning")
        self.assertEqual(finding["chapter"], "CH-0001")
        self.assertIn("1", finding["message"])

    def test_too_many_or_malformed_terms_are_reported(self):
        for terms in ("the tide", [{"term": "tide"}], [{"term": "tide", "definition": "The sea rises."}] * 4):
            with self.subTest(terms=terms):
                self.write_book([row(1, ["The tide turns at noon."], new_terms=terms)])

                result = self.bf.audit_engagement(self.project, self.book)

                codes = [finding["code"] for finding in result["findings"]]
                self.assertIn("engagement.too-many-terms", codes)
                finding = next(finding for finding in result["findings"] if finding["code"] == "engagement.too-many-terms")
                self.assertEqual(finding["severity"], "warning")
                self.assertEqual(finding["chapter"], "CH-0001")

    def test_the_continuity_audit_still_parses_without_a_kind(self):
        parser = self.bf.build_parser()

        args = parser.parse_args(["audit", "--book", "BOOK-0001"])

        self.assertEqual(args.kind, "continuity")
        self.assertEqual(args.book, "BOOK-0001")

    def test_the_engagement_audit_without_a_book_is_refused(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = self.bf.main(["--project", str(self.project), "audit", "--kind", "engagement"])

        self.assertEqual(code, 2)
        self.assertIn("requires --book", stderr.getvalue())

    def test_the_engagement_audit_writes_nothing_under_book_forge(self):
        self.write_book(clean_book())
        before = self.listing()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.bf.main(["--project", str(self.project), "audit", "--book", self.book, "--kind", "engagement"])

        self.assertEqual(code, 0)
        self.assertEqual(self.listing(), before)
        self.assertEqual(json.loads(stdout.getvalue())["kind"], "engagement")


if __name__ == "__main__":
    unittest.main()
