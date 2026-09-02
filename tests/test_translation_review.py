import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"
GLM = "openrouter/z-ai/glm-5.3-flash"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_translation_review", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SOURCE = "# The Dawn Barge\n\n" + "She chewed tide-chalk on the tower and the Faith counted lamps. " * 12


class ScriptedProvider:
    """Answers as whatever the envelope says will answer it, per role."""

    def __init__(self, translations, critic=None):
        self.translations = list(translations)
        self.critic = critic
        self.calls = []

    def __call__(self, role, envelope, attempt_dir):
        payload = envelope["payload"]
        self.calls.append(role)
        if role == "translation-critic":
            text = json.dumps(self.critic if self.critic is not None else {"findings": [], "verdict": "faithful"})
        else:
            text = self.translations.pop(0)
        return {
            "text": text,
            "provider": "openrouter",
            "model": payload["model"],
            "variant": payload["variant"],
            "session_id": f"ses-{len(self.calls)}",
            "tokens": {"input": envelope["estimated_input_tokens"], "output": 400},
            "cost": 0.001,
            "latency_ms": 50,
            "finish": "stop",
        }


def translation(body, boundary="La sera finisce."):
    return json.dumps({
        "translated_markdown": f"# La chiatta dell'alba\n\n{body}",
        "glossary_updates": [],
        "boundary": boundary,
    })


GOOD_BODY = "Masticava gesso di marea sulla torre e la Fede contava le lampade. " * 12
CALQUE_BODY = "Masticava calcare sulla torre e la Chiesa contava le lampade. " * 12
FORBIDDEN_BODY = "Binta stette sulla torre con il gesso di marea e la Fede contava. " * 12


