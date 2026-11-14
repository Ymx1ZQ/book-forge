"""M101: a chapter is read for sequence, staging, timeline and local repetition
after the reviser and before it is promoted, and the reader's edits are applied
by the engine only when their text occurs once."""
import json
import os
import signal
import tempfile
import threading
import time
import unittest
from pathlib import Path

from engagement_support import with_engagement_fields
from test_pivotal import PivotalProvider, ReviewOnlyProvider
from test_review import MODEL, RoleProvider, cold_answer, load_module

HYDROGEN = "openrouter/google/gemini-4-hydrogen"
FLASH = "openrouter/google/gemini-3.8-flash"
LENSES = ("sequence-lens-staging", "sequence-lens-world", "sequence-lens-repetition")
PROMPTS = Path(__file__).parents[1] / "assets" / "prompts"


def chapter(*sentences, tail="", filler=640):
    """A chapter of the contract's length whose first and last sentences a test can edit."""
    return "# Chapter\n\n" + " ".join(sentences) + " " + " ".join(["memory"] * filler) + (f" {tail}" if tail else "") + "\n"


def finding(identifier, find, replace, kind="staging"):
    return {
        "id": identifier, "kind": kind, "evidence": find, "conflicts_with": "",
        "issue": f"{identifier} cannot happen as written", "edit": {"find": find, "replace": replace},
    }


def answer(*rows):
    return {"findings": list(rows)}


CLEAN = answer()
CASE = "Mara took the bass case from the car."
DOOR = "She stood at the door."
POSTMARK = "The postmark said April."
STUCK = finding("Q-01", "a sentence the chapter never had", "anything", kind="timeline")
# What a check that never repairs its finding answers, round by round.
STUCK_READS = {"1-staging": [answer(STUCK)], "2": [answer(STUCK)], "3": [answer(STUCK)]}


def read_key(task_id):
    """`SEQ-BOOK-0001-CH-0001-1-staging` -> `1-staging`; `...-CH-0001-2` -> `2`."""
    return task_id.split("-CH-", 1)[1].split("-", 1)[1]


class SeqProvider(RoleProvider):
    """Answers each sequence read by its round and lens, and keeps what every call was handed.

    `reads` maps `1-staging`, `1-world`, `1-repetition`, `2` and `3` to answers taken
    in turn; an exception in the list is raised in place of answering, and a read
    with nothing scripted gets a clean answer."""

    def __init__(self, responses, reads=None):
        super().__init__(responses)
        self.reads = {key: list(values) for key, values in (reads or {}).items()}
        self.envelopes = []

    def __call__(self, role, envelope, attempt_dir):
        task = json.loads((Path(attempt_dir) / "capsule.json").read_text())["task"]["id"]
        with self.lock:
            self.envelopes.append({"role": role, "task": task, "capsule": envelope["payload"]["task"],
                                   "prompt": envelope["payload"].get("role_prompt", "")})
        if role != "sequence-checker":
            return super().__call__(role, envelope, attempt_dir)
        with self.lock:
            queue = self.reads.get(read_key(task)) or []
            value = queue.pop(0) if queue else CLEAN
            self.calls.append(role)
            number = len(self.calls)
        if isinstance(value, BaseException):
            raise value
        return {
            "text": json.dumps(value), "provider": "openrouter", "model": envelope["payload"]["model"],
            "variant": envelope["payload"]["variant"], "session_id": f"ses-seq-{number}",
            "tokens": {"input": envelope["estimated_input_tokens"], "output": 200},
            "cost": 0.001, "latency_ms": 10, "finish": "stop",
        }


class Killed(SeqProvider):
    """SIGKILLs its own process at the first sequence read: what a dead driver leaves."""

    def __call__(self, role, envelope, attempt_dir):
        if role == "sequence-checker":
            os.kill(os.getpid(), signal.SIGKILL)
        return super().__call__(role, envelope, attempt_dir)


class SequenceFixture(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        self.book = self.bf.add_book(self.project, "Book")["id"]
        chapter_dir = self.project / f"books/{self.book}/chapters"
        chapter_dir.mkdir()
        self.contract = with_engagement_fields({
            "schema": 1, "book": self.book, "id": "CH-0001", "order": 1, "title": "Chapter",
            "pov": "CHR-0001", "beats": ["Find signal"], "plants": [], "reveals": [],
            "target_words": 700, "imports": ["UNI-0001#kernel"], "pivotal": None,
        })
        (chapter_dir / "CH-0001.json").write_text(json.dumps(self.contract))
        draft = {"prose_markdown": chapter(CASE, DOOR), "beat_map": [{"beat": "Find signal", "evidence": "found"}], "consequences": []}

        class DraftProvider:
            def __call__(inner_self, role, envelope, attempt_dir):
                return {"text": json.dumps(draft), "provider": "openrouter", "model": MODEL, "variant": "low",
                        "session_id": "ses-draft", "tokens": {"input": 1000, "output": 800}, "cost": .001,
                        "latency_ms": 10, "finish": "stop"}

        self.bf.draft_chapter(self.project, self.book, "CH-0001", provider=DraftProvider())

    def revision(self, prose, dispositions=None, consequences=None):
        return {
            "prose_markdown": prose, "beat_map": [{"beat": "Find signal", "evidence": "found"}],
            "consequences": list(consequences or []), "dispositions": list(dispositions or []),
            "reader_state": "Mara is at the door.",
        }

    def provider(self, reads, revisions, **responses):
        return SeqProvider({
            "cold-reader": [cold_answer()],
            "technical-editor": [{"findings": [], "consequences": []}],
            "reviser": list(revisions),
            **responses,
        }, reads)

    def close(self, provider):
        return self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)

    def plan(self):
        return json.loads((self.project / ".book-forge/plan.json").read_text())

    def held(self):
        return [(row["task"], row["state"]) for row in self.plan()["attempts"] if row["state"] in {"running", "promotion_pending"}]

    def manuscript(self):
        return self.project / f"books/{self.book}/manuscript/chapters/CH-0001.md"

    def record(self):
        return json.loads((self.project / f"books/{self.book}/reviews/CH-0001/sequence.json").read_text())

    def rejected(self):
        return self.project / f"books/{self.book}/work/CH-0001/sequence-rejected.json"

    def task_state(self, task_id):
        return next(row["state"] for row in self.plan()["tasks"] if row["id"] == task_id)

    def sequence_capsules(self, provider):
        return [row for row in provider.envelopes if row["role"] == "sequence-checker"]

    def seq(self, key):
        return f"SEQ-{self.book}-CH-0001-{key}"


class RepetitionCandidateTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def words(self, text):
        return [row["word"] for row in self.bf._repetition_candidates(text) if "word" in row]

    def phrases(self, text):
        return {row["phrase"]: row["sentences"] for row in self.bf._repetition_candidates(text) if "phrase" in row}

    def test_a_content_word_three_times_within_sixty_words_is_a_candidate(self):
        text = (
            "The postmark was smudged. " + "She sat by him. " * 4 + "She read the postmark again. "
            + "She sat by him. " * 3 + "The postmark said April."
        )
        self.assertLess(len(text.split()), 60)
        row = next(row for row in self.bf._repetition_candidates(text) if row.get("word") == "postmark")
        self.assertEqual(row["sentences"], ["The postmark was smudged.", "She read the postmark again.", "The postmark said April."])

    def test_the_same_word_spread_over_three_hundred_words_is_not(self):
        gap = "She sat by him. " * 40
        text = f"The postmark was smudged. {gap}She read the postmark again. {gap}The postmark said April."
        self.assertGreater(len(text.split()), 300)
        self.assertNotIn("postmark", self.words(text))

    def test_a_proper_noun_is_never_one(self):
        text = "She called Harrow. Then she asked Harrow again, and Harrow did not answer her."
        self.assertNotIn("harrow", self.words(text))

    def test_short_words_and_stopwords_are_not_counted(self):
        text = "Every door, every door, every door. Through it, through it, through it."
        self.assertEqual(self.bf._repetition_candidates(text), [])

    def test_a_three_word_phrase_twice_a_thousand_words_apart_is_a_candidate(self):
        gap = "It was so. " * 334
        self.assertGreater(len(gap.split()), 1000)
        text = f"She carried the bass case down. {gap}He carried the bass case up."
        phrases = self.phrases(text)
        self.assertEqual(phrases["carried the bass"], ["She carried the bass case down.", "He carried the bass case up."])
        # The two-word phrases inside it are left to it; the one that runs past it is not.
        self.assertNotIn("carried the", phrases)
        self.assertIn("bass case", phrases)

    def test_a_two_word_phrase_inside_a_repeated_three_word_one_is_dropped(self):
        text = "She checked the storage unit door. Later she checked the storage unit door again."
        phrases = self.phrases(text)
        self.assertIn("storage unit door", phrases)
        self.assertNotIn("storage unit", phrases)
        self.assertNotIn("unit door", phrases)

    def test_a_name_repeated_is_not_one(self):
        text = "Mara Quint came in. Much later, Mara Quint came in again. Quint's voice rose. Quint's voice fell."
        self.assertEqual(self.phrases(text), {})

    def test_a_phrase_of_stopwords_is_not_one(self):
        text = "It was there in the end. Then it was there in the end again. He had been back first time."
        self.assertEqual(self.phrases(text), {})

    def test_a_phrase_does_not_run_across_punctuation(self):
        text = "She kept the case. Light came in. She shut the case. Light went out."
        self.assertNotIn("case light", self.phrases(text))


class PinTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def test_the_checker_runs_on_hydrogen_at_high(self):
        self.assertEqual(self.bf._role_pin({}, "sequence-checker"), (HYDROGEN, "high"))
        self.assertEqual(self.bf._expected_pin("sequence-checker"), ("google/gemini-4-hydrogen", "high"))

    def test_the_project_may_name_another_model(self):
        config = {"roles": {"sequence-checker": {"model": FLASH, "variant": "medium"}}}
        self.assertEqual(self.bf._role_pin(config, "sequence-checker"), (FLASH, "medium"))
        self.assertEqual(self.bf._role_pin({"roles": {"sequence-checker": {"variant": "low"}}}, "sequence-checker"), (HYDROGEN, "low"))

    def test_hydrogen_is_catalogued_and_advises_nobody_by_default(self):
        cfg = self.bf.CHORUS_MODEL_CONFIGS[HYDROGEN]
        self.assertEqual(cfg["default_effort"], "high")
        self.assertEqual(sorted(cfg["variants"]), ["high", "low", "medium"])
        self.assertNotIn(HYDROGEN, self.bf.CHORUS_DEFAULT_MODELS)
        self.assertNotIn(HYDROGEN, self.bf.STYLE_REVIEW_MODELS)

    def test_the_budgets_and_the_fallback_are_the_generic_ones(self):
        self.assertEqual(self.bf.ROLE_SPECS["sequence-checker"], ("all", "high", 4))
        self.assertEqual(self.bf.ROLE_BUDGETS["sequence-checker"], (16000, 6000))
        self.assertEqual(self.bf.REASONING_ROOM["sequence-checker"], 64000)
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "world"
            self.bf.init_project(project, "World")
            fallback = self.bf._role_fallback(project, "sequence-checker")
            self.assertEqual((fallback["model"], fallback["variant"], fallback["from"]), (FLASH, "high", HYDROGEN))

    def test_the_reviser_runs_at_medium_and_still_follows_the_writer(self):
        self.assertEqual(self.bf._role_pin({}, "reviser"), (MODEL, "medium"))
        config = {"roles": {"writer": {"model": "openrouter/z-ai/glm-5.3-flash", "variant": "high"}}}
        self.assertEqual(self.bf._role_pin(config, "reviser"), ("openrouter/z-ai/glm-5.3-flash", "high"))

    def test_the_reviser_at_medium_has_the_reasoning_room_of_the_other_roles_at_medium(self):
        self.assertEqual(self.bf.REASONING_ROOM["reviser"], self.bf.REASONING_ROOM["continuity-reviser"])

    def test_runtime_sync_writes_the_agent_and_lists_the_model(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "world"
            self.bf.init_project(project, "World")
            self.bf.sync_runtime(project)
            agent = (project / ".opencode/agents/sequence-checker.md").read_text()
            self.assertIn(f"model: {HYDROGEN}\n", agent)
            self.assertIn("variant: high\n", agent)
            models = json.loads((project / "opencode.json").read_text())["provider"]["openrouter"]["models"]
            self.assertIn("google/gemini-4-hydrogen", models)
            self.assertEqual(sorted(models["google/gemini-4-hydrogen"]["variants"]), ["high", "low", "medium"])
            self.assertEqual(self.bf._stale_agent_pins(project), [])

    def test_a_project_override_reaches_the_agent(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "world"
            self.bf.init_project(project, "World")
            config_path = project / "book-forge.yaml"
            config = json.loads(config_path.read_text())
            config["roles"] = {"sequence-checker": {"model": FLASH, "variant": "medium"}}
            config_path.write_text(json.dumps(config))
            self.bf.sync_runtime(project)
            agent = (project / ".opencode/agents/sequence-checker.md").read_text()
            self.assertIn(f"model: {FLASH}\n", agent)
            self.assertIn("variant: medium\n", agent)


class PromptTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def test_round_one_reads_through_three_lenses_and_later_rounds_through_the_single_prompt(self):
        self.assertEqual(self.bf.SEQUENCE_FIRST_LENSES, LENSES)
        self.assertEqual(self.bf.SEQUENCE_LATER_LENSES, ("sequence-checker",))
        self.assertEqual(self.bf._sequence_call_budget(), 5)

    def test_the_skill_ships_a_prompt_for_every_lens_and_each_envelope_carries_its_own(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "world"
            self.bf.init_project(project, "World")
            self.bf.sync_runtime(project)
            for lens in LENSES + ("sequence-checker",):
                with self.subTest(lens=lens):
                    text = (PROMPTS / f"{lens}.md").read_text().strip()
                    envelope = self.bf.build_envelope(
                        project, role="sequence-checker", prompt_role=lens, task_capsule={"prose": "x"},
                        imports=[], state={}, tools=[], max_output_tokens=6000,
                    )
                    self.assertEqual(envelope["payload"]["role_prompt"], text)
                    self.assertEqual(envelope["payload"]["model"], HYDROGEN)
            self.assertFalse(any(PROMPTS.glob("sequence-lens-timeline*")))

    def test_every_read_is_told_a_settled_finding_is_not_reported_again(self):
        for lens in LENSES + ("sequence-checker",):
            with self.subTest(lens=lens):
                text = (PROMPTS / f"{lens}.md").read_text()
                self.assertIn("The capsule may carry `settled`", text)
                self.assertIn("do not report one again unless the text it quotes has changed", text)

    def test_the_readers_of_repetition_are_told_candidates_may_be_phrases(self):
        for lens in ("sequence-checker", "sequence-lens-repetition"):
            with self.subTest(lens=lens):
                self.assertIn("two- or three-word phrases (`phrase` in place of `word`)", (PROMPTS / f"{lens}.md").read_text())


class EditTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def test_an_edit_applies_only_to_text_that_occurs_once(self):
        refuse = self.bf._sequence_edit_refusal
        self.assertIsNone(refuse("a door. a case.", {"find": "a case", "replace": "the case"}))
        self.assertIn("occurs 2 times", refuse("a door. a door.", {"find": "a door", "replace": "the door"}))
        self.assertIn("not in the chapter", refuse("a door.", {"find": "a window", "replace": "the window"}))
        self.assertIn("empty", refuse("a door.", {"find": "  ", "replace": "x"}))
        self.assertIn("changes nothing", refuse("a door.", {"find": "a door", "replace": "a door"}))

    def test_an_edit_never_lands_on_text_an_earlier_edit_of_its_round_put_in(self):
        refuse = self.bf._sequence_edit_refusal
        read = "a door. a case."
        # An earlier edit wrote "the gate"; the round never read it.
        self.assertIn("as read", refuse("the gate. a case.", {"find": "the gate", "replace": "the porch"}, start=read))
        # An earlier edit copied "a case"; it occurred once in what the round read.
        self.assertIn("occurs 2 times", refuse("a case. a case.", {"find": "a case", "replace": "the case"}, start=read))
        self.assertIn("as read", refuse("a door. a door.", {"find": "a door", "replace": "the door"}, start="a door. a door."))
        self.assertIsNone(refuse("the gate. a case.", {"find": "a case", "replace": "the case"}, start=read))

    def test_a_replacement_may_be_empty_and_may_not_grow_past_the_limit(self):
        refuse = self.bf._sequence_edit_refusal
        self.assertIsNone(refuse("It rained. It rained again.", {"find": " It rained again.", "replace": ""}))
        find = "a door"
        limit = self.bf.CONTINUITY_EDIT_GROWTH * len(find) + 200
        self.assertIsNone(refuse("a door.", {"find": find, "replace": "x" * limit}))
        self.assertIn("too long", refuse("a door.", {"find": find, "replace": "x" * (limit + 1)}))

    def test_a_finding_without_a_usable_shape_is_set_aside_and_the_rest_are_used(self):
        usable, set_aside = self.bf._sequence_findings({"findings": [
            finding("Q-01", "a", "b"),
            {"id": "Q-02", "kind": "staging", "evidence": "x", "issue": "y"},
            {**finding("Q-03", "a", "b"), "edit": {"find": "a"}},
            finding("Q-01", "c", "d"),
            "not an object",
        ]})
        self.assertEqual([row["id"] for row in usable], ["Q-01"])
        self.assertEqual(len(set_aside), 4)
        with self.assertRaises(self.bf.MalformedAnswer):
            self.bf._sequence_findings({"findings": [{"id": "Q-01"}]})
        with self.assertRaises(self.bf.MalformedAnswer):
            self.bf._sequence_findings({"verdict": "fine"})
        self.assertEqual(self.bf._sequence_findings(CLEAN), ([], []))

    def test_findings_past_the_answer_bound_are_set_aside(self):
        rows = [finding(f"Q-{n:02d}", f"w{n}", f"v{n}") for n in range(1, self.bf.SEQUENCE_MAX_FINDINGS + 3)]
        usable, set_aside = self.bf._sequence_findings({"findings": rows})
        self.assertEqual(len(usable), self.bf.SEQUENCE_MAX_FINDINGS)
        self.assertEqual(len(set_aside), 2)
        usable, set_aside = self.bf._sequence_findings({"findings": rows}, self.bf.SEQUENCE_LENS_MAX_FINDINGS)
        self.assertEqual((len(usable), len(set_aside)), (10, len(rows) - 10))


class CheckLoopTests(SequenceFixture):
    def test_a_clean_first_round_costs_three_calls_and_promotes_the_revision_byte_identical(self):
        revised = chapter(CASE, DOOR)
        provider = self.provider({}, [self.revision(revised)])
        result = self.close(provider)
        self.assertEqual(provider.calls.count("sequence-checker"), 3)
        self.assertEqual(result["calls"], 6)
        self.assertEqual(self.manuscript().read_text(), revised.rstrip() + "\n")
        reads = self.sequence_capsules(provider)
        self.assertEqual(sorted(row["task"] for row in reads), sorted(self.seq(f"1-{lens}") for lens in ("staging", "world", "repetition")))
        for row in reads:
            capsule = row["capsule"]
            self.assertEqual(capsule["prose"], revised)
            self.assertEqual(capsule["contract"], {"title": "Chapter", "pov": "CHR-0001", "beats": ["Find signal"]})
            self.assertEqual(capsule["answer_bound"], "Report at most 10 findings.")
            self.assertIn("repetition_candidates", capsule)
            self.assertNotIn("unresolved", capsule)
            self.assertNotIn("settled", capsule)
            lens = "sequence-lens-" + read_key(row["task"]).split("-", 1)[1]
            self.assertEqual(row["prompt"], (PROMPTS / f"{lens}.md").read_text().strip())
        record = self.record()
        self.assertEqual(record["open"], [])
        self.assertEqual(len(record["rounds"]), 1)
        self.assertEqual(self.held(), [])

    def test_edits_from_two_lenses_are_both_applied_and_round_two_reads_through_the_single_prompt(self):
        revised = chapter(CASE, DOOR, tail=POSTMARK)
        provider = self.provider({
            "1-staging": [answer(finding("Q-01", CASE, "Mara had already brought the bass case in."))],
            "1-repetition": [answer(finding("Q-01", " " + DOOR, "", kind="restatement"))],
            "1-world": [answer(finding("Q-01", POSTMARK, "The postmark said March.", kind="plausibility"))],
        }, [self.revision(revised)])
        self.close(provider)
        text = self.manuscript().read_text()
        self.assertTrue(text.startswith("# Chapter\n\nMara had already brought the bass case in. memory"))
        self.assertNotIn(DOOR, text)
        self.assertTrue(text.endswith("The postmark said March.\n"))
        later = [row for row in self.sequence_capsules(provider) if row["task"] == self.seq("2")]
        self.assertEqual(len(later), 1)
        self.assertEqual(later[0]["prompt"], (PROMPTS / "sequence-checker.md").read_text().strip())
        self.assertEqual(later[0]["capsule"]["answer_bound"], "Report at most 15 findings.")
        self.assertIn("Mara had already brought the bass case in.", later[0]["capsule"]["prose"])
        self.assertEqual(later[0]["capsule"]["unresolved"], [])
        record = self.record()
        self.assertEqual(record["rounds"][0]["applied"], ["staging-Q-01", "world-Q-01", "repetition-Q-01"])
        self.assertEqual(record["rounds"][0]["model"], self.bf.SEQUENCE_CHECKER_MODEL)
        self.assertEqual(record["rounds"][0]["cost"], 0.003)
        self.assertEqual(record["after"], f"REVISE-{self.book}-CH-0001")
        self.assertEqual(len(record["rounds"]), 2)
        state = json.loads((self.project / f"books/{self.book}/state.yaml").read_text())
        self.assertTrue(state["previous_chapter_tail"].rstrip().endswith("The postmark said March."))

    def test_an_edit_whose_text_occurs_twice_is_offered_back_as_unresolved(self):
        revised = chapter(DOOR, DOOR, CASE)
        provider = self.provider({
            "1-staging": [answer(finding("Q-01", DOOR, "She stood at the gate."))],
            "2": [answer(finding("Q-01", f"{DOOR} {DOOR}", DOOR, kind="restatement"))],
        }, [self.revision(revised)])
        self.close(provider)
        later = [row for row in self.sequence_capsules(provider) if row["task"] == self.seq("2")]
        unresolved = later[0]["capsule"]["unresolved"]
        self.assertEqual([row["id"] for row in unresolved], ["staging-Q-01"])
        self.assertIn("occurs 2 times", unresolved[0]["why"])
        self.assertEqual(self.manuscript().read_text().count(DOOR), 1)
        self.assertEqual(provider.calls.count("sequence-checker"), 5)

    def test_an_edit_on_text_an_earlier_edit_of_the_round_put_in_is_not_applied(self):
        provider = self.provider({
            "1-staging": [answer(finding("Q-01", DOOR, "She stood at the gate."))],
            "1-world": [answer(finding("Q-01", "She stood at the gate.", "She stood at the porch."))],
        }, [self.revision(chapter(CASE, DOOR))])
        self.close(provider)
        text = self.manuscript().read_text()
        self.assertIn("She stood at the gate.", text)
        self.assertNotIn("porch", text)
        self.assertEqual(self.record()["rounds"][0]["unresolved"], ["world-Q-01"])

    def test_every_read_is_billed_to_the_chapter_within_a_budget_of_its_own(self):
        revised = chapter(DOOR, DOOR, CASE)
        provider = self.provider({
            "1-staging": [answer(finding("Q-01", DOOR, "She stood at the gate."))],
            "2": [answer(finding("Q-01", f"{DOOR} {DOOR}", DOOR, kind="restatement"))],
        }, [self.revision(revised)])
        self.close(provider)
        report = self.bf.telemetry_report(self.project)
        codes = {row["code"] for row in report["violations"]}
        self.assertNotIn("accepted_call_unattributed", codes)
        self.assertNotIn("chapter_call_budget", codes)
        self.assertEqual(report["by_role"]["sequence-checker"]["calls"], 5)

    def test_an_edit_past_the_growth_limit_is_not_applied(self):
        provider = self.provider({"1-staging": [answer(finding("Q-01", "bass", "x" * 400))]}, [self.revision(chapter(CASE))])
        self.close(provider)
        self.assertNotIn("x" * 400, self.manuscript().read_text())
        record = self.record()
        self.assertEqual(record["rounds"][0]["unresolved"], ["staging-Q-01"])
        self.assertEqual(record["open"], [])

    def test_sequence_json_is_a_declared_output_of_revise(self):
        self.close(self.provider({}, [self.revision(chapter(CASE, DOOR))]))
        task = next(row for row in self.plan()["tasks"] if row["id"] == f"REVISE-{self.book}-CH-0001")
        self.assertIn(f"books/{self.book}/reviews/CH-0001/sequence.json", task["outputs"])
        self.assertEqual(task["state"], "succeeded")

    def test_a_revise_task_an_older_engine_declared_is_given_the_output(self):
        self.bf._ensure_review_tasks(self.project, self.book, "CH-0001")
        plan_path = self.project / ".book-forge/plan.json"
        plan = json.loads(plan_path.read_text())
        task = next(row for row in plan["tasks"] if row["id"] == f"REVISE-{self.book}-CH-0001")
        task["outputs"] = [path for path in task["outputs"] if not path.endswith("sequence.json")]
        self.bf._save_plan(self.project, plan)
        self.close(self.provider({}, [self.revision(chapter(CASE, DOOR))]))
        self.assertTrue((self.project / f"books/{self.book}/reviews/CH-0001/sequence.json").is_file())

    def test_a_checker_that_fails_leaves_no_claim_held_and_the_revision_retryable(self):
        class Broken(RoleProvider):
            def __call__(inner, role, envelope, attempt_dir):
                if role == "sequence-checker":
                    raise self.bf.ProviderProducedNothing("nothing on the wire")
                return super().__call__(role, envelope, attempt_dir)

        provider = Broken({"cold-reader": [cold_answer()], "technical-editor": [{"findings": [], "consequences": []}],
                           "reviser": [self.revision(chapter(CASE, DOOR))]})
        with self.assertRaises(self.bf.BookForgeError):
            self.close(provider)
        self.assertEqual(self.held(), [])
        self.assertFalse(self.manuscript().exists())
        self.assertEqual(self.task_state(f"REVISE-{self.book}-CH-0001"), "pending")

    def test_a_malformed_answer_is_asked_again_once(self):
        provider = self.provider({"1-staging": [{"verdict": "fine"}, CLEAN]}, [self.revision(chapter(CASE, DOOR))])
        self.close(provider)
        self.assertEqual(provider.calls.count("sequence-checker"), 4)
        states = [row["state"] for row in self.plan()["attempts"] if row["task"] == self.seq("1-staging")]
        self.assertEqual(states, ["validation_failed", "succeeded"])


class ProseGateTests(SequenceFixture):
    """An edit is held to the gate the reviser's prose passed: one that fails it is
    reverted and set aside, and the chapter is promoted without it."""

    def assert_reverted(self, reason):
        record = self.record()
        first = record["rounds"][0]
        self.assertEqual(first["applied"], [])
        self.assertEqual(first["unresolved"], [])
        reverted = [row for row in first["set_aside"] if row["id"] == "staging-Q-01"]
        self.assertEqual(len(reverted), 1)
        self.assertIn(reason, reverted[0]["why"])
        self.assertEqual(record["open"], [])
        # Nothing applied and nothing left to re-issue: the next round would read the same text.
        self.assertEqual(len(record["rounds"]), 1)

    def test_an_edit_that_writes_a_placeholder_is_reverted(self):
        provider = self.provider({"1-staging": [answer(finding("Q-01", CASE, "Mara took the TODO case from the car."))]},
                                 [self.revision(chapter(CASE, DOOR))])
        self.close(provider)
        self.assertIn(CASE, self.manuscript().read_text())
        self.assertNotIn("TODO", self.manuscript().read_text())
        self.assertEqual(provider.calls.count("sequence-checker"), 3)
        self.assert_reverted("placeholder")

    def test_an_edit_that_tells_a_withheld_fact_is_reverted_and_the_checker_is_told_what_is_withheld(self):
        withheld = [{"id": "WH-0001", "status": "withheld", "seen_as": "the heavy air", "revealed_in": "CH-0002",
                     "told_by": "CHR-0001", "never_write": ["Earth"]}]
        path = self.project / f"books/{self.book}/chapters/CH-0001.json"
        path.write_text(json.dumps({**self.contract, "withheld": withheld}))
        provider = self.provider({"1-staging": [answer(finding("Q-01", CASE, "Mara took the bass case from the car, as on Earth."))]},
                                 [self.revision(chapter(CASE, DOOR))])
        self.close(provider)
        self.assertNotIn("Earth", self.manuscript().read_text())
        for row in self.sequence_capsules(provider):
            self.assertEqual(row["capsule"]["contract"]["withheld"], withheld)
        self.assert_reverted("WH-0001")

    def test_an_edit_that_takes_the_chapter_under_its_word_count_is_reverted(self):
        tail = " ".join(f"note{number}" for number in range(250))
        revised = chapter(CASE, DOOR, tail=tail, filler=300)
        provider = self.provider({"1-staging": [answer(finding("Q-01", " " + tail, "", kind="restatement"))]},
                                 [self.revision(revised)])
        self.close(provider)
        self.assertIn(tail, self.manuscript().read_text())
        self.assert_reverted("word count")

    def test_a_closed_chapter_s_edit_is_held_to_the_same_gate(self):
        self.close(self.provider({}, [self.revision(chapter(CASE, DOOR))]))
        before = self.manuscript().read_bytes()
        result = self.bf.sequence_check_chapter(self.project, self.book, "CH-0001", provider=self.provider(
            {"1-staging": [answer(finding("Q-01", CASE, "Mara took the [PLACEHOLDER] case."))]}, []))
        self.assertEqual(self.manuscript().read_bytes(), before)
        self.assertEqual((result["applied"], result["open"], result["rounds"]), ([], [], 1))


class OpenFindingTests(SequenceFixture):
    def test_findings_left_open_fail_the_revision_without_blocking_and_reach_the_next_reviser(self):
        first = self.provider(STUCK_READS, [self.revision(chapter(CASE, DOOR))])
        with self.assertRaisesRegex(self.bf.BookForgeError, "Sequence check left 1 findings open; chapter remains unpromoted"):
            self.close(first)
        self.assertEqual(first.calls.count("sequence-checker"), 5)
        self.assertFalse(self.manuscript().exists())
        self.assertEqual(self.held(), [])
        reviser_id = f"REVISE-{self.book}-CH-0001"
        self.assertEqual(self.task_state(reviser_id), "pending")
        attempts = [row for row in self.plan()["attempts"] if row["task"] == reviser_id]
        self.assertEqual(attempts[-1]["state"], "validation_failed")
        self.assertEqual([row["evidence"] for row in json.loads(self.rejected().read_text())["findings"]], [STUCK["evidence"]])
        state = json.loads((self.project / f"books/{self.book}/state.yaml").read_text())
        self.assertNotIn("CH-0001", state.get("closed_chapters", []))

        disposition = {"finding": "Q-0001", "action": "repaired", "evidence": "the year", "loss": "none", "supersedes": []}
        second = SeqProvider({"reviser": [self.revision(chapter(CASE, DOOR), [disposition])]})
        self.close(second)
        reviser_capsule = next(row["capsule"] for row in second.envelopes if row["role"] == "reviser")
        owed = [row for row in reviser_capsule["findings"] if row["id"] == "Q-0001"]
        self.assertEqual(owed, [{
            "id": "Q-0001", "dimension": "sequence", "severity": "warning", "fix_required": True,
            "review": "sequence", "evidence": STUCK["evidence"], "issue": STUCK["issue"],
        }])
        self.assertNotIn("cold-reader", second.calls)
        self.assertTrue(self.manuscript().is_file())
        self.assertFalse(self.rejected().exists())
        self.assertEqual(self.held(), [])

    def test_the_retried_revision_is_claimed_by_the_next_run_and_closes(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.close(self.provider(STUCK_READS, [self.revision(chapter(CASE, DOOR))]))
        disposition = {"finding": "Q-0001", "action": "repaired", "evidence": "the year", "loss": "none", "supersedes": []}
        result = self.bf.run_next(self.project, book_id=self.book,
                                  provider=SeqProvider({"reviser": [self.revision(chapter(CASE, DOOR), [disposition])]}))
        self.assertEqual(result["state"], "closed")
        attempts = [row["state"] for row in self.plan()["attempts"] if row["task"] == f"REVISE-{self.book}-CH-0001"]
        self.assertEqual(attempts, ["validation_failed", "succeeded"])
        self.assertTrue(self.manuscript().is_file())
        self.assertFalse(self.rejected().exists())
        self.assertEqual(self.held(), [])

    def test_a_reviser_that_ignores_the_open_finding_is_refused(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.close(self.provider(STUCK_READS, [self.revision(chapter(CASE, DOOR))]))
        with self.assertRaisesRegex(self.bf.BookForgeError, "Q-0001"):
            self.close(SeqProvider({"reviser": [self.revision(chapter(CASE, DOOR))]}))

    def test_a_finding_the_reviser_rejected_is_settled_and_does_not_fail_the_chapter_again(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.close(self.provider(STUCK_READS, [self.revision(chapter(CASE, DOOR))]))
        reason = "The chapter has no such sentence; the finding quotes text that is not there."
        dismissed = {"finding": "Q-0001", "action": "dismissed", "evidence": reason, "loss": "none", "supersedes": []}
        second = SeqProvider({"reviser": [self.revision(chapter(CASE, DOOR), [dismissed])]}, STUCK_READS)
        self.close(second)
        self.assertTrue(self.manuscript().is_file())
        self.assertFalse(self.rejected().exists())
        settled = [{"evidence": STUCK["evidence"], "issue": STUCK["issue"], "action": "dismissed", "reason": reason}]
        for row in self.sequence_capsules(second):
            self.assertEqual(row["capsule"]["settled"], settled)
        first_round = self.record()["rounds"][0]
        self.assertEqual(first_round["findings"], [])
        self.assertIn("settled", next(row["why"] for row in first_round["set_aside"] if row["id"] == "staging-Q-01"))
        self.assertEqual(second.calls.count("sequence-checker"), 3)

    def test_a_settled_finding_stays_settled_while_the_chapter_keeps_failing(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.close(self.provider(STUCK_READS, [self.revision(chapter(CASE, DOOR))]))
        dismissed = {"finding": "Q-0001", "action": "dismissed", "evidence": "no such sentence", "loss": "none", "supersedes": []}
        other = finding("Q-02", "another sentence the chapter never had", "x")
        with self.assertRaisesRegex(self.bf.BookForgeError, "left 1 findings open"):
            self.close(SeqProvider({"reviser": [self.revision(chapter(CASE, DOOR), [dismissed])]},
                                   {"1-staging": [answer(STUCK, other)], "2": [answer(other)], "3": [answer(STUCK, other)]}))
        left = json.loads(self.rejected().read_text())
        self.assertEqual([row["evidence"] for row in left["findings"]], [other["evidence"]])
        self.assertEqual([row["evidence"] for row in left["settled"]], [STUCK["evidence"]])
        # The next reviser owes the new finding only, and the old one is still settled.
        repaired = {"finding": "Q-0001", "action": "repaired", "evidence": "changed", "loss": "none", "supersedes": []}
        third = SeqProvider({"reviser": [self.revision(chapter(CASE, DOOR), [repaired])]}, {"1-staging": [answer(STUCK)]})
        self.close(third)
        self.assertTrue(self.manuscript().is_file())

    def test_a_passing_check_removes_what_an_earlier_check_left_open_even_when_promotion_then_fails(self):
        blocker = {"id": "F-STATE-1", "dimension": "state", "severity": "blocking", "objective": True,
                   "evidence": "final paragraph", "issue": "Signal knowledge omitted", "fix_required": True}
        consequence = {"scope": "book", "fact": "Mara knows the signal.", "entities": ["CHR-0001"]}
        technical = {"finding": "T-0001", "action": "repaired", "evidence": "final paragraph", "loss": "none", "supersedes": []}
        owed = {"finding": "Q-0001", "action": "repaired", "evidence": "the year", "loss": "none", "supersedes": []}
        with self.assertRaisesRegex(self.bf.BookForgeError, "Sequence check left"):
            self.close(self.provider(STUCK_READS, [self.revision(chapter(CASE, DOOR), [technical], [consequence])],
                                     **{"technical-editor": [{"findings": [blocker], "consequences": [consequence]}]}))
        self.assertTrue(self.rejected().exists())
        with self.assertRaisesRegex(self.bf.BookForgeError, "Independent semantic verification failed"):
            self.close(SeqProvider({
                "reviser": [self.revision(chapter(CASE, DOOR), [technical, owed], [consequence])],
                "technical-editor": [{"verified": False, "findings": []}],
            }))
        self.assertFalse(self.rejected().exists())
        self.assertEqual(self.held(), [])


class StyleRevisionTests(SequenceFixture):
    def recheck(self, provider):
        return self.bf.recheck_style_closed_chapter(self.project, self.book, "CH-0001", self.contract, provider)

    def test_a_style_revision_goes_through_the_check_and_its_open_findings_reach_the_style_reviser(self):
        self.close(self.provider({}, [self.revision(chapter(CASE, DOOR))]))
        style_id = f"REVISE-STYLE-{self.book}-CH-0001"
        with self.assertRaisesRegex(self.bf.BookForgeError, "Sequence check left 1 findings open"):
            self.recheck(SeqProvider({"reviser": [self.revision(chapter(CASE, DOOR))]}, STUCK_READS))
        self.assertEqual(self.held(), [])
        self.assertEqual(self.task_state(style_id), "pending")
        self.assertTrue(self.rejected().exists())
        task = next(row for row in self.plan()["tasks"] if row["id"] == style_id)
        self.assertIn(f"books/{self.book}/reviews/CH-0001/sequence.json", task["outputs"])

        disposition = {"finding": "Q-0001", "action": "repaired", "evidence": "the year", "loss": "none", "supersedes": []}
        provider = SeqProvider({"reviser": [self.revision(chapter(CASE, DOOR), [disposition])]},
                               {"1-staging": [answer(finding("Q-01", DOOR, "She stood at the gate."))]})
        result = self.recheck(provider)
        self.assertEqual(result["state"], "style_revised")
        reviser = next(row["capsule"] for row in provider.envelopes if row["role"] == "reviser")
        self.assertEqual(reviser["mode"], "style-only")
        self.assertEqual([row["severity"] for row in reviser["findings"] if row["id"] == "Q-0001"], ["warning"])
        self.assertIn("She stood at the gate.", self.manuscript().read_text())
        record = self.record()
        self.assertEqual(record["after"], style_id)
        self.assertEqual(record["rounds"][0]["applied"], ["staging-Q-01"])
        self.assertEqual(self.task_state(style_id), "succeeded")
        self.assertFalse(self.rejected().exists())
        self.assertEqual(self.held(), [])


class BudgetTests(SequenceFixture):
    def test_a_retried_revision_and_a_later_closed_chapter_check_stay_within_the_budget(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.close(self.provider(STUCK_READS, [self.revision(chapter(CASE, DOOR))]))
        disposition = {"finding": "Q-0001", "action": "repaired", "evidence": "the year", "loss": "none", "supersedes": []}
        self.close(SeqProvider({"reviser": [self.revision(chapter(CASE, DOOR), [disposition])]}))
        self.bf.sequence_check_chapter(self.project, self.book, "CH-0001", provider=SeqProvider({}))
        report = self.bf.telemetry_report(self.project)
        self.assertEqual(report["by_role"]["sequence-checker"]["calls"], 11)
        self.assertEqual([row for row in report["violations"] if row["code"] == "chapter_call_budget"], [])


class KilledDuringTheCheckTests(SequenceFixture):
    """A process killed by SIGKILL while its revision is being checked raises
    nothing: the revision's claim is `running`, accepted, under a dead pid. The
    answer lived in that process only, so recovery settles it as failed, as it
    does a verification, and the next run claims the revision again."""

    def killed(self, work):
        pid = os.fork()
        if pid == 0:
            try:
                work()
            finally:
                os._exit(1)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL, status)

    def assert_recovered(self, task_id):
        self.assertIn((task_id, "running"), self.held())
        state = self.bf.recover_before_dispatch(self.project)
        self.assertEqual(state["needs_a_person"], [])
        attempts = [row for row in self.plan()["attempts"] if row["task"] == task_id]
        self.assertEqual(attempts[-1]["state"], "validation_failed")
        self.assertIn("sequence check", attempts[-1]["failure"])
        self.assertEqual(self.task_state(task_id), "pending")
        self.assertEqual(self.held(), [])
        self.assertNotIn("outcome_unknown", [row["state"] for row in self.plan()["attempts"]])

    def test_a_revision_killed_during_its_check_is_retried_without_a_person(self):
        self.killed(lambda: self.close(Killed({
            "cold-reader": [cold_answer()], "technical-editor": [{"findings": [], "consequences": []}],
            "reviser": [self.revision(chapter(CASE, DOOR))],
        })))
        self.assert_recovered(f"REVISE-{self.book}-CH-0001")
        result = self.bf.run_next(self.project, book_id=self.book, provider=SeqProvider({"reviser": [self.revision(chapter(CASE, DOOR))]}))
        self.assertEqual(result["state"], "closed")
        self.assertEqual(self.held(), [])

    def test_a_sequence_read_killed_after_its_answer_was_accepted_is_not_an_unknown_outcome(self):
        def work():
            def die(*args, **kwargs):
                os.kill(os.getpid(), signal.SIGKILL)

            self.bf._sequence_findings = die
            self.close(self.provider({}, [self.revision(chapter(CASE, DOOR))]))

        self.killed(work)
        accepted = [row for row in self.plan()["attempts"] if row["task"].startswith("SEQ-") and row.get("provider_accepted")]
        self.assertEqual(len(accepted), 1)
        self.assert_recovered(f"REVISE-{self.book}-CH-0001")
        seq = next(row for row in self.plan()["attempts"] if row["id"] == accepted[0]["id"])
        self.assertEqual(seq["state"], "validation_failed")

    def test_a_style_revision_killed_during_its_check_is_retried_without_a_person(self):
        self.close(self.provider({}, [self.revision(chapter(CASE, DOOR))]))
        self.killed(lambda: self.bf.recheck_style_closed_chapter(
            self.project, self.book, "CH-0001", self.contract, Killed({"reviser": [self.revision(chapter(CASE, DOOR))]})))
        self.assert_recovered(f"REVISE-STYLE-{self.book}-CH-0001")


class KilledDuringThePivotalCheckTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        self.book = self.bf.add_book(self.project, "Book")["id"]
        chapters = self.project / f"books/{self.book}/chapters"
        chapters.mkdir()
        (chapters / "CH-0001.json").write_text(json.dumps(with_engagement_fields({
            "schema": 1, "book": self.book, "id": "CH-0001", "order": 1,
            "pov": "CHR-0001", "beats": ["Choose"], "plants": [], "reveals": [],
            "target_words": 700, "imports": ["UNI-0001#kernel"], "pivotal": "finale",
        })))

    def test_a_pivotal_revision_killed_during_its_check_is_retried_without_a_person(self):
        class KilledPivotal(PivotalProvider):
            def __call__(inner, role, envelope, attempt_dir):
                if role == "sequence-checker":
                    os.kill(os.getpid(), signal.SIGKILL)
                return super().__call__(role, envelope, attempt_dir)

        pid = os.fork()
        if pid == 0:
            try:
                self.bf.produce_pivotal_chapter(self.project, self.book, "CH-0001", provider=KilledPivotal())
            finally:
                os._exit(1)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFSIGNALED(status), status)
        state = self.bf.recover_before_dispatch(self.project)
        self.assertEqual(state["needs_a_person"], [])
        plan = self.bf._load_plan(self.project)
        revise = [row for row in plan["attempts"] if row["task"] == f"REVISE-{self.book}-CH-0001"]
        self.assertEqual(revise[-1]["state"], "validation_failed")
        result = self.bf.run_next(self.project, book_id=self.book, provider=ReviewOnlyProvider())
        self.assertEqual(result["state"], "closed")


class LensTests(SequenceFixture):
    def setUp(self):
        super().setUp()
        real = self.bf.build_envelope

        def build_envelope(*args, prompt_role=None, **kwargs):
            # The extra lenses have no prompt file in the skill; they read the checker's.
            if prompt_role and prompt_role.startswith("lens-"):
                prompt_role = "sequence-checker"
            return real(*args, prompt_role=prompt_role, **kwargs)

        self.bf.build_envelope = build_envelope

    def test_the_findings_of_several_lenses_are_merged_in_lens_order(self):
        self.bf.SEQUENCE_FIRST_LENSES = ("sequence-checker", "lens-b")
        provider = self.provider({
            "1-sequence-checker": [answer(finding("Q-01", CASE, "Mara carried the bass case."))],
            "1-lens-b": [answer(finding("Q-01", CASE, "Mara left the bass case."), finding("Q-02", DOOR, "She stood at the gate."))],
        }, [self.revision(chapter(CASE, DOOR))])
        self.close(provider)
        reads = self.sequence_capsules(provider)
        first_round = [row for row in reads if row["task"].startswith(f"SEQ-{self.book}-CH-0001-1-")]
        self.assertEqual(sorted(row["task"] for row in first_round),
                         [f"SEQ-{self.book}-CH-0001-1-lens-b", f"SEQ-{self.book}-CH-0001-1-sequence-checker"])
        self.assertEqual(first_round[0]["capsule"]["prose"], first_round[1]["capsule"]["prose"])
        merged = self.record()["rounds"][0]
        self.assertEqual([row["id"] for row in merged["findings"]],
                         ["sequence-checker-Q-01", "lens-b-Q-01", "lens-b-Q-02"])
        # Applied after both answered, each against the text as it then stood: the
        # second lens's edit of the same sentence no longer finds it.
        self.assertEqual(merged["applied"], ["sequence-checker-Q-01", "lens-b-Q-02"])
        self.assertEqual(merged["unresolved"], ["lens-b-Q-01"])
        self.assertEqual(merged["cost"], 0.002)
        text = self.manuscript().read_text()
        self.assertIn("Mara carried the bass case.", text)
        self.assertIn("She stood at the gate.", text)
        self.assertEqual(self.held(), [])

    def test_no_more_than_two_lenses_are_asked_at_once(self):
        state = {"now": 0, "most": 0, "calls": 0}
        guard = threading.Lock()
        # The first batch's two calls must be in flight together: a round that asked
        # them one after the other breaks the barrier instead of passing by timing.
        together = threading.Barrier(2, timeout=10)

        class Slow(RoleProvider):
            def __call__(inner, role, envelope, attempt_dir):
                if role != "sequence-checker":
                    return super().__call__(role, envelope, attempt_dir)
                with guard:
                    state["now"] += 1
                    state["most"] = max(state["most"], state["now"])
                    index = state["calls"]
                    state["calls"] += 1
                if index < 2:
                    together.wait()
                time.sleep(0.05)
                with guard:
                    state["now"] -= 1
                return {"text": json.dumps(CLEAN), "provider": "openrouter", "model": HYDROGEN, "variant": "high",
                        "session_id": "ses-lens", "tokens": {"input": 10, "output": 10}, "cost": 0.0,
                        "latency_ms": 1, "finish": "stop"}

        self.close(Slow({"cold-reader": [cold_answer()], "technical-editor": [{"findings": [], "consequences": []}],
                         "reviser": [self.revision(chapter(CASE, DOOR))]}))
        self.assertEqual(state["most"], 2)
        self.assertEqual(state["calls"], 3)
        self.assertTrue(self.manuscript().is_file())


class ClosedChapterTests(SequenceFixture):
    def test_revise_sequence_edits_the_manuscript_journals_and_adopts(self):
        self.close(self.provider({}, [self.revision(chapter(CASE, DOOR))]))
        before = self.manuscript().read_text()
        stuck = finding("Q-02", "a sentence the chapter never had", "x", kind="timeline")
        provider = self.provider({
            "1-staging": [answer(finding("Q-01", CASE, "Mara had the bass case already."), stuck)],
            "2": [answer(stuck)], "3": [answer(stuck)],
        }, [])
        result = self.bf.sequence_check_chapter(self.project, self.book, "CH-0001", provider=provider)
        after = self.manuscript().read_text()
        self.assertNotEqual(before, after)
        self.assertIn("Mara had the bass case already.", after)
        self.assertEqual(result["applied"], ["1:staging-Q-01"])
        self.assertEqual([row["id"] for row in result["open"]], ["Q-02"])
        journal = [json.loads(line) for line in (self.project / ".book-forge/sequence-repairs.jsonl").read_text().splitlines()]
        self.assertEqual([(row["finding"], row["old"], row["new"]) for row in journal],
                         [("staging-Q-01", CASE, "Mara had the bass case already.")])
        adopted = [json.loads(line) for line in (self.project / ".book-forge/adopted.jsonl").read_text().splitlines()]
        self.assertEqual(adopted[-1]["artifact"], f"SOURCE-{self.book}-CH-0001")
        self.assertEqual(adopted[-1]["reason"], "sequence check")
        self.assertEqual(self.bf.reconcile_artifacts(self.project), [])
        self.assertEqual(self.held(), [])

    def test_a_failure_in_a_later_round_keeps_what_the_earlier_round_applied(self):
        self.close(self.provider({}, [self.revision(chapter(CASE, DOOR))]))
        provider = self.provider({
            "1-staging": [answer(finding("Q-01", CASE, "Mara had the bass case already."))],
            "2": [RuntimeError("the provider went away")] * 3,
        }, [])
        with self.assertRaisesRegex(RuntimeError, "the provider went away"):
            self.bf.sequence_check_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertIn("Mara had the bass case already.", self.manuscript().read_text())
        journal = [json.loads(line) for line in (self.project / ".book-forge/sequence-repairs.jsonl").read_text().splitlines()]
        self.assertEqual([row["finding"] for row in journal], ["staging-Q-01"])
        adopted = [json.loads(line) for line in (self.project / ".book-forge/adopted.jsonl").read_text().splitlines()]
        self.assertEqual(adopted[-1]["reason"], "sequence check")
        self.assertEqual(self.bf.reconcile_artifacts(self.project), [])
        self.assertEqual(self.held(), [])

    def test_a_clean_closed_chapter_is_left_untouched(self):
        self.close(self.provider({}, [self.revision(chapter(CASE, DOOR))]))
        before = self.manuscript().read_bytes()
        result = self.bf.sequence_check_chapter(self.project, self.book, "CH-0001", provider=self.provider({}, []))
        self.assertEqual(self.manuscript().read_bytes(), before)
        self.assertEqual((result["applied"], result["open"], result["rounds"]), ([], [], 1))
        self.assertFalse((self.project / ".book-forge/sequence-repairs.jsonl").exists())

    def test_the_command_line_takes_the_flag_and_refuses_it_beside_a_note(self):
        args = self.bf.build_parser().parse_args(["revise", "--book", self.book, "--chapter", "CH-0001", "--sequence"])
        self.assertTrue(args.sequence)
        code = self.bf.main(["--project", str(self.project), "revise", "--book", self.book, "--chapter", "CH-0001", "--sequence", "--note", "x"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
