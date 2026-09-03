import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_review", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prose(words=700):
    return "# Chapter\n\n" + " ".join(["memory"] * words)


class RoleProvider:
    def __init__(self, responses):
        self.responses = {role: list(values) for role, values in responses.items()}
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, role, envelope, attempt_dir):
        with self.lock:
            text = self.responses[role].pop(0)
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
        self.assertEqual(provider.calls.count("technical-editor"), 1)

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
            role = "advisor-google-gemini-3-7-flash"
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
                                "openrouter/z-ai/glm-5.3-flash", "openrouter/google/gemini-3.7-flash",
                                "openrouter/openai/gpt-5.6-luna", "openrouter/qwen/qwen3.8-flash"]}}
        config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.contract = {"id": "CH-0001", "book": self.book, "pov": "CHR-0001", "target_words": 900,
                         "beats": ["Mara opens the log"], "imports": []}

    def provider(self, role, envelope, attempt_dir):
        findings = [{"id": f"{n:02d}", "dimension": "style", "severity": "warning",
                     "evidence": f"span {n}", "issue": f"issue {n}", "fix_required": True} for n in (1, 2, 3)]
        return {"text": json.dumps({"findings": findings}), "provider": "openrouter",
                "model": "openrouter/deepseek/deepseek-v4-flash-0731", "variant": "high",
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


if __name__ == "__main__":
    unittest.main()
