import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_pov_voices", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VoiceProvider:
    """A designer that answers the voice call, optionally skipping some character."""

    def __init__(self, skip=()):
        self.skip = set(skip)
        self.capsules = []

    def __call__(self, role, envelope, attempt_dir):
        capsule = envelope["payload"]["task"]
        self.capsules.append(capsule)
        payload = {"voices": [
            {"id": row["id"], "voice": f"{row['name']} counts before speaking. \"Not yet,\" she says."}
            for row in capsule["characters"] if row["id"] not in self.skip
        ]}
        return {
            "text": json.dumps(payload),
            "provider": "openrouter",
            "model": MODEL,
            "variant": load_module().ROLE_SPECS["designer"][1],
            "session_id": f"ses-{len(self.capsules)}",
            "tokens": {"input": envelope["estimated_input_tokens"], "output": 200},
            "cost": 0.001,
            "latency_ms": 5,
            "finish": "stop",
        }


class PovVoiceFixture(unittest.TestCase):
    """Landfall carried ten characters and one voice block. Three of its four
    points of view had none, so six chapters were about to be written with the
    character's summary and nothing about how they sound."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]
        self.canon = self.project / "universe" / "canon"
        self.character("CHR-0001", "Mara", voice="She answers questions with questions.")
        self.character("CHR-0002", "Weyr")
        self.character("CHR-0003", "Flint")
        self.bf.rebuild_indexes(self.project)

    def character(self, character_id, name, voice=None):
        body = (
            f"---\nid: {character_id}\ncontinuity: CNT-0001\n---\n\n# {name}\n\n"
            f"<!-- bf:block summary -->\n{name} keeps a promise nobody asked for.\n"
        )
        if voice:
            body += f"\n<!-- bf:block voice -->\n{voice}\n"
        (self.canon / "characters" / f"{character_id}.md").write_text(body, encoding="utf-8")

    def proposal(self, povs):
        return {
            "premise": "A diver must decide whether memory can be owned.",
            "entry_state": {"CHR-0001": "isolated"},
            "arc": ["refusal", "cost", "choice"],
            "exit_boundary": {"CHR-0001": "committed"},
            "chapters": [
                {
                    "id": f"CH-{order:04d}", "order": order, "title": f"Tide {order}", "pov": pov,
                    "beats": ["Someone wants a thing and is refused"],
                    "plants": [], "reveals": [], "target_words": 900,
                    "imports": ["UNI-0001#kernel", f"{pov}#summary"], "obligations": [], "pivotal": None,
                }
                for order, pov in enumerate(povs, start=1)
            ],
        }


class TheVoiceIsWrittenNotSkippedTests(PovVoiceFixture):
    def test_a_pov_without_a_voice_gets_one_and_the_chapters_gain_the_import(self):
        proposal = self.proposal(["CHR-0001", "CHR-0002", "CHR-0003"])
        provider = VoiceProvider()
        written = self.bf._fill_missing_pov_voices(self.project, self.book, proposal, provider)
        self.assertEqual(written, ["CHR-0002", "CHR-0003"])
        for character_id in written:
            text = (self.canon / "characters" / f"{character_id}.md").read_text()
            self.assertIn("<!-- bf:block voice -->", text)
        imports = {row["pov"]: row["imports"] for row in proposal["chapters"]}
        self.assertIn("CHR-0002#voice", imports["CHR-0002"])
        self.assertIn("CHR-0003#voice", imports["CHR-0003"])

    def test_the_voice_that_already_exists_is_never_rewritten(self):
        before = (self.canon / "characters" / "CHR-0001.md").read_text()
        self.bf._fill_missing_pov_voices(self.project, self.book, self.proposal(["CHR-0001", "CHR-0002"]), VoiceProvider())
        self.assertEqual((self.canon / "characters" / "CHR-0001.md").read_text(), before)

    def test_a_book_whose_voices_all_exist_makes_no_call(self):
        provider = VoiceProvider()
        self.assertEqual(self.bf._fill_missing_pov_voices(self.project, self.book, self.proposal(["CHR-0001"]), provider), [])
        self.assertEqual(provider.capsules, [])

    def test_only_the_points_of_view_are_asked_for_and_each_one_once(self):
        """Three chapters of the same POV are one hole, not three."""
        provider = VoiceProvider()
        self.bf._fill_missing_pov_voices(self.project, self.book, self.proposal(["CHR-0002"] * 3), provider)
        self.assertEqual([row["id"] for row in provider.capsules[0]["characters"]], ["CHR-0002"])
        self.assertEqual(len(provider.capsules), 1)

    def test_the_call_carries_the_summary_and_the_chapters_the_character_narrates(self):
        provider = VoiceProvider()
        self.bf._fill_missing_pov_voices(self.project, self.book, self.proposal(["CHR-0001", "CHR-0002"]), provider)
        asked = provider.capsules[0]["characters"][0]
        self.assertEqual(asked["id"], "CHR-0002")
        self.assertIn("Weyr keeps a promise", asked["summary"])
        self.assertEqual(asked["pov_of"], ["CH-0002"])

    def test_a_voice_the_designer_skips_leaves_the_character_alone_and_the_rest_written(self):
        proposal = self.proposal(["CHR-0002", "CHR-0003"])
        written = self.bf._fill_missing_pov_voices(self.project, self.book, proposal, VoiceProvider(skip=["CHR-0002"]))
        self.assertEqual(written, ["CHR-0003"])
        self.assertNotIn("bf:block voice", (self.canon / "characters" / "CHR-0002.md").read_text())

    def test_the_cast_is_sliced_so_the_call_is_the_size_of_the_slice(self):
        for order in range(4, 12):
            self.character(f"CHR-{order:04d}", f"Name {order}")
        self.bf.rebuild_indexes(self.project)
        povs = [f"CHR-{order:04d}" for order in range(2, 12)]
        provider = VoiceProvider()
        written = self.bf._fill_missing_pov_voices(self.project, self.book, self.proposal(povs), provider)
        self.assertEqual(len(written), 10)
        sizes = [len(capsule["characters"]) for capsule in provider.capsules]
        self.assertEqual(sizes, [self.bf.DESIGN_VOICE_SLICE_SIZE, self.bf.DESIGN_VOICE_SLICE_SIZE, 2])
        for capsule in provider.capsules:
            self.assertLessEqual(len(capsule["characters"]), self.bf.DESIGN_VOICE_SLICE_SIZE)

    def test_a_pov_who_is_not_in_canon_at_all_is_left_to_validation(self):
        """There is no file to write a block into; the unknown import is the finding."""
        provider = VoiceProvider()
        self.assertEqual(self.bf._fill_missing_pov_voices(self.project, self.book, self.proposal(["CHR-9999"]), provider), [])
        self.assertEqual(provider.capsules, [])


class TheGuardAsksTheCharacterNotTheBlockTests(PovVoiceFixture):
    def blocking(self, proposal):
        return [row for row in self.bf.validate_book_design(self.project, self.book, proposal)
                if row["severity"] == "blocking"]

    def test_a_pov_whose_voice_block_does_not_exist_is_blocking(self):
        """The requirement used to disappear exactly when the block was missing."""
        codes = [row for row in self.blocking(self.proposal(["CHR-0002"])) if row["code"] == "chapter.import-pov"]
        self.assertEqual(codes[0]["missing"], ["CHR-0002#voice"])

    def test_the_same_book_validates_once_the_voice_has_been_written(self):
        proposal = self.proposal(["CHR-0002"])
        proposal["chapters"][0]["imports"].append("PLC-0001#summary")
        (self.canon / "places" / "PLC-0001.md").write_text(
            "---\nid: PLC-0001\ncontinuity: CNT-0001\n---\n\n# The Archive\n\n"
            "<!-- bf:block summary -->\nA drowned reading room.\n", encoding="utf-8",
        )
        self.bf._fill_missing_pov_voices(self.project, self.book, proposal, VoiceProvider())
        self.assertEqual([row["code"] for row in self.blocking(proposal)], [])


class TheBlockIsWrittenIntoTheFileTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def test_a_block_is_appended_when_it_is_not_there(self):
        text = "---\nid: CHR-0002\n---\n\n# Weyr\n\n<!-- bf:block summary -->\nHe breaks dams.\n"
        out = self.bf._with_canon_block(text, "voice", "Short sentences. He counts locks.")
        self.assertIn("<!-- bf:block summary -->\nHe breaks dams.", out)
        self.assertTrue(out.rstrip().endswith("Short sentences. He counts locks."))

    def test_a_block_that_already_stands_is_replaced_in_place(self):
        text = (
            "---\nid: CHR-0002\n---\n\n# Weyr\n\n<!-- bf:block summary -->\nHe breaks dams.\n"
            "\n<!-- bf:block voice -->\nold\n\n<!-- bf:block past -->\nA lock at fourteen.\n"
        )
        out = self.bf._with_canon_block(text, "voice", "new")
        self.assertNotIn("old", out)
        self.assertIn("<!-- bf:block voice -->\nnew", out)
        self.assertIn("<!-- bf:block past -->\nA lock at fourteen.", out, "the blocks after it survive")
        self.assertEqual(out.count("bf:block voice"), 1)


if __name__ == "__main__":
    unittest.main()
