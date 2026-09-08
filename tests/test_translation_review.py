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

    def __init__(self, translations, critic=None, reader=None, reviser=None, revision_check=None):
        self.translations = list(translations)
        self.critic = critic
        self.reader = reader
        self.reviser = reviser
        self.revision_check = revision_check
        self.revised_with = None
        self.checked = None
        self.calls = []

    def __call__(self, role, envelope, attempt_dir):
        payload = envelope["payload"]
        self.calls.append(role)
        # A declared chain runs each writer under its own `reviser-<slug>` pin, not
        # under `locale-reviser`. Answered here too, or a chain test measures the
        # pins through a failure path instead of through the rewrite.
        if role == "locale-reviser" or role.startswith("reviser-"):
            task = envelope["payload"]["task"]
            self.revised_with = task
            # Unchanged unless a test scripts otherwise: the reviser saying the
            # chapter already reads as its language.
            answer = self.reviser if self.reviser is not None else {
                "revised_markdown": task["chapter_markdown"], "changed": [],
            }
            return {
                "text": json.dumps(answer),
                "provider": "openrouter", "model": envelope["payload"]["model"],
                "variant": envelope["payload"]["variant"], "session_id": "ses-rev",
                "tokens": {"input": envelope["estimated_input_tokens"], "output": 100},
                "cost": 0.0, "latency_ms": 10, "finish": "stop",
            }
        if role == "locale-reader":
            # A reader that finds nothing is the common case and a real answer.
            text = json.dumps(self.reader if self.reader is not None else {"summary": "letto", "followed": True, "stumbles": []})
        elif role == "translation-critic" and "changed" in envelope["payload"]["task"]:
            self.checked = envelope["payload"]["task"]
            text = json.dumps(self.revision_check if self.revision_check is not None else {"moved": []})
        elif role == "translation-critic":
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


class WhatTheGlossaryCheckWasWrongAboutTests(TranslationReviewFixture):
    """Scored over landfall's seventeen chapters the check raised 32 findings and
    the critic called 28 of them mistaken. All 28 came from this pass, in three
    ways. Each one below is the exact row that produced it."""

    def test_the_rendering_stops_at_the_first_semicolon(self):
        """The whole target cell became the string the translation had to contain,
        markdown and caveats included, so no translation could ever satisfy it —
        and the row was written to stop a calque, which made it worse."""
        row = "- **clear eye / clear-eyed** → occhio limpido; **dagli occhi limpidi solo di una persona** — sight.\n"
        self.assertEqual(self.bf._glossary_terms(row)[0][1], ["occhio limpido"])
        self.assertEqual(
            self.bf._glossary_compliance("Her clear eye read the water.", "Il suo occhio limpido leggeva l'acqua.", row),
            [],
        )

    def test_a_short_term_is_not_found_inside_a_longer_word(self):
        """`wake` matched inside `awake`: the pattern was anchored at the end and
        open at the start, and twelve of landfall's rows are short enough to do it."""
        row = "- **wake** → la scia — the water a hull leaves.\n"
        self.assertEqual(self.bf._glossary_compliance("The crew were awake.", "L'equipaggio era sveglio.", row), [])
        self.assertEqual(len(self.bf._glossary_compliance("The hull left a wake.", "Lo scafo lasciò una traccia.", row)), 1)

    def test_a_rendering_too_long_to_match_is_named_rather_than_enforced(self):
        """Fourteen rows asked for a rendering a translator will vary and be right
        to. Requiring one literally reported chapters that were correct."""
        row = "- **go count your chalk** → vatti a contare il gesso al caldo — a dismissive idiom.\n"
        self.bf._GLOSSARY_UNMATCHABLE_REPORTED.clear()
        self.assertEqual(self.bf._glossary_compliance("Go count your chalk.", "Vatti a contare il gesso.", row), [])
        self.assertTrue(self.bf._GLOSSARY_UNMATCHABLE_REPORTED, "the row is named so the glossary can be fixed")

    def test_a_row_can_declare_its_rendering_conditional_and_be_left_alone(self):
        """`ledger → a una catena` applies to chained logs; the check applied it to
        the shore ledger under the harbour counter. The condition lives in the note
        and the matcher cannot read the note, so the row says so on the arrow."""
        row = f"- **ledger** {self.bf.GLOSSARY_CONDITIONAL_ARROW} a una catena — only where the log is chained.\n"
        self.assertEqual(self.bf._glossary_terms(row), [])
        self.assertEqual(self.bf._glossary_compliance("The ledger lay open.", "Il registro era aperto.", row), [])

    def test_a_gloss_containing_the_separator_is_not_cut_in_half(self):
        """`on a chain (log/ledger)` was split on the slash before the gloss was
        removed, so `ledger)` stood as a term and was hunted for in every chapter."""
        row = "- **on a chain (log/ledger)** → a una catena — only where the log is chained.\n"
        self.assertEqual(self.bf._glossary_terms(row)[0][0], ["on a chain"])
        self.assertEqual(
            self.bf._glossary_compliance("The ledger lay open.", "Il registro era aperto.", row),
            [],
            "the row is about a chained log and never named a term called `ledger)`",
        )

    def test_a_short_english_word_does_not_give_up_its_ending(self):
        """Giving up the last letter is how `mano della palude` recognises `mani
        della palude`. Done to English it turned the row `By then` into the pattern
        `by the` and reported it eleven times across a book that writes `by then`
        in three chapters."""
        row = "- **By then** → A quel punto — a time adverbial.\n"
        self.assertEqual(self.bf._glossary_compliance("He stood by the rail.", "Stava alla ringhiera.", row), [])
        self.assertEqual(len(self.bf._glossary_compliance("By then the tide had turned.", "La marea era girata.", row)), 1)
        self.assertEqual(self.bf._glossary_compliance("By then the tide had turned.", "A quel punto la marea era girata.", row), [])

    def test_the_locale_side_still_inflects(self):
        row = "- **fen-hand** → mano della palude — fixed.\n"
        self.assertEqual(self.bf._glossary_compliance("A fen-hand waited.", "Le mani della palude aspettavano.", row), [])

    def test_the_four_findings_that_held_still_hold(self):
        """The check earns its place on these: neither is reachable by reading the
        Italian alone, and neither is reachable by the monolingual reader, which by
        design cannot see the glossary."""
        reeds = "- **reed-beds** → distese di canne — never `letti` for beds of reeds.\n"
        self.assertEqual(len(self.bf._glossary_compliance(
            "Six hands cutting snails from the reed-beds.", "Sei mani a tagliare lumache dai letti di canne.", reeds)), 1)
        self.assertEqual(self.bf._glossary_compliance(
            "Six hands cutting snails from the reed-beds.", "Sei mani a tagliare lumache dalle distese di canne.", reeds), [])
        breath = "- **a held breath** → un respiro trattenuto — a formulaic recurrence.\n"
        self.assertEqual(len(self.bf._glossary_compliance(
            "the sense of a held breath", "il senso di un fiato sospeso", breath)), 1)
        self.assertEqual(self.bf._glossary_compliance(
            "the sense of a held breath", "il senso di un respiro trattenuto", breath), [])


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
        self.assertEqual(provider.calls, ["translator", "locale-reviser", "locale-reader", "translation-critic", "translator"])
        self.assertIn("gesso di marea", (self.locale_root / "chapters" / "CH-0001.md").read_text())

    def test_a_finding_that_quotes_nothing_is_set_aside_and_drives_no_repair(self):
        vague = {"id": "01", "severity": "warning", "kind": "style", "issue": "si potrebbe migliorare"}
        provider = ScriptedProvider([translation(GOOD_BODY)], critic=self.critic([vague]))
        self.translate(provider)
        self.assertEqual(provider.calls, ["translator", "locale-reviser", "locale-reader", "translation-critic"])
        review = json.loads((self.locale_root / "reviews" / "CH-0001.json").read_text())
        self.assertEqual(len(review["set_aside"]), 1)
        self.assertEqual(review["findings"], [])

    def test_a_note_alone_is_recorded_and_costs_no_repair(self):
        note = {**self.calque_finding(), "severity": "note"}
        provider = ScriptedProvider([translation(GOOD_BODY)], critic=self.critic([note]))
        self.translate(provider)
        self.assertEqual(provider.calls, ["translator", "locale-reviser", "locale-reader", "translation-critic"])

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
                if role == "locale-reviser":
                    # Unchanged: the reviser saying the chapter already reads as its language.
                    return {
                        "text": json.dumps({"revised_markdown": envelope["payload"]["task"]["chapter_markdown"], "changed": []}),
                        "provider": "openrouter", "model": envelope["payload"]["model"],
                        "variant": envelope["payload"]["variant"], "session_id": "ses-rev",
                        "tokens": {"input": envelope["estimated_input_tokens"], "output": 100},
                        "cost": 0.0, "latency_ms": 10, "finish": "stop",
                    }
                if role == "locale-reader":
                    # A reader that finds nothing is the common case and a real answer.
                    text = json.dumps({"summary": "letto", "followed": True, "stumbles": []})
                elif role == "translation-critic":
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
                if role == "locale-reviser":
                    # Unchanged: the reviser saying the chapter already reads as its language.
                    return {
                        "text": json.dumps({"revised_markdown": envelope["payload"]["task"]["chapter_markdown"], "changed": []}),
                        "provider": "openrouter", "model": envelope["payload"]["model"],
                        "variant": envelope["payload"]["variant"], "session_id": "ses-rev",
                        "tokens": {"input": envelope["estimated_input_tokens"], "output": 100},
                        "cost": 0.0, "latency_ms": 10, "finish": "stop",
                    }
                if role == "locale-reader":
                    # A reader that finds nothing is the common case and a real answer.
                    text = json.dumps({"summary": "letto", "followed": True, "stumbles": []})
                elif role == "translation-critic" and envelope["payload"]["task"]["chapter"] == "CH-0001":
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
                if role == "locale-reviser":
                    # Unchanged: the reviser saying the chapter already reads as its language.
                    return {
                        "text": json.dumps({"revised_markdown": envelope["payload"]["task"]["chapter_markdown"], "changed": []}),
                        "provider": "openrouter", "model": envelope["payload"]["model"],
                        "variant": envelope["payload"]["variant"], "session_id": "ses-rev",
                        "tokens": {"input": envelope["estimated_input_tokens"], "output": 100},
                        "cost": 0.0, "latency_ms": 10, "finish": "stop",
                    }
                if role == "locale-reader":
                    # A reader that finds nothing is the common case and a real answer.
                    text = json.dumps({"summary": "letto", "followed": True, "stumbles": []})
                elif role == "translation-critic":
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
        self.assertEqual(provider.calls, ["translator", "locale-reviser", "locale-reader", "translation-critic", "translator"])
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
        self.assertEqual(provider.calls, ["locale-reviser", "locale-reader", "translation-critic"], "no repair was asked for")
        self.assertFalse(report["reviewed"][0]["repaired"])

    def test_a_finding_the_critic_upholds_still_drives_the_repair(self):
        report, provider = self.review([{"id": "G-01", "verdict": "holds", "why": "manca davvero"}])
        self.assertEqual(provider.calls, ["locale-reviser", "locale-reader", "translation-critic", "translator"])
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
            if role == "locale-reviser":
                # Unchanged: the reviser saying the chapter already reads as its language.
                return {
                    "text": json.dumps({"revised_markdown": envelope["payload"]["task"]["chapter_markdown"], "changed": []}),
                    "provider": "openrouter", "model": envelope["payload"]["model"],
                    "variant": envelope["payload"]["variant"], "session_id": "ses-rev",
                    "tokens": {"input": envelope["estimated_input_tokens"], "output": 100},
                    "cost": 0.0, "latency_ms": 10, "finish": "stop",
                }
            if role == "locale-reader":
                # A reader that finds nothing is the common case and a real answer.
                text = json.dumps({"summary": "letto", "followed": True, "stumbles": []})
            elif role == "translation-critic":
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

    def test_two_passes_returning_the_same_findings_stop_as_no_progress(self):
        """Two identical passes, so both the old count rule and the rule that
        replaced it refuse them. The reason now names which findings came back
        rather than how many there were, because the totals stopped deciding."""
        same = {"findings": [self.finding(1), self.finding(2)], "verdict": "repairable"}
        row, provider = self.run_until_clean([same, same, same, same])
        self.assertEqual(row["ended"], "no-progress")
        self.assertEqual(row["passes"], 2)
        self.assertIn("2 of 2 finding(s) came back", row["why"])

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
            if role == "locale-reviser":
                # Unchanged: the reviser saying the chapter already reads as its language.
                return {
                    "text": json.dumps({"revised_markdown": envelope["payload"]["task"]["chapter_markdown"], "changed": []}),
                    "provider": "openrouter", "model": envelope["payload"]["model"],
                    "variant": envelope["payload"]["variant"], "session_id": "ses-rev",
                    "tokens": {"input": envelope["estimated_input_tokens"], "output": 100},
                    "cost": 0.0, "latency_ms": 10, "finish": "stop",
                }
            if role == "locale-reader":
                # A reader that finds nothing is the common case and a real answer.
                text = json.dumps({"summary": "letto", "followed": True, "stumbles": []})
            elif role == "translation-critic":
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
            if role == "locale-reviser":
                # Unchanged: the reviser saying the chapter already reads as its language.
                return {
                    "text": json.dumps({"revised_markdown": envelope["payload"]["task"]["chapter_markdown"], "changed": []}),
                    "provider": "openrouter", "model": envelope["payload"]["model"],
                    "variant": envelope["payload"]["variant"], "session_id": "ses-rev",
                    "tokens": {"input": envelope["estimated_input_tokens"], "output": 100},
                    "cost": 0.0, "latency_ms": 10, "finish": "stop",
                }
            if role == "locale-reader":
                # A reader that finds nothing is the common case and a real answer.
                text = json.dumps({"summary": "letto", "followed": True, "stumbles": []})
            elif role == "translation-critic":
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
            if role == "locale-reviser":
                # Unchanged: the reviser saying the chapter already reads as its language.
                return {
                    "text": json.dumps({"revised_markdown": envelope["payload"]["task"]["chapter_markdown"], "changed": []}),
                    "provider": "openrouter", "model": envelope["payload"]["model"],
                    "variant": envelope["payload"]["variant"], "session_id": "ses-rev",
                    "tokens": {"input": envelope["estimated_input_tokens"], "output": 100},
                    "cost": 0.0, "latency_ms": 10, "finish": "stop",
                }
            if role == "locale-reader":
                # A reader that finds nothing is the common case and a real answer.
                text = json.dumps({"summary": "letto", "followed": True, "stumbles": []})
            elif role == "translation-critic":
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



