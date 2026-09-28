import collections
import importlib.util
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4.1-flash"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_review", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prose(words=700):
    return "# Chapter\n\n" + " ".join(["memory"] * words)


class RoleProvider:
    """Answers per role, and per half for the role that is asked in two calls.

    The technical editor is asked twice on one chapter — the canon half with the
    imported blocks, the contract half with none — and both calls arrive under the
    same role name. They are told apart by the capsule's `asked` field, which is
    what the engine uses to tell them apart too. A test that scripts only
    `technical-editor` is scripting the canon half and gets an empty contract half,
    so it goes on measuring what it was written to measure."""

    QUIET_CONTRACT_HALF = {"findings": [], "consequences": [], "verified": True}

    def __init__(self, responses):
        self.responses = {role: list(values) for role, values in responses.items()}
        self.calls = []
        self.lock = threading.Lock()

    def _key(self, role, envelope):
        if role != "technical-editor":
            return role
        asked = envelope["payload"]["task"].get("asked") or []
        return "technical-contract" if "contract" in asked else "technical-editor"

    def __call__(self, role, envelope, attempt_dir):
        key = self._key(role, envelope)
        with self.lock:
            scripted = self.responses.get(key)
            if key == "technical-contract" and not scripted:
                text = dict(self.QUIET_CONTRACT_HALF)
            else:
                text = scripted.pop(0)
            number = len(self.calls) + 1
            self.calls.append(role)
        variants = {"cold-reader": "low", "technical-editor": "high", "reviser": "low"}
        return {
            "text": json.dumps(text), "provider": "openrouter", "model": MODEL,
            "variant": variants[role], "session_id": f"ses-{number}",
            "tokens": {"input": envelope["estimated_input_tokens"], "output": 200},
            "cost": 0.001, "latency_ms": 10, "finish": "stop",
        }


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        self.book = self.bf.add_book(self.project, "Book")["id"]
        chapter_dir = self.project / f"books/{self.book}/chapters"
        chapter_dir.mkdir()
        contract = {
            "schema": 1, "book": self.book, "id": "CH-0001", "order": 1,
            "pov": "CHR-0001", "beats": ["Find signal"], "plants": [], "reveals": [],
            "target_words": 700, "imports": ["UNI-0001#kernel"], "pivotal": None,
        }
        (chapter_dir / "CH-0001.json").write_text(json.dumps(contract))
        draft = {
            "prose_markdown": prose(), "beat_map": [{"beat": "Find signal", "evidence": "found"}],
            "consequences": [],
        }
        class DraftProvider:
            def __call__(inner_self, role, envelope, attempt_dir):
                return {"text": json.dumps(draft), "provider": "openrouter", "model": MODEL, "variant": "low", "session_id": "ses-draft", "tokens": {"input": 1000, "output": 800}, "cost": .001, "latency_ms": 10, "finish": "stop"}
        self.bf.draft_chapter(self.project, self.book, "CH-0001", provider=DraftProvider())

    def reviser(self, consequences=None, dispositions=None):
        return {
            "prose_markdown": prose(),
            "beat_map": [{"beat": "Find signal", "evidence": "found"}],
            "consequences": consequences or [],
            "dispositions": dispositions or [],
            "reader_state": "The signal exists and Mara knows it.",
        }

    def test_closes_in_three_review_calls_and_updates_state(self):
        provider = RoleProvider({
            "cold-reader": [{"findings": []}],
            "technical-editor": [{"findings": [], "consequences": []}],
            "reviser": [self.reviser()],
        })
        result = self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(result["calls"], 3)
        self.assertEqual(set(provider.calls[:2]), {"cold-reader", "technical-editor"})
        self.assertEqual(provider.calls[-1], "reviser")
        self.assertTrue((self.project / f"books/{self.book}/manuscript/chapters/CH-0001.md").is_file())
        state = json.loads((self.project / f"books/{self.book}/state.yaml").read_text())
        self.assertEqual(state["closed_chapters"], ["CH-0001"])
        self.assertTrue(json.loads((self.project / ".book-forge/state.json").read_text())["source_locked"])
        config_path = self.project / "book-forge.yaml"
        config = json.loads(config_path.read_text())
        config["source_language"] = "fr"
        config_path.write_text(json.dumps(config))
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.status_project(self.project)

    def test_seeded_undisclosed_consequence_requires_repair_and_verification(self):
        finding = {"id": "F-STATE-1", "dimension": "state", "severity": "blocking", "objective": True, "evidence": "final paragraph", "issue": "Signal knowledge omitted", "fix_required": True}
        consequence = {"scope": "book", "fact": "Mara knows the signal.", "entities": ["CHR-0001"]}
        disposition = {"finding": "T-0001", "action": "repaired", "evidence": "final paragraph", "loss": "none", "supersedes": []}
        provider = RoleProvider({
            "cold-reader": [{"findings": []}],
            "technical-editor": [{"findings": [finding], "consequences": [consequence]}, {"verified": True, "findings": []}],
            "reviser": [self.reviser([consequence], [disposition])],
        })
        result = self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(result["calls"], 4)
        state = json.loads((self.project / f"books/{self.book}/state.yaml").read_text())
        self.assertEqual(state["consequences"][0]["fact"], "Mara knows the signal.")

        second = Path(self.temp.name) / "blocked"
        self.bf.init_project(second, "Blocked")
        book = self.bf.add_book(second, "Book")["id"]
        chapter_dir = second / f"books/{book}/chapters"
        chapter_dir.mkdir()
        contract = json.loads((self.project / f"books/{self.book}/chapters/CH-0001.json").read_text())
        contract["book"] = book
        (chapter_dir / "CH-0001.json").write_text(json.dumps(contract))
        class DraftProvider:
            def __call__(inner_self, role, envelope, attempt_dir):
                return {"text": json.dumps({"prose_markdown": prose(), "beat_map": [{"beat": "Find signal", "evidence": "found"}], "consequences": []}), "provider": "openrouter", "model": MODEL, "variant": "low", "session_id": "ses-d", "tokens": {}, "cost": 0, "latency_ms": 1, "finish": "stop"}
        self.bf.draft_chapter(second, book, "CH-0001", provider=DraftProvider())
        bad = RoleProvider({
            "cold-reader": [{"findings": []}],
            "technical-editor": [{"findings": [finding], "consequences": [consequence]}],
            "reviser": [self.reviser([], [{**disposition, "action": "dismissed"}])],
        })
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.review_and_close_chapter(second, book, "CH-0001", provider=bad)
        self.assertFalse((second / f"books/{book}/manuscript/chapters/CH-0001.md").exists())

    def test_duplicate_finding_ids_across_reviews_are_disambiguated_for_the_reviser(self):
        cold_finding = {"id": "F-0001", "dimension": "clarity", "severity": "warning", "evidence": "a span", "issue": "vague", "fix_required": True}
        tech_finding = {"id": "F-0001", "dimension": "state", "severity": "warning", "evidence": "another span", "issue": "missing consequence", "fix_required": True, "objective": False}
        provider = RoleProvider({
            "cold-reader": [{"findings": [cold_finding]}],
            "technical-editor": [{"findings": [tech_finding], "consequences": []}],
            "reviser": [self.reviser([], [
                {"finding": "F-0001", "action": "repaired", "evidence": "fixed", "loss": "none", "supersedes": []},
                {"finding": "T-0001", "action": "accepted-risk", "evidence": "kept", "loss": "none", "supersedes": []},
            ])],
        })
        result = self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(result["calls"], 3)
        dispositions = json.loads((self.project / f"books/{self.book}/reviews/CH-0001/dispositions.json").read_text())
        self.assertEqual([row["finding"] for row in dispositions["dispositions"]], ["F-0001", "F-0001"])
        self.assertEqual(
            [row["action"] for row in dispositions["dispositions"]],
            ["repaired", "accepted-risk"],
        )

    def test_resume_reuses_materialized_reviews_without_recalling_reviewers(self):
        cold_finding = {"id": "F-0001", "dimension": "clarity", "severity": "warning", "evidence": "a span", "issue": "vague", "fix_required": True}
        tech_finding = {"id": "F-0001", "dimension": "state", "severity": "warning", "evidence": "another span", "issue": "missing", "fix_required": True, "objective": False}
        provider = RoleProvider({
            "cold-reader": [{"findings": [cold_finding]}],
            "technical-editor": [{"findings": [tech_finding], "consequences": []}],
            "reviser": [self.reviser([], [
                {"finding": "F-0001", "action": "repaired", "evidence": "fixed", "loss": "none", "supersedes": []},
                {"finding": "T-0001", "action": "accepted-risk", "evidence": "kept", "loss": "none", "supersedes": []},
            ])],
        })
        self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(provider.calls.count("cold-reader"), 1)
        # Two, and it is the change this counts: the technical editor is asked its
        # canon half and its contract half, and the second carries no imports.
        self.assertEqual(provider.calls.count("technical-editor"), 2)

        contract = json.loads((self.project / f"books/{self.book}/chapters/CH-0001.json").read_text())
        draft = (self.project / f"books/{self.book}/work/CH-0001/draft.md").read_text()
        writer_consequences = json.loads((self.project / f"books/{self.book}/work/CH-0001/consequences.json").read_text())
        only_reviser = RoleProvider({
            "reviser": [self.reviser([], [
                {"finding": "F-0001", "action": "repaired", "evidence": "fixed", "loss": "none", "supersedes": []},
                {"finding": "T-0001", "action": "accepted-risk", "evidence": "kept", "loss": "none", "supersedes": []},
            ])],
        })
        cold, technical, receipts = self.bf._call_parallel_reviews(
            self.project, self.book, "CH-0001", contract, draft, writer_consequences, only_reviser
        )
        self.assertEqual(only_reviser.calls, [])
        self.assertEqual([f["id"] for f in cold["findings"]], ["F-0001"])
        self.assertEqual([f["id"] for f in technical["findings"]], ["F-0001"])

    def test_revision_with_string_consequences_fails_with_clear_message(self):
        finding = {"id": "F-0001", "dimension": "state", "severity": "warning", "evidence": "span", "issue": "missing fact", "fix_required": True, "objective": False}
        consequence = {"scope": "book", "fact": "Mara knows the signal.", "entities": ["CHR-0001"]}
        provider = RoleProvider({
            "cold-reader": [{"findings": []}],
            "technical-editor": [{"findings": [finding], "consequences": [consequence]}],
            "reviser": [{
                "prose_markdown": prose(),
                "beat_map": [{"beat": "Find signal", "evidence": "found"}],
                "consequences": ["Mara knows the signal."],
                "dispositions": [{"finding": "T-0001", "action": "repaired", "evidence": "fixed", "loss": "none", "supersedes": []}],
                "reader_state": "Mara knows the signal.",
            }],
        })
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertIn("consequences must be a list of objects", str(caught.exception))


