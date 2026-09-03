import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"
GLM = "openrouter/z-ai/glm-5.3-flash"
QWEN = "openrouter/qwen/qwen3.8-flash"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_writer_pin", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_response(words=700):
    return json.dumps({
        "prose_markdown": "# The Signal\n\n" + " ".join(["memory"] * words),
        "beat_map": [{"beat": "Find the signal", "evidence": "The signal is found."}],
        "consequences": [{"scope": "book", "fact": "The signal is known.", "entities": ["CHR-0001"]}],
    })


class EnvelopePinnedProvider:
    """Answers as whatever model the envelope says will answer it.

    A provider that reported a fixed model would pass the receipt check by luck.
    Reading the pin out of the envelope makes the test fail when the envelope
    stops carrying it, which is the thing being guarded.
    """

    def __init__(self, unusable=(), words=700):
        self.unusable = set(unusable)
        self.words = words
        self.calls = []

    def __call__(self, role, envelope, attempt_dir):
        payload = envelope["payload"]
        self.calls.append({
            "role": role,
            "model": payload["model"],
            "variant": payload["variant"],
            "hash": envelope["hash"],
            "task": payload["task"],
        })
        text = "not a contract" if payload["model"] in self.unusable else valid_response(self.words)
        return {
            "text": text,
            "provider": "openrouter",
            "model": payload["model"],
            "variant": payload["variant"],
            "session_id": f"ses-{len(self.calls)}",
            "tokens": {"input": envelope["estimated_input_tokens"], "output": 500},
            "cost": 0.002,
            "latency_ms": 100,
            "finish": "stop",
        }


class WriterPinFixture(unittest.TestCase):
    """Landfall's design closed with no chapter written, so the prose model could
    still be chosen. It could not be changed on its own: every role read one
    constant, and moving the writer moved the canon-auditor with it."""

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
            "schema": 1, "book": self.book, "id": "CH-0001", "order": 1,
            "pov": "CHR-0001", "beats": ["Find the signal"], "plants": [], "reveals": [],
            "target_words": 700, "imports": ["UNI-0001#kernel"], "pivotal": None,
            "title": "The Dawn Barge",
        }
        (chapters / "CH-0001.json").write_text(json.dumps(self.contract))

    def pin_writer(self, **override):
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["roles"] = {"writer": override}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        return config

    def agent(self, name):
        return (self.project / ".opencode" / "agents" / f"{name}.md").read_text(encoding="utf-8")


class ARoleCarriesItsOwnPinTests(WriterPinFixture):
    def test_an_overridden_writer_is_the_only_role_that_moves(self):
        self.pin_writer(model=GLM)
        self.bf.sync_runtime(self.project)
        self.assertIn(f"model: {GLM}", self.agent("writer"))
        self.assertIn(f"model: {MODEL}", self.agent("designer"))
        self.assertIn(f"model: {MODEL}", self.agent("canon-auditor"))

    def test_an_effort_the_new_model_does_not_offer_falls_to_the_one_it_declares(self):
        """The writer runs at `low`, and qwen3.8-flash has no `low` to run at."""
        self.assertEqual(self.bf.ROLE_SPECS["writer"][1], "low")
        self.assertEqual(self.bf._role_pin({"roles": {"writer": {"model": QWEN}}}, "writer"), (QWEN, "high"))

    def test_a_variant_outside_the_ladder_is_refused_and_the_ladder_is_named(self):
        with self.assertRaises(self.bf.BookForgeError) as raised:
            self.bf._role_pin({"roles": {"writer": {"model": QWEN, "variant": "low"}}}, "writer")
        self.assertIn("high", str(raised.exception))
        self.assertIn(QWEN, str(raised.exception))

    def test_a_model_the_catalogue_never_configured_is_refused(self):
        with self.assertRaises(self.bf.BookForgeError) as raised:
            self.bf._role_pin({"roles": {"writer": {"model": "openrouter/acme/typewriter"}}}, "writer")
        self.assertIn("typewriter", str(raised.exception))

    def test_a_project_that_names_no_role_keeps_every_pin_where_it_was(self):
        for role, (_mode, variant, _steps) in self.bf.ROLE_SPECS.items():
            if role == "translation-critic":
                continue  # its default is deliberately not the translator's model
            self.assertEqual(self.bf._role_pin({}, role), (MODEL, variant))

    def test_the_critic_never_defaults_to_the_translator(self):
        """A model rereading its own rendering approves it."""
        for translator in (MODEL, GLM, QWEN, self.bf.CHORUS_SYNTHESIZER):
            config = {"roles": {"translator": {"model": translator}}}
            critic = self.bf._role_pin(config, "translation-critic")[0]
            self.assertNotEqual(critic, self.bf._role_pin(config, "translator")[0])
            self.assertIn(critic, self.bf.CHORUS_MODEL_CONFIGS)

    def test_a_critic_pinned_to_the_translator_is_refused_with_the_reason(self):
        config = {"roles": {"translator": {"model": GLM}, "translation-critic": {"model": GLM}}}
        with self.assertRaises(self.bf.BookForgeError) as raised:
            self.bf._role_pin(config, "translation-critic")
        self.assertIn("approved, not audited", str(raised.exception))

    def test_the_generated_catalogue_carries_a_pin_the_chorus_does_not(self):
        config = {"roles": {"writer": {"model": "openrouter/z-ai/glm-5.3"}}}
        catalogue = self.bf._opencode_config([MODEL], config)["provider"]["openrouter"]["models"]
        self.assertIn("z-ai/glm-5.3", catalogue)

    def test_the_receipt_is_measured_against_the_override(self):
        """An override moves what it names and nothing else: glm-5.3-flash has a
        `low` step, so a writer pinned to it without an effort keeps the writer's."""
        self.pin_writer(model=GLM)
        provider = EnvelopePinnedProvider()
        result = self.bf.draft_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(result["receipt"]["model"], GLM)
        self.assertEqual(result["receipt"]["variant"], "low")

    def test_an_effort_can_be_named_beside_the_model(self):
        self.pin_writer(model=GLM, variant="high")
        result = self.bf.draft_chapter(self.project, self.book, "CH-0001", provider=EnvelopePinnedProvider())
        self.assertEqual((result["receipt"]["model"], result["receipt"]["variant"]), (GLM, "high"))

    def test_a_receipt_from_the_model_nobody_asked_for_is_still_refused(self):
        self.pin_writer(model=GLM)

        class WrongModelProvider(EnvelopePinnedProvider):
            def __call__(self, role, envelope, attempt_dir):
                answer = super().__call__(role, envelope, attempt_dir)
                return {**answer, "model": MODEL}

        with self.assertRaises(self.bf.BookForgeError) as raised:
            self.bf.draft_chapter(self.project, self.book, "CH-0001", provider=WrongModelProvider())
        self.assertIn("pinned OpenRouter model", str(raised.exception))