class AReaderWhoCannotSeeTheSourceTests(TranslationReviewFixture):
    """Nine broken constructions shipped in two pages of landfall's first Italian
    chapter, past a locale style that forbids exactly them and a critic that had read
    it. `go count your chalk` became «vai a contare il tuo gesso», which is not a
    thing anyone says. The critic passed it because it had the English in front of
    it, and with the English in front of you a calque parses."""

    def test_the_reader_is_given_the_translation_and_the_style_and_nothing_else(self):
        capsule = self.bf._locale_reader_capsule("CH-0001", "il testo tradotto", "lo stile")
        self.assertEqual(capsule["translated_markdown"], "il testo tradotto")
        self.assertEqual(capsule["locale_style"], "lo stile")
        self.assertNotIn("source_markdown", capsule, "seeing the source makes a calque legible")
        self.assertNotIn("glossary", capsule, "the glossary would excuse an unreadable term as agreed")
        self.assertIn(str(self.bf.LOCALE_READER_MAX_FINDINGS), str(capsule["answer_bound"]))

    def test_a_stumble_becomes_a_finding_the_repair_can_take(self):
        value = {"summary": "una donna di guardia", "followed": True, "stumbles": [
            {"sentence": "vai a contare il tuo gesso", "why": "non so cosa voglia dire", "severity": "blocking"},
            {"sentence": "La montava come la montava il muro", "why": "un muro non monta la guardia", "severity": "blocking"},
        ]}
        findings = self.bf._locale_reader_findings(value)
        self.assertEqual(len(findings), 2)
        self.assertEqual([f["origin"] for f in findings], ["reader", "reader"])
        self.assertEqual(findings[0]["translated"], "vai a contare il tuo gesso")
        self.assertEqual(findings[0]["kind"], "readability")
        self.assertEqual(findings[0]["fix"], "", "a reader does not propose a rendering")

    def test_a_stumble_quoting_nothing_is_dropped(self):
        """It cannot be repaired and it cannot be checked."""
        value = {"stumbles": [{"sentence": "   ", "why": "boh", "severity": "warning"}]}
        self.assertEqual(self.bf._locale_reader_findings(value), [])

    def test_no_stumbles_is_a_real_answer(self):
        self.assertEqual(self.bf._locale_reader_findings({"summary": "chiaro", "followed": True, "stumbles": []}), [])

    def test_the_prompt_refuses_to_rewrite_and_refuses_the_source(self):
        prompt = (
            Path(self.bf.__file__).resolve().parent.parent / "assets" / "prompts" / "locale-reader.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Do not propose a rewrite", prompt)
        self.assertIn("answer_bound", prompt)
        self.assertIn("not being shown an original", prompt)

    def test_the_role_is_registered_with_a_budget(self):
        self.assertIn("locale-reader", self.bf.ROLE_SPECS)
        self.assertIn("locale-reader", self.bf.ROLE_BUDGETS)
        self.assertGreater(self.bf.ROLE_BUDGETS["locale-reader"][1], 0)

    def test_a_reader_nobody_could_ask_still_cannot_stop_the_run(self):
        """The pass is advisory and must not raise by any route — not a refused
        answer, not a provider that has never heard of the role."""
        def refuses(role, envelope, attempt_dir):
            raise RuntimeError("Agent locale-reader not found")

        reason: list[str] = []
        findings = self.bf._ask_locale_reader(
            self.project, self.book, "it-IT", "CH-0001", "il testo", "lo stile", refuses, reason,
        )
        self.assertEqual(findings, [])
        self.assertTrue(reason, "an unread chapter says why, so it is not read as a clean pass")
        self.assertIn("locale-reader", reason[0])

    def test_a_reader_that_read_and_found_nothing_leaves_no_reason_behind(self):
        def answers(role, envelope, attempt_dir):
            return {
                "text": json.dumps({"summary": "chiaro", "followed": True, "stumbles": []}),
                "provider": "openrouter", "model": envelope["payload"]["model"],
                "variant": envelope["payload"]["variant"], "session_id": "ses-clean",
                "tokens": {"input": 10, "output": 20}, "cost": 0.0, "latency_ms": 1, "finish": "stop",
            }

        reason: list[str] = []
        findings = self.bf._ask_locale_reader(
            self.project, self.book, "it-IT", "CH-0002", "il testo", "lo stile", answers, reason,
        )
        self.assertEqual(findings, [])
        self.assertEqual(reason, [], "nothing found is not the same answer as nobody asked")


if __name__ == "__main__":
    unittest.main()