if __name__ == "__main__":
    unittest.main()


class StyleLensTests(unittest.TestCase):
    """The style pass keeps each reviewer's model pin and drops its chorus lens."""

    def setUp(self):
        self.bf = load_module()

    def test_the_style_lens_replaces_the_advisor_lens(self):
        import tempfile
        from pathlib import Path as _Path
        with tempfile.TemporaryDirectory() as temp:
            project = _Path(temp) / "world"
            self.bf.init_project(project, "World")
            role = "advisor-google-gemini-3-8-flash"
            envelope = self.bf.build_envelope(project, role=role, task_capsule={"mode": "style"}, imports=[], state={}, tools=[], max_output_tokens=100, prompt_role="style-review")
            prompt = envelope["payload"]["role_prompt"]
        self.assertIn("You are the style reviewer", prompt)
        self.assertIn("shorter than the original", prompt)
        self.assertNotIn("science-coherence", prompt)
class DispositionScopeTests(unittest.TestCase):
    """The reviser was failed for leaving praise unremarked: of 35 findings on a
    1600-word chapter, none was blocking, 21 were warnings and 14 were notes."""

    def setUp(self):
        self.bf = load_module()
        self.contract = {"id": "CH-0001", "book": "BOOK-0001", "target_words": 20, "beats": ["Mara opens the log"], "pov": "CHR-0001"}
        self.findings = [
            {"id": "F-1", "severity": "warning", "dimension": "style", "evidence": "e", "issue": "i", "fix_required": True},
            {"id": "F-2", "severity": "note", "dimension": "style", "evidence": "e", "issue": "the plants are clean", "fix_required": False},
        ]

    def revision(self, dispositions):
        return {
            "prose_markdown": "# The Ninth Tide\n\n" + " ".join(["Mara opened the log and the warden said nothing."] * 2),
            "beat_map": [{"beat": "Mara opens the log", "evidence": "Mara opened the log"}],
            "consequences": [], "dispositions": dispositions, "reader_state": "Mara opened it.",
        }

    def disposition(self, finding_id):
        return {"finding": finding_id, "action": "repaired", "evidence": "cut the clause", "loss": "none"}

    def test_a_revision_that_answers_the_warnings_and_no_note_validates(self):
        value = self.bf._validate_revision(self.contract, self.revision([self.disposition("F-1")]), self.findings, [])
        self.assertEqual([row["finding"] for row in value["dispositions"]], ["F-1"])

    def test_a_note_may_still_be_dispositioned(self):
        value = self.bf._validate_revision(self.contract, self.revision([self.disposition("F-1"), self.disposition("F-2")]), self.findings, [])
        self.assertEqual(len(value["dispositions"]), 2)

    def test_a_missing_warning_still_fails_and_names_it(self):
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf._validate_revision(self.contract, self.revision([self.disposition("F-2")]), self.findings, [])
        self.assertIn("F-1", str(caught.exception))

    def test_a_disposition_for_a_finding_nobody_raised_fails(self):
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf._validate_revision(self.contract, self.revision([self.disposition("F-1"), self.disposition("F-9")]), self.findings, [])
        self.assertIn("F-9", str(caught.exception))

    def test_a_malformed_note_disposition_still_fails(self):
        bad = {"finding": "F-2", "action": "repaired"}
        with self.assertRaises(self.bf.BookForgeError):
            self.bf._validate_revision(self.contract, self.revision([self.disposition("F-1"), bad]), self.findings, [])



