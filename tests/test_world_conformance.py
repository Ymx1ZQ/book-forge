import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _decide_locale_style(bf, project, book, locale):
    """A project must decide how the book speaks before anything is translated."""
    path = bf._project_root(project) / "books" / book / "translations" / bf._canonical_locale(locale) / "style.md"
    path.write_text("---\nid: LOC\n---\n\n# Locale Style\n\n<!-- bf:block style -->\nFormal address throughout; guillemets for dialogue; past tense preserved.\n", encoding="utf-8")


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
PROMPTS = MODULE_PATH.parents[1] / "assets" / "prompts"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_world", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EraDatingTests(unittest.TestCase):
    """A brief saying contemporary produced a 1950s novel because no era ever
    carried a date."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])

    def proposal(self, era):
        return {
            "kernel": [{"id": "LAW-0001", "summary": "Memory is property."}],
            "eras": [era], "events": [], "places": [], "factions": [],
            "characters": [{"id": "CHR-0001", "summary": "A diver.", "tier": "L1"}],
            "themes": ["memory"], "style": {"person": "third-limited", "tense": "past"},
            "continuity_material": {"CNT-0001": ["LAW-0001", "CHR-0001"]},
        }

    def codes(self, era):
        return {row["code"] for row in self.bf.validate_universe_design(self.project, self.proposal(era))}

    def test_an_era_without_a_date_is_blocking(self):
        codes = self.codes({"id": "ERA-0001", "name": "The Lull", "summary": "An off-season pause."})
        self.assertIn("era.undated", codes)

    def test_a_dated_era_with_material_facts_passes_that_check(self):
        codes = self.codes({
            "id": "ERA-0001", "name": "The Lull", "summary": "An off-season pause.",
            "when": "2019", "material": ["a bus twice a day", "everyone carries a phone", "cash at the bar"],
        })
        self.assertNotIn("era.undated", codes)
        self.assertNotIn("era.material-thin", codes)

    def test_a_dated_era_with_thin_material_warns_but_does_not_block(self):
        rows = self.bf.validate_universe_design(self.project, self.proposal(
            {"id": "ERA-0001", "name": "The Lull", "summary": "A pause.", "when": "2019", "material": ["a bus twice a day"]}
        ))
        thin = [row for row in rows if row["code"] == "era.material-thin"]
        self.assertEqual([row["severity"] for row in thin], ["warning"])


class PromptContractTests(unittest.TestCase):
    """The instructions the roles are given must name the checks they are for."""

    def read(self, name):
        return (PROMPTS / name).read_text(encoding="utf-8")

    def test_the_technical_editor_checks_the_world_and_not_the_sentences(self):
        prompt = self.read("technical-editor.md")
        for phrase in ("POV character", "Knowledge", "The place", "The era", "act on something the text never gave them"):
            self.assertIn(phrase, prompt)

    def test_the_writer_is_told_what_dialogue_may_not_do(self):
        prompt = self.read("writer.md")
        for phrase in ("epigraph", "practical want", "misunderstands", "introduces themselves by their function", "costs the asker"):
            self.assertIn(phrase, prompt)

    def test_the_style_review_reads_dialogue_for_the_same_five(self):
        prompt = self.read("style-review.md")
        self.assertIn("states the book's theme", prompt)
        self.assertIn("no practical want", prompt)

    def test_the_auditor_checks_reveals_against_the_arc(self):
        prompt = self.read("canon-auditor.md")
        self.assertIn("reveal schedule", prompt)
        self.assertIn("plant in an earlier chapter", prompt)

    def test_the_translator_is_bound_by_the_locale_style_file(self):
        prompt = self.read("translator.md")
        self.assertIn("binding, not advisory", prompt)
        self.assertIn("title case", prompt)

    def test_the_designer_dates_its_eras(self):
        prompt = self.read("designer.md")
        self.assertIn("`when` is a year or a decade", prompt)


class RepetitionTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def test_a_repeated_phrase_is_a_finding(self):
        prose = "# T\n\n" + ("She stood with the window open and waited. " * 3) + "Then the boat left the harbour at dawn."
        rows = self.bf._repetition_findings(prose)
        self.assertTrue(any("window open" in row["evidence"] for row in rows))
        self.assertTrue(all(row["severity"] == "note" for row in rows), "a mechanical count informs, it does not oblige")

    def test_ordinary_prose_produces_nothing(self):
        prose = "# T\n\nShe crossed the square. The bell rang once. A gull turned above the roofs and was gone."
        self.assertEqual(self.bf._repetition_findings(prose), [])

    def test_a_character_name_is_not_a_tic(self):
        prose = "# T\n\n" + " ".join(f"Concetta said something to the {noun}." for noun in
                                     ["baker", "priest", "child", "widow", "sailor", "cook", "boy"])
        self.assertEqual([row for row in self.bf._repetition_findings(prose) if row["evidence"] == "concetta"], [])

    def test_a_recurring_word_informs_without_obliging_the_reviser(self):
        prose = ("# T\n\nA lantern swung by the door. Someone lifted the lantern high. "
                 "Below, a lantern burned out. She bought a lantern in the market. "
                 "The old lantern hung crooked. A lantern is a poor sun.")
        rows = [row for row in self.bf._repetition_findings(prose) if row["evidence"] == "lantern"]
        self.assertEqual([row["severity"] for row in rows], ["note"])
        self.assertEqual([row["fix_required"] for row in rows], [False])


class LocaleStyleGateTests(unittest.TestCase):
    """No translation starts before someone has decided how the book speaks."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", "en", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]
        self.root = self.bf._project_root(self.project)
        self.bf.add_translation(self.project, self.book, "it")
        self.style = self.root / "books" / self.book / "translations" / "it" / "style.md"

    def test_the_generated_stub_blocks_and_names_the_file(self):
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf._require_locale_style(self.root, self.book, "it")
        self.assertIn("style.md", str(caught.exception))

    def test_an_edited_file_passes(self):
        self.style.write_text("---\nid: LOC\n---\n\n# Locale Style\n\n<!-- bf:block style -->\nFormal address throughout; guillemets for dialogue.\n", encoding="utf-8")
        self.bf._require_locale_style(self.root, self.book, "it")

    def test_english_title_case_in_a_romance_locale_is_a_finding(self):
        problem = self.bf._heading_case_problem("# La Stanza Sopra il Portone\n\nTesto.", "it")
        self.assertIn("title case", problem)

    def test_the_target_language_own_capitalisation_passes(self):
        self.assertIsNone(self.bf._heading_case_problem("# La stanza sopra il portone\n\nTesto.", "it"))

    def test_english_headings_are_left_alone(self):
        self.assertIsNone(self.bf._heading_case_problem("# The Room Above the Gate\n\nText.", "en"))



