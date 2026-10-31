import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

from engagement_support import with_engagement_fields


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_sync_outline", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contract(chapter_id, order, *, title=None, **extra):
    row = {
        "schema": 1,
        "id": chapter_id,
        "order": order,
        "title": title or f"The Ninth Tide {order}",
        "pov": "CHR-0001",
        "beats": [f"Event {order}."],
        "plants": [],
        "reveals": [],
        "target_words": 900,
        "imports": [],
        "obligations": [],
        "pivotal": None,
    }
    row.update(extra)
    return row


class SyncOutlineTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]
        self.book_root = self.project / "books" / self.book

    def write_contract(self, row):
        directory = self.book_root / "chapters"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{row['id']}.json"
        path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")

    def write_outline(self, rows, *, ensure_ascii, sort_keys, newline):
        self.book_root.mkdir(parents=True, exist_ok=True)
        text = json.dumps(
            {"schema": 1, "chapters": rows},
            indent=2,
            ensure_ascii=ensure_ascii,
            sort_keys=sort_keys,
        ) + newline
        (self.book_root / "outline.yaml").write_text(text, encoding="utf-8")
        return text

    def stale_book(self):
        first = contract(
            "CH-0001",
            1,
            title="The Ninth Tide — One",
            beats=["She breaks the lock."],
            want="Mara wants the harbour log before dawn.",
            obstacle="The warden blocks the door.",
            turn={"kind": "reveal", "text": "The log names her father."},
            plants=["PLT-0001"],
            obligations=["OBL-0001"],
        )
        exempt = with_engagement_fields(
            contract("CH-0002", 2, title="The Sea Before Names"),
            chapter_kind="prologue",
            exempt_reason="It frames the story before anyone is named.",
            omit=("want", "obstacle", "turn"),
        )
        self.write_contract(first)
        self.write_contract(exempt)
        rows = [
            {
                "id": "CH-0001",
                "order": 1,
                "title": "The Ninth Tide — One",
                "pov": "CHR-0001",
                "beats": ["An old beat."],
                "want": "An old want.",
                "obstacle": "An old obstacle.",
                "turn": {"kind": "decision", "text": "An old turn."},
                "plants": [],
                "obligations": [],
                "chapter_kind": "interlude",
                "exempt_reason": "A stale reason.",
            },
            {
                "id": "CH-0002",
                "order": 2,
                "title": "The Sea Before Names",
                "pov": "CHR-0001",
                "beats": ["Another old beat."],
                "want": "A stale want.",
                "obstacle": "A stale obstacle.",
                "turn": {"kind": "loss", "text": "A stale turn."},
            },
        ]
        return first, exempt, rows

    def listing(self):
        base = self.project / ".book-forge"
        return sorted(str(path.relative_to(base)) for path in base.rglob("*"))

    def test_it_copies_the_fields_and_reports_how_many_changed(self):
        self.stale_book()
        self.write_outline(
            [
                {
                    "id": "CH-0001",
                    "order": 1,
                    "title": "The Ninth Tide — One",
                    "pov": "CHR-0001",
                    "beats": ["An old beat."],
                    "want": "An old want.",
                    "obstacle": "An old obstacle.",
                    "turn": {"kind": "decision", "text": "An old turn."},
                    "plants": [],
                    "obligations": [],
                    "chapter_kind": "interlude",
                    "exempt_reason": "A stale reason.",
                },
                {
                    "id": "CH-0002",
                    "order": 2,
                    "title": "The Sea Before Names",
                    "pov": "CHR-0001",
                    "beats": ["Another old beat."],
                    "want": "A stale want.",
                    "obstacle": "A stale obstacle.",
                    "turn": {"kind": "loss", "text": "A stale turn."},
                },
            ],
            ensure_ascii=True,
            sort_keys=False,
            newline="",
        )

        result = self.bf.design_sync_outline(self.project, self.book)

        self.assertEqual(result, {"book": self.book, "changed": 16})
        rows = json.loads((self.book_root / "outline.yaml").read_text(encoding="utf-8"))["chapters"]
        self.assertEqual(rows[0]["beats"], ["She breaks the lock."])
        self.assertEqual(rows[0]["want"], "Mara wants the harbour log before dawn.")
        self.assertEqual(rows[0]["obstacle"], "The warden blocks the door.")
        self.assertEqual(rows[0]["turn"], {"kind": "reveal", "text": "The log names her father."})
        self.assertEqual(rows[0]["plants"], ["PLT-0001"])
        self.assertEqual(rows[0]["obligations"], ["OBL-0001"])
        self.assertNotIn("chapter_kind", rows[0])
        self.assertNotIn("exempt_reason", rows[0])
        self.assertEqual(rows[1]["chapter_kind"], "prologue")
        self.assertEqual(rows[1]["exempt_reason"], "It frames the story before anyone is named.")
        for field_name in ("want", "obstacle", "turn"):
            self.assertNotIn(field_name, rows[1])

    def test_it_keeps_the_files_json_formatting(self):
        self.stale_book()
        original = self.write_outline(
            [
                {
                    "id": "CH-0001",
                    "order": 1,
                    "title": "The Ninth Tide — One",
                    "pov": "CHR-0001",
                    "beats": ["An old beat."],
                    "want": "An old want.",
                    "obstacle": "An old obstacle.",
                    "turn": {"kind": "decision", "text": "An old turn."},
                },
                {
                    "id": "CH-0002",
                    "order": 2,
                    "title": "The Sea Before Names",
                    "pov": "CHR-0001",
                    "beats": ["Another old beat."],
                },
            ],
            ensure_ascii=True,
            sort_keys=False,
            newline="",
        )
        self.assertIn("\\u2014", original)

        self.bf.design_sync_outline(self.project, self.book)

        written = (self.book_root / "outline.yaml").read_text(encoding="utf-8")
        self.assertFalse(written.endswith("\n"))
        self.assertIn("\\u2014", written)
        parsed = json.loads(written)
        self.assertEqual(written, json.dumps(parsed, indent=2, ensure_ascii=True, sort_keys=False))

    def test_a_second_run_reports_nothing_and_does_not_write(self):
        self.stale_book()
        self.write_outline(
            [
                {
                    "id": "CH-0001",
                    "order": 1,
                    "title": "The Ninth Tide — One",
                    "pov": "CHR-0001",
                    "beats": ["An old beat."],
                },
                {
                    "id": "CH-0002",
                    "order": 2,
                    "title": "The Sea Before Names",
                    "pov": "CHR-0001",
                    "beats": ["Another old beat."],
                },
            ],
            ensure_ascii=True,
            sort_keys=False,
            newline="",
        )
        self.bf.design_sync_outline(self.project, self.book)
        path = self.book_root / "outline.yaml"
        before = path.read_bytes()
        before_mtime = path.stat().st_mtime_ns

        result = self.bf.design_sync_outline(self.project, self.book)

        self.assertEqual(result, {"book": self.book, "changed": 0})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, before_mtime)

    def test_the_command_creates_no_task_or_receipt(self):
        self.stale_book()
        self.write_outline(
            [{"id": "CH-0001", "order": 1, "title": "The Ninth Tide — One", "pov": "CHR-0001", "beats": ["Old."]}],
            ensure_ascii=True,
            sort_keys=False,
            newline="",
        )
        before = self.listing()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.bf.main([
                "--project", str(self.project),
                "design", "sync-outline", "--book", self.book,
            ])

        self.assertEqual(code, 0)
        self.assertEqual(self.listing(), before)
        self.assertGreater(json.loads(stdout.getvalue())["changed"], 0)

    def test_an_unknown_book_is_refused(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = self.bf.main([
                "--project", str(self.project),
                "design", "sync-outline", "--book", "BOOK-9999",
            ])

        self.assertEqual(code, 2)
        self.assertIn("Unknown book", stderr.getvalue())


class RunGateTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]

    def write_contract(self, row):
        directory = self.project / "books" / self.book / "chapters"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{row['id']}.json").write_text(json.dumps(row), encoding="utf-8")

    def test_run_refuses_an_invalid_contract_and_names_the_chapter(self):
        invalid = with_engagement_fields(contract("CH-0001", 1), omit=("want", "obstacle", "turn"))
        self.write_contract(invalid)

        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.run_next(self.project, book_id=self.book)

        message = str(caught.exception)
        self.assertIn("CH-0001", message)
        self.assertIn("want", message)
        self.assertIn("obstacle", message)
        self.assertIn("turn", message)
        self.assertIn("Repair the contracts", message)

    def test_advance_refuses_an_invalid_contract(self):
        invalid = with_engagement_fields(contract("CH-0001", 1), omit=("want", "obstacle", "turn"))
        self.write_contract(invalid)

        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.advance_book(self.project, self.book, until="design")

        self.assertIn("CH-0001", str(caught.exception))

    def test_an_exempt_chapter_passes_the_gate(self):
        exempt = with_engagement_fields(
            contract("CH-0001", 1),
            chapter_kind="prologue",
            exempt_reason="It frames the story.",
            omit=("want", "obstacle", "turn"),
        )
        self.write_contract(exempt)
        self.bf.draft_chapter = lambda *args, **kwargs: {"state": "drafted"}

        self.assertEqual(self.bf.run_next(self.project, book_id=self.book), {"state": "drafted"})

    def test_a_fully_valid_book_starts(self):
        valid = with_engagement_fields(contract("CH-0001", 1))
        self.write_contract(valid)
        self.bf.draft_chapter = lambda *args, **kwargs: {"state": "drafted"}

        self.assertEqual(self.bf.run_next(self.project, book_id=self.book), {"state": "drafted"})


if __name__ == "__main__":
    unittest.main()