class StyleFindingIdentityTests(unittest.TestCase):
    """Every reviewer numbers its findings from 01. Without the reviewer's name,
    four of them answer to S-01 and three are lost whatever the reviser does."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]
        config_path = self.project / "book-forge.yaml"
        config = json.loads(config_path.read_text())
        config["chorus"] = {"enabled": True, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER,
                            "style_review": {"enabled": True, "default_models": [
                                "openrouter/z-ai/glm-5.3-flash", "openrouter/google/gemini-3.8-flash",
                                "openrouter/deepseek/deepseek-v4.1-flash", "openrouter/qwen/qwen3.8-flash"]}}
        config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.contract = {"id": "CH-0001", "book": self.book, "pov": "CHR-0001", "target_words": 900,
                         "beats": ["Mara opens the log"], "imports": []}

    def provider(self, role, envelope, attempt_dir):
        findings = [{"id": f"{n:02d}", "dimension": "style", "severity": "warning",
                     "evidence": f"span {n}", "issue": f"issue {n}", "fix_required": True} for n in (1, 2, 3)]
        return {"text": json.dumps({"findings": findings}), "provider": "openrouter",
                "model": "openrouter/deepseek/deepseek-v4.1-flash", "variant": "high",
                "session_id": "ses-1", "tokens": {"input": 10, "output": 10}, "cost": 0.0,
                "latency_ms": 1, "finish": "stop"}

    def test_four_reviewers_numbering_from_one_produce_no_collision(self):
        findings = self.bf._call_style_review(
            self.bf._project_root(self.project), self.book, "CH-0001", self.contract, "# T\n\nProse.", self.provider
        )
        ids = [row["id"] for row in findings]
        self.assertEqual(len(ids), 12)
        self.assertEqual(len(set(ids)), 12, "each finding must keep its own name")

    def test_the_identifier_still_marks_it_as_style_and_names_the_reviewer(self):
        findings = self.bf._call_style_review(
            self.bf._project_root(self.project), self.book, "CH-0001", self.contract, "# T\n\nProse.", self.provider
        )
        for row in findings:
            self.assertTrue(row["id"].startswith("S-"), row["id"])
            self.assertEqual(row["dimension"], "style")
            self.assertIn(row["reviewer"], row["id"])



class StylePassLengthTests(unittest.TestCase):
    """A style pass is told to propose only shorter replacements. Measuring it
    against the contract's target forbids cutting once a chapter is under target."""

    def setUp(self):
        self.bf = load_module()
        self.contract = {"id": "CH-0001", "book": "BOOK-0001", "target_words": 2000,
                         "beats": ["Mara opens the log"], "pov": "CHR-0001"}
        self.findings = [{"id": "S-glm-01", "severity": "warning", "dimension": "style",
                          "evidence": "e", "issue": "cut the appositive", "fix_required": True}]

    def prose(self, words):
        sentence = "Mara opened the log and the warden said nothing at all again. "
        text = (sentence * (words // 11 + 2))
        return "# The Ninth Tide\n\n" + " ".join(text.split()[:words])

    def revision(self, words):
        return {"prose_markdown": self.prose(words),
                "beat_map": [{"beat": "Mara opens the log", "evidence": "Mara opened the log"}],
                "consequences": [],
                "dispositions": [{"finding": "S-glm-01", "action": "repaired", "evidence": "cut", "loss": "none"}],
                "reader_state": "Mara opened it."}

    def test_a_style_pass_may_cut_a_chapter_already_under_target(self):
        baseline = self.prose(1438)
        value = self.bf._validate_revision(self.contract, self.revision(1335), self.findings, [], baseline_prose=baseline)
        floor = int(int(self.contract["target_words"]) * 0.70)
        self.assertLess(value["word_count"], floor, "the point is that the contract floor would have refused it")

    def test_a_style_pass_that_halves_the_chapter_is_still_refused(self):
        baseline = self.prose(1438)
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf._validate_revision(self.contract, self.revision(700), self.findings, [], baseline_prose=baseline)
        self.assertIn("word count", str(caught.exception))

    def test_a_style_pass_that_pads_the_chapter_is_refused(self):
        baseline = self.prose(1438)
        with self.assertRaises(self.bf.BookForgeError):
            self.bf._validate_revision(self.contract, self.revision(2200), self.findings, [], baseline_prose=baseline)

    def test_without_a_baseline_the_contract_still_governs(self):
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf._validate_revision(self.contract, self.revision(1335), self.findings, [])
        self.assertIn("1400", str(caught.exception))



class OneBadFindingCannotStopABookTests(unittest.TestCase):
    """`advance` reached CH-0004 and died on `Review finding is missing required
    evidence fields`. The cold reader had answered well — 707 output tokens, valid
    JSON, several usable findings — and one of them carried `evidence` as a sentence
    instead of the object the contract asks for, with no `fix_required`. That one
    field discarded the review, then the chapter, then a run of twenty-six."""

    def setUp(self):
        self.bf = load_module()

    def good(self, index, **extra):
        return {
            "id": f"F-{index:04d}", "dimension": "clarity", "severity": "note",
            "evidence": {"quote": "the lamp stood as a debt"}, "issue": "unclear",
            "fix_required": False, **extra,
        }

    def test_a_readable_finding_survives_an_unreadable_one_beside_it(self):
        loose = {"id": "F-0002", "dimension": "clarity", "severity": "note",
                 "evidence": "a sentence rather than the object", "issue": "unclear"}
        usable, aside = self.bf._validate_findings({"findings": [self.good(1), loose]}, technical=False)
        self.assertEqual([row["id"] for row in usable], ["F-0001"])
        self.assertEqual(len(aside), 1)
        self.assertIn("fix_required", aside[0]["why"], "the record names the field that was missing")
        self.assertEqual(aside[0]["id"], "F-0002")

    def test_a_review_where_nothing_survives_still_fails(self):
        """That is an answer nobody can act on, and the retry exists for it."""
        loose = {"id": "F-0002", "dimension": "clarity", "severity": "note", "issue": "unclear"}
        with self.assertRaises(self.bf.BookForgeError):
            self.bf._validate_findings({"findings": [loose]}, technical=False)

    def test_a_review_that_found_nothing_is_not_a_review_that_failed(self):
        self.assertEqual(self.bf._validate_findings({"findings": []}, technical=False), ([], []))

    def test_a_duplicate_id_is_set_aside_rather_than_fatal(self):
        usable, aside = self.bf._validate_findings(
            {"findings": [self.good(1), self.good(1)]}, technical=False
        )
        self.assertEqual(len(usable), 1)
        self.assertIn("duplicate", aside[0]["why"])

    def test_a_technical_finding_without_its_objective_flag_is_set_aside(self):
        usable, aside = self.bf._validate_findings(
            {"findings": [self.good(1, objective=True), self.good(2)]}, technical=True
        )
        self.assertEqual([row["id"] for row in usable], ["F-0001"])
        self.assertIn("objective", aside[0]["why"])

    def test_a_reviewer_that_spends_its_ceiling_is_told_apart_from_one_that_answered_badly(self):
        """The technical editor beside that cold reader answered `output: 0` after
        `reasoning: 31999` — the third failure class, which needs the question
        changed rather than repeated."""
        spent = {"text": "", "tokens": {"input": 13185, "output": 0, "reasoning": 31999}}
        with self.assertRaises(self.bf.ReasoningCeilingSpent):
            self.bf._refuse_empty_answer("technical-editor", "CH-0004", spent)
        # An empty answer with nothing spent on reasoning is the other failure and
        # keeps the retry that was built for it.
        self.bf._refuse_empty_answer("technical-editor", "CH-0004", {"text": "", "tokens": {"output": 0}})



class APassOfTwoRolesResumesOnTheOneThatAnsweredTests(ReviewTests):
    """On CH-0005 the cold reader answered, validated, materialized and was
    promoted; the technical editor beside it spent its ceiling and raised. The
    retry re-claimed both and died on `Only a running attempt can be marked
    accepted` for the one already promoted."""

    def run_a_full_review(self):
        cold = {"id": "F-0001", "dimension": "clarity", "severity": "warning", "evidence": "a span", "issue": "vague", "fix_required": True}
        tech = {"id": "F-0001", "dimension": "state", "severity": "warning", "evidence": "another span", "issue": "missing", "fix_required": True, "objective": False}
        provider = RoleProvider({
            "cold-reader": [{"findings": [cold]}],
            "technical-editor": [{"findings": [tech], "consequences": []}],
            "reviser": [self.reviser([], [
                {"finding": "F-0001", "action": "repaired", "evidence": "fixed", "loss": "none", "supersedes": []},
                {"finding": "T-0001", "action": "accepted-risk", "evidence": "kept", "loss": "none", "supersedes": []},
            ])],
        })
        self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)

    def call_reviews(self, provider):
        contract = json.loads((self.project / f"books/{self.book}/chapters/CH-0001.json").read_text())
        draft = (self.project / f"books/{self.book}/work/CH-0001/draft.md").read_text()
        consequences = json.loads((self.project / f"books/{self.book}/work/CH-0001/consequences.json").read_text())
        return self.bf._call_parallel_reviews(
            self.project, self.book, "CH-0001", contract, draft, consequences, provider
        )

    def test_only_the_role_that_did_not_answer_is_called_again(self):
        self.run_a_full_review()
        # Unpick the technical half, as a pass that half-succeeded leaves it. The
        # plan is hash-protected, so the task is reopened through the engine's own
        # function rather than by editing the file underneath it.
        (self.project / f"books/{self.book}/reviews/CH-0001/technical-editor.json").unlink()
        self.bf._reopen_task(self.project, f"REVIEW-TECH-{self.book}-CH-0001")

        again = RoleProvider({"technical-editor": [{"verified": True, "findings": [], "consequences": []}]})
        cold, technical, _ = self.call_reviews(again)
        self.assertEqual(again.calls, ["technical-editor"], "the answer already paid for is reused")
        self.assertEqual([f["id"] for f in cold["findings"]], ["F-0001"])
        self.assertTrue(technical["verified"])

    def test_a_pass_where_both_answered_calls_neither(self):
        self.run_a_full_review()
        nobody = RoleProvider({})
        self.call_reviews(nobody)
        self.assertEqual(nobody.calls, [])


class TheReviewersAreBoundedTests(unittest.TestCase):
    """The technical editor spent its ceiling on two chapters running. It is the
    fourth role in this engine to fail that way and the first that gates a
    chapter — the critic is advisory and can be set aside, this cannot."""

    def setUp(self):
        self.bf = load_module()

    def test_the_bound_is_a_constant_the_engine_owns(self):
        self.assertIsInstance(self.bf.REVIEW_MAX_FINDINGS, int)
        self.assertGreaterEqual(self.bf.REVIEW_MAX_FINDINGS, 1)

    def test_the_style_advisors_are_bounded_too(self):
        """CH-0008 handed the reviser 45 findings, 30 of them from the four style
        advisors, with 21 to disposition and 15 of those from the chorus. It missed
        three, three times running."""
        self.assertIsInstance(self.bf.STYLE_MAX_FINDINGS, int)
        self.assertGreaterEqual(self.bf.STYLE_MAX_FINDINGS, 1)
        four_advisors = 4 * self.bf.STYLE_MAX_FINDINGS
        self.assertLess(four_advisors, 21, "the chorus must no longer outweigh what a reviser can finish")
        self.assertGreater(four_advisors, self.bf.REVIEW_MAX_FINDINGS,
                           "a chorus that says less than one gate is not a chorus")

    def test_the_style_prompt_names_no_count_of_its_own(self):
        base = Path(self.bf.__file__).resolve().parent.parent / "assets" / "prompts"
        self.assertIn("answer_bound", (base / "style-review.md").read_text(encoding="utf-8"))

    def test_neither_prompt_names_a_count_of_its_own(self):
        base = Path(self.bf.__file__).resolve().parent.parent / "assets" / "prompts"
        for name in ("cold-reader.md", "technical-editor.md"):
            text = (base / name).read_text(encoding="utf-8")
            self.assertIn("answer_bound", text, name)



class AReviewerThatCannotBeReadSettlesItsOwnClaimTests(ReviewTests):
    """A person was needed twice in one night, both times for this. The review
    marks the provider accepted and then raises with the claim unsettled, so
    recovery finds an accepted claim with a session id and declares
    `outcome_unknown` — correct when the engine does not know what happened, and
    here it does: the answer came back, was read, and could not be used."""

    def state_of(self, task_id):
        plan = json.loads((self.project / ".book-forge" / "plan.json").read_text())
        return next(row["state"] for row in plan["tasks"] if row["id"] == task_id)

    def run_reviews(self, provider):
        """Through the route, so the tasks exist the way a real run creates them."""
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)

    def test_an_unreadable_answer_leaves_the_task_failed_and_not_unknown(self):
        class Unreadable:
            calls = []

            def __call__(self, role, envelope, attempt_dir):
                self.calls.append(role)
                return {
                    "text": "I could not settle on an answer.", "provider": "openrouter",
                    "model": MODEL, "variant": "low", "session_id": "ses-1",
                    "tokens": {"input": 10, "output": 20}, "cost": 0.0, "latency_ms": 1, "finish": "stop",
                }

        self.run_reviews(Unreadable())
        for task in (f"REVIEW-COLD-{self.book}-CH-0001", f"REVIEW-TECH-{self.book}-CH-0001"):
            self.assertIn(self.state_of(task), {"pending", "failed"},
                          f"{task} still holds its claim and would become outcome_unknown")

    def test_a_spent_ceiling_leaves_the_task_failed_so_the_retry_can_ask_again(self):
        class Spent:
            def __call__(self, role, envelope, attempt_dir):
                return {
                    "text": "", "provider": "openrouter", "model": MODEL, "variant": "low",
                    "session_id": "ses-1", "tokens": {"input": 15000, "output": 0, "reasoning": 32000},
                    "cost": 0.1, "latency_ms": 1, "finish": "stop",
                }

        self.run_reviews(Spent())
        for task in (f"REVIEW-COLD-{self.book}-CH-0001", f"REVIEW-TECH-{self.book}-CH-0001"):
            self.assertIn(self.state_of(task), {"pending", "failed"},
                          f"{task} still holds its claim and would become outcome_unknown")



