import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_engagement_fields", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def chapter(**overrides):
    row = {
        "id": "CH-0001",
        "order": 1,
        "title": "The Ninth Tide",
        "pov": "CHR-0001",
        "beats": ["Mara wants the log and the warden will not open it"],
        "want": "Mara wants the harbour log before the tide turns.",
        "obstacle": "The warden will not open the door.",
        "turn": {"kind": "decision", "text": "She breaks the lock herself."},
        "plants": [],
        "reveals": [],
        "target_words": 900,
        "imports": ["UNI-0001#kernel"],
        "obligations": [],
        "pivotal": None,
    }
    row.update(overrides)
    return row


def proposal(rows):
    return {
        "premise": "A diver must decide whether memory can be owned.",
        "entry_state": {"CHR-0001": "isolated"},
        "arc": ["refusal", "cost", "choice"],
        "exit_boundary": {"CHR-0001": "committed"},
        "chapters": rows,
    }


class EngagementFieldTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]

    def findings(self, value):
        return self.bf.validate_book_design(self.project, self.book, value)

    def engagement_findings(self, value):
        return [
            row for row in self.findings(value)
            if row["code"].startswith(("chapter.engagement", "chapter.exempt", "chapter.chapter-kind"))
        ]

    def test_a_row_without_the_fields_is_refused_and_names_the_chapter_and_the_field(self):
        value = proposal([chapter(want=None, obstacle=None, turn=None)])
        row = next(row for row in self.engagement_findings(value) if row["code"] == "chapter.engagement-missing")
        self.assertEqual(row["severity"], "blocking")
        self.assertEqual(row["chapter"], "CH-0001")
        self.assertIn("want", row["field"])
        self.assertIn("CH-0001 is missing want", row["message"])

    def test_a_row_with_the_fields_passes(self):
        value = proposal([chapter()])
        self.assertEqual(self.engagement_findings(value), [])
        self.assertEqual([row for row in self.findings(value) if row["severity"] == "blocking"], [])

    def test_an_exempt_row_may_omit_the_fields(self):
        value = proposal([chapter(
            chapter_kind="prologue",
            exempt_reason="The prologue is the sea before anyone is named.",
            want=None, obstacle=None, turn=None,
        )])
        self.assertEqual(self.engagement_findings(value), [])

    def test_a_chapter_kind_without_a_reason_is_refused(self):
        value = proposal([chapter(chapter_kind="interlude")])
        row = next(row for row in self.engagement_findings(value) if row["code"] == "chapter.exempt-reason")
        self.assertEqual(row["severity"], "blocking")
        self.assertEqual(row["chapter"], "CH-0001")

    def test_a_beat_longer_than_450_characters_is_refused_first(self):
        value = proposal([chapter(beats=["The storm " * 100])])
        findings = self.findings(value)
        codes = [row["code"] for row in findings if row["code"].startswith("chapter.beat")]
        self.assertEqual(codes[0], "chapter.beat-too-long")
        self.assertIn("chapter.beat-shape", codes)
        blocking = next(row for row in findings if row["code"] == "chapter.beat-too-long")
        self.assertEqual(blocking["severity"], "blocking")
        self.assertEqual(blocking["chapter"], "CH-0001")

    def test_beats_that_use_want_more_than_once_are_refused(self):
        value = proposal([chapter(beats=["Mara wants the log.", "The warden wants the key."])])
        row = next(row for row in self.findings(value) if row["code"] == "chapter.wants-in-beats")
        self.assertEqual(row["severity"], "blocking")
        self.assertEqual(row["chapter"], "CH-0001")
        self.assertIn("2", row["message"])

    def test_a_malformed_new_terms_list_is_refused(self):
        for terms in ("The tide", [{"term": "tide"}], [{"term": "tide", "definition": "The sea's rise."}] * 4):
            with self.subTest(terms=terms):
                value = proposal([chapter(new_terms=terms)])
                row = next(row for row in self.findings(value) if row["code"] == "chapter.new-terms")
                self.assertEqual(row["severity"], "blocking")
                self.assertEqual(row["chapter"], "CH-0001")

    def test_three_well_formed_new_terms_are_accepted(self):
        terms = [
            {"term": "tide", "definition": "The sea's daily rise."},
            {"term": "warden", "definition": "The keeper of the harbour door."},
            {"term": "log", "definition": "The harbour's record of arrivals."},
        ]
        value = proposal([chapter(new_terms=terms)])
        self.assertFalse([row for row in self.findings(value) if row["code"] == "chapter.new-terms"])

    def test_a_contract_on_disk_without_the_fields_is_invalid(self):
        path = self.project / f"books/{self.book}/chapters/CH-0001.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        invalid = {key: value for key, value in chapter().items() if key not in {"want", "obstacle", "turn"}}
        path.write_text(json.dumps(invalid), encoding="utf-8")

        loaded = self.bf._read_json(path)

        self.assertEqual(self.bf._chapter_engagement_status(loaded), "invalid")
        self.assertEqual(self.engagement_findings(proposal([loaded])), [
            row for row in self.findings(proposal([loaded]))
            if row["code"] == "chapter.engagement-missing"
        ])
        self.assertTrue(all(row["severity"] == "blocking" for row in self.engagement_findings(proposal([loaded]))))


class BeatShapeTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def test_bookkeeping_and_overlong_beats_are_refused(self):
        samples = {
            "Refs:": "Refs: ledger, chapter five",
            "plant": "Plant #1 pays in the last chapter",
            "B2 Ch": "B2 Ch.21 closes the thread",
            "Ch.12": "See Ch. 12 for the payoff",
            "writing-notes": "writing-notes: keep the weather cold",
            "CHORUS": "CHORUS wants a turn here",
            "long": "The storm " * 100,
        }
        for name, beat in samples.items():
            with self.subTest(name=name):
                self.assertTrue(self.bf._beat_shape_problems([beat]))

    def test_a_stageable_beat_is_accepted(self):
        beat = (
            "Noah wants four hundred grams of sardines and cannot reach the market without help "
            "he refuses; he hauls the chair over the kerb alone."
        )
        self.assertEqual(self.bf._beat_shape_problems([beat]), [])


class PromptTests(unittest.TestCase):
    def setUp(self):
        self.prompts = Path(load_module().__file__).resolve().parents[1] / "assets" / "prompts"

    def test_the_designer_prompt_carries_the_seven_engagement_rules(self):
        prompt = (self.prompts / "designer.md").read_text(encoding="utf-8")
        for phrase in (
            "the first three chapters of a book give the POV character a want and a visible clock",
            "one event a reader could film and one thing the POV character can lose, and ends on a turn, never on a recap",
            "no run of three chapters in one thread without a turning point, a new danger or a new question",
            "a scene shape is not used a third time in a book without a changed consequence",
            "a named antagonist or opposing group acts on the page by the end of the first third",
            "after the climax, at most one chapter of consequence",
            "a hint of a reveal is stated outright at most once before its reveal chapter",
        ):
            self.assertIn(phrase.lower(), prompt.lower())

    def test_the_designer_prompt_describes_the_three_fields_and_the_exemption(self):
        prompt = (self.prompts / "designer.md").read_text(encoding="utf-8")
        for phrase in ("`want`", "`obstacle`", "`turn`", "`chapter_kind`", "`exempt_reason`", "`new_terms`"):
            self.assertIn(phrase, prompt)

    def test_the_designer_prompt_defines_a_beat_as_an_event(self):
        prompt = (self.prompts / "designer.md").read_text(encoding="utf-8")
        self.assertIn("a beat is one thing that happens on the page", prompt.lower())
        self.assertIn("with a person as its subject", prompt.lower())
        self.assertIn("never in the beats", prompt.lower())
        self.assertNotIn("who wants what", prompt.lower())

    def test_the_writer_prompt_defines_the_declared_terms(self):
        prompt = (self.prompts / "writer.md").read_text(encoding="utf-8")
        self.assertIn("new_terms", prompt)

    def test_the_writer_prompt_puts_the_three_on_the_page(self):
        prompt = (self.prompts / "writer.md").read_text(encoding="utf-8")
        self.assertIn("the POV character's want, the obstacle and the turn are on the page, the turn being the last thing that happens", prompt)


class WriterSeesTheFieldsTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]

    def test_the_writer_is_given_the_three_fields_from_the_contract(self):
        contract = chapter()
        envelope = self.bf.build_envelope(
            self.project,
            role="writer",
            task_capsule=contract,
            imports=contract["imports"],
            state={},
            tools=[],
            max_output_tokens=2000,
        )
        task = envelope["payload"]["task"]
        self.assertEqual(task["want"], contract["want"])
        self.assertEqual(task["obstacle"], contract["obstacle"])
        self.assertEqual(task["turn"], contract["turn"])


class ColdReaderDoesNotSeeTheFieldsTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]

    def test_the_stranger_gets_the_prose_and_not_the_engagement_fields(self):
        contract = chapter(
            want="WANT-MARKER the log",
            obstacle="OBSTACLE-MARKER the warden",
            turn={"kind": "reveal", "text": "TURN-MARKER the lock breaks"},
        )
        capsule = self.bf._cold_reader_capsule(
            self.project, self.book, "CH-0001", contract, "# The Ninth Tide\n\nMara waits.",
        )
        for key in ("want", "obstacle", "turn"):
            self.assertNotIn(key, capsule)
        serialized = json.dumps(capsule)
        for marker in ("WANT-MARKER", "OBSTACLE-MARKER", "TURN-MARKER"):
            self.assertNotIn(marker, serialized)


if __name__ == "__main__":
    unittest.main()
