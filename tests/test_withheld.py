import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"

TRUTH = "The colony arrived on five ships from another star and nobody alive remembers it."


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_withheld", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def proposal(withheld=None):
    chapters = [
        {"id": "CH-0001", "order": 1, "pov": "CHR-0001", "beats": ["A choice opens the conflict"], "plants": ["the sky hums and nobody says why"], "reveals": [], "target_words": 1800, "imports": ["UNI-0001#kernel"], "pivotal": None},
        {"id": "CH-0002", "order": 2, "pov": "CHR-0001", "beats": ["The choice costs an ally"], "plants": ["a word in a language nobody speaks"], "reveals": [], "target_words": 2000, "imports": ["UNI-0001#kernel"], "pivotal": None},
        {"id": "CH-0003", "order": 3, "pov": "CHR-0001", "beats": ["Someone who knows finally says it"], "plants": [], "reveals": ["the arrival is told"], "target_words": 2200, "imports": ["UNI-0001#kernel"], "pivotal": None},
        {"id": "CH-0004", "order": 4, "pov": "CHR-0001", "beats": ["Agency resolves the dilemma"], "plants": [], "reveals": [], "target_words": 2200, "imports": ["UNI-0001#kernel"], "pivotal": None},
    ]
    value = {
        "premise": "A warden must decide what a light is worth.",
        "entry_state": {"CHR-0001": "isolated"},
        "arc": ["refusal", "cost", "choice"],
        "exit_boundary": {"CHR-0001": "committed"},
        "chapters": chapters,
    }
    if withheld is not None:
        value["withheld"] = withheld
    return value


def row(**overrides):
    base = {
        "id": "WH-0001",
        "fact": TRUTH,
        "seen_as": "a sky that hums, and machines that are fed",
        "revealed_in": "CH-0003",
        "told_by": "CHR-0002",
    }
    base.update(overrides)
    return base


class WithheldCutTests(unittest.TestCase):
    """What each chapter's writer is allowed to know."""

    def setUp(self):
        self.bf = load_module()
        self.orders = {"CH-0001": 1, "CH-0002": 2, "CH-0003": 3, "CH-0004": 4}

    def cut(self, chapter):
        return self.bf._withheld_for_chapter([row()], chapter, self.orders)[0]

    def test_a_chapter_before_the_reveal_is_given_the_experience_and_not_the_fact(self):
        for chapter in ("CH-0001", "CH-0002"):
            with self.subTest(chapter=chapter):
                cut = self.cut(chapter)
                self.assertEqual(cut["status"], "withheld")
                self.assertNotIn("fact", cut)
                self.assertEqual(cut["seen_as"], "a sky that hums, and machines that are fed")
                self.assertEqual(cut["revealed_in"], "CH-0003")

    def test_the_revealing_chapter_is_given_the_fact_and_the_teller(self):
        cut = self.cut("CH-0003")
        self.assertEqual(cut["status"], "revealed here")
        self.assertEqual(cut["fact"], TRUTH)
        self.assertEqual(cut["told_by"], "CHR-0002")

    def test_a_chapter_after_the_reveal_may_speak_of_it_plainly(self):
        cut = self.cut("CH-0004")
        self.assertEqual(cut["status"], "known")
        self.assertEqual(cut["fact"], TRUTH)

    def test_a_row_whose_reveal_chapter_is_unknown_stays_withheld(self):
        cut = self.bf._withheld_for_chapter([row(revealed_in="CH-0099")], "CH-0004", self.orders)[0]
        self.assertEqual(cut["status"], "withheld")
        self.assertNotIn("fact", cut)


class ColdReaderNeverSeesTheFactTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def test_the_fact_is_stripped_at_every_status_including_the_reveal(self):
        for status in ("withheld", "revealed here", "known"):
            with self.subTest(status=status):
                contract = {"id": "CH-0003", "withheld": [{**row(), "status": status}]}
                reader = self.bf._withheld_for_reader(contract)
                self.assertNotIn("fact", reader["withheld"][0])
                self.assertEqual(reader["withheld"][0]["status"], status)
                self.assertEqual(reader["withheld"][0]["seen_as"], row()["seen_as"])

    def test_the_original_contract_is_left_alone(self):
        contract = {"id": "CH-0003", "withheld": [{**row(), "status": "known"}]}
        self.bf._withheld_for_reader(contract)
        self.assertEqual(contract["withheld"][0]["fact"], TRUTH)

    def test_a_contract_without_a_withheld_list_is_returned_unchanged(self):
        contract = {"id": "CH-0003"}
        self.assertIs(self.bf._withheld_for_reader(contract), contract)


class WithheldOnDiskTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")

    def design(self, withheld):
        book = self.bf.add_book(self.project, "Landfall")["id"]
        self.bf.apply_book_design(self.project, book, proposal(withheld))
        return book

    def contract(self, book, chapter):
        return json.loads((self.project / f"books/{book}/chapters/{chapter}.json").read_text())

    def test_no_pre_reveal_contract_on_disk_contains_the_truth(self):
        book = self.design([row()])
        for chapter in ("CH-0001", "CH-0002"):
            raw = (self.project / f"books/{book}/chapters/{chapter}.json").read_text()
            self.assertNotIn(TRUTH, raw)
            self.assertEqual(self.contract(book, chapter)["withheld"][0]["status"], "withheld")
        self.assertIn(TRUTH, (self.project / f"books/{book}/chapters/CH-0003.json").read_text())

    def test_the_design_records_the_whole_list_and_the_arc_still_reads_back(self):
        book = self.design([row()])
        design = (self.project / f"books/{book}/design.md").read_text()
        self.assertIn("## Withheld", design)
        self.assertIn(TRUTH, design)
        restored = self.bf._book_proposal_from_artifacts(self.project, book)
        self.assertEqual(restored["withheld"], [row()])
        self.assertEqual(restored["arc"], ["refusal", "cost", "choice"])
        self.assertEqual(restored["premise"], "A warden must decide what a light is worth.")

    def test_a_book_that_withholds_nothing_is_byte_identical_to_before(self):
        book = self.bf.add_book(self.project, "Plain")["id"]
        without = self.bf._book_design_outputs(self.project, book, proposal())
        empty = self.bf._book_design_outputs(self.project, book, proposal([]))
        self.assertEqual(without, empty)
        self.assertNotIn("## Withheld", str(without[f"books/{book}/design.md"]))
        self.assertNotIn("withheld", json.loads(without[f"books/{book}/chapters/CH-0001.json"]))


class WithheldValidationTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        self.book = self.bf.add_book(self.project, "Landfall")["id"]

    def codes(self, withheld):
        findings = self.bf.validate_book_design(self.project, self.book, proposal(withheld))
        return {finding["code"] for finding in findings}

    def test_a_clean_row_passes(self):
        self.assertNotIn("withheld.reveal-unknown", self.codes([row()]))
        self.assertEqual(self.bf.apply_book_design(self.project, self.book, proposal([row()]))["state"], "design_clean")

    def test_a_reveal_chapter_that_does_not_exist_is_blocking(self):
        self.assertIn("withheld.reveal-unknown", self.codes([row(revealed_in="CH-0099")]))

    def test_a_reveal_in_the_first_chapter_is_blocking(self):
        self.assertIn("withheld.reveal-first-chapter", self.codes([row(revealed_in="CH-0001")]))

    def test_a_row_with_no_fact_or_no_lived_experience_is_blocking(self):
        self.assertIn("withheld.incomplete", self.codes([row(fact="")]))
        self.assertIn("withheld.incomplete", self.codes([row(seen_as="   ")]))

    def test_a_blocking_row_stops_the_design_from_being_written(self):
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.apply_book_design(self.project, self.book, proposal([row(revealed_in="CH-0099")]))
        self.assertIn("withheld.reveal-unknown", str(caught.exception))
        self.assertFalse((self.project / f"books/{self.book}/chapters").exists())