class ARoleThatAnswersOnTheSecondAskIsGivenOneTests(ReviewTests):
    """Measured over 18 calls of the technical editor on one book: 15 answered, and
    two attempts came back differently on the identical envelope. For this role the
    spent ceiling is variance, so the same question asked again gets answered — the
    opposite of the translation critic, which returned nothing on four identical
    asks out of four."""

    class SpendsThenAnswers:
        """Empty with a spent ceiling for the first `empties` asks of each role."""

        def __init__(self, empties):
            self.empties = collections.Counter()
            self.budget = empties
            self.calls = []

        def __call__(self, role, envelope, attempt_dir):
            # Counted per half, not per role: the technical editor is two calls on
            # one chapter and each is asked again on its own when it spends its
            # ceiling, which is what these two tests measure.
            key = RoleProvider._key(self, role, envelope)
            self.calls.append(key)
            payload = envelope["payload"]
            base = {
                "provider": "openrouter", "model": payload["model"], "variant": payload["variant"],
                "session_id": f"ses-{len(self.calls)}", "cost": 0.1, "latency_ms": 1, "finish": "stop",
            }
            if self.empties[key] < self.budget:
                self.empties[key] += 1
                return {**base, "text": "", "tokens": {"input": 15000, "output": 0, "reasoning": 32000}}
            answer = {"findings": [], "verdict": "faithful"}
            if role == "technical-editor":
                answer = {"verified": True, "findings": [], "consequences": []}
            return {**base, "text": json.dumps(answer), "tokens": {"input": 15000, "output": 400}}

    def close_chapter(self, provider):
        """Through the route, so the tasks exist the way a real run creates them."""
        try:
            self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        except self.bf.BookForgeError as stopped:
            return stopped
        return None

    def test_a_reviewer_empty_once_and_answering_next_is_asked_again_in_one_pass(self):
        provider = self.SpendsThenAnswers(1)
        self.close_chapter(provider)
        self.assertEqual(provider.calls.count("technical-editor"), 2, "asked again inside the pass")
        self.assertEqual(provider.calls.count("technical-contract"), 2, "and so is its other half")
        self.assertEqual(provider.calls.count("cold-reader"), 2, "and so is the role beside it")

    def test_a_reviewer_empty_every_time_still_fails_and_costs_a_constant(self):
        provider = self.SpendsThenAnswers(99)
        stopped = self.close_chapter(provider)
        self.assertIsInstance(stopped, self.bf.ReasoningCeilingSpent)
        self.assertEqual(
            provider.calls.count("technical-editor"), self.bf.REVIEW_CEILING_REASKS,
            "bounded: a role that never answers costs a constant, not a night",
        )

    def test_the_translation_critic_is_not_given_the_same_treatment(self):
        """Re-asking was measured useless there: 0 of 4 on four identical asks."""
        self.assertEqual(self.bf.CRITIC_ATTEMPTS, 3)
        source = (Path(self.bf.__file__)).read_text(encoding="utf-8")
        critic = source[source.index("def _review_translation("):]
        critic = critic[: critic.index("def _record_unapplied(")]
        self.assertNotIn("REVIEW_CEILING_REASKS", critic)