class WhatTheReaderCallsUnnaturalIsRewrittenTests(TranslationReviewFixture):
    """landfall's CH-0001 review, finding R-04, severity `note`, origin `reader`:
    «senza di esso l'aria della palude le sedeva sul petto come un cappotto bagnato
    a metà guardia». Italian does not seat air on a chest. The role built to find
    that found it, graded it by what it cost to read — nothing — and the repair
    filter keeps `blocking` and `warning` only, so the one role that could see the
    defect filed it into the one grade that is dropped.

    And where it goes now matters as much as that it goes: to the reviser, which
    has never seen the English, and not to the repair, which has it open."""

    def read_back(self, stumbles, reviser=None):
        self.translate(ScriptedProvider([translation(GOOD_BODY)]))
        provider = ScriptedProvider(
            [translation(GOOD_BODY)],
            critic={"findings": [], "verdict": "faithful"},
            reader={"summary": "letto", "followed": True, "stumbles": stumbles},
            reviser=reviser,
        )
        report = self.bf.review_translation(self.project, self.book, "it", provider=provider)
        return report, provider

    def stumble(self, **over):
        # Quoted out of the fixture chapter, because a finding is filtered to the
        # passage it belongs to before the reviser sees it. The sentence this class
        # is really about — «l'aria della palude le sedeva sul petto», landfall's
        # R-04 — is in the docstring; the mechanism is the same.
        row = {
            "sentence": "la Fede contava le lampade",
            "why": "in italiano non si dice così",
            "severity": "note",
        }
        row.update(over)
        return row

    def test_a_finding_outside_this_passage_never_reaches_it(self):
        """The reader now finds a chapter's worth — fifteen on landfall's CH-0001
        against three when it read the whole thing at once — and handing all fifteen
        to each twelve-paragraph passage makes most of them noise the model sorts
        instead of working. It rewrote five of fifteen."""
        _, provider = self.read_back([
            self.stumble(natural=False),
            {"sentence": "una frase che in questo capitolo non c'è", "why": "x",
             "natural": False, "severity": "warning"},
        ])
        handed = [row["sentence"] for row in provider.revised_with["findings"]]
        self.assertEqual(handed, ["la Fede contava le lampade"])

    def review_file(self):
        return json.loads(
            (self.project / f"books/{self.book}/translations/it/reviews/CH-0001.json").read_text()
        )

    def test_a_smooth_sentence_no_writer_would_produce_reaches_the_reviser(self):
        _, provider = self.read_back([self.stumble(natural=False)])
        self.assertIn("locale-reviser", provider.calls)
        self.assertEqual(
            [row["sentence"] for row in provider.revised_with["findings"]],
            ["la Fede contava le lampade"],
        )

    def test_it_never_reaches_the_call_that_has_the_source_open(self):
        """Post-edited text carries more source interference than text written from
        scratch, so repairing a calque beside its original is the defect's own cause."""
        _, provider = self.read_back([self.stumble(natural=False)])
        self.assertNotIn("translator", provider.calls)

    def test_the_reviser_is_never_shown_the_source(self):
        _, provider = self.read_back([self.stumble(natural=False)])
        self.assertNotIn("source_markdown", provider.revised_with)
        self.assertIn("chapter_markdown", provider.revised_with)

    def test_the_floor_is_recorded_as_a_warning_not_left_a_note(self):
        self.read_back([self.stumble(natural=False)])
        raised = [row for row in self.review_file()["findings"] if row.get("origin") == "reader"]
        self.assertEqual([row["severity"] for row in raised], ["warning"])
        self.assertIs(raised[0]["natural"], False)

    def test_a_note_the_reader_calls_natural_is_still_only_a_preference(self):
        _, provider = self.read_back([self.stumble(natural=True)])
        self.assertNotIn("translator", provider.calls)

    def test_a_reader_that_omits_the_question_keeps_the_grade_it_gave(self):
        """The field is new, so an answer without it behaves as it did before."""
        self.read_back([self.stumble()])
        raised = [row for row in self.review_file()["findings"] if row.get("origin") == "reader"]
        self.assertEqual([row["severity"] for row in raised], ["note"])

    def test_a_grade_above_the_floor_is_not_lowered_to_it(self):
        self.read_back([self.stumble(severity="blocking", natural=False)])
        raised = [row for row in self.review_file()["findings"] if row.get("origin") == "reader"]
        self.assertEqual([row["severity"] for row in raised], ["blocking"])

    def test_a_sentence_the_reader_could_not_understand_still_goes_to_the_source(self):
        """`blocking` is not a language defect, it is a meaning one: the reader could
        not recover what the sentence says, and only the source settles that."""
        _, provider = self.read_back([self.stumble(severity="blocking", natural=False)])
        self.assertIn("translator", provider.calls)


class TheRewriteIsGatedSentenceBySentenceTests(TranslationReviewFixture):
    """The rewrite is done without the source on purpose, and the ablation in the
    refinement literature says that is exactly what costs fidelity. So the gate fails
    closed — and per sentence, not per passage: rejecting the passage whole discarded
    `Torv si trattenne un respiro ancora` → `Torv trattenne un altro respiro`, Italian
    against not-Italian, because three other sentences in the chapter moved a fact."""

    CHAPTER = "# La chiatta dell'alba\n\n" + GOOD_BODY

    def read_back(self, revised, changed=None, revision_check=None):
        self.translate(ScriptedProvider([translation(GOOD_BODY)]))
        provider = ScriptedProvider(
            [translation(GOOD_BODY)],
            critic={"findings": [], "verdict": "faithful"},
            reviser={"revised_markdown": revised, "changed": changed or []},
            revision_check=revision_check,
        )
        self.bf.review_translation(self.project, self.book, "it", provider=provider)
        chapter = (self.project / f"books/{self.book}/translations/it/chapters/CH-0001.md").read_text()
        record = json.loads(
            (self.project / f"books/{self.book}/translations/it/revisions/CH-0001.json").read_text()
        )
        return provider, chapter, record

    def test_a_clean_rewrite_is_applied_and_lands_on_disk(self):
        better = self.CHAPTER.replace("contava le lampade", "faceva il conto delle lampade")
        _, chapter, record = self.read_back(
            better, changed=[{"before": "contava le lampade", "after": "faceva il conto delle lampade", "why": "x"}]
        )
        self.assertIn("faceva il conto delle lampade", chapter)
        self.assertTrue(record["applied"])
        self.assertEqual(record["reverted"], [])

    def test_only_the_sentence_that_moved_is_put_back(self):
        """The whole point: one bad rewrite among several must not cost the others."""
        better = self.CHAPTER.replace(
            "Masticava gesso di marea sulla torre e la Fede contava le lampade.",
            "Sulla torre masticava gesso di marea mentre la Fede spegneva le lampade.",
            1,
        ).replace("Masticava gesso di marea sulla torre", "Sulla torre masticava gesso di marea", 1)
        _, chapter, record = self.read_back(
            better,
            changed=[
                {"before": "la Fede contava le lampade", "after": "la Fede spegneva le lampade", "why": "x"},
                {"before": "Masticava gesso di marea sulla torre", "after": "Sulla torre masticava gesso di marea", "why": "y"},
            ],
            revision_check={"moved": [{"before": "la Fede contava le lampade",
                                       "after": "la Fede spegneva le lampade",
                                       "what_moved": "counting became extinguishing"}]},
        )
        self.assertNotIn("spegneva le lampade", chapter, "the moved sentence must be put back")
        self.assertIn("Sulla torre masticava gesso di marea", chapter, "the sentence that did not move must stand")
        self.assertEqual(len(record["reverted"]), 1)
        self.assertTrue(record["applied"])

    def test_a_rewrite_that_changes_a_number_does_not_survive(self):
        moved = self.CHAPTER.replace("contava le lampade", "contava 14 lampade", 1)
        _, chapter, record = self.read_back(moved, changed=[{"before": "a", "after": "b", "why": "x"}])
        self.assertNotIn("14", chapter)
        self.assertFalse(record["applied"])
        self.assertIn("numbers differ from source", record["rejected"])

    def test_a_check_that_cannot_be_reached_reverts_everything(self):
        """Fails closed. The rewrite was made blind; nobody downstream can see what it
        did, so an unverified one does not ship."""
        better = self.CHAPTER.replace("contava le lampade", "faceva il conto delle lampade")
        _, chapter, record = self.read_back(
            better,
            changed=[{"before": "contava le lampade", "after": "faceva il conto delle lampade", "why": "x"}],
            revision_check={"nonsense": True},
        )
        self.assertIn("faceva il conto delle lampade", chapter,
                      "a parseable answer with no `moved` key is an empty verdict, not an unreachable check")

    def test_the_check_is_asked_even_when_validation_would_refuse(self):
        """Order matters now: putting a moved sentence back can be what makes the
        passage valid again, so the check runs before the validation decides."""
        moved = self.CHAPTER.replace("contava le lampade", "contava 14 lampade", 1)
        provider, _, _ = self.read_back(moved, changed=[{"before": "a", "after": "b", "why": "x"}])
        self.assertIsNotNone(provider.checked)

    def test_the_check_sees_the_pairs_and_the_source_and_not_the_chapter(self):
        better = self.CHAPTER.replace("contava le lampade", "faceva il conto delle lampade")
        provider, _, _ = self.read_back(
            better, changed=[{"before": "contava le lampade", "after": "faceva il conto delle lampade", "why": "x"}]
        )
        self.assertEqual([row["after"] for row in provider.checked["changed"]], ["faceva il conto delle lampade"])
        self.assertIn("source_markdown", provider.checked)