class TranslationReviewFixture(unittest.TestCase):
    """The prose has a review stack — cold reader, technical editor, four style
    reviewers, reviser. A translation had one call and nobody read it, and
    landfall's Italian shipped `Binta stette` and a word-by-word idiom."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "Book")["id"]
        chapters = self.project / f"books/{self.book}/chapters"
        chapters.mkdir(exist_ok=True)
        self.contract = {
            "schema": 1, "book": self.book, "id": "CH-0001", "order": 1, "pov": "CHR-0001",
            "beats": ["Find the signal"], "plants": [], "reveals": [], "target_words": 120,
            "imports": [], "pivotal": None, "title": "The Dawn Barge",
        }
        (chapters / "CH-0001.json").write_text(json.dumps(self.contract))
        manuscript = self.project / f"books/{self.book}/manuscript/chapters"
        manuscript.mkdir(parents=True, exist_ok=True)
        (manuscript / "CH-0001.md").write_text(SOURCE, encoding="utf-8")
        self.bf.add_translation(self.project, self.book, "it")
        self.locale_root = self.project / f"books/{self.book}/translations/it"
        (self.locale_root / "style.md").write_text(
            "---\nid: S\n---\n\n<!-- bf:block style -->\nImperfetto come tempo di base. Caporali per i dialoghi.\n",
            encoding="utf-8",
        )
        (self.locale_root / "glossary.md").write_text(
            "---\nid: G\n---\n\n<!-- bf:block terms -->\n"
            "- **tide-chalk** → gesso di marea — fixed term.\n"
            "- **the Faith** → la Fede — the institutional religion.\n",
            encoding="utf-8",
        )
        # The critic may never be the translator, and the fixture pins both.
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["roles"] = {"translator": {"model": GLM, "variant": "high"}}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

    def checks(self, forbidden):
        self.bf._write_json(self.locale_root / "checks.yaml", {"schema": 1, "locale": "it", "forbidden": forbidden})

    def translate(self, provider):
        return self.bf.translate_next(self.project, self.book, "it", provider=provider, run_all=False)


class WhatCostsNoModelCallTests(TranslationReviewFixture):
    def test_a_forbidden_form_is_caught_before_the_translation_is_accepted(self):
        self.checks([{"pattern": r"\bstette\b", "reason": "usa l'imperfetto"}])
        provider = ScriptedProvider([translation(FORBIDDEN_BODY), translation(GOOD_BODY)])
        self.translate(provider)
        self.assertEqual(provider.calls.count("translator"), 2, "the first answer must be sent back for repair")
        self.assertNotIn("stette", (self.locale_root / "chapters" / "CH-0001.md").read_text())

    def test_a_locale_with_no_checks_file_still_translates(self):
        provider = ScriptedProvider([translation(GOOD_BODY)])
        self.translate(provider)
        self.assertTrue((self.locale_root / "chapters" / "CH-0001.md").is_file())

    def test_a_dropped_glossary_term_is_found_without_asking_anyone(self):
        glossary = (self.locale_root / "glossary.md").read_text()
        found = self.bf._glossary_compliance(SOURCE, f"# T\n\n{CALQUE_BODY}", glossary)
        self.assertEqual(len(found), 2)
        self.assertTrue(any("tide-chalk" in row for row in found))
        self.assertTrue(any("the Faith" in row for row in found))

    def test_a_rendering_that_is_there_but_inflected_is_not_a_finding(self):
        glossary = (self.locale_root / "glossary.md").read_text()
        inflected = "# T\n\nMasticava i gessi di marea mentre la Fede contava."
        self.assertEqual(self.bf._glossary_compliance(SOURCE, inflected, glossary), [])


class WhatTheGlossaryCheckFlagsTests(TranslationReviewFixture):
    """On landfall's three chapters the check reported twelve missing terms and was
    wrong about seven, in four distinct ways. Advice nobody can trust is advice
    nobody reads, and the repair it drives is paid for either way."""

    GLOSSARY = (
        "- **the shore ledger** → il registro di riva — fixed.\n"
        "- **fen-hand** → mano della palude — fixed.\n"
        "- **mirror-road relays** → i ripetitori a specchio (via degli specchi) — fixed.\n"
        "- **wind / foggia — the boatman's rig** → la foggia — malformed row.\n"
    )

    def flag(self, source, translated):
        return self.bf._glossary_compliance(source, translated, self.GLOSSARY)

    def test_a_contracted_article_still_satisfies_the_row(self):
        """The row says `il registro di riva`; Italian writes `del registro di riva`."""
        self.assertEqual(self.flag("The shore ledger was open.", "Il testo del registro di riva era aperto."), [])

    def test_a_four_letter_word_inflects_when_the_term_has_more_than_one(self):
        """`mano della palude` must recognise `mani della palude`."""
        self.assertEqual(self.flag("A fen-hand waited.", "Le mani della palude aspettavano."), [])

    def test_a_parenthetical_gloss_is_not_part_of_the_rendering(self):
        self.assertEqual(self.flag("The mirror-road relays woke.", "I ripetitori a specchio si svegliarono."), [])

    def test_a_row_whose_braces_swallow_its_note_is_not_read_as_a_term(self):
        """`**wind / foggia — the boatman's rig**` made `wind` a glossary term."""
        self.assertNotIn("wind", [row[0][0] for row in self.bf._glossary_terms(self.GLOSSARY)])
        self.assertEqual(self.flag("The wind rose off the water.", "Il vento si alzava dall'acqua."), [])

    def test_a_term_the_translation_really_drops_is_still_reported(self):
        found = self.flag("A fen-hand waited by the shore ledger.", "Qualcuno aspettava accanto al libro.")
        self.assertEqual(len(found), 2)

    def test_a_short_word_is_not_satisfied_by_a_longer_one_that_starts_with_it(self):
        """An open tail read `watch-lieutenancy` as `watch-lieutenant` and called a
        correct rendering of the office a missing rendering of the person."""
        glossary = "- **the oar** → remo — fixed.\n"
        self.assertEqual(self.bf._glossary_compliance("The oar dipped.", "Il remo si immerse.", glossary), [])
        self.assertEqual(len(self.bf._glossary_compliance("The oar dipped.", "Un passato remoto.", glossary)), 1)

    def test_a_derived_word_is_not_the_term(self):
        glossary = "- **watch-lieutenant** → il tenente di ronda — fixed.\n"
        self.assertEqual(
            self.bf._glossary_compliance("He knew the watch-lieutenancy.", "Conosceva la tenenza di ronda.", glossary),
            [],
            "the source says lieutenancy, which is not the term the row fixes",
        )


class WhatTheCriticIsForTests(TranslationReviewFixture):
    def critic(self, findings, verdict="repairable"):
        return {"findings": findings, "verdict": verdict}

    def calque_finding(self):
        return {
            "id": "01", "severity": "warning", "kind": "calque",
            "source": "kept her lungs from forgetting",
            "translated": "teneva i suoi polmoni dal dimenticare",
            "rule": "Contro il calco",
            "issue": "resa parola per parola",
            "fix": "impediva ai polmoni di dimenticare",
        }

    def test_a_cited_finding_drives_one_repair_and_the_repair_is_kept(self):
        provider = ScriptedProvider(
            [translation(CALQUE_BODY), translation(GOOD_BODY)],
            critic=self.critic([self.calque_finding()]),
        )
        self.translate(provider)
        self.assertEqual(provider.calls, ["translator", "translation-critic", "translator"])
        self.assertIn("gesso di marea", (self.locale_root / "chapters" / "CH-0001.md").read_text())

    def test_a_finding_that_quotes_nothing_is_set_aside_and_drives_no_repair(self):
        vague = {"id": "01", "severity": "warning", "kind": "style", "issue": "si potrebbe migliorare"}
        provider = ScriptedProvider([translation(GOOD_BODY)], critic=self.critic([vague]))
        self.translate(provider)
        self.assertEqual(provider.calls, ["translator", "translation-critic"])
        review = json.loads((self.locale_root / "reviews" / "CH-0001.json").read_text())
        self.assertEqual(len(review["set_aside"]), 1)
        self.assertEqual(review["findings"], [])

    def test_a_note_alone_is_recorded_and_costs_no_repair(self):
        note = {**self.calque_finding(), "severity": "note"}
        provider = ScriptedProvider([translation(GOOD_BODY)], critic=self.critic([note]))
        self.translate(provider)
        self.assertEqual(provider.calls, ["translator", "translation-critic"])

    def test_a_repair_refused_once_is_asked_again_and_the_second_one_lands(self):
        """CH-0003's repair came back carrying a forbidden form, was rightly refused,
        and took thirteen findings — ten of them meaning — down with it."""
        self.checks([{"pattern": r"\bvolle\b", "reason": "forma che ferma il lettore"}])
        bad = translation("Volle il gesso di marea e la Fede contava. " * 12)
        provider = ScriptedProvider(
            [translation(CALQUE_BODY), bad, translation(GOOD_BODY)],
            critic=self.critic([self.calque_finding()]),
        )
        self.translate(provider)
        self.assertEqual(provider.calls.count("translator"), 3, "one translation and two repair attempts")
        text = (self.locale_root / "chapters" / "CH-0001.md").read_text()
        self.assertIn("gesso di marea", text)
        self.assertNotIn("Volle", text)

    def test_the_second_ask_carries_why_the_first_was_refused(self):
        self.checks([{"pattern": r"\bvolle\b", "reason": "forma che ferma il lettore"}])
        captured = []

        class Capturing(ScriptedProvider):
            def __call__(self, role, envelope, attempt_dir):
                captured.append(envelope["payload"]["task"])
                return super().__call__(role, envelope, attempt_dir)

        provider = Capturing(
            [translation(CALQUE_BODY), translation("Volle il gesso di marea e la Fede contava. " * 12), translation(GOOD_BODY)],
            critic=self.critic([self.calque_finding()]),
        )
        self.translate(provider)
        last = captured[-1]
        self.assertIn("refused", last["repair"])
        self.assertIn("olle", last["repair"]["refused"]["why_the_last_repair_was_rejected"].lower())

    def test_a_repair_refused_every_time_leaves_the_translation_and_records_the_findings(self):
        kept = translation(GOOD_BODY)
        refusals = ["not a contract at all"] * self.bf.CRITIC_ATTEMPTS
        provider = ScriptedProvider([kept, *refusals], critic=self.critic([self.calque_finding()]))
        self.translate(provider)
        text = (self.locale_root / "chapters" / "CH-0001.md").read_text()
        self.assertIn("gesso di marea", text)
        self.assertNotIn("not a contract", text)
        unapplied = json.loads((self.locale_root / "reviews" / "CH-0001.unapplied.json").read_text())
        self.assertEqual(len(unapplied["unapplied"]), 1)
        self.assertEqual(unapplied["unapplied"][0]["kind"], "calque")

    def test_an_unreadable_answer_is_asked_again_and_the_second_one_counts(self):
        """The critic's output is the most structured this engine asks for, so it is
        the likeliest to come back malformed, and it was the only role asked once."""

        class OnceUnreadable(ScriptedProvider):
            answers = 0

            def __call__(self, role, envelope, attempt_dir):
                if role == "translation-critic":
                    OnceUnreadable.answers += 1
                    if OnceUnreadable.answers == 1:
                        payload = dict(envelope["payload"])
                        self.calls.append(role)
                        return {
                            "text": "Here is my reading, in prose, with no object at all.",
                            "provider": "openrouter", "model": payload["model"], "variant": payload["variant"],
                            "session_id": "ses-bad", "tokens": {"input": 1, "output": 1},
                            "cost": 0.0, "latency_ms": 1, "finish": "stop",
                        }
                return super().__call__(role, envelope, attempt_dir)

        OnceUnreadable.answers = 0
        provider = OnceUnreadable(
            [translation(CALQUE_BODY), translation(GOOD_BODY)],
            critic={"findings": [self.calque_finding()], "verdict": "repairable"},
        )
        self.translate(provider)
        self.assertEqual(provider.calls.count("translation-critic"), 2)
        review = json.loads((self.locale_root / "reviews" / "CH-0001.json").read_text())
        self.assertEqual(review["set_aside"], [])
        self.assertTrue(review["findings"])

    def test_a_chapter_the_critic_never_reads_does_not_stop_the_next_one(self):
        """CH-0002's failure blocked the run and CH-0003 died on a dispatch refusal
        that had nothing to do with CH-0003."""
        second = {"schema": 1, "book": self.book, "id": "CH-0002", "order": 2, "pov": "CHR-0001",
                  "beats": ["Wait"], "plants": [], "reveals": [], "target_words": 120,
                  "imports": [], "pivotal": None, "title": "The Blue Tear"}
        (self.project / f"books/{self.book}/chapters/CH-0002.json").write_text(json.dumps(second))
        (self.project / f"books/{self.book}/manuscript/chapters/CH-0002.md").write_text(SOURCE, encoding="utf-8")
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["translation"] = {"review": False}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.translate(ScriptedProvider([translation(GOOD_BODY)]))
        self.translate(ScriptedProvider([translation(GOOD_BODY)]))
        config.pop("translation")
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

        class BlindOnFirst(ScriptedProvider):
            def __call__(self, role, envelope, attempt_dir):
                if role == "translation-critic" and envelope["payload"]["task"]["chapter"] == "CH-0001":
                    self.calls.append(role)
                    payload = envelope["payload"]
                    return {
                        "text": "no object here either", "provider": "openrouter",
                        "model": payload["model"], "variant": payload["variant"],
                        "session_id": "ses-bad", "tokens": {"input": 1, "output": 1},
                        "cost": 0.0, "latency_ms": 1, "finish": "stop",
                    }
                return super().__call__(role, envelope, attempt_dir)

        provider = BlindOnFirst([translation(GOOD_BODY)], critic={"findings": [], "verdict": "faithful"})
        report = self.bf.review_translation(self.project, self.book, "it", provider=provider)
        by_chapter = {row["chapter"]: row for row in report["reviewed"]}
        self.assertEqual(by_chapter["CH-0001"]["verdict"], "unread")
        self.assertEqual(by_chapter["CH-0002"]["verdict"], "faithful")

    def test_a_critic_that_cannot_be_read_never_stops_the_translation(self):
        class BrokenCritic(ScriptedProvider):
            def __call__(self, role, envelope, attempt_dir):
                if role == "translation-critic":
                    raise self.bf_error("the critic produced nothing")
                return super().__call__(role, envelope, attempt_dir)

        BrokenCritic.bf_error = self.bf.BookForgeError
        provider = BrokenCritic([translation(GOOD_BODY)])
        self.translate(provider)
        self.assertTrue((self.locale_root / "chapters" / "CH-0001.md").is_file())

    def test_a_full_set_of_quoted_findings_is_parsed_and_repaired(self):
        """Landfall's first critic answer was cut mid-string at 3000 tokens and the
        whole pass was lost. Every finding carries three quotes, so twelve of them
        must fit the budget the call is given."""
        findings = [
            {
                "id": f"{index:02d}", "severity": "warning", "kind": "calque",
                "source": "kept her lungs from forgetting " * 6,
                "translated": "teneva i suoi polmoni dal dimenticare " * 6,
                "rule": "Contro il calco, sezione dello stile della localizzazione",
                "issue": "resa parola per parola " * 6,
                "fix": "impediva ai polmoni di dimenticare " * 6,
            }
            for index in range(1, 13)
        ]
        provider = ScriptedProvider(
            [translation(CALQUE_BODY), translation(GOOD_BODY)],
            critic=self.critic(findings),
        )
        self.translate(provider)
        self.assertEqual(provider.calls, ["translator", "translation-critic", "translator"])
        review = json.loads((self.locale_root / "reviews" / "CH-0001.json").read_text())
        self.assertEqual(len(review["findings"]), 12 + 2, "twelve cited findings plus the two the glossary found")
        self.assertEqual(review["set_aside"], [])

    def test_the_critic_is_given_room_for_a_full_answer(self):
        self.assertGreaterEqual(self.bf.ROLE_BUDGETS["translation-critic"][1], 9000)

    def test_the_review_can_be_switched_off(self):
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["translation"] = {"review": False}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        provider = ScriptedProvider([translation(GOOD_BODY)])
        self.translate(provider)
        self.assertEqual(provider.calls, ["translator"])


class TheChecksAreScoredByTheReaderTheyFeedTests(TranslationReviewFixture):
    """On landfall's three chapters the glossary check raised twelve findings and
    was right about five, and that number was counted by hand."""

    def review(self, machine_verdicts, translated_body=CALQUE_BODY):
        self.translate(ScriptedProvider([translation(translated_body)], critic={"findings": [], "verdict": "faithful"}))             if False else None
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["translation"] = {"review": False}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.translate(ScriptedProvider([translation(translated_body)]))
        config.pop("translation")
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        provider = ScriptedProvider(
            [translation(GOOD_BODY)],
            critic={"findings": [], "machine_findings": machine_verdicts, "verdict": "faithful"},
        )
        report = self.bf.review_translation(self.project, self.book, "it", provider=provider)
        return report, provider

    def test_a_finding_the_critic_calls_mistaken_never_reaches_the_repair(self):
        """`trestle` is a work stand in one sentence and a jetty in the row that
        fixes it: a string rule cannot tell the senses apart and the reader can."""
        report, provider = self.review([
            {"id": "G-01", "verdict": "mistaken", "why": "il termine c'e', in altra forma"},
            {"id": "G-02", "verdict": "mistaken", "why": "la riga fissa un altro senso della parola"},
        ])
        self.assertEqual(provider.calls, ["translation-critic"], "no repair was asked for")
        self.assertFalse(report["reviewed"][0]["repaired"])

    def test_a_finding_the_critic_upholds_still_drives_the_repair(self):
        report, provider = self.review([{"id": "G-01", "verdict": "holds", "why": "manca davvero"}])
        self.assertEqual(provider.calls, ["translation-critic", "translator"])
        self.assertTrue(report["reviewed"][0]["repaired"])

    def test_silence_on_a_finding_is_not_a_refutation(self):
        report, provider = self.review([])
        self.assertEqual(report["reviewed"][0]["machine_checks"]["mistaken"], 0)
        self.assertEqual(
            report["reviewed"][0]["machine_checks"]["held"],
            report["reviewed"][0]["machine_checks"]["raised"],
        )

    def test_the_counts_land_in_the_review_file_and_in_the_report(self):
        report, _ = self.review([{"id": "G-01", "verdict": "mistaken", "why": "c'e' gia'"}])
        row = report["reviewed"][0]
        self.assertEqual(row["machine_checks"]["mistaken"], 1)
        self.assertEqual(report["machine_checks"]["raised"], row["machine_checks"]["raised"])
        review = json.loads((self.locale_root / "reviews" / "CH-0001.json").read_text())
        self.assertEqual(review["machine_findings"]["mistaken"], 1)
        self.assertEqual(review["mistaken"][0]["why"], "c'e' gia'")

    def test_the_scorer_holds_what_nobody_ruled_on(self):
        machine = [{"id": "G-01", "rule": "r", "issue": "i"}, {"id": "G-02", "rule": "r", "issue": "i"}]
        held, mistaken, score = self.bf._score_machine_findings(machine, [{"id": "G-01", "verdict": "mistaken"}])
        self.assertEqual([row["id"] for row in held], ["G-02"])
        self.assertEqual(score, {"raised": 2, "held": 1, "mistaken": 1})
        held, mistaken, score = self.bf._score_machine_findings(machine, "not a list at all")
        self.assertEqual(len(held), 2, "an answer nobody can read refutes nothing")


class WhenAReviewIsFinishedTests(TranslationReviewFixture):
    """CH-0001 was read back four times and returned 17 findings, then 6, then 12,
    the last twelve all `meaning` on a chapter whose verdict in the same answer
    was `faithful`. Nobody could say whether that was three improvements or three
    inventions, and the decision to stop reading was made by feel."""

    def setUp(self):
        super().setUp()
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["translation"] = {"review": False}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.translate(ScriptedProvider([translation(GOOD_BODY)]))
        config.pop("translation")
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

    def finding(self, index, kind="calque", severity="warning"):
        return {
            "id": f"{index:02d}", "severity": severity, "kind": kind,
            "source": f"source span {index}", "translated": f"resa numero {index}",
            "rule": "Contro il calco", "issue": "resa parola per parola", "fix": "una resa migliore",
        }

    class Cycling:
        """Answers every translator call with fresh valid prose and every critic
        call with whatever the script says for that pass."""

        def __init__(self, outer, critic_answers):
            self.outer = outer
            self.critic_answers = list(critic_answers)
            self.calls = []

        def __call__(self, role, envelope, attempt_dir):
            payload = envelope["payload"]
            self.calls.append(role)
            if role == "translation-critic":
                answer = self.critic_answers.pop(0) if self.critic_answers else {"findings": [], "verdict": "faithful"}
                text = json.dumps(answer)
            else:
                text = translation(GOOD_BODY + "Ancora. " * (len(self.calls) % 3))
            return {
                "text": text, "provider": "openrouter", "model": payload["model"], "variant": payload["variant"],
                "session_id": f"ses-{len(self.calls)}", "tokens": {"input": 1, "output": 1},
                "cost": 0.0, "latency_ms": 1, "finish": "stop",
            }

    def run_until_clean(self, critic_answers):
        provider = self.Cycling(self, critic_answers)
        report = self.bf.review_translation(self.project, self.book, "it", provider=provider, until_clean=True)
        return report["reviewed"][0], provider

    def test_a_chapter_with_nothing_to_act_on_converges_in_one_pass(self):
        row, provider = self.run_until_clean([{"findings": [], "verdict": "faithful"}])
        self.assertEqual(row["ended"], "clean")
        self.assertTrue(row["converged"])
        self.assertEqual(row["passes"], 1)
        self.assertEqual(provider.calls.count("translator"), 0, "nothing to repair")

    def test_two_passes_at_the_same_count_stop_as_no_progress(self):
        same = {"findings": [self.finding(1), self.finding(2)], "verdict": "repairable"}
        row, provider = self.run_until_clean([same, same, same, same])
        self.assertEqual(row["ended"], "no-progress")
        self.assertEqual(row["passes"], 2)
        self.assertIn("the pass before found 2", row["why"])

    def test_a_finding_that_comes_back_after_a_claimed_repair_is_named(self):
        same = {"findings": [self.finding(1), self.finding(2)], "verdict": "repairable"}
        self.run_until_clean([same, same])
        state = json.loads((self.locale_root / "reviews" / "CH-0001.state.json").read_text())
        self.assertEqual(len(state["not_landed"]), 2)
        self.assertEqual(state["state"], "no-progress")

    def test_a_faithful_verdict_beside_a_meaning_finding_is_inconsistent(self):
        contradiction = {"findings": [self.finding(1, kind="meaning")], "verdict": "faithful"}
        row, provider = self.run_until_clean([contradiction, {"findings": [], "verdict": "faithful"}])
        self.assertTrue(row["verdict_inconsistent"] or json.loads(
            (self.locale_root / "reviews" / "CH-0001.json").read_text())["convergence"]["verdict_inconsistent"])
        self.assertGreaterEqual(provider.calls.count("translator"), 1, "the finding is still acted on")

    def test_the_cap_ends_a_chapter_that_never_converges(self):
        self.bf.REVIEW_PASS_CAP = 3
        answers = [
            {"findings": [self.finding(i) for i in range(1, 5)], "verdict": "repairable"},
            {"findings": [self.finding(i) for i in range(5, 8)], "verdict": "repairable"},
            {"findings": [self.finding(i) for i in range(8, 10)], "verdict": "repairable"},
        ]
        row, _ = self.run_until_clean(answers)
        self.assertEqual(row["ended"], "cap")
        self.assertEqual(row["passes"], 3)
        self.assertFalse(row["converged"])

    def test_a_single_pass_is_still_the_default(self):
        provider = self.Cycling(self, [{"findings": [self.finding(1)], "verdict": "repairable"}])
        report = self.bf.review_translation(self.project, self.book, "it", provider=provider)
        self.assertEqual(report["reviewed"][0]["passes"], 1)


class ReadingBackWhatIsAlreadyTranslatedTests(TranslationReviewFixture):
    def setUp(self):
        super().setUp()
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["translation"] = {"review": False}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.translate(ScriptedProvider([translation(CALQUE_BODY)]))
        config.pop("translation")
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

    def test_a_chapter_translated_before_the_critic_existed_is_still_read(self):
        provider = ScriptedProvider(
            [translation(GOOD_BODY)],
            critic={"findings": [{
                "id": "01", "severity": "warning", "kind": "glossary",
                "source": "tide-chalk", "translated": "calcare",
                "rule": "the locale glossary", "issue": "termine non reso", "fix": "gesso di marea",
            }], "verdict": "repairable"},
        )
        report = self.bf.review_translation(self.project, self.book, "it", provider=provider)
        row = report["reviewed"][0]
        self.assertEqual(row["chapter"], "CH-0001")
        self.assertTrue(row["repaired"])
        self.assertIn("gesso di marea", (self.locale_root / "chapters" / "CH-0001.md").read_text())

    def test_the_glossary_findings_are_counted_even_when_the_critic_is_silent(self):
        provider = ScriptedProvider([translation(GOOD_BODY)], critic={"findings": [], "verdict": "faithful"})
        report = self.bf.review_translation(self.project, self.book, "it", provider=provider)
        self.assertEqual(report["reviewed"][0]["by_kind"]["glossary"], 2)

    def test_a_rule_written_after_the_translation_still_reaches_it(self):
        """The first real review left `su la scala` standing: the locale's rules ran
        only while a chapter was being translated, and this chapter already was."""
        self.checks([{"pattern": r"\bsu la\b", "reason": "preposizione non articolata: sulla"}])
        path = self.locale_root / "chapters" / "CH-0001.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n\nLampade su la scala del porto.\n", encoding="utf-8")
        provider = ScriptedProvider([translation(GOOD_BODY)], critic={"findings": [], "verdict": "faithful"})
        report = self.bf.review_translation(self.project, self.book, "it", provider=provider)
        row = report["reviewed"][0]
        self.assertGreaterEqual(row["by_kind"].get("style", 0), 1)
        self.assertTrue(row["repaired"])
        self.assertNotIn("su la scala", path.read_text(encoding="utf-8"))

    def test_a_chapter_can_be_read_back_more_than_once(self):
        """The second review of landfall's CH-0001 produced its finding and could
        not act on it: the task from the first review had already succeeded."""
        first = ScriptedProvider([translation(GOOD_BODY)], critic={"findings": [], "verdict": "faithful"})
        self.bf.review_translation(self.project, self.book, "it", provider=first)
        self.checks([{"pattern": r"\bsu la\b", "reason": "preposizione non articolata"}])
        path = self.locale_root / "chapters" / "CH-0001.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n\nLampade su la scala.\n", encoding="utf-8")
        second = ScriptedProvider([translation(GOOD_BODY)], critic={"findings": [], "verdict": "faithful"})
        report = self.bf.review_translation(self.project, self.book, "it", provider=second)
        self.assertIn("translation-critic", second.calls)
        self.assertTrue(report["reviewed"][0]["repaired"])
        self.assertNotIn("su la scala", path.read_text(encoding="utf-8"))

    def test_it_refuses_a_locale_with_nothing_translated(self):
        self.bf.add_translation(self.project, self.book, "fr")
        (self.project / f"books/{self.book}/translations/fr/style.md").write_text(
            "---\nid: S\n---\n\n<!-- bf:block style -->\nRegistre courant.\n", encoding="utf-8")
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.review_translation(self.project, self.book, "fr", provider=ScriptedProvider([]))


class AChapterThatWasNotReadTests(TranslationReviewFixture):
    """Two consecutive reviews of landfall's CH-0001 failed all three asks apiece.
    The route said so — `verdict: unread`, `converged: false`, `set_aside: 1` — and
    the state file written beside the chapter said `clean`, reason `nothing left to
    act on`, about a chapter nobody had read. That file is what the next pass
    compares against and what anyone reading the repository is told."""

    def setUp(self):
        super().setUp()
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["translation"] = {"review": False}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.translate(ScriptedProvider([translation(GOOD_BODY)]))
        config.pop("translation")
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

    def finding(self, index):
        return {
            "id": f"{index:02d}", "severity": "warning", "kind": "calque",
            "source": f"source span {index}", "translated": f"resa numero {index}",
            "rule": "Contro il calco", "issue": "resa parola per parola", "fix": "una resa migliore",
        }

    class Answering:
        """Critic answers in order. A plain string is returned verbatim, which is
        what a model that spent its whole ceiling on reasoning leaves behind."""

        def __init__(self, critic_answers):
            self.critic_answers = list(critic_answers)
            self.calls = []

        def __call__(self, role, envelope, attempt_dir):
            payload = envelope["payload"]
            self.calls.append(role)
            if role == "translation-critic":
                answer = self.critic_answers.pop(0) if self.critic_answers else {"findings": [], "verdict": "faithful"}
                text = answer if isinstance(answer, str) else json.dumps(answer)
            else:
                text = translation(GOOD_BODY + "Ancora. " * (len(self.calls) % 3))
            return {
                "text": text, "provider": "openrouter", "model": payload["model"], "variant": payload["variant"],
                "session_id": f"ses-{len(self.calls)}", "tokens": {"input": 1, "output": 1},
                "cost": 0.0, "latency_ms": 1, "finish": "stop",
            }

    NOTHING = "Ho riletto a lungo il capitolo e non sono arrivato a una conclusione."

    def review(self, critic_answers):
        provider = self.Answering(critic_answers)
        report = self.bf.review_translation(self.project, self.book, "it", provider=provider)
        return report["reviewed"][0], provider

    def state(self):
        return json.loads((self.locale_root / "reviews" / "CH-0001.state.json").read_text())

    def test_three_failed_asks_leave_unread_on_disk_and_the_earlier_fingerprints(self):
        self.review([{"findings": [self.finding(1), self.finding(2)], "verdict": "repairable"}])
        read = self.state()
        self.assertEqual(len(read["fingerprints"]), 2)

        row, provider = self.review([self.NOTHING, self.NOTHING, self.NOTHING])
        self.assertEqual(row["verdict"], "unread")
        self.assertEqual(provider.calls.count("translation-critic"), 3)

        after = self.state()
        self.assertEqual(after["state"], "unread", "a chapter nobody read is not a chapter that is clean")
        self.assertEqual(after["asks"], 3)
        self.assertIn("not read", after["reason"])
        self.assertEqual(after["fingerprints"], read["fingerprints"], "a failed reading erases nothing")
        self.assertEqual(after["actionable"], read["actionable"])

    def test_a_genuine_zero_finding_answer_still_records_clean(self):
        row, _ = self.review([{"findings": [], "verdict": "faithful"}])
        self.assertEqual(row["ended"], "clean")
        self.assertEqual(self.state()["state"], "clean")

    def test_a_pass_after_a_failed_one_compares_against_the_last_reading_that_worked(self):
        both = {"findings": [self.finding(1), self.finding(2)], "verdict": "repairable"}
        self.review([both])
        self.review([self.NOTHING, self.NOTHING, self.NOTHING])
        row, _ = self.review([both])
        self.assertEqual(row["repeated"], 2, "compared against the pass that read, not the one that failed")
        self.assertEqual(self.state()["state"], "no-progress")

    def test_a_first_pass_that_fails_records_unread_with_no_earlier_reading(self):
        row, _ = self.review([self.NOTHING, self.NOTHING, self.NOTHING])
        self.assertEqual(row["ended"], "unread")
        read = self.state()
        self.assertEqual(read["state"], "unread")
        self.assertEqual(read["carried_from"], "no earlier pass")
        self.assertEqual(read["fingerprints"], [])


class WhenTheCriticSpendsItsCeilingTests(TranslationReviewFixture):
    """40 translation-critic calls on landfall, 22 of them `output: 0` after exactly
    32000 reasoning tokens — $1.91 of $3.36 for no characters. The engine asked
    each one three times, because an empty answer looked to it like a malformed
    one."""

    def setUp(self):
        super().setUp()
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["translation"] = {"review": False}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.translate(ScriptedProvider([translation(GOOD_BODY)]))
        config.pop("translation")
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

    class Exhausted:
        """A model that reasons to its ceiling and writes nothing, which is an
        answer the provider charges for."""

        def __init__(self, reasoning=32000):
            self.reasoning = reasoning
            self.calls = []

        def __call__(self, role, envelope, attempt_dir):
            payload = envelope["payload"]
            self.calls.append(role)
            if role == "translation-critic":
                return {
                    "text": "", "provider": "openrouter", "model": payload["model"], "variant": payload["variant"],
                    "session_id": f"ses-{len(self.calls)}",
                    "tokens": {"input": 15000, "output": 0, "reasoning": self.reasoning},
                    "cost": 0.12, "latency_ms": 50, "finish": "stop",
                }
            return {
                "text": translation(GOOD_BODY), "provider": "openrouter", "model": payload["model"],
                "variant": payload["variant"], "session_id": f"ses-{len(self.calls)}",
                "tokens": {"input": 1, "output": 1}, "cost": 0.0, "latency_ms": 1, "finish": "stop",
            }

    def test_an_answer_with_no_room_left_to_write_is_not_asked_again(self):
        provider = self.Exhausted()
        report = self.bf.review_translation(self.project, self.book, "it", provider=provider)
        row = report["reviewed"][0]
        self.assertEqual(row["verdict"], "unread")
        self.assertEqual(
            provider.calls.count("translation-critic"), 1,
            "an identical envelope that exhausted the ceiling exhausts it again",
        )

    def test_it_is_told_apart_from_an_answer_that_came_back_malformed(self):
        self.bf.review_translation(self.project, self.book, "it", provider=self.Exhausted())
        state = json.loads((self.locale_root / "reviews" / "CH-0001.state.json").read_text())
        self.assertEqual(state["state"], "unread")
        self.assertEqual(state["asks"], 1)
        self.assertIn("no room to write", state["unread_because"])
        self.assertNotIn("no JSON object", state["unread_because"])

    def test_an_empty_answer_that_did_no_reasoning_is_still_a_malformed_one(self):
        provider = self.Exhausted(reasoning=0)
        self.bf.review_translation(self.project, self.book, "it", provider=provider)
        self.assertEqual(
            provider.calls.count("translation-critic"), self.bf.CRITIC_ATTEMPTS,
            "nothing on the wire is the case the retry was built for",
        )

    def test_a_spent_ceiling_is_not_silence_and_costs_no_wait(self):
        spent = self.bf.ReasoningCeilingSpent("translation-critic answered CH-0001 with 0 output token(s)")
        self.assertFalse(self.bf._is_silence(spent), "the provider answered and billed for it")
        self.assertEqual(
            self.bf._wait_before_retry("translation-critic", "CH-0001", 1, spent, self.bf.run_opencode_role),
            0.0,
        )


class TheAnswerBoundTests(TranslationReviewFixture):
    """Measured on CH-0003, the chapter this role failed most: twelve calls at
    `medium`, three arms of four. The question as asked answered 0 of 4 and
    stopped at exactly 32000 reasoning tokens every time. The same question with
    the bound lowered to four answered 4 of 4. Half the chapter at twelve
    answered 3 of 4, and its failure was at 31999 — on half the text. The size of
    the answer decides, not the size of the question."""

    class Watching:
        """Keeps the capsule it was asked with, so the bound can be read off the
        envelope rather than off the prompt."""

        def __init__(self):
            self.capsules = []

        def __call__(self, role, envelope, attempt_dir):
            payload = envelope["payload"]
            if role == "translation-critic":
                self.capsules.append(payload["task"])
                text = json.dumps({"findings": [], "verdict": "faithful"})
            else:
                text = translation(GOOD_BODY)
            return {
                "text": text, "provider": "openrouter", "model": payload["model"],
                "variant": payload["variant"], "session_id": "ses-1",
                "tokens": {"input": 1, "output": 1}, "cost": 0.0, "latency_ms": 1, "finish": "stop",
            }

    def test_the_capsule_carries_the_bound_the_engine_owns(self):
        provider = self.Watching()
        self.translate(provider)
        self.assertEqual(len(provider.capsules), 1)
        bound = str(provider.capsules[0].get("answer_bound") or "")
        self.assertIn(str(self.bf.CRITIC_MAX_FINDINGS), bound)

    def test_the_prompt_does_not_carry_a_number_of_its_own(self):
        """The bound the model is told and the bound the engine owns have to be one
        value, or tuning one silently leaves the other behind."""
        prompt = (
            Path(self.bf.__file__).resolve().parent.parent
            / "assets" / "prompts" / "translation-critic.md"
        ).read_text(encoding="utf-8")
        self.assertIn("answer_bound", prompt)
        for word in ("twelve findings", "at most twelve"):
            self.assertNotIn(word, prompt)

    def test_the_bound_is_small_enough_to_have_been_measured(self):
        self.assertLessEqual(self.bf.CRITIC_MAX_FINDINGS, 4, "four is the value four repetitions answered on")


if __name__ == "__main__":
    unittest.main()