class TheReviserIsGivenRoomForTheAnswerAskedForTests(unittest.TestCase):
    """CH-0013 stopped the run three times on `Expecting ',' delimiter` at column
    17602. The budget was `target_words * 2` — 4000 tokens for a 2000-word chapter
    — and the three answers came back at 5251, 5771 and 6069, cut mid-string. The
    formula counted the rewritten prose and not the disposition the reviser owes
    for every finding."""

    def setUp(self):
        self.bf = load_module()

    def test_more_findings_buy_more_room_on_the_same_chapter(self):
        contract = {"target_words": 2000}
        few = self.bf._reviser_budget(contract, [1] * 2)
        many = self.bf._reviser_budget(contract, [1] * 20)
        self.assertGreater(many, few)
        self.assertGreaterEqual(many, 6069, "the measured answers must fit")

    def test_the_budget_never_exceeds_the_role_s_declared_ceiling(self):
        ceiling = self.bf.ROLE_BUDGETS["reviser"][1]
        self.assertEqual(self.bf._reviser_budget({"target_words": 9000}, [1] * 500), ceiling)

    def test_a_chapter_with_no_findings_is_sized_as_before(self):
        self.assertEqual(self.bf._reviser_budget({"target_words": 2000}, []), 4000)

    def test_a_contract_without_a_target_still_gets_a_floor(self):
        self.assertGreaterEqual(self.bf._reviser_budget({}, []), 1000)


if __name__ == "__main__":
    unittest.main()


