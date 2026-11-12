import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_reshape", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def chapter(index, title):
    return {
        "id": f"CH-{index:04d}", "order": index, "title": title, "pov": "CHR-0001",
        "beats": [f"Mara does thing {index} and the warden answers"], "want": "Mara wants the log.",
        "obstacle": "The warden will not open it.", "turn": {"kind": "decision", "text": "She opens it herself."},
        "plants": [], "reveals": [], "target_words": 2000, "imports": ["UNI-0001#kernel"], "obligations": [], "pivotal": None,
    }


def proposal():
    return {
        "premise": "A warden must decide what a light is worth.",
        "entry_state": {"CHR-0001": "isolated"},
        "arc": ["refusal", "cost", "choice"],
        "exit_boundary": {"CHR-0001": "committed"},
        "chapters": [chapter(i, f"Title {i}") for i in range(1, 7)],
        "withheld": [{"id": "WH-0001", "fact": "The light feeds on the keepers' names", "seen_as": "a hum nobody mentions", "revealed_in": "CH-0005", "told_by": "CHR-0002"}],
    }


class ReshapeTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "B")["id"]
        self.bf.apply_book_design(self.project, self.book, proposal())
        self.root = self.bf._project_root(self.project)

    def contracts(self):
        folder = self.root / "books" / self.book / "chapters"
        return {p.stem: json.loads(p.read_text()) for p in sorted(folder.glob("CH-*.json"))}

    def close(self, *chapters):
        path = self.root / "books" / self.book / "state.yaml"
        state = json.loads(path.read_text())
        state["closed_chapters"] = list(chapters)
        path.write_text(json.dumps(state))

    def test_a_repair_round_reads_live_reader_state_and_leaves_it_untouched(self):
        reader = self.root / "books" / self.book / "reader-state.md"
        reader.write_text("# Reader State\n\nAfter CH-0003 the reader knows the warden lied.\n")
        built = self.bf._book_proposal_from_artifacts(self.root, self.book)
        self.assertEqual([f for f in self.bf.validate_book_design(self.root, self.book, built) if f["code"] == "book.arc-incomplete"], [])
        self.bf._write_book_design_outputs(self.root, self.book, built)
        self.assertIn("the warden lied", reader.read_text())

    def plan(self, *entries):
        return {"chapters": list(entries)}

    def test_a_drop_renumbers_and_removes_the_last_contract(self):
        result = self.bf.reshape_book_design(self.project, self.book, self.plan(
            {"from": "CH-0001"}, {"from": "CH-0002"}, {"from": "CH-0003"}, {"from": "CH-0005"}, {"from": "CH-0006"}))
        self.assertEqual(result["removed"], ["CH-0006"])
        contracts = self.contracts()
        self.assertEqual(list(contracts), [f"CH-000{i}" for i in range(1, 6)])
        self.assertEqual([contracts[f"CH-000{i}"]["title"] for i in range(1, 6)], ["Title 1", "Title 2", "Title 3", "Title 5", "Title 6"])
        self.assertEqual(contracts["CH-0004"]["order"], 4)

    def test_withheld_follows_the_renumbering_and_absorbs_a_dropped_chapter(self):
        self.bf.reshape_book_design(self.project, self.book, self.plan(
            {"from": "CH-0001"}, {"from": "CH-0002"}, {"from": "CH-0003"}, {"from": "CH-0004", "absorbs": ["CH-0005"]}, {"from": "CH-0006"}))
        row = json.loads(json.dumps(self.bf._book_proposal_from_artifacts(self.root, self.book)["withheld"]))[0]
        self.assertEqual(row["revealed_in"], "CH-0004")

    def test_a_dropped_chapter_that_a_reveal_names_must_be_absorbed(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.reshape_book_design(self.project, self.book, self.plan(
                {"from": "CH-0001"}, {"from": "CH-0002"}, {"from": "CH-0003"}, {"from": "CH-0004"}, {"from": "CH-0006"}))

    def test_an_insert_takes_its_place_and_shifts_the_rest(self):
        self.bf.reshape_book_design(self.project, self.book, self.plan(
            {"from": "CH-0001"}, {"from": "CH-0002"}, {"new": chapter(0, "Added")}, {"from": "CH-0003"},
            {"from": "CH-0004"}, {"from": "CH-0005"}, {"from": "CH-0006"}))
        contracts = self.contracts()
        self.assertEqual(len(contracts), 7)
        self.assertEqual(contracts["CH-0003"]["title"], "Added")
        self.assertEqual(contracts["CH-0004"]["title"], "Title 3")
        self.assertEqual(self.bf._book_proposal_from_artifacts(self.root, self.book)["withheld"][0]["revealed_in"], "CH-0006")

    def test_a_written_chapter_cannot_move_change_or_vanish(self):
        self.close("CH-0001", "CH-0002")
        keep = [{"from": f"CH-000{i}"} for i in range(1, 7)]
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.reshape_book_design(self.project, self.book, self.plan(keep[1], keep[0], *keep[2:]))
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.reshape_book_design(self.project, self.book, self.plan({**keep[0], "set": {"title": "X"}}, *keep[1:]))
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.reshape_book_design(self.project, self.book, self.plan(*keep[2:]))
        self.assertEqual(len(self.contracts()), 6)

    def test_a_contract_that_did_not_change_is_not_rewritten_and_a_moved_one_keeps_its_extra_fields(self):
        folder = self.root / "books" / self.book / "chapters"
        for number in (1, 6):
            path = folder / f"CH-000{number}.json"
            contract = json.loads(path.read_text())
            contract["tags"] = ["spicy"]
            path.write_text(json.dumps(contract, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        before = (folder / "CH-0001.json").read_bytes()
        self.bf.reshape_book_design(self.project, self.book, self.plan(
            {"from": "CH-0001"}, {"from": "CH-0002"}, {"from": "CH-0003"}, {"from": "CH-0004"}, {"from": "CH-0006", "absorbs": ["CH-0005"]}))
        self.assertEqual((folder / "CH-0001.json").read_bytes(), before)
        self.assertEqual(self.contracts()["CH-0005"]["tags"], ["spicy"])

    def test_reader_state_that_holds_the_live_state_is_left_alone(self):
        path = self.root / "books" / self.book / "reader-state.md"
        path.write_text("# Reader State\n\nMary has been read aloud to the whole square.\n")
        self.bf.reshape_book_design(self.project, self.book, self.plan(*({"from": f"CH-000{i}"} for i in range(1, 5)), {"from": "CH-0006", "absorbs": ["CH-0005"]}))
        self.assertEqual(path.read_text(), "# Reader State\n\nMary has been read aloud to the whole square.\n")

    def test_a_chapter_before_a_moved_reveal_carries_its_new_id(self):
        self.bf.reshape_book_design(self.project, self.book, self.plan(
            {"from": "CH-0001"}, {"from": "CH-0002"}, {"new": chapter(0, "Added")}, {"from": "CH-0003"},
            {"from": "CH-0004"}, {"from": "CH-0005"}, {"from": "CH-0006"}))
        for number in (1, 2):
            rows = self.contracts()[f"CH-000{number}"]["withheld"]
            self.assertEqual(rows[0]["revealed_in"], "CH-0006")

    def test_a_chapter_named_twice_is_refused(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.reshape_book_design(self.project, self.book, self.plan({"from": "CH-0001"}, {"from": "CH-0001"}))


if __name__ == "__main__":
    unittest.main()