class NeverWriteTests(unittest.TestCase):
    """The words that would give the fact away do not reach the page."""

    def setUp(self):
        self.bf = load_module()

    def contract(self, status, never_write=("ship", "Earth")):
        return {
            "id": "CH-0002",
            "title": "The Dawn Warden",
            "beats": ["A warden counts the light"],
            "target_words": 100,
            "withheld": [{"id": "WH-0001", "seen_as": "a sky that hums", "revealed_in": "CH-0003", "status": status, "never_write": list(never_write)}],
        }

    def draft(self, sentence):
        body = " ".join(["The lamp burned low and she counted what was left of it."] * 8)
        return json.dumps({
            "prose_markdown": f"# The Dawn Warden\n\n{sentence} {body}",
            "beat_map": [{"beat": "A warden counts the light", "evidence": "she counted"}],
            "consequences": [],
        })

    def test_a_forbidden_word_before_the_reveal_fails_the_draft_and_names_the_word(self):
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.validate_writer_output(self.contract("withheld"), self.draft("The ship had brought them here."))
        self.assertIn("WH-0001", str(caught.exception))
        self.assertIn("ship", str(caught.exception))
        self.assertIn("CH-0003", str(caught.exception))

    def test_the_same_word_passes_at_the_chapter_that_reveals_it(self):
        for status in ("revealed here", "known"):
            with self.subTest(status=status):
                value = self.bf.validate_writer_output(self.contract(status), self.draft("The ship had brought them here."))
                self.assertIn("ship", value["prose_markdown"])

    def test_a_forbidden_word_inside_a_longer_word_is_not_a_leak(self):
        value = self.bf.validate_writer_output(self.contract("withheld"), self.draft("Their worship was a hardship and a relationship."))
        self.assertIn("worship", value["prose_markdown"])

    def test_the_check_is_blind_to_case(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.validate_writer_output(self.contract("withheld"), self.draft("EARTH was a word nobody used."))

    def test_a_capitalised_entry_is_a_name_and_spares_the_common_word(self):
        contract = self.contract("withheld", never_write=("Earth", "Kepler"))
        value = self.bf.validate_writer_output(contract, self.draft("She turned the wet earth over with her heel."))
        self.assertIn("earth", value["prose_markdown"])
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.validate_writer_output(contract, self.draft("Earth was a word nobody used."))
        self.assertIn("Earth", str(caught.exception))

    def test_a_lowercase_entry_is_still_caught_in_any_case(self):
        contract = self.contract("withheld", never_write=("ship",))
        for sentence in ("The ship was gone.", "The Ship was gone.", "The SHIP was gone."):
            with self.subTest(sentence=sentence):
                with self.assertRaises(self.bf.BookForgeError):
                    self.bf.validate_writer_output(contract, self.draft(sentence))

    def test_a_chapter_with_no_withheld_list_is_never_checked(self):
        contract = {"id": "CH-0002", "title": "The Dawn Warden", "beats": ["A warden counts the light"], "target_words": 100}
        value = self.bf.validate_writer_output(contract, self.draft("The ship had brought them here."))
        self.assertIn("ship", value["prose_markdown"])

    def test_the_forbidden_words_travel_only_to_the_chapters_that_must_avoid_them(self):
        orders = {"CH-0001": 1, "CH-0002": 2, "CH-0003": 3, "CH-0004": 4}
        source = [row(never_write=["ship", "Earth"])]
        self.assertEqual(self.bf._withheld_for_chapter(source, "CH-0001", orders)[0]["never_write"], ["ship", "Earth"])
        self.assertNotIn("never_write", self.bf._withheld_for_chapter(source, "CH-0003", orders)[0])
        self.assertNotIn("never_write", self.bf._withheld_for_chapter(source, "CH-0004", orders)[0])

    def test_the_cold_reader_is_not_handed_the_forbidden_words_either(self):
        contract = self.contract("withheld")
        reader = self.bf._withheld_for_reader(contract)
        self.assertNotIn("never_write", reader["withheld"][0])
        self.assertEqual(reader["withheld"][0]["seen_as"], "a sky that hums")

    def test_a_malformed_forbidden_word_list_is_blocking(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        project = Path(temp.name) / "world"
        self.bf.init_project(project, "World")
        book = self.bf.add_book(project, "Landfall")["id"]
        findings = self.bf.validate_book_design(project, book, proposal([row(never_write="ship")]))
        self.assertIn("withheld.never-write-shape", {finding["code"] for finding in findings})


if __name__ == "__main__":
    unittest.main()