class TheChapterReviewersInputDoesNotGrowTests(ReviewTests):
    """The technical editor's capsule grew with the book — 19429 characters of
    context at CH-0004, 35126 at CH-0009, 48037 at CH-0010 — while the prose it read
    stayed flat. What grows is the canon a chapter imports, and the blocks fatten as
    chapters close and write back into them, so the input of the role that gates
    every chapter followed how far the book had got.

    Split by dimension, which is a line the role's own answer already draws. The
    contract half is asked with no imports at all; the canon half keeps them and is
    asked only the four checks whose answer lives in a block."""

    class Watching(RoleProvider):
        def __init__(self, responses):
            super().__init__(responses)
            self.payloads = {}

        def __call__(self, role, envelope, attempt_dir):
            self.payloads[self._key(role, envelope)] = envelope["payload"]
            return super().__call__(role, envelope, attempt_dir)

    def reviews(self, provider):
        contract = json.loads((self.project / f"books/{self.book}/chapters/CH-0001.json").read_text())
        draft = (self.project / f"books/{self.book}/work/CH-0001/draft.md").read_text()
        consequences = json.loads((self.project / f"books/{self.book}/work/CH-0001/consequences.json").read_text())
        self.bf._ensure_review_tasks(self.project, self.book, "CH-0001")
        return self.bf._call_parallel_reviews(
            self.project, self.book, "CH-0001", contract, draft, consequences, provider,
        )

    def quiet(self, **halves):
        answers = {
            "cold-reader": [{"findings": []}],
            "technical-editor": [{"verified": True, "findings": []}],
            "technical-contract": [{"verified": True, "findings": [], "consequences": []}],
        }
        answers.update({key: [value] for key, value in halves.items()})
        return self.Watching(answers)

    def test_the_contract_half_is_asked_with_no_canon_at_all(self):
        provider = self.quiet()
        self.reviews(provider)
        self.assertEqual(provider.payloads["technical-contract"]["context"], [])

    def test_the_canon_half_still_carries_what_the_chapter_imports(self):
        provider = self.quiet()
        self.reviews(provider)
        self.assertEqual(
            [row["id"] for row in provider.payloads["technical-editor"]["context"]], ["UNI-0001#kernel"],
        )

    def test_each_half_is_told_which_checks_are_its_own(self):
        provider = self.quiet()
        self.reviews(provider)
        self.assertEqual(provider.payloads["technical-editor"]["task"]["asked"], ["voice", "knowledge", "place", "era"])
        self.assertEqual(provider.payloads["technical-contract"]["task"]["asked"], ["contract", "state", "consequences"])

    def test_the_contract_half_is_the_smaller_envelope(self):
        """Not a preference: it is the whole reason for the split."""
        provider = self.quiet()
        self.reviews(provider)
        canon = json.dumps(provider.payloads["technical-editor"])
        contract = json.dumps(provider.payloads["technical-contract"])
        self.assertLess(len(contract), len(canon))

    def test_the_consequences_come_from_the_half_that_extracts_them(self):
        fact = {"scope": "book", "fact": "Mara knows the signal.", "entities": ["CHR-0001"]}
        _, technical, _ = self.reviews(self.quiet(
            **{"technical-contract": {"verified": True, "findings": [], "consequences": [fact]}}
        ))
        self.assertEqual(technical["consequences"], [fact])

    def test_a_chapter_is_cleared_only_when_both_halves_clear_it(self):
        _, technical, _ = self.reviews(self.quiet(
            **{"technical-contract": {"verified": False, "findings": [], "consequences": []}}
        ))
        self.assertFalse(technical["verified"], "the half that did not clear it decides")

    def test_what_both_halves_found_reaches_the_caller_as_one_review(self):
        canon = {"id": "F-0001", "dimension": "canon", "severity": "warning",
                 "evidence": "paragraph two", "issue": "the place has no harbour", "fix_required": True,
                 "objective": True}
        state = {"id": "F-0001", "dimension": "state", "severity": "warning",
                 "evidence": "the last line", "issue": "the consequence is not carried", "fix_required": True,
                 "objective": False}
        _, technical, _ = self.reviews(self.quiet(
            **{
                "technical-editor": {"verified": True, "findings": [canon]},
                "technical-contract": {"verified": True, "findings": [state], "consequences": []},
            }
        ))
        self.assertEqual([row["dimension"] for row in technical["findings"]], ["canon", "state"])

    def test_the_canon_half_is_not_refused_for_extracting_no_consequences(self):
        """It was never its question, and it has no contract half's material to answer it."""
        _, technical, _ = self.reviews(self.quiet(
            **{"technical-editor": {"verified": True, "findings": []}}
        ))
        self.assertTrue(technical["verified"])

    def test_the_contract_half_still_has_to_extract_them(self):
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.reviews(self.quiet(**{"technical-contract": {"verified": True, "findings": []}}))
        self.assertIn("consequence extraction", str(caught.exception))

    def test_a_resume_pays_for_neither_half_twice(self):
        self.reviews(self.quiet())
        again = self.quiet()
        cold, technical, receipts = self.reviews(again)
        self.assertEqual(again.calls, [], "both halves were promoted and both are reused")
        self.assertEqual(receipts, [])
        self.assertTrue(technical["verified"])

    def test_the_halves_stay_separately_readable_on_disk(self):
        """The comparison this entry owes — do the two halves find what the whole
        one found — has to be made against something."""
        self.reviews(self.quiet())
        reviews = self.project / f"books/{self.book}/reviews/CH-0001"
        self.assertTrue((reviews / "technical-editor.json").is_file())
        self.assertTrue((reviews / "technical-editor-contract.json").is_file())


class Raw:
    """A scripted answer given verbatim: malformed text, or nothing at all."""

    def __init__(self, text, tokens=None):
        self.text = text
        self.tokens = tokens or {"input": 1000, "output": 200}


SPENT = Raw("", {"input": 15000, "output": 0, "reasoning": 32000})
# The shape ATT-0027 returned on the pilot: a key with a trailing space and a
# single-quoted value, 22,955 characters into an otherwise well-formed revision.
MALFORMED_REVISION = (
    '{"prose_markdown":"# Chapter\\n\\nmemory","beat_map":[{"beat":"Find signal",'
    '"evidence ":\'> LOOK\' through \'He left it sitting on the screen.\'"}]}'
)


class ScriptedProvider(RoleProvider):
    """RoleProvider that can also return raw text, and raise in place of answering."""

    def __call__(self, role, envelope, attempt_dir):
        key = self._key(role, envelope)
        with self.lock:
            scripted = self.responses.get(key)
            head = scripted[0] if scripted else None
            if isinstance(head, BaseException):
                scripted.pop(0)
                self.calls.append(role)
                raise head
            if not isinstance(head, Raw):
                pass
            else:
                scripted.pop(0)
                self.calls.append(role)
                number = len(self.calls)
                variants = {"cold-reader": "low", "technical-editor": "high", "reviser": "low"}
                return {
                    "text": head.text, "provider": "openrouter", "model": MODEL,
                    "variant": variants[role], "session_id": f"ses-{number}",
                    "tokens": head.tokens, "cost": 0.001, "latency_ms": 10, "finish": "stop",
                }
        return super().__call__(role, envelope, attempt_dir)