class TheSameChapterAskedOfSeveralModelsTests(WriterPinFixture):
    def bakeoff(self, models=(MODEL, GLM, QWEN), provider=None):
        provider = provider or EnvelopePinnedProvider()
        index = self.bf.draft_bakeoff(self.project, self.book, "CH-0001", list(models), provider=provider)
        return index, provider

    def test_every_candidate_leaves_a_draft_and_none_is_promoted(self):
        index, provider = self.bakeoff()
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual({row["state"] for row in index["candidates"]}, {"drafted"})
        self.assertIsNone(index["promoted"])
        for row in index["candidates"]:
            self.assertTrue((self.project / row["draft"]).is_file())
        self.assertFalse((self.project / f"books/{self.book}/work/CH-0001/draft.md").exists())

    def test_the_index_says_what_each_candidate_was_and_what_it_cost(self):
        index, _ = self.bakeoff()
        by_model = {row["model"]: row for row in index["candidates"]}
        self.assertEqual(set(by_model), {MODEL, GLM, QWEN})
        for row in by_model.values():
            self.assertEqual(row["variant"], "high")
            self.assertEqual(row["target_words"], 700)
            self.assertGreater(row["words"], 0)
            self.assertEqual(row["cost"], 0.002)

    def test_each_candidate_is_asked_the_same_question_under_a_different_pin(self):
        _, provider = self.bakeoff()
        self.assertEqual(len({call["model"] for call in provider.calls}), 3)
        self.assertEqual(len({call["hash"] for call in provider.calls}), 3)
        capsules = [json.dumps(call["task"], sort_keys=True) for call in provider.calls]
        self.assertEqual(len(set(capsules)), 1)
        self.assertEqual({call["variant"] for call in provider.calls}, {"high"})

    def test_a_candidate_that_writes_nothing_usable_is_recorded_and_the_others_land(self):
        index, provider = self.bakeoff(provider=EnvelopePinnedProvider(unusable={QWEN}))
        by_model = {row["model"]: row for row in index["candidates"]}
        self.assertEqual(by_model[QWEN]["state"], "unusable")
        self.assertNotIn("draft", by_model[QWEN])
        self.assertEqual(by_model[MODEL]["state"], "drafted")
        self.assertEqual(by_model[GLM]["state"], "drafted")
        self.assertTrue((self.project / by_model[GLM]["draft"]).is_file())

    def test_the_candidates_write_to_their_own_directories(self):
        index, _ = self.bakeoff(models=(MODEL, GLM))
        paths = {row["draft"] for row in index["candidates"]}
        self.assertEqual(len(paths), 2)
        for path in paths:
            self.assertIn(f"books/{self.book}/work/CH-0001/bakeoff/", path)

    def test_a_bakeoff_of_one_model_is_not_a_comparison(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.draft_bakeoff(self.project, self.book, "CH-0001", [MODEL], provider=EnvelopePinnedProvider())

    def test_a_model_can_be_named_the_short_way(self):
        index, _ = self.bakeoff(models=("deepseek-v4-flash-0731", "glm-5.3-flash"))
        self.assertEqual({row["model"] for row in index["candidates"]}, {MODEL, GLM})

    def test_a_candidate_gets_the_writer_prompt_and_the_writer_budget(self):
        _, provider = self.bakeoff(models=(MODEL, GLM))
        for call in provider.calls:
            self.assertTrue(call["role"].startswith("writer-"))
        agents = self.project / ".opencode" / "agents"
        self.assertIn("Book Forge writer role", (agents / f"writer-{self.bf._chorus_slug(GLM)}.md").read_text())


class TheReviserFollowsTheWriterTests(WriterPinFixture):
    """The bake-off chose landfall's writer by reading three drafts of CH-0001. The
    reviser writes prose too — it applies the cold reader's and the technical
    editor's findings sentence by sentence — and it was never pinned, so the book
    was written on `glm-5.3-flash` at `high` and repaired on the project default at
    `low`: two hands on the same paragraph."""

    def test_a_project_that_pins_only_the_writer_gets_that_hand_for_both(self):
        config = {"roles": {"writer": {"model": GLM, "variant": "high"}}}
        self.assertEqual(self.bf._role_pin(config, "reviser"), self.bf._role_pin(config, "writer"))
        self.assertEqual(self.bf._role_pin(config, "reviser"), (GLM, "high"))

    def test_a_project_that_pins_both_keeps_them_apart(self):
        config = {"roles": {"writer": {"model": GLM, "variant": "high"}, "reviser": {"variant": "low"}}}
        self.assertEqual(self.bf._role_pin(config, "reviser"), (MODEL, "low"), "saying so is how you get two hands")

    def test_a_project_that_pins_neither_is_unchanged(self):
        self.assertEqual(self.bf._role_pin({}, "reviser"), (MODEL, self.bf.ROLE_SPECS["reviser"][1]))

    def test_pinning_the_writer_does_not_move_any_other_role(self):
        config = {"roles": {"writer": {"model": GLM, "variant": "high"}}}
        for role in ("cold-reader", "technical-editor", "canon-auditor", "judge"):
            self.assertEqual(self.bf._role_pin(config, role), (MODEL, self.bf.ROLE_SPECS[role][1]))



class TheCatalogueHoldsABatchModelTests(WriterPinFixture):
    """The translation critic is 53 calls and $4.50 of this project's $7.94 — 57% of
    the spend for 13% of the volume — because it reasons 27510 tokens per call and
    reasoning bills at the completion rate. The batch variant is the same model at
    half price, and a role that already takes seven minutes cannot notice the
    latency."""

    BATCH = "openrouter/google/gemini-3.8-flash:batch"

    def test_the_batch_variant_is_a_model_the_catalogue_configures(self):
        self.assertIn(self.BATCH, self.bf.CHORUS_MODEL_CONFIGS)
        cfg = self.bf.CHORUS_MODEL_CONFIGS[self.BATCH]
        self.assertIn("provider", cfg, "a catalogue model carries its provider pin")
        self.assertTrue(cfg["variants"], "and an effort ladder")

    def test_it_resolves_as_a_critic_pin(self):
        config = {"roles": {
            "translator": {"model": GLM, "variant": "high"},
            "translation-critic": {"model": self.BATCH, "variant": "high"},
        }}
        self.assertEqual(self.bf._role_pin(config, "translation-critic"), (self.BATCH, "high"))

    def test_it_is_refused_as_the_critic_when_it_is_also_the_translator(self):
        """A model rereading its own rendering approves its own blind spots, and
        that holds for a batch variant like any other."""
        config = {"roles": {
            "translator": {"model": self.BATCH},
            "translation-critic": {"model": self.BATCH},
        }}
        with self.assertRaises(self.bf.BookForgeError):
            self.bf._role_pin(config, "translation-critic")

    def test_a_variant_the_ladder_does_not_offer_is_still_refused(self):
        config = {"roles": {
            "translator": {"model": GLM, "variant": "high"},
            "translation-critic": {"model": self.BATCH, "variant": "max"},
        }}
        with self.assertRaises(self.bf.BookForgeError):
            self.bf._role_pin(config, "translation-critic")


if __name__ == "__main__":
    unittest.main()