class AGlossaryIsReadAgainstItselfTests(TranslationReviewFixture):
    """landfall's glossary said `the Wall → il Cavallone` with **Never «il Muro»**
    written into the note and the reason recorded, and two thirds of the way down
    the same file fixed the watch formula as «Il Muro è libero», *fissa ad ogni
    ricorrenza*. Nothing read a glossary against itself, so the review meant to take
    «il Muro» out of five chapters would have put it back through the formula."""

    def glossary(self, extra):
        path = self.project / f"books/{self.book}/translations/it/glossary.md"
        path.write_text(path.read_text() + extra, encoding="utf-8")
        return path.read_text()

    def test_a_row_that_uses_what_another_row_forbids_is_reported(self):
        text = self.glossary(
            "- **the Wall / tide-wall** → il Cavallone — the bore. ✗ «il Muro» because Italian has one word for wall.\n"
            "- **Wall's clear** → «Il Muro è libero» — the watch formula, fixed at every recurrence.\n"
        )
        problems = self.bf._glossary_self_contradictions(text)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("forbids 'il Muro'", problems[0])

    def test_rows_that_agree_are_not_reported(self):
        text = self.glossary(
            "- **the Wall / tide-wall** → il Cavallone — the bore. ✗ «il Muro» because Italian has one word for wall.\n"
            "- **Wall's clear** → «Il Cavallone è libero» — the watch formula, fixed at every recurrence.\n"
        )
        self.assertEqual(self.bf._glossary_self_contradictions(text), [])

    def test_a_forbidden_rendering_in_a_chapter_is_a_finding(self):
        """The term is quoted mid-sentence on purpose. A capitalised term is matched
        with its case, because that is what tells `the Wall` from an ordinary wall,
        and the cost is that a sentence-initial `The Wall` is not seen. The existing
        compliance check has always behaved this way and was scored at that setting,
        so it is recorded here rather than changed underneath that measurement."""
        text = self.glossary(
            "- **the Wall / tide-wall** → il Cavallone — the bore. ✗ «il Muro» because Italian has one word for wall.\n"
        )
        findings = self.bf._glossary_compliance(
            "By dusk the Wall came home on the hour.", "Al tramonto il Muro tornò a casa all'ora.", text
        )
        self.assertTrue([row for row in findings if "forbids" in row], findings)

    def test_a_forbidden_rendering_is_not_a_finding_when_the_source_never_uses_the_term(self):
        """The conjunction is what keeps an ordinary word out of the report: the
        chapter has to be rendering *this* term for the prohibition to apply."""
        text = self.glossary(
            "- **the Wall / tide-wall** → il Cavallone — the bore. ✗ «il Muro» because Italian has one word for wall.\n"
        )
        findings = self.bf._glossary_compliance(
            "She put her hand on the stone.", "Appoggiò la mano al Muro della torre.", text
        )
        self.assertEqual([row for row in findings if "forbids" in row], [])

    def test_a_row_without_the_mark_declares_no_prohibition(self):
        """Prose is not read: the row that mattered said **Never «il Muro»** in bold
        English and every check in the engine walked past it."""
        text = self.glossary(
            "- **the Wall / tide-wall** → il Cavallone — the bore, **Never «il Muro»**, Italian has one word.\n"
            "- **Wall's clear** → «Il Muro è libero» — the watch formula.\n"
        )
        self.assertEqual(self.bf._glossary_self_contradictions(text), [])


class ASliceIsReadAndRewrittenOnItsOwnTests(TranslationReviewFixture):
    """Measured on landfall's CH-0001, 45 paragraphs in one call each: the reader was
    allowed six stumbles and reported three, and the reviser — told in as many words
    to read the whole chapter and not stop at the findings — rewrote exactly the three
    sentences it had been handed. Neither was short of allowance. Both were short of
    attention, which is a property of how much text one call holds."""

    def test_a_long_chapter_is_read_and_revised_in_runs_of_paragraphs(self):
        long_chapter = "# Titolo\n\n" + "\n\n".join(f"Paragrafo numero uno di prova {n}." for n in range(40))
        slices = self.bf._paragraph_slices(long_chapter)
        self.assertGreater(len(slices), 1)
        self.assertEqual("\n\n".join(text for _, _, text in slices), long_chapter)

    def test_a_short_chapter_is_still_one_call(self):
        """The engine must not pay four calls for a chapter that fits in one."""
        self.assertEqual(len(self.bf._paragraph_slices("uno\n\ndue\n\ntre")), 1)

    def test_every_paragraph_belongs_to_exactly_one_slice(self):
        text = "\n\n".join(f"riga {n}" for n in range(37))
        slices = self.bf._paragraph_slices(text)
        covered = [n for first, last, _ in slices for n in range(first, last + 1)]
        self.assertEqual(covered, list(range(1, 38)))

    def test_a_slice_that_loses_a_paragraph_is_dropped_and_the_original_kept(self):
        """The chapter is rebuilt by joining the pieces, so a slice that merges two
        paragraphs moves the book's structure everywhere downstream of it."""
        chapter = "# La chiatta dell'alba\n\n" + GOOD_BODY
        self.translate(ScriptedProvider([translation(GOOD_BODY)]))
        provider = ScriptedProvider(
            [translation(GOOD_BODY)],
            critic={"findings": [], "verdict": "faithful"},
            reviser={"revised_markdown": "una riga sola dove ce n'erano due", "changed": []},
        )
        self.bf.review_translation(self.project, self.book, "it", provider=provider)
        kept = (self.project / f"books/{self.book}/translations/it/chapters/CH-0001.md").read_text()
        self.assertEqual(kept.strip(), chapter.strip())


class TheTranslatorIsComparedTheWayTheWriterIsTests(TranslationReviewFixture):
    """`bakeoff` has compared writers since the beginning and never translators, so
    the role whose output a reader could not follow is the one no comparison covered.
    landfall's translator was pinned to `glm-5.3-flash` because that is the writer's
    model, and nothing had ever measured it against another."""

    def bake(self, reader_by_model):
        self.translate(ScriptedProvider([translation(GOOD_BODY)]))

        class Bench:
            def __init__(self):
                self.calls = []

            def __call__(self, role, envelope, attempt_dir):
                payload = envelope["payload"]
                self.calls.append(role)
                model = payload["model"]
                if role == "locale-reader":
                    stumbles = reader_by_model.get(self.pinned, [])
                    text = json.dumps({"summary": "letto", "followed": True, "stumbles": stumbles})
                else:
                    self.pinned = model
                    text = translation(GOOD_BODY)
                return {
                    "text": text, "provider": "openrouter", "model": model,
                    "variant": payload["variant"], "session_id": "ses",
                    "tokens": {"input": envelope["estimated_input_tokens"], "output": 400},
                    "cost": 0.002, "latency_ms": 50, "finish": "stop",
                }

        bench = Bench()
        bench.pinned = ""
        return self.bf.translate_bakeoff(
            self.project, self.book, "CH-0001", "it", [MODEL, GLM], provider=bench,
        ), bench

    def stumble(self, sentence):
        return {"sentence": sentence, "why": "non è italiano", "natural": False, "severity": "warning"}

    def test_the_candidate_the_reader_stumbles_on_least_ranks_first(self):
        index, _ = self.bake({
            MODEL: [self.stumble("una frase")],
            GLM: [self.stumble("una"), self.stumble("due"), self.stumble("tre")],
        })
        self.assertEqual(index["ranking"][0], MODEL)
        self.assertEqual(index["scored_by"], "locale-reader, defects per thousand words")

    def test_every_candidate_is_scored_per_thousand_words_and_nothing_is_promoted(self):
        index, _ = self.bake({MODEL: [], GLM: [self.stumble("una frase")]})
        for row in index["candidates"]:
            self.assertEqual(row["state"], "drafted")
            self.assertIn("defects_per_1000_words", row)
        chapter = (self.project / f"books/{self.book}/translations/it/chapters/CH-0001.md").read_text()
        self.assertIn("Masticava gesso di marea", chapter, "the bake-off must not touch the translation")

    def test_a_bake_off_needs_two_models(self):
        self.translate(ScriptedProvider([translation(GOOD_BODY)]))
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.translate_bakeoff(self.project, self.book, "CH-0001", "it", [MODEL], provider=None)

    def test_a_translator_candidate_answers_on_the_translator_prompt(self):
        """The agent body says which role it is, so a writer pin answering a
        translation capsule would carry `you are the writer` into the call."""
        self.assertEqual(self.bf.CANDIDATE_MODELS[self.bf._translator_candidate_name(GLM)], (GLM, "translator"))
        self.assertEqual(self.bf.CANDIDATE_MODELS[self.bf._writer_candidate_name(GLM)], (GLM, "writer"))