class SettlementHelpers:
    FINDING = {"id": "F-STATE-1", "dimension": "state", "severity": "blocking", "objective": True,
               "evidence": "final paragraph", "issue": "Signal knowledge omitted", "fix_required": True}
    CONSEQUENCE = {"scope": "book", "fact": "Mara knows the signal.", "entities": ["CHR-0001"]}
    DISPOSITION = {"finding": "T-0001", "action": "repaired", "evidence": "final paragraph", "loss": "none", "supersedes": []}

    def plan(self):
        return json.loads((self.project / ".book-forge" / "plan.json").read_text())

    def task_state(self, task_id):
        return next(row["state"] for row in self.plan()["tasks"] if row["id"] == task_id)

    def attempts_of(self, task_id):
        return [row["state"] for row in self.plan()["attempts"] if row["task"] == task_id]

    def held(self):
        return [(row["id"], row["task"], row["state"]) for row in self.plan()["attempts"]
                if row["state"] in {"running", "promotion_pending"}]

    def verifying_reviews(self, *verifier_answers):
        """The canon half raises an objective blocker, so a verifier is asked."""
        return {
            "cold-reader": [{"findings": []}],
            "technical-editor": [{"findings": [self.FINDING], "consequences": [self.CONSEQUENCE]}, *verifier_answers],
        }

    def good_revision(self):
        return self.reviser([self.CONSEQUENCE], [self.DISPOSITION])

    def manuscript(self):
        return self.project / f"books/{self.book}/manuscript/chapters/CH-0001.md"


class AVerificationThatFailsReleasesTheRevisionTests(SettlementHelpers, ReviewTests):
    """ATT-0019 on the pilot: the verifier spent 33,499 reasoning tokens and wrote
    nothing, `_parse_contract_json` raised outside any handler, VERIFY stayed
    `running` and the reviser's attempt stayed `promotion_pending`. `claim_task`
    refused REVISE from then on, and only a chapter reset reached it."""

    def assert_settled_and_retryable(self):
        self.assertEqual(self.held(), [], "no claim may outlive the call that raised")
        self.assertNotIn(self.task_state(f"REVISE-{self.book}-CH-0001"), {"running", "promotion_pending"})
        self.assertNotIn(self.task_state(f"VERIFY-{self.book}-CH-0001"), {"running", "promotion_pending"})
        again = ScriptedProvider({
            "reviser": [self.good_revision()],
            "technical-editor": [{"verified": True, "findings": []}],
        })
        result = self.bf.run_next(self.project, book_id=self.book, provider=again)
        self.assertEqual(result["state"], "closed", "run --next retries without a reset")
        self.assertTrue(self.manuscript().is_file())

    def test_an_empty_verifier_answer_is_asked_again_in_the_same_pass(self):
        provider = ScriptedProvider({
            **self.verifying_reviews(SPENT, {"verified": True, "findings": []}),
            "reviser": [self.good_revision()],
        })
        result = self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(result["state"], "closed")
        self.assertEqual(provider.calls.count("technical-editor"), 1 + 1 + 2, "canon, contract, and the verifier twice")

    def test_a_verifier_empty_on_every_ask_leaves_revise_retryable(self):
        asks = self.bf.REVIEW_CEILING_REASKS
        provider = ScriptedProvider({
            **self.verifying_reviews(*([SPENT] * asks)),
            "reviser": [self.good_revision()],
        })
        with self.assertRaises(self.bf.ReasoningCeilingSpent):
            self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(provider.calls.count("technical-editor"), 2 + asks, "bounded: the verifier costs a constant")
        self.assertFalse(self.manuscript().exists())
        self.assert_settled_and_retryable()

    def test_a_verifier_that_raises_settles_both_claims(self):
        provider = ScriptedProvider({
            **self.verifying_reviews(self.bf.ProviderProducedNothing("technical-editor produced no result")),
            "reviser": [self.good_revision()],
        })
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assert_settled_and_retryable()

    def test_a_rejected_verification_leaves_revise_retryable(self):
        rejected = {"verified": False, "findings": [{"id": "V-1", "severity": "blocking", "issue": "still omitted"}]}
        provider = ScriptedProvider({
            **self.verifying_reviews(rejected),
            "reviser": [self.good_revision()],
        })
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertIn("verification failed", str(caught.exception))
        self.assertIn("validation_failed", self.attempts_of(f"REVISE-{self.book}-CH-0001"))
        self.assert_settled_and_retryable()


class AKilledReviewBatchKeepsWhatWasPaidForTests(SettlementHelpers, ReviewTests):
    """A `run --next` killed during the review batch lost the cold reader's and the
    contract review's answers: nothing was promoted until every future returned."""

    def test_a_review_that_returned_is_promoted_before_its_siblings_finish(self):
        cold_path = self.project / f"books/{self.book}/reviews/CH-0001/cold-reader.json"
        test = self

        class KilledAfterTheColdReader(ScriptedProvider):
            def __call__(self, role, envelope, attempt_dir):
                if self._key(role, envelope) == "technical-editor":
                    deadline = time.monotonic() + 10
                    while not cold_path.is_file() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    raise SystemExit("killed by the wrapper's timeout")
                return super().__call__(role, envelope, attempt_dir)

        provider = KilledAfterTheColdReader({"cold-reader": [{"findings": []}]})
        with self.assertRaises(SystemExit):
            self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        test.assertTrue(cold_path.is_file(), "the cold reader's paid answer is on disk")
        test.assertEqual(test.task_state(f"REVIEW-COLD-{self.book}-CH-0001"), "succeeded")

    def test_one_unusable_review_does_not_discard_the_others(self):
        provider = ScriptedProvider({
            "cold-reader": [{"findings": []}],
            "technical-editor": [Raw("I could not settle on an answer.")],
        })
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(self.task_state(f"REVIEW-COLD-{self.book}-CH-0001"), "succeeded")
        self.assertEqual(self.task_state(f"REVIEW-TECHC-{self.book}-CH-0001"), "succeeded")
        self.assertIn(self.task_state(f"REVIEW-TECH-{self.book}-CH-0001"), {"pending", "failed"})
        self.assertEqual(self.held(), [])


