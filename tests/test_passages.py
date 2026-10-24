"""M58 and M63: revise only the passages a note names, in a promoted chapter and its translation."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
GLM = "openrouter/z-ai/glm-5.3-flash"

P2 = "Mara climbed the tower at dawn and counted the lamps the Faith had left burning."
P3 = "She read the letter twice. It was not a warning. It was an invitation."
P4 = "Below, the barge waited with its ropes slack, and the tide was already turning."
SOURCE = f"# The Dawn Barge\n\n{P2}\n\n{P3}\n\n{P4}\n"
I2 = "Mara salì sulla torre all'alba e contò le lampade che la Fede aveva lasciato accese."
I3 = "Lesse la lettera due volte. Non era un avvertimento. Era un invito."
I4 = "Sotto, la chiatta aspettava con le cime lente, e la marea stava già girando."
P3_NEW = "She read the letter twice. It was an invitation."
I3_NEW = "Lesse la lettera due volte. Era un invito."


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_passages", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Provider:
    """Answers each prompt the passage revision asks, as scripted per test."""

    def __init__(self, *, reviser=None, verdict=True, wrong=None, notes=None, translations=None):
        self.reviser = reviser if reviser is not None else {"paragraphs": [{"n": 3, "text": P3_NEW}], "dispositions": []}
        self.verdict = verdict
        self.wrong = list(wrong or [])
        self.notes = notes if notes is not None else []
        self.translations = list(translations or [I3_NEW])
        self.asked = []

    def __call__(self, role, envelope, attempt_dir):
        payload = envelope["payload"]
        task = payload["task"]
        prompt = payload["role_prompt"]
        if role == "translator" and "translated_markdown" in prompt:
            kind, value = "translate", {"translated_markdown": f"# La chiatta dell'alba\n\n{I2}\n\n{I3}\n\n{I4}", "glossary_updates": [], "boundary": "La marea gira."}
        elif "Revise only the paragraphs the notes point at" in prompt:
            kind, value = "revise", self.reviser
        elif "You check a revision of a finished chapter" in prompt:
            kind, value = "check", {"verdicts": [{"n": c["n"], "ok": self.verdict, "why": "kept" if self.verdict else "a fact moved"} for c in task["changes"]]}
        elif "Translate the paragraphs of a chapter whose source changed" in prompt:
            kind = "retranslate"
            value = {"paragraphs": [{"n": row["n"], "text": self.translations.pop(0) if self.translations else I3_NEW} for row in task["paragraphs"]]}
        elif "You check paragraphs that were just translated again" in prompt:
            kind, value = "translation-check", {"wrong": self.wrong.pop(0) if self.wrong else []}
        elif "Read a finished chapter for the sentence shapes" in prompt:
            kind, value = "humanize", {"notes": self.notes}
        elif role == "translation-critic":
            kind, value = "critic", {"findings": [], "verdict": "faithful"}
        elif role == "locale-reader":
            kind, value = "reader", {"summary": "letto", "followed": True, "stumbles": []}
        else:
            kind, value = role, {}
        self.asked.append(kind)
        return {
            "text": json.dumps(value), "provider": "openrouter", "model": payload["model"],
            "variant": payload["variant"], "session_id": f"ses-{len(self.asked)}",
            "tokens": {"input": 10, "output": 10}, "cost": 0.0, "latency_ms": 1, "finish": "stop",
        }


class PassageFixture(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "Book")["id"]
        self.contract = {
            "schema": 1, "book": self.book, "id": "CH-0001", "order": 1, "pov": "CHR-0001",
            "beats": ["Mara reads the letter"], "plants": [], "reveals": [], "target_words": 60,
            "imports": [], "pivotal": None, "title": "The Dawn Barge",
        }
        chapters = self.project / f"books/{self.book}/chapters"
        chapters.mkdir(exist_ok=True)
        (chapters / "CH-0001.json").write_text(json.dumps(self.contract))
        manuscript = self.project / f"books/{self.book}/manuscript/chapters"
        manuscript.mkdir(parents=True, exist_ok=True)
        (manuscript / "CH-0001.md").write_text(SOURCE, encoding="utf-8")
        self.bf.add_translation(self.project, self.book, "it")
        locale_root = self.project / f"books/{self.book}/translations/it"
        (locale_root / "style.md").write_text(
            "---\nid: S\n---\n\n<!-- bf:block style -->\nImperfetto come tempo di base. Caporali per i dialoghi.\n",
            encoding="utf-8",
        )
        (locale_root / "glossary.md").write_text(
            "---\nid: G\n---\n\n<!-- bf:block terms -->\n- **the Faith** → la Fede — the institutional religion.\n",
            encoding="utf-8",
        )
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["roles"] = {"translator": {"model": GLM, "variant": "high"}}
        config["translation"] = {"review": False}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.bf.sync_runtime(self.project)
        self.bf.translate_next(self.project, self.book, "it", provider=Provider(), run_all=False)

    def source(self):
        return (self.project / f"books/{self.book}/manuscript/chapters/CH-0001.md").read_text(encoding="utf-8")

    def italian(self):
        return (self.project / f"books/{self.book}/translations/it/chapters/CH-0001.md").read_text(encoding="utf-8")


class ReviseOnePassageTests(PassageFixture):
    def test_only_the_named_paragraph_changes_in_both_languages(self):
        source_before, italian_before = self.source(), self.italian()
        report = self.bf.revise_passages(
            self.project, self.book, "CH-0001",
            [{"note": "Say what the letter is without saying first what it is not.", "anchor": "It was not a warning"}],
            Provider(),
        )
        self.assertEqual(report["state"], "revised")
        self.assertEqual(report["changed"], [3])
        source_after, italian_after = self.source(), self.italian()
        self.assertEqual(source_after, source_before.replace(P3, P3_NEW))
        self.assertEqual(italian_after, italian_before.replace(I3, I3_NEW))
        self.assertEqual(report["locales"][0]["state"], "retranslated")

    def test_the_translation_is_current_against_the_revised_source(self):
        self.bf.revise_passages(self.project, self.book, "CH-0001", [{"note": "Drop the negation.", "paragraphs": [3]}], Provider())
        state = json.loads((self.project / f"books/{self.book}/translations/it/state.yaml").read_text())
        source_path = self.project / f"books/{self.book}/manuscript/chapters/CH-0001.md"
        self.assertEqual(state["input_hashes"]["source"]["CH-0001"], self.bf._file_hash(source_path))
        registry = self.bf._artifact_registry(self.project)
        row = registry["artifacts"][f"TRANSLATION-{self.book}-CH-0001-it"]
        self.assertEqual(row["dependency_hashes"][f"SOURCE-{self.book}-CH-0001"],
                         registry["artifacts"][f"SOURCE-{self.book}-CH-0001"]["hash"])
        currentness = json.loads((self.project / ".book-forge" / "currentness.json").read_text())
        self.assertTrue(currentness["artifacts"][f"TRANSLATION-{self.book}-CH-0001-it"]["current"])

    def test_a_rejected_paragraph_reverts_and_nothing_is_translated(self):
        source_before, italian_before = self.source(), self.italian()
        provider = Provider(verdict=False)
        report = self.bf.revise_passages(self.project, self.book, "CH-0001", [{"note": "Drop the negation.", "paragraphs": [3]}], provider)
        self.assertEqual(report["state"], "unchanged")
        self.assertEqual(report["reverted"], [{"n": 3, "why": "a fact moved"}])
        self.assertEqual((self.source(), self.italian()), (source_before, italian_before))
        self.assertNotIn("retranslate", provider.asked)

    def test_a_paragraph_outside_the_note_is_refused(self):
        reviser = {"paragraphs": [{"n": 2, "text": "Mara ran up the tower."}, {"n": 3, "text": P3_NEW}], "dispositions": []}
        report = self.bf.revise_passages(self.project, self.book, "CH-0001", [{"note": "Drop the negation.", "paragraphs": [3]}], Provider(reviser=reviser))
        self.assertEqual(report["changed"], [3])
        self.assertEqual(report["refused"], [{"n": 2, "why": "outside the paragraphs the notes allow"}])
        self.assertIn(P2, self.source())

    def test_the_heading_cannot_be_named(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.revise_passages(self.project, self.book, "CH-0001", [{"note": "Retitle it.", "paragraphs": [1]}], Provider())

    def test_an_anchor_the_chapter_does_not_have_is_refused_before_any_call(self):
        provider = Provider()
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.revise_passages(self.project, self.book, "CH-0001", [{"note": "x", "anchor": "no such words"}], provider)
        self.assertEqual(provider.asked, [])

    def test_a_wrong_retranslation_is_asked_once_more_with_the_critics_note(self):
        provider = Provider(wrong=[[{"n": 3, "what": "the letter is read once"}]], translations=["Lesse la lettera una volta. Era un invito.", I3_NEW])
        report = self.bf.revise_passages(self.project, self.book, "CH-0001", [{"note": "Drop the negation.", "paragraphs": [3]}], provider)
        self.assertEqual(provider.asked.count("retranslate"), 2)
        self.assertEqual(report["locales"][0]["checked_wrong_then_repaired"], [3])
        self.assertIn(I3_NEW, self.italian())

    def test_the_note_and_the_change_are_recorded_beside_the_chapter(self):
        self.bf.revise_passages(self.project, self.book, "CH-0001", [{"note": "Drop the negation.", "paragraphs": [3]}], Provider())
        record = json.loads((self.project / f"books/{self.book}/reviews/CH-0001/passages.json").read_text())
        change = record["revisions"][0]["changes"][0]
        self.assertEqual((change["n"], change["before"], change["after"], change["ok"]), (3, P3, P3_NEW, True))
        feedback = json.loads((self.project / f"books/{self.book}/feedback/CH-0001.json").read_text())
        self.assertEqual(feedback["notes"][0]["status"], "applied")
        self.assertEqual(feedback["notes"][0]["changed"], [3])


class RevisePromptAndCliTests(PassageFixture):
    def test_a_cut_for_effect_keeps_the_facts_in_every_prompt(self):
        prompts = Path(__file__).parents[1] / "assets" / "prompts"
        self.assertIn("never a fact it carries", (prompts / "humanize-reader.md").read_text())
        self.assertIn("cuts the effect", (prompts / "passage-reviser.md").read_text())
        self.assertIn("does not license dropping a fact", (prompts / "passage-check.md").read_text())

    def test_the_cli_reads_several_notes_from_a_file(self):
        path = Path(self.temp.name) / "notes.json"
        path.write_text(json.dumps([{"note": "a", "anchor": "x"}, {"note": "b"}]))
        args = self.bf.build_parser().parse_args(["revise", "--book", "B", "--chapter", "CH-0001", "--notes", str(path)])
        self.assertEqual(self.bf._cli_notes(args), [{"note": "a", "anchor": "x"}, {"note": "b"}])

    def test_the_cli_still_takes_one_note(self):
        args = self.bf.build_parser().parse_args(["revise", "--book", "B", "--chapter", "CH-0001", "--note", "a", "--anchor", "x"])
        self.assertEqual(self.bf._cli_notes(args), [{"note": "a", "anchor": "x"}])


class HumanizeTests(PassageFixture):
    def test_the_readers_notes_revise_only_their_paragraphs(self):
        notes = [{"n": 3, "shape": 1, "quote": "It was not a warning. It was an invitation.", "note": "Say what it is."}]
        provider = Provider(notes=notes)
        report = self.bf.humanize_book(self.project, self.book, "CH-0001", provider)["chapters"][0]
        self.assertEqual(report["changed"], [3])
        self.assertEqual(self.source(), SOURCE.replace(P3, P3_NEW))

    def test_the_quote_corrects_a_wrong_paragraph_number(self):
        notes = [{"n": 4, "shape": 1, "quote": "It was not a warning", "note": "Say what it is."}]
        report = self.bf.humanize_book(self.project, self.book, "CH-0001", Provider(notes=notes))["chapters"][0]
        self.assertEqual(report["changed"], [3])

    def test_a_chapter_with_nothing_to_revise_costs_one_call_and_stays(self):
        provider = Provider(notes=[])
        report = self.bf.humanize_book(self.project, self.book, "CH-0001", provider)["chapters"][0]
        self.assertEqual(report["state"], "clean")
        self.assertEqual(provider.asked, ["humanize"])
        self.assertEqual(self.source(), SOURCE)

    def test_the_reader_receives_the_scanners_hits(self):
        seen = []

        class Capturing(Provider):
            def __call__(inner, role, envelope, attempt_dir):
                if "Read a finished chapter" in envelope["payload"]["role_prompt"]:
                    seen.append(envelope["payload"]["task"])
                return super().__call__(role, envelope, attempt_dir)

        self.bf.humanize_book(self.project, self.book, "CH-0001", Capturing(notes=[]))
        self.assertEqual([hit["paragraph"] for hit in seen[0]["prose_tells"]], [3])


if __name__ == "__main__":
    unittest.main()