class TheGlossaryHoldsTheBooksTermsAndNothingElseTests(TranslationReviewFixture):
    """landfall's glossary reached 216 rows and holds `By then → A quel punto`,
    `gleams → brilla`, and a whole sentence recorded because one chapter got its
    tense wrong once. Every row is read into every translator, critic, reviser and
    repair call for the rest of the book, and is the authority the critic cites — so
    an ordinary word promoted to a fixed rendering turns a defensible synonym in a
    later chapter into a finding."""

    def row(self, source, translation, **over):
        return {"source": source, "translation": translation, "note": "x", **over}

    def test_a_coined_term_becomes_a_row(self):
        out = self.bf._append_glossary("- **a** → b — n\n", [self.row("tide-chalk", "gesso di marea")])
        self.assertIn("tide-chalk", out)

    def test_an_ordinary_word_the_translator_marks_a_note_does_not(self):
        out = self.bf._append_glossary("- **a** → b — n\n", [self.row("By then", "A quel punto", kind="note")])
        self.assertNotIn("By then", out)

    def test_a_whole_sentence_never_becomes_a_row_however_it_is_labelled(self):
        """The backstop for an answer that omits `kind` or gets it wrong: a source
        side longer than a term is a sentence, whatever it calls itself."""
        long_row = self.row(
            "The Wall took the shelf the way it always took it",
            "Il Cavallone prese le secche come le prendeva sempre",
            kind="term",
        )
        self.assertNotIn("took the shelf", self.bf._append_glossary("- **a** → b — n\n", [long_row]))

    def test_a_rendering_longer_than_the_matcher_can_check_never_becomes_a_row(self):
        wordy = self.row("prayer", "Pray your salt lasts you all the way to it and back", kind="term")
        self.assertNotIn("Pray your salt", self.bf._append_glossary("- **a** → b — n\n", [wordy]))

    def test_what_is_not_a_term_is_kept_beside_the_chapter(self):
        locale_root = self.project / f"books/{self.book}/translations/it"
        kept = self.bf._record_chapter_notes(
            locale_root, "CH-0001",
            [self.row("tide-chalk", "gesso di marea"), self.row("By then", "A quel punto", kind="note")],
        )
        self.assertEqual([row["source"] for row in kept], ["By then"])
        written = json.loads((locale_root / "notes" / "CH-0001.json").read_text())
        self.assertEqual([row["source"] for row in written["notes"]], ["By then"])

    def test_a_chapter_with_only_terms_writes_no_note_file(self):
        locale_root = self.project / f"books/{self.book}/translations/it"
        self.bf._record_chapter_notes(locale_root, "CH-0002", [self.row("tide-chalk", "gesso di marea")])
        self.assertFalse((locale_root / "notes" / "CH-0002.json").exists())


class TheRewriteIsUnconditionalAndTheReaderIsTheTestTests(TranslationReviewFixture):
    """The order used to be reader-then-reviser, which made a bounded sample of a
    pervasive defect into the work list. On landfall's CH-0001 the reader named fifteen
    sentences, the reviser rewrote five, and «Binta si morse il gesso di marea in
    pezzettini» — the book's first sentence, a reflexive Italian keeps for parts of the
    body and a resultative it does not build — was in neither set. Nothing failed: the
    role built for that defect was never shown it."""

    def run_back(self, reader_answers, reviser=None, rewrites=()):
        self.translate(ScriptedProvider([translation(GOOD_BODY)]))

        class Bench(ScriptedProvider):
            def __init__(self, answers, rewrites=(), **kw):
                super().__init__([translation(GOOD_BODY)], **kw)
                self.answers = list(answers)
                self.rewrites = list(rewrites)

            def __call__(self, role, envelope, attempt_dir):
                if role == "locale-reader" and self.answers:
                    self.reader = self.answers.pop(0)
                if role == "locale-reviser" and self.rewrites:
                    self.reviser = self.rewrites.pop(0)
                return super().__call__(role, envelope, attempt_dir)

        provider = Bench(reader_answers, rewrites=rewrites, critic={"findings": [], "verdict": "faithful"}, reviser=reviser)
        self.bf.review_translation(self.project, self.book, "it", provider=provider)
        return provider

    def clean(self):
        return {"summary": "letto", "followed": True, "stumbles": []}

    def dirty(self):
        return {"summary": "letto", "followed": True, "stumbles": [
            {"sentence": "la Fede contava le lampade", "why": "non è italiano",
             "natural": False, "severity": "warning"},
        ]}

    def test_the_rewrite_runs_before_anyone_has_found_anything(self):
        provider = self.run_back([self.clean()])
        self.assertLess(provider.calls.index("locale-reviser"), provider.calls.index("locale-reader"))

    def test_the_rewriter_is_handed_no_work_list_on_the_first_pass(self):
        provider = self.run_back([self.clean()])
        self.assertEqual(provider.revised_with["findings"], [])

    def test_a_passage_the_reader_still_calls_unnatural_is_written_again(self):
        provider = self.run_back([self.dirty(), self.clean()])
        self.assertEqual(provider.calls.count("locale-reviser"), 2)

    def test_a_second_pass_that_landed_is_read_back(self):
        chapter = "# La chiatta dell'alba\n\n" + GOOD_BODY
        provider = self.run_back(
            [self.dirty(), self.clean()],
            rewrites=[
                {"revised_markdown": chapter, "changed": []},
                {"revised_markdown": chapter.replace("contava", "faceva il conto di", 1), "changed": []},
            ],
        )
        self.assertEqual(provider.calls.count("locale-reader"), 2)

    def test_a_second_pass_that_changed_nothing_costs_no_second_reading(self):
        provider = self.run_back([self.dirty(), self.clean()])
        self.assertEqual(provider.calls.count("locale-reader"), 1)

    def test_a_chapter_the_reader_passes_is_not_written_twice(self):
        provider = self.run_back([self.clean()])
        self.assertEqual(provider.calls.count("locale-reviser"), 1)

    def test_the_second_pass_carries_what_the_reader_said_as_evidence(self):
        provider = self.run_back([self.dirty(), self.clean()])
        self.assertEqual(
            [row["sentence"] for row in provider.revised_with["findings"]],
            ["la Fede contava le lampade"],
        )


class TwoWritersCoverWhatOneMissesTests(TranslationReviewFixture):
    """Nine models rewrote the same 500 words. gemini-3.8-flash fixed about fifteen of
    eighteen defects and missed `come up gold`; gpt-5.6-terra wrote the best prose of
    any of them, was the only one to fix that, and left `La masticava` for `il gesso`.
    grok-4.6 was alone in finding `fascia di marea`. No model's fixes contained
    another's, so the pass runs the writers in order and each is gated on its own."""

    def chain(self, models):
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["translation"] = {**config.get("translation", {}), "rewriters": models}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

    def test_one_writer_is_the_default_and_costs_one_pass(self):
        self.assertEqual(self.bf._rewriter_chain(self.project), [""])

    def test_a_declared_chain_is_resolved_against_the_catalogue(self):
        self.chain(["glm-5.3-flash", "gemini-3.8-flash"])
        self.assertEqual(
            self.bf._rewriter_chain(self.project),
            ["openrouter/z-ai/glm-5.3-flash", "openrouter/google/gemini-3.8-flash"],
        )

    def test_each_writer_in_the_chain_gets_its_own_pin(self):
        self.chain([MODEL, GLM])
        self.translate(ScriptedProvider([translation(GOOD_BODY)]))
        provider = ScriptedProvider(
            [translation(GOOD_BODY)], critic={"findings": [], "verdict": "faithful"},
        )
        self.bf.review_translation(self.project, self.book, "it", provider=provider)
        pins = [c for c in provider.calls if c.startswith("reviser-")]
        self.assertEqual(pins, [self.bf._reviser_candidate_name(MODEL), self.bf._reviser_candidate_name(GLM)])


class ALiveProcessKeepsEveryClaimItHoldsTests(TranslationReviewFixture):
    """A translation holds its claim across the whole read-back, because the chapter
    file is its output and the rewrite decides what that file says. It makes one call
    and then waits for the reader, the writers and the critic. With a chain of two
    writers that passed the twenty-minute lease, the reaper found the translator's
    claim expired, recorded live work as an unknown outcome, and blocked the run under
    a process that was busy."""

    def two_claims(self, other_pid=None):
        import os, time
        self.translate(ScriptedProvider([translation(GOOD_BODY)]))
        plan = self.bf._load_plan(self.project)
        now = time.time()
        answering = {"id": "ATT-LIVE", "task": "T-LIVE", "state": "running", "role": "translator",
                     "owner_pid": os.getpid(), "fence": 1, "lease_seconds": 1200.0,
                     "heartbeat_at": now, "lease_expires_at": now + 1200,
                     "provider_accepted": False, "request_hash": "a", "run": "RUN-0001"}
        waiting = {"id": "ATT-HELD", "task": "T-HELD", "state": "running", "role": "translator",
                   "owner_pid": other_pid if other_pid is not None else os.getpid(),
                   "fence": 1, "lease_seconds": 1200.0,
                   "heartbeat_at": now - 1300, "lease_expires_at": now - 100,
                   "provider_accepted": False, "request_hash": "b", "run": "RUN-0001"}
        plan["attempts"].extend([answering, waiting])
        self.bf._save_plan(self.project, plan)
        # `mark_provider_accepted` records the session on the attempt's intent file.
        for row in (answering, waiting):
            d = self.bf._attempt_dir(self.project, row)
            d.mkdir(parents=True, exist_ok=True)
            self.bf._write_json(d / "intent.json", {"accepted": False})
        self.bf.mark_provider_accepted(self.project, "ATT-LIVE", "ses-x")
        return next(a for a in self.bf._load_plan(self.project)["attempts"] if a["id"] == "ATT-HELD")

    def test_another_call_answering_renews_every_claim_this_process_holds(self):
        import time
        self.assertGreater(self.two_claims()["lease_expires_at"], time.time())

    def test_a_claim_owned_by_another_process_is_not_renewed(self):
        """The lease still has to catch a dead owner, which is what it is for."""
        import os, time
        self.assertLess(self.two_claims(other_pid=os.getpid() + 99999)["lease_expires_at"], time.time())