class AMalformedAnswerIsAskedAgainBeforeBlockingTests(SettlementHelpers, ReviewTests):
    """ATT-0027 on the pilot: the reviser's revision broke on a single-quoted value,
    REVISE was blocked, and the chapter went on only after a manual
    `resume --resolve-blocked`. The identical envelope answered on the next ask."""

    def test_a_malformed_revision_is_asked_again_in_the_same_pass(self):
        provider = ScriptedProvider({
            "cold-reader": [{"findings": []}],
            "technical-editor": [{"findings": [], "consequences": []}],
            "reviser": [Raw(MALFORMED_REVISION), self.reviser()],
        })
        result = self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(result["state"], "closed")
        self.assertEqual(provider.calls.count("reviser"), 2)
        self.assertEqual(self.attempts_of(f"REVISE-{self.book}-CH-0001"), ["validation_failed", "succeeded"])

    def test_a_reviser_malformed_on_every_ask_is_bounded_and_blocks(self):
        asks = self.bf.MALFORMED_ANSWER_ASKS
        provider = ScriptedProvider({
            "cold-reader": [{"findings": []}],
            "technical-editor": [{"findings": [], "consequences": []}],
            "reviser": [Raw(MALFORMED_REVISION)] * asks,
        })
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertIn("not contract JSON", str(caught.exception))
        self.assertEqual(provider.calls.count("reviser"), asks)
        self.assertEqual(self.task_state(f"REVISE-{self.book}-CH-0001"), "blocked")
        self.assertEqual(self.held(), [])

    def test_a_revision_that_parses_but_fails_validation_is_not_asked_again(self):
        """Only the unreadable answer is variance; a wrong one is a finding."""
        provider = ScriptedProvider({
            "cold-reader": [{"findings": []}],
            "technical-editor": [{"findings": [], "consequences": []}],
            "reviser": [{**self.reviser(), "reader_state": ""}],
        })
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(provider.calls.count("reviser"), 1)

    def test_a_malformed_verifier_answer_is_asked_again(self):
        provider = ScriptedProvider({
            **self.verifying_reviews(Raw('{"verified": tru'), {"verified": True, "findings": []}),
            "reviser": [self.good_revision()],
        })
        result = self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(result["state"], "closed")
        self.assertEqual(provider.calls.count("technical-editor"), 2 + 2)


class ARejectedVerificationTeachesTheRetryTests(SettlementHelpers, ReviewTests):
    """A rejected verification used to be dropped: `verification.json` is VERIFY's
    declared output and is written only on success, so the retried reviser was
    handed the identical envelope and asked to make the same revision again."""

    REJECTION = {"id": "V-1", "severity": "blocking", "issue": "Mara still does not know the signal in the last scene"}

    def rejected_path(self):
        return self.project / f"books/{self.book}/work/CH-0001/verification-rejected.json"

    def reject_once(self):
        provider = ScriptedProvider({
            **self.verifying_reviews({"verified": False, "findings": [self.REJECTION]}),
            "reviser": [self.good_revision()],
        })
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)

    def test_the_retried_reviser_is_given_the_rejected_findings(self):
        self.reject_once()
        self.assertTrue(self.rejected_path().is_file())
        self.assertFalse((self.project / f"books/{self.book}/reviews/CH-0001/verification.json").exists(),
                         "VERIFY's declared output is not written by a rejection")
        seen = []

        class Watching(ScriptedProvider):
            def __call__(inner, role, envelope, attempt_dir):
                if role == "reviser":
                    seen.append(envelope["payload"]["task"])
                return super().__call__(role, envelope, attempt_dir)

        again = Watching({"reviser": [self.good_revision()], "technical-editor": [{"verified": True, "findings": []}]})
        self.assertEqual(self.bf.run_next(self.project, book_id=self.book, provider=again)["state"], "closed")
        rejected = seen[0]["rejected_verification"]
        self.assertEqual([row["issue"] for row in rejected["findings"]], [self.REJECTION["issue"]])
        self.assertTrue(str(rejected["attempt"]).startswith("ATT-"))
        self.assertFalse(self.rejected_path().exists(), "a passing verification supersedes the rejection")

    def test_a_first_revision_carries_no_rejection(self):
        seen = []

        class Watching(ScriptedProvider):
            def __call__(inner, role, envelope, attempt_dir):
                if role == "reviser":
                    seen.append(envelope["payload"]["task"])
                return super().__call__(role, envelope, attempt_dir)

        provider = Watching({**self.verifying_reviews({"verified": True, "findings": []}), "reviser": [self.good_revision()]})
        self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertNotIn("rejected_verification", seen[0])


class AProcessKilledDuringVerificationIsRecoveredTests(SettlementHelpers, ReviewTests):
    """A process killed by SIGKILL mid-verification raises nothing: VERIFY stays
    `running` under a dead pid and the revision stays `promotion_pending`, which
    `claim_task` refuses. Recovery has to settle both without a reset."""

    DEAD_PID = 2 ** 22 + 12345

    def kill_during_verification(self):
        test = self

        class Killed(ScriptedProvider):
            def __call__(inner, role, envelope, attempt_dir):
                if role == "technical-editor" and envelope["payload"]["task"].get("mode") == "changed-span-verification":
                    # Leave exactly what a dead process leaves: an accepted
                    # verification claim and a staged revision, owned by nobody.
                    plan = test.bf._load_plan(test.project)
                    for row in plan["attempts"]:
                        if row["state"] in {"running", "promotion_pending"}:
                            row["owner_pid"] = test.DEAD_PID
                    test.bf._save_plan(test.project, plan)
                    raise KeyboardInterrupt  # stands in for the kill; nothing may settle on the way out
                return super().__call__(role, envelope, attempt_dir)

        provider = Killed({**self.verifying_reviews(), "reviser": [self.good_revision()]})
        with self.assertRaises(KeyboardInterrupt):
            self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)

    def test_the_next_run_closes_the_chapter_without_a_reset(self):
        # The kill is simulated by rewriting ownership, so the exception path's
        # own settlement must be bypassed to leave the state a SIGKILL leaves.
        original = self.bf._verify_revision

        def unguarded(root, verify_id, envelope, runner, *, reviser_attempt, rejected_path=None):
            claim = self.bf.claim_task(root, verify_id, request_hash=str(envelope["hash"]))
            self.bf.mark_provider_accepted(root, claim["attempt"], "ses-killed")
            runner("technical-editor", envelope, Path(claim["capsule"]).parent)

        self.bf._verify_revision = unguarded
        try:
            self.kill_during_verification()
        finally:
            self.bf._verify_revision = original
        states = {row["task"]: row["state"] for row in self.plan()["attempts"]}
        self.assertEqual(states[f"REVISE-{self.book}-CH-0001"], "promotion_pending")
        self.assertEqual(states[f"VERIFY-{self.book}-CH-0001"], "running")
        again = ScriptedProvider({"reviser": [self.good_revision()], "technical-editor": [{"verified": True, "findings": []}]})
        self.assertEqual(self.bf.run_next(self.project, book_id=self.book, provider=again)["state"], "closed")
        self.assertTrue(self.manuscript().is_file())
        self.assertEqual(self.held(), [])
        self.assertNotIn("outcome_unknown", [row["state"] for row in self.plan()["attempts"]])

    def test_a_live_owner_s_staged_revision_is_left_alone(self):
        recovered = self.bf.recover_run(self.project)
        self.assertEqual(recovered.get("released", []), [])