class EraAsCanonTests(unittest.TestCase):
    """An era that is not a block reaches nobody: the index carried CHR, PLC, FAC,
    LAW, UNI and STYLE, and no ERA at all, while chapters were told to import one."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])

    def test_an_era_is_written_as_canon_with_its_date_and_its_facts(self):
        outputs = self.bf._universe_design_outputs({
            "kernel": [{"id": "LAW-0001", "summary": "Memory is property."}],
            "eras": [{"id": "ERA-0001", "name": "Now", "summary": "The present season.",
                      "when": "2020", "material": ["a bus twice a day", "everyone has a phone", "cash at the bar"]}],
            "events": [], "places": [], "factions": [],
            "characters": [{"id": "CHR-0001", "summary": "A diver."}],
            "style": {"person": "third-limited", "tense": "past"},
        })
        path = "universe/canon/eras/ERA-0001.md"
        self.assertIn(path, outputs)
        text = outputs[path]
        self.assertIn("<!-- bf:block when -->\n2020", text)
        self.assertIn("- everyone has a phone", text)

    def test_the_era_becomes_importable_and_reaches_the_writer(self):
        canon = self.project / "universe" / "canon" / "eras"
        canon.mkdir(parents=True, exist_ok=True)
        (canon / "ERA-0001.md").write_text(
            "---\nid: ERA-0001\ncontinuity: CNT-0001\n---\n\n# Now\n\n"
            "<!-- bf:block summary -->\nThe present season.\n\n"
            "<!-- bf:block when -->\n2020\n\n"
            "<!-- bf:block material -->\n- everyone has a phone\n",
            encoding="utf-8",
        )
        index = self.bf.rebuild_indexes(self.project)
        self.assertIn("ERA-0001#when", index["blocks"])
        envelope = self.bf.build_envelope(
            self.project, role="writer",
            task_capsule={"id": "CH-0001", "book": "BOOK-0001", "target_words": 900, "beats": ["b"], "pov": "CHR-0001"},
            imports=["ERA-0001#when", "ERA-0001#material"], state={}, tools=[], max_output_tokens=2000,
        )
        blob = json.dumps(envelope["payload"]["context"], ensure_ascii=False)
        self.assertIn("2020", blob)
        self.assertIn("everyone has a phone", blob)


if __name__ == "__main__":
    unittest.main()