class ANameTheTranslationNeverExplainsTests(TranslationReviewFixture):
    """`The Fen Sow` is a barge. Italian got `la Scrofa`, an ordinary word for a female
    pig, and the first person to read the chapter asked what it was. English carried it
    on grammar Italian does not have — `she`, `her pilot`, `her nose`, and `a barge` in
    the same sentence — and none of it survives a language that drops the possessive.

    Neither existing role can see it. The monolingual reader is asked where the *language*
    failed and nothing here is bad Italian; the bilingual critic has the source, so the
    referent is never in doubt for it. And no rewriter can fix it: the answer is not in
    the Italian to be rewritten."""

    def read_back(self, unidentified):
        self.translate(ScriptedProvider([translation(GOOD_BODY)]))
        provider = ScriptedProvider(
            [translation(GOOD_BODY)],
            critic={"findings": [], "verdict": "faithful"},
            reader={"summary": "letto", "followed": True, "stumbles": [], "unidentified": unidentified},
        )
        self.bf.review_translation(self.project, self.book, "it", provider=provider)
        review = json.loads(
            (self.project / f"books/{self.book}/translations/it/reviews/CH-0001.json").read_text()
        )
        return review, provider

    def sow(self):
        return [{"name": "la Scrofa", "sentence": "La Scrofa restava sulla rotta sbagliata",
                 "took_it_for": "un animale; ho capito che era una barca sedici paragrafi dopo"}]

    def test_a_name_the_reader_could_not_place_is_a_finding(self):
        review, _ = self.read_back(self.sow())
        rows = [f for f in review["findings"] if f.get("kind") == "unidentified"]
        self.assertEqual(len(rows), 1)
        self.assertIn("la Scrofa", rows[0]["issue"])

    def test_it_goes_to_the_call_that_holds_the_source(self):
        """The opposite of a calque: only the source says what the thing is."""
        _, provider = self.read_back(self.sow())
        self.assertIn("translator", provider.calls)

    def test_it_never_goes_to_the_rewriter_as_work(self):
        _, provider = self.read_back(self.sow())
        handed = [row["sentence"] for row in (provider.revised_with or {}).get("findings", [])]
        self.assertEqual(handed, [], "a rewriter cannot supply what the translation never said")

    def test_a_reader_that_names_nothing_costs_no_repair(self):
        _, provider = self.read_back([])
        self.assertNotIn("translator", provider.calls)

    def test_an_entry_without_a_name_is_dropped(self):
        review, _ = self.read_back([{"sentence": "x", "took_it_for": "y"}])
        self.assertEqual([f for f in review["findings"] if f.get("kind") == "unidentified"], [])


REVISED_BODY = "Masticava il gesso di marea sulla torre mentre la Fede contava le lampade. " * 12


class ASliceThatCameBackUnusableTests(TranslationReviewFixture):
    """landfall's CH-0003 lost paragraphs 25-36 to one truncated JSON answer. The
    slice was kept as it came, the line saying so went to stderr, and the chapter's
    own summary reported the sentences the other slices had gained. The record in
    `revisions/` carried `slices`, `rewritten`, `reverted` and `changed`, and no
    field from which a reader could tell a twelfth of the chapter was never read."""

    TRUNCATED = '{"revised_markdown": "# La chiatta dell\'alba\\n\\nMasticava il gesso'

    class Reviser(ScriptedProvider):
        """Hands the reviser a scripted raw answer per ask, valid JSON or not."""

        def __init__(self, answers, **kw):
            super().__init__([translation(GOOD_BODY)], **kw)
            self.answers = list(answers)
            self.asks = 0

        def __call__(self, role, envelope, attempt_dir):
            if role != "locale-reviser":
                return super().__call__(role, envelope, attempt_dir)
            self.asks += 1
            self.calls.append(role)
            payload = envelope["payload"]
            return {
                "text": self.answers.pop(0) if self.answers else "{}",
                "provider": "openrouter", "model": payload["model"], "variant": payload["variant"],
                "session_id": f"ses-rev-{self.asks}",
                "tokens": {"input": envelope["estimated_input_tokens"], "output": 100},
                "cost": 0.0, "latency_ms": 10, "finish": "stop",
            }

    def run_back(self, answers):
        self.translate(ScriptedProvider([translation(GOOD_BODY)]))
        provider = self.Reviser(answers, critic={"findings": [], "verdict": "faithful"})
        self.bf.review_translation(self.project, self.book, "it", provider=provider)
        return provider

    def good(self):
        return json.dumps({"revised_markdown": f"# La chiatta dell'alba\n\n{REVISED_BODY}", "changed": []})

    def chapter(self):
        return (self.project / f"books/{self.book}/translations/it/chapters/CH-0001.md").read_text(encoding="utf-8")

    def record(self):
        return json.loads(
            (self.project / f"books/{self.book}/translations/it/revisions/CH-0001.json").read_text(encoding="utf-8")
        )

    def test_a_truncated_answer_is_asked_again(self):
        provider = self.run_back([self.TRUNCATED, self.good()])
        self.assertEqual(provider.asks, 2, "one malformed answer must not be final for the passage")

    def test_the_second_ask_lands_the_rewrite(self):
        self.run_back([self.TRUNCATED, self.good()])
        self.assertIn("mentre la Fede contava", self.chapter())

    def test_a_slice_that_answers_first_time_is_asked_once(self):
        provider = self.run_back([self.good()])
        self.assertEqual(provider.asks, 1, "a working answer must not cost a second call")

    def test_two_unusable_answers_keep_the_passage(self):
        self.run_back([self.TRUNCATED, self.TRUNCATED])
        self.assertNotIn("mentre la Fede contava", self.chapter())

    def test_two_unusable_answers_stop_at_two(self):
        provider = self.run_back([self.TRUNCATED, self.TRUNCATED])
        self.assertEqual(provider.asks, self.bf.LOCALE_SLICE_ASKS)

    def test_the_record_names_the_paragraphs_that_were_never_revised(self):
        self.run_back([self.TRUNCATED, self.good()])
        record = self.record()
        self.assertIn("unrevised", record)
        self.assertIn("asked", record)

    def test_a_passage_kept_unrevised_is_counted_in_the_record(self):
        """The chapter here has one slice, so the pass reaches nothing at all — and
        the record has to say so rather than report an empty change list."""
        self.run_back([self.TRUNCATED, self.TRUNCATED])
        record = self.record()
        self.assertEqual(record["unrevised"], ["1-2"])
        self.assertEqual(record["asked"], 1)
        self.assertFalse(record["applied"], "nothing was rewritten, so nothing was applied")


