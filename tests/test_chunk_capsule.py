import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"
WORLD = "The tide comes in twice and the salt is counted. " * 400


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_chunk_capsule", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROLE_VARIANTS = {name: spec[1] for name, spec in load_module().ROLE_SPECS.items()}


class CapsuleProvider:
    """Records every capsule it is handed, and can refuse a chunk by length."""

    def __init__(self, bf, chapter_count=9, empty_until_reduced=()):
        self.bf = bf
        self.chapter_count = chapter_count
        self.empty_until_reduced = set(empty_until_reduced)
        self.capsules = []

    def _answer(self, envelope, payload, role, finish="stop"):
        return {
            "text": json.dumps(payload) if finish == "stop" else '{"withheld":[',
            "provider": "openrouter", "model": MODEL, "variant": ROLE_VARIANTS.get(role, "high"),
            "session_id": f"ses-{len(self.capsules)}", "tokens": {"input": 100, "output": 200},
            "cost": 0.001, "latency_ms": 5, "finish": finish,
        }

    def __call__(self, role, envelope, attempt_dir):
        task = envelope["payload"]["task"]
        if role == "canon-auditor":
            payload = {"findings": []}
            if "neighbourhood_digest" not in task["design_scope"]:
                payload["open_promises"] = []
            return self._answer(envelope, payload, role)
        chunk = task.get("chunk") or {}
        category = chunk.get("category")
        self.capsules.append(task)
        if category in self.empty_until_reduced and "worldbuilding" in task:
            return self._answer(envelope, {}, role, finish="length")
        if category == "spine":
            return self._answer(envelope, {
                "premise": "A warden decides.", "entry_state": {"CHR-0001": "here"},
                "arc": ["refusal", "cost", "choice"], "exit_boundary": {"CHR-0001": "gone"},
                "chapter_count": self.chapter_count,
            }, role)
        if category == "withheld":
            return self._answer(envelope, {"withheld": [{
                "id": "WH-0001", "fact": "The gods are the machines they came in.",
                "seen_as": "six machines fed and prayed to", "revealed_in": "CH-0006",
                "told_by": "CHR-0008", "never_write": ["ship"],
            }]}, role)
        first, last = int(chunk["first_order"]), int(chunk["last_order"])
        if category == "outline":
            return self._answer(envelope, {"chapter_outline": [
                {"id": f"CH-{i:04d}", "order": i, "title": "The Dawn Warden", "pov": "CHR-0001", "summary": "s"}
                for i in range(first, last + 1)
            ]}, role)
        return self._answer(envelope, {"chapters": [
            {
                "id": f"CH-{i:04d}", "order": i, "title": "The Dawn Warden", "pov": "CHR-0001",
                "beats": ["She counts the light and the ledger is short"], "plants": [], "reveals": [],
                "target_words": 900, "imports": ["UNI-0001#kernel"], "obligations": [], "pivotal": None,
            }
            for i in range(first, last + 1)
        ]}, role)


class ChunkCapsuleFixture(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["chorus"] = {"enabled": False, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        (self.project / "universe" / "worldbuilding.md").write_text(WORLD, encoding="utf-8")
        self.book = self.bf.add_book(self.project, "Landfall")["id"]
        (self.project / f"books/{self.book}/book-brief.json").write_text(json.dumps({
            "schema": 1, "premise": "A warden decides.", "characters": ["Binta"], "plot": ["walk"],
            "tone": "quiet", "reader_knowledge": "The reader is not told where this is.",
        }))

    def design(self, provider):
        return self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)

    def by_category(self, provider, category):
        return [row for row in provider.capsules if (row.get("chunk") or {}).get("category") == category]


class WhatAChunkReadsTests(ChunkCapsuleFixture):
    """The withheld chunk was handed 85102 bytes of worldbuilding to return four
    rows, and came back empty three times."""

    def test_the_withheld_chunk_is_not_handed_the_worldbuilding(self):
        provider = CapsuleProvider(self.bf)
        self.design(provider)
        withheld = self.by_category(provider, "withheld")
        self.assertEqual(len(withheld), 1)
        self.assertNotIn("worldbuilding", withheld[0])

    def test_it_still_gets_what_it_needs_to_answer(self):
        provider = CapsuleProvider(self.bf)
        self.design(provider)
        capsule = self.by_category(provider, "withheld")[0]
        self.assertIn("reader_knowledge", capsule["brief"])
        self.assertEqual(capsule["spine"]["premise"], "A warden decides.")
        self.assertTrue(capsule["reveal_candidates"])
        self.assertIn("available_blocks", capsule)

    def test_the_chunks_that_invent_the_world_still_read_it(self):
        provider = CapsuleProvider(self.bf)
        self.design(provider)
        for category in ("spine", "outline", "chapters"):
            for capsule in self.by_category(provider, category):
                with self.subTest(category=category):
                    self.assertIn("worldbuilding", capsule)

    def test_the_cut_makes_the_call_much_smaller(self):
        provider = CapsuleProvider(self.bf)
        self.design(provider)
        withheld = len(json.dumps(self.by_category(provider, "withheld")[0]))
        spine = len(json.dumps(self.by_category(provider, "spine")[0]))
        self.assertLess(withheld, spine // 2)


class ARangelessChunkHasAWayDownTests(ChunkCapsuleFixture):
    """`_halve_chunk` splits on a range of chapters, so the spine, the withheld
    list and a repair had nothing between an empty answer and a blocked design."""

    def test_a_chunk_that_answers_only_without_the_world_still_finishes_the_design(self):
        provider = CapsuleProvider(self.bf, empty_until_reduced=("spine",))
        self.assertEqual(self.design(provider)["state"], "design_clean")
        spines = self.by_category(provider, "spine")
        self.assertEqual(len(spines), 4, "three attempts on the full capsule, then one on the reduced one")
        self.assertIn("worldbuilding", spines[0])
        self.assertNotIn("worldbuilding", spines[-1])

    def test_the_reduced_call_is_a_last_resort_and_never_the_first(self):
        provider = CapsuleProvider(self.bf)
        self.design(provider)
        for capsule in self.by_category(provider, "spine"):
            self.assertIn("worldbuilding", capsule)

    def test_a_chunk_with_a_range_is_still_halved_rather_than_stripped(self):
        provider = CapsuleProvider(self.bf, chapter_count=9, empty_until_reduced=("outline",))
        with self.assertRaises(self.bf.BookForgeError):
            self.design(provider)
        for capsule in self.by_category(provider, "outline"):
            self.assertIn("worldbuilding", capsule, "an outline slice halves; it is never stripped")

    def test_a_chunk_that_never_answers_still_blocks_the_task(self):
        class Hopeless(CapsuleProvider):
            def __call__(self, role, envelope, attempt_dir):
                task = envelope["payload"]["task"]
                if (task.get("chunk") or {}).get("category") == "spine":
                    self.capsules.append(task)
                    return self._answer(envelope, {}, role, finish="length")
                return super().__call__(role, envelope, attempt_dir)

        provider = Hopeless(self.bf)
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.design(provider)
        self.assertIn("failed_length", str(caught.exception))
        self.assertEqual(len(self.by_category(provider, "spine")), 6)


if __name__ == "__main__":
    unittest.main()
