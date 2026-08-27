import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_slices", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROLE_VARIANTS = {name: spec[1] for name, spec in load_module().ROLE_SPECS.items()}
CHAPTER_COUNT = 40


class SliceProvider:
    """A designer that can only answer one slice per call.

    Any call asking for more than BOOK_DESIGN_SLICE_SIZE chapters comes back
    truncated, the way the real provider does once reasoning has eaten the
    output budget. A design that completes here is one the engine sliced itself.
    """

    def __init__(self, bf, chapter_count=CHAPTER_COUNT):
        self.bf = bf
        self.chapter_count = chapter_count
        self.chunks = []
        self.capsules = []
        self.calls = 0

    def _truncated(self, envelope):
        return {
            "text": '{"chapters":[{"id":"CH-0001"',
            "provider": "openrouter", "model": MODEL, "variant": "medium",
            "session_id": f"ses-{self.calls}", "tokens": {"input": envelope["estimated_input_tokens"], "output": 12288},
            "cost": 0.01, "latency_ms": 5, "finish": "length",
        }

    def _ok(self, envelope, payload, role="designer"):
        return {
            "text": json.dumps(payload),
            "provider": "openrouter", "model": MODEL, "variant": ROLE_VARIANTS.get(role, "high"),
            "session_id": f"ses-{self.calls}", "tokens": {"input": envelope["estimated_input_tokens"], "output": 800},
            "cost": 0.01, "latency_ms": 5, "finish": "stop",
        }

    def __call__(self, role, envelope, attempt_dir):
        self.calls += 1
        if role.startswith("advisor-") or role == "chorus-synthesizer":
            return self._ok(envelope, {"findings": [], "suggestions": []}, role)
        task = envelope["payload"]["task"]
        if role != "designer":
            return self._ok(envelope, {"findings": []}, role)
        chunk = task.get("chunk")
        self.chunks.append(chunk)
        self.capsules.append(task)
        if chunk is None:
            return self._truncated(envelope)
        if chunk.get("category") == "spine":
            return self._ok(envelope, {
                "premise": "A diver must decide whether memory can be owned.",
                "entry_state": {"CHR-0001": "isolated"},
                "arc": ["refusal", "cost", "choice"],
                "exit_boundary": {"CHR-0001": "committed"},
                "chapter_outline": [
                    {"id": f"CH-{index:04d}", "order": index, "title": f"The Ninth Tide {index}", "pov": "CHR-0001", "summary": "She goes down again."}
                    for index in range(1, self.chapter_count + 1)
                ],
            })
        first, last = int(chunk["first_order"]), int(chunk["last_order"])
        if last - first + 1 > self.bf.BOOK_DESIGN_SLICE_SIZE:
            return self._truncated(envelope)
        return self._ok(envelope, {"chapters": [
            {
                "id": f"CH-{index:04d}", "order": index, "title": f"The Ninth Tide {index}",
                "pov": "CHR-0001", "beats": ["She wants the log and the warden will not open it"],
                "plants": [], "reveals": [], "target_words": 3000,
                "imports": ["UNI-0001#kernel"], "obligations": [], "pivotal": None,
            }
            for index in range(first, last + 1)
        ]})


class BookDesignSliceFixture(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["chorus"] = {"enabled": False, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.book = self.bf.add_book(self.project, "A")["id"]
        (self.project / f"books/{self.book}/book-brief.json").write_text(
            json.dumps({"schema": 1, "premise": "A diver must decide.", "characters": ["Mara"], "plot": ["dive"], "tone": "quiet", "length_notes": "40 chapters"})
        )


class SliceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def test_forty_chapters_split_into_slices_of_eight(self):
        chunks = self.bf._book_design_chunks(40)
        self.assertEqual(len(chunks), 5)
        self.assertEqual([(c["first_order"], c["last_order"]) for c in chunks], [(1, 8), (9, 16), (17, 24), (25, 32), (33, 40)])
        self.assertEqual([self.bf._chunk_slug(c) for c in chunks][:2], ["chapters-1-8", "chapters-9-16"])

    def test_a_short_book_gets_one_slice_and_a_ragged_tail_is_kept(self):
        self.assertEqual([(c["first_order"], c["last_order"]) for c in self.bf._book_design_chunks(3)], [(1, 3)])
        self.assertEqual(self.bf._book_design_chunks(10)[-1]["last_order"], 10)


class BookDesignSliceTests(BookDesignSliceFixture):
    def test_a_forty_chapter_design_completes_against_a_one_slice_provider(self):
        provider = SliceProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)

        outline = json.loads((self.project / f"books/{self.book}/outline.yaml").read_text())
        self.assertEqual(len(outline["chapters"]), CHAPTER_COUNT)
        self.assertEqual([row["order"] for row in outline["chapters"]], list(range(1, CHAPTER_COUNT + 1)))
        self.assertTrue((self.project / f"books/{self.book}/chapters/CH-0040.json").is_file())
        self.assertIn("memory can be owned", (self.project / f"books/{self.book}/design.md").read_text())

    def test_the_engine_asks_for_the_spine_then_one_slice_at_a_time(self):
        provider = SliceProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        categories = [chunk["category"] for chunk in provider.chunks]
        self.assertEqual(categories[0], "spine")
        self.assertEqual(categories[1:], ["chapters"] * 5)
        for chunk in provider.chunks[1:]:
            self.assertLessEqual(int(chunk["last_order"]) - int(chunk["first_order"]) + 1, self.bf.BOOK_DESIGN_SLICE_SIZE)

    def test_every_slice_call_carries_the_spine_and_the_outline(self):
        provider = SliceProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        spine_capsule, *slice_capsules = provider.capsules
        self.assertNotIn("spine", spine_capsule)
        for capsule in slice_capsules:
            self.assertEqual(capsule["spine"]["premise"], "A diver must decide whether memory can be owned.")
            self.assertEqual(len(capsule["chapter_outline"]), CHAPTER_COUNT)

    def test_no_call_is_ever_asked_for_the_whole_book(self):
        provider = SliceProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        self.assertTrue(all(chunk is not None for chunk in provider.chunks))

    def test_the_capsule_no_longer_begs_the_model_to_chunk_itself(self):
        provider = SliceProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        for capsule in provider.capsules:
            self.assertNotIn("chunking", capsule)

    def test_a_spine_without_an_outline_blocks_instead_of_designing_nothing(self):
        provider = SliceProvider(self.bf, chapter_count=0)
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        self.assertIn("chapter_outline", str(caught.exception))

    def test_each_slice_is_accounted_for_separately_in_the_receipt(self):
        provider = SliceProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        receipts = [json.loads(path.read_text()) for path in (self.project / ".book-forge" / "runs").rglob("execution-receipt.json")]
        chunked = [row["chunk_telemetry"] for row in receipts if row.get("chunk_telemetry")]
        self.assertEqual(len(chunked), 1)
        self.assertEqual([row["chunk"] for row in chunked[0]], ["spine", "chapters-1-8", "chapters-9-16", "chapters-17-24", "chapters-25-32", "chapters-33-40"])


if __name__ == "__main__":
    unittest.main()