class WhatALimitDoesToTheRestOfTheChapterTests(TranslationReviewFixture):
    """A spending limit is not this slice's failure. Swallowed by the slice's own
    handler it would keep every remaining passage unrevised and count each one, which
    reads as a chapter the writer had little to change."""

    def test_a_provider_limit_is_not_swallowed_as_an_unusable_slice(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        body = source[source.index("def _revise_one_slice("):]
        body = body[:body.index("\ndef ", 10)]
        self.assertIn("except ProviderLimitReached:", body)
        self.assertLess(
            body.index("except ProviderLimitReached:"),
            body.index("except Exception as unrevised:"),
            "the bare handler below would take it first",
        )


class ConvergenceIsAboutWhatCameBackTests(unittest.TestCase):
    """landfall CH-0003 was reviewed twice. The second pass fixed all seven findings
    of the first, repeated none of them, produced eleven new ones on the 34 paragraphs
    it had rewritten, and was recorded `no-progress` because 11 >= 7. `repeated` was
    computed three lines above the decision and not consulted."""

    def setUp(self):
        self.bf = load_module()

    def finding(self, ident, kind="readability", **extra):
        return {
            "id": ident, "severity": "warning", "kind": kind, "origin": "reader",
            "source": "", "translated": f"frase {ident}", "rule": "r",
            "issue": f"problema {ident}", "fix": "", **extra,
        }

    def pass_of(self, findings, previous=None, repaired_before=True):
        return self.bf._convergence(previous or {}, findings, "repairable", repaired_before)

    def test_a_pass_that_repeats_nothing_is_progress(self):
        first = self.pass_of([self.finding(f"A{n}") for n in range(7)])
        second = self.pass_of([self.finding(f"B{n}") for n in range(11)], previous=first)
        self.assertEqual(second["repeated"], 0)
        self.assertNotEqual(second["state"], "no-progress")

    def test_the_totals_alone_no_longer_decide(self):
        first = self.pass_of([self.finding(f"A{n}") for n in range(7)])
        second = self.pass_of([self.finding(f"B{n}") for n in range(11)], previous=first)
        self.assertEqual(second["actionable"], 11)
        self.assertGreater(second["actionable"], first["actionable"])
        self.assertEqual(second["state"], "more-to-do")

    def test_a_finding_that_came_back_is_no_progress(self):
        first = self.pass_of([self.finding(f"A{n}") for n in range(4)])
        second = self.pass_of(
            [self.finding("A1"), self.finding("A2"), self.finding("A3"), self.finding("Z")],
            previous=first,
        )
        self.assertEqual(second["repeated"], 3)
        self.assertEqual(second["state"], "no-progress")

    def test_the_reason_says_the_repair_claimed_to_apply_them(self):
        first = self.pass_of([self.finding("A1")])
        second = self.pass_of([self.finding("A1")], previous=first, repaired_before=True)
        self.assertIn("came back after the repair said it applied them", second["reason"])

    def test_nothing_left_is_still_clean(self):
        self.assertEqual(self.pass_of([])["state"], "clean")


class QuestionsTheLoopCannotCloseTests(unittest.TestCase):
    """`keelback` and `zecche-lanterna` are fixed terms in landfall's glossary, one
    kept and one rendered. The monolingual reader is denied the glossary so an
    unreadable term is reported rather than excused, and it reported both — every
    pass, forever, because no role can answer `yes, deliberately`. Three of CH-0003's
    eleven findings were these, so the chapter could not converge whatever the models
    did."""

    GLOSSARY = (
        "---\nid: G\n---\n\n<!-- bf:block terms -->\n"
        "- **keelback (the animal)** → keelback — Gli animali da cortile restano 'keelback'.\n"
        "- **lantern-ticks** → zecche-lanterna — Phosphorescent organisms; fixed term.\n"
        "- **Silent Ones** → i Silenziosi — Order rank; singular Silenzioso.\n"
        "- **tide-chalk** → gesso di marea — fixed term.\n"
        "- **revert** → revert\n"
    )

    def setUp(self):
        self.bf = load_module()

    def name(self, term):
        return {
            "id": "N-01", "severity": "warning", "kind": "unidentified", "origin": "reader",
            "source": "", "translated": f"una frase con {term}", "term": term,
            "rule": "the text says what a thing is",
            "issue": f"a reader could not tell what {term!r} is", "fix": "",
        }

    def test_a_name_the_glossary_fixed_is_marked_for_the_author(self):
        rows = self.bf._mark_author_questions([self.name("keelback")], self.GLOSSARY)
        self.assertTrue(rows[0]["author_question"])

    def test_the_name_arrives_with_the_article_the_text_gave_it(self):
        """What the role actually returns. The first build matched on equality and
        was tested with bare terms it had invented, so it passed and then flagged
        none of CH-0003's three: the reader had said `i keelback`, `un Silenzioso`,
        `la gabbia`."""
        rows = self.bf._mark_author_questions([self.name("i keelback")], self.GLOSSARY)
        self.assertTrue(rows[0]["author_question"])
        self.assertEqual(rows[0]["glossary_term"], "keelback")

    def test_a_singular_is_carried_onto_the_plural_row(self):
        """The glossary holds `i Silenziosi` and the chapter says `un Silenzioso`:
        a different article and a different ending."""
        rows = self.bf._mark_author_questions([self.name("un Silenzioso")], self.GLOSSARY)
        self.assertTrue(rows[0]["author_question"])

    def test_an_ordinary_word_is_still_a_defect(self):
        """`la gabbia` is not a glossary term — a reader who cannot tell what the
        cage is has found something, and it must not be filed as settled."""
        rows = self.bf._mark_author_questions([self.name("la gabbia")], self.GLOSSARY)
        self.assertNotIn("author_question", rows[0])
        self.assertEqual(len(self.bf._bilingual_repair_findings(rows)), 1)

    def test_a_rendered_term_counts_too_not_only_a_kept_one(self):
        """`zecche-lanterna` is translated, not kept, and is just as unanswerable:
        the English does not explain a lantern-tick either."""
        rows = self.bf._mark_author_questions([self.name("zecche-lanterna")], self.GLOSSARY)
        self.assertTrue(rows[0]["author_question"])

    def test_a_name_the_glossary_never_settled_stays_a_defect(self):
        rows = self.bf._mark_author_questions([self.name("la Scrofa")], self.GLOSSARY)
        self.assertNotIn("author_question", rows[0])

    def test_an_author_question_is_not_sent_to_the_repair(self):
        rows = self.bf._mark_author_questions([self.name("keelback")], self.GLOSSARY)
        self.assertEqual(self.bf._bilingual_repair_findings(rows), [])

    def test_a_name_the_glossary_never_settled_still_reaches_the_repair(self):
        rows = self.bf._mark_author_questions([self.name("la Scrofa")], self.GLOSSARY)
        self.assertEqual(len(self.bf._bilingual_repair_findings(rows)), 1)

    def test_a_chapter_whose_only_findings_are_questions_reads_as_clean(self):
        rows = self.bf._mark_author_questions([self.name("keelback"), self.name("zecche-lanterna")], self.GLOSSARY)
        out = self.bf._convergence({}, rows, "repairable", False)
        self.assertEqual(out["state"], "clean")
        self.assertEqual(out["actionable"], 0)
        self.assertEqual(len(out["questions"]), 2)
        self.assertIn("await the author", out["reason"])

    def test_the_questions_are_named_where_a_person_will_read_them(self):
        rows = self.bf._mark_author_questions([self.name("keelback")], self.GLOSSARY)
        out = self.bf._convergence({}, rows, "repairable", False)
        self.assertEqual(out["questions"][0]["term"], "keelback")

    def test_a_kept_row_is_recognised_by_its_two_sides_being_the_same(self):
        kept = dict(self.bf._glossary_kept_rows(self.GLOSSARY))
        self.assertNotIn("Silent Ones", kept)
        self.assertIn("keelback", kept)
        self.assertIn("revert", kept)
        self.assertNotIn("lantern-ticks", kept)
        self.assertNotIn("tide-chalk", kept)

    def test_a_kept_row_that_says_nothing_about_why_is_told_apart(self):
        kept = dict(self.bf._glossary_kept_rows(self.GLOSSARY))
        self.assertEqual(kept["revert"], "", "no note at all")
        self.assertTrue(kept["keelback"].strip(), "this one states something")


class TheNamesQuestionBelongsToTheWholeChapterTests(TranslationReviewFixture):
    """landfall CH-0003 closes on «la gabbia ticchettava ancora, bevendo», for the
    English `the cage ticked on, drinking`. The reader of paragraphs 49-51 could not
    tell what the cage was; the chapter says so in paragraph 21, in both languages.
    The finding routed to the repair that holds the source, which supplied the
    explanation, and the closing line came back as «e le zecche dentro bevevano»."""

    ANSWER = {
        "summary": "letto", "followed": True, "stumbles": [],
        "unidentified": [{"name": "la gabbia", "sentence": "la gabbia ticchettava ancora",
                          "took_it_for": "una cosa che tutti conoscono"}],
    }

    def test_a_slice_that_names_something_is_not_asked_about_names(self):
        self.assertEqual(self.bf._locale_reader_findings(self.ANSWER, names_asked=False), [])

    def test_the_call_with_the_whole_chapter_still_is(self):
        found = self.bf._locale_reader_findings(self.ANSWER, names_asked=True)
        self.assertEqual([row["kind"] for row in found], ["unidentified"])

    def test_a_slice_still_reports_its_stumbles(self):
        answer = {**self.ANSWER, "stumbles": [
            {"sentence": "la Fede contava le lampade", "why": "non è italiano",
             "natural": False, "severity": "warning"},
        ]}
        found = self.bf._locale_reader_findings(answer, names_asked=False)
        self.assertEqual([row["kind"] for row in found], ["readability"])

    def test_the_capsule_says_which_questions_this_call_is_asked(self):
        whole = self.bf._locale_reader_capsule(
            "CH-0001", "testo", "stile", passage="par", first=1, last=12, of=5, whole="tutto",
        )
        later = self.bf._locale_reader_capsule(
            "CH-0001", "testo", "stile", passage="par", first=13, last=24, of=5, whole="",
        )
        self.assertEqual(whole["asked"], ["stumbles", "unidentified"])
        self.assertEqual(later["asked"], ["stumbles"])
        self.assertIn("names_are_not_your_question", later)
        self.assertNotIn("names_are_not_your_question", whole)

    def test_a_chapter_short_enough_for_one_call_keeps_the_question(self):
        one = self.bf._locale_reader_capsule("CH-0001", "testo", "stile", whole="testo")
        self.assertEqual(one["asked"], ["stumbles", "unidentified"])

    def test_only_the_first_of_five_slices_may_report_a_name(self):
        """End to end over a chapter long enough to be sliced: every call returns the
        same unidentified name, and only the one holding the whole chapter is heard."""
        long_chapter = "# T\n\n" + "\n\n".join(f"Paragrafo numero {n} della prova." for n in range(1, 40))

        class EveryCallNamesIt(ScriptedProvider):
            def __call__(self, role, envelope, attempt_dir):
                if role == "locale-reader":
                    self.reader = TheNamesQuestionBelongsToTheWholeChapterTests.ANSWER
                return super().__call__(role, envelope, attempt_dir)

        provider = EveryCallNamesIt([translation(GOOD_BODY)])
        found = self.bf._ask_locale_reader(
            self.project, self.book, "it", "CH-0001", long_chapter, "stile", provider,
        )
        self.assertGreater(len(self.bf._paragraph_slices(long_chapter)), 1, "the chapter must be sliced")
        self.assertEqual(len([row for row in found if row["kind"] == "unidentified"]), 1)


class AProviderThatDidNotAnswerIsAskedAgainTests(TranslationReviewFixture):
    """Retranslating landfall CH-0003 died twice on `[Z.AI] temporarily rate-limited
    upstream`, a condition that had lifted by the time either model was probed. The
    translator's retry loop guards what the model said — malformed JSON, a failed
    validation — and the call deciding whether it said anything sat above it, so
    `ProviderOutcomeUnknown`, the class this engine defines for *ask again*, ended
    the route on its first occurrence."""

    class RefusesThenAnswers(ScriptedProvider):
        """Refuses the named role a set number of times, the way an upstream limit does."""

        def __init__(self, answers, *, role, refusals, limit=False, **kw):
            super().__init__(answers, **kw)
            self.role, self.refusals, self.limit = role, refusals, limit
            self.refused = 0

        def __call__(self, name, envelope, attempt_dir):
            if name == self.role and self.refused < self.refusals:
                self.refused += 1
                self.calls.append(f"{name}:refused")
                if self.limit:
                    raise self.bf.ProviderLimitReached(
                        "The provider refused the call and asking again will not clear it: "
                        "APIError: Key limit exceeded (daily limit)."
                    )
                raise self.bf.ProviderOutcomeUnknown(
                    "ses-x",
                    "OpenCode ended without a complete result: APIError: [Z.AI] "
                    "z-ai/glm-5.3-flash is temporarily rate-limited upstream.",
                )
            return super().__call__(name, envelope, attempt_dir)

    def provider(self, **kw):
        made = self.RefusesThenAnswers([translation(GOOD_BODY)], **kw)
        made.bf = self.bf
        return made

    def chapter(self):
        return self.project / f"books/{self.book}/translations/it/chapters/CH-0001.md"

    def test_a_momentary_refusal_costs_an_ask_and_not_the_chapter(self):
        provider = self.provider(role="translator", refusals=1)
        self.translate(provider)
        self.assertEqual(provider.refused, 1)
        self.assertTrue(self.chapter().exists(), "the chapter must be translated on the second ask")

    def test_two_refusals_in_a_row_are_still_survived(self):
        provider = self.provider(role="translator", refusals=2)
        self.translate(provider)
        self.assertTrue(self.chapter().exists())

    def test_a_provider_that_never_answers_gives_up(self):
        provider = self.provider(role="translator", refusals=99)
        with self.assertRaises(self.bf.ProviderOutcomeUnknown):
            self.translate(provider)
        self.assertEqual(provider.refused, self.bf.TRANSLATOR_PROVIDER_ASKS)

    def test_a_spending_limit_ends_it_on_the_first_refusal(self):
        """A cap does not lift by asking again, and telling the two apart is what
        makes widening the retry safe."""
        provider = self.provider(role="translator", refusals=99, limit=True)
        with self.assertRaises(self.bf.ProviderLimitReached):
            self.translate(provider)
        self.assertEqual(provider.refused, 1, "a cap must not be asked three times")

    def test_the_repair_attempts_are_not_spent_on_the_provider(self):
        """`TRANSLATION_ATTEMPTS` are repairs, each carrying what was wrong with the
        last answer. A provider that never answered produced nothing to repair."""
        provider = self.provider(role="translator", refusals=2)
        self.translate(provider)
        self.assertEqual(provider.calls.count("translator"), 1, "one answer, after two refusals")


ORDINARY_EN = "She chewed tide-chalk on the tower and the Faith counted lamps."
ORDINARY_IT = "Masticava gesso di marea sulla torre e la Fede contava."
# The same sentence rendered at length because the target language needs the words,
# not because anything was explained.
LONGER_IT = "Masticava il gesso di marea sopra la torre mentre la Fede contava le lampade."
# landfall CH-0003's closing line, and the rendering that carries the addition: the
# English never says what is in the cage, the chapter said it thirty paragraphs
# earlier, and the Italian says it again here.
ADDITION_EN = "Behind her, down the dark, the cage ticked on, drinking."
ADDITION_IT = "Alle spalle, giù nel buio, la gabbia ticchettava ancora e dentro le zecche bevevano."
ADDITION_IT_PLAIN = "Giù nel buio, alle sue spalle, la gabbia continuava a ticchettare."


def chapter(sentences, title="# T"):
    return f"{title}\n\n" + " ".join(sentences)


class ASentenceTheTranslationExplainedTests(unittest.TestCase):
    """landfall CH-0003 ends `the cage ticked on, drinking` and the Italian ends
    «la gabbia ticchettava ancora e dentro le zecche bevevano». Nothing in the chain
    can refuse it: both monolingual roles have no source, and the revision check asks
    whether a fact moved — nothing moved, because the ticks really are in the cage.

    The critic's prompt states the rule twice and the critic was at its ceiling: four
    findings, all blocking, all real meaning errors. An addition that is true ranks
    below four assertions that are wrong. So it is counted instead of read."""

    def setUp(self):
        self.bf = load_module()

    def measure(self, source_sentences, target_sentences):
        return self.bf._expansion_candidates(chapter(source_sentences), chapter(target_sentences))

    def book_of(self, target_last, source_last=ADDITION_EN, ordinary=23, target_ordinary=ORDINARY_IT):
        return self.measure(
            [ORDINARY_EN] * ordinary + [source_last],
            [target_ordinary] * ordinary + [target_last],
        )

    def test_a_sentence_carrying_a_clause_the_source_never_wrote_is_proposed(self):
        found = self.book_of(ADDITION_IT)
        self.assertEqual([row["id"] for row in found], ["X-01"])
        self.assertEqual(found[0]["kind"], "addition")

    def test_the_pair_is_quoted_because_the_id_alone_rules_nothing(self):
        found = self.book_of(ADDITION_IT)
        self.assertEqual(found[0]["source"], ADDITION_EN)
        self.assertEqual(found[0]["translated"], ADDITION_IT)

    def test_the_same_sentence_without_the_addition_is_not_proposed(self):
        self.assertEqual(self.book_of(ADDITION_IT_PLAIN), [])

    def test_a_sentence_merely_longer_because_the_language_is_longer_is_not(self):
        """The measurement that decided this: on raw word counts the defect and its
        repair both run 1.40 times landfall CH-0003's median, so a word is not the
        unit. Words of four letters or more separated them, 1.50 against 1.17."""
        self.assertEqual(self.book_of(LONGER_IT, source_last=ORDINARY_EN), [])

    def test_the_baseline_is_the_chapter_and_not_a_constant(self):
        """A translation that runs half again as long everywhere proposes nothing:
        how much longer the target runs is a property of the pair, not a defect."""
        self.assertEqual(self.book_of(LONGER_IT, source_last=ORDINARY_EN, target_ordinary=LONGER_IT), [])

    def test_a_chapter_too_short_to_have_a_median_proposes_nothing(self):
        self.assertEqual(self.book_of(ADDITION_IT, ordinary=8), [])

    def test_it_stops_at_its_own_bound(self):
        found = self.measure(
            [ORDINARY_EN] * 20 + [ADDITION_EN] * 6,
            [ORDINARY_IT] * 20 + [ADDITION_IT] * 6,
        )
        self.assertEqual(len(found), self.bf.EXPANSION_MAX_CANDIDATES)

    def test_a_paragraph_the_two_languages_cut_differently_is_left_out(self):
        """A translator that joins two sentences into one is making a rendering
        choice, and an alignment invented across it would measure the choice."""
        source = chapter([ORDINARY_EN] * 23) + "\n\n" + ADDITION_EN + " " + ORDINARY_EN
        target = chapter([ORDINARY_IT] * 23) + "\n\n" + ADDITION_IT
        self.assertEqual(self.bf._expansion_candidates(source, target), [])

    def test_a_chapter_whose_paragraphs_do_not_match_proposes_nothing(self):
        source = chapter([ORDINARY_EN] * 23 + [ADDITION_EN])
        self.assertEqual(self.bf._expansion_candidates(source, source + "\n\nUn paragrafo in più."), [])


class AnAdditionDoesNotCompeteWithAMeaningErrorTests(TranslationReviewFixture):
    """The critic returned exactly four findings on landfall CH-0003, every one of
    them blocking and every one a real meaning error, and the closing line came back
    explained. The bound was doing its job; the addition had nowhere to go."""

    FOUR_BLOCKING = {
        "verdict": "repairable",
        "findings": [
            {"id": f"{n:02d}", "severity": "blocking", "kind": "meaning",
             "source": f"line {n}", "translated": f"riga {n}",
             "rule": "the source", "issue": "il senso cambia", "fix": f"riga {n} corretta"}
            for n in range(1, 5)
        ],
    }

    class RemembersTheCapsule(ScriptedProvider):
        def __call__(self, role, envelope, attempt_dir):
            task = envelope["payload"]["task"]
            if role == "translation-critic" and "machine_findings" in task:
                self.critic_task = task
            if role == "translator" and "repair" in task:
                self.repaired_with = task["repair"]["findings"]
            return super().__call__(role, envelope, attempt_dir)

    def read_back(self, critic):
        source = chapter([ORDINARY_EN] * 23 + [ADDITION_EN], title="# The Dawn Barge")
        body = " ".join([ORDINARY_IT] * 23 + [ADDITION_IT])
        (self.project / f"books/{self.book}/manuscript/chapters/CH-0001.md").write_text(source, encoding="utf-8")
        # The translate path runs the review too, and a held candidate reaches the
        # repair there: scripted to answer with the same chapter, so the addition
        # is still standing when this test reads it back.
        self.translate(ScriptedProvider([translation(body)] * 4))
        provider = self.RemembersTheCapsule([translation(body)] * 4, critic=critic)
        provider.critic_task = None
        provider.repaired_with = []
        self.bf.review_translation(self.project, self.book, "it", provider=provider)
        review = json.loads(
            (self.project / f"books/{self.book}/translations/it/reviews/CH-0001.json").read_text()
        )
        return review, provider

    def test_the_critic_is_given_the_pair_and_not_only_an_id(self):
        _, provider = self.read_back(self.FOUR_BLOCKING)
        raised = [row for row in provider.critic_task["machine_findings"] if row["id"].startswith("X-")]
        self.assertEqual(len(raised), 1)
        self.assertEqual(raised[0]["translated"], ADDITION_IT)

    def test_a_chapter_at_the_finding_bound_still_reports_the_addition(self):
        review, _ = self.read_back(self.FOUR_BLOCKING)
        self.assertEqual(len([row for row in review["findings"] if row["kind"] == "meaning"]), 4)
        self.assertEqual(len([row for row in review["findings"] if row["kind"] == "addition"]), 1)

    def test_the_capsule_says_they_are_answered_as_well_as_the_findings(self):
        _, provider = self.read_back(self.FOUR_BLOCKING)
        self.assertIn("in addition", provider.critic_task["machine_findings_bound"])

    def test_a_candidate_the_critic_calls_mistaken_is_dropped(self):
        review, _ = self.read_back({
            **self.FOUR_BLOCKING,
            "machine_findings": [{"id": "X-01", "verdict": "mistaken", "why": "l'italiano richiede le parole"}],
        })
        self.assertEqual([row for row in review["findings"] if row["kind"] == "addition"], [])

    def test_an_addition_goes_to_the_call_that_holds_the_source(self):
        """Only the source says what the translation added. The rewriter has no
        source and reads an explained image as the better sentence."""
        _, provider = self.read_back(self.FOUR_BLOCKING)
        self.assertIn("addition", [row.get("kind") for row in provider.repaired_with])
