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
                "chapter_count": self.chapter_count,
            })
        first, last = int(chunk["first_order"]), int(chunk["last_order"])
        if chunk.get("category") == "outline":
            return self._ok(envelope, {"chapter_outline": [
                {"id": f"CH-{index:04d}", "order": index, "title": f"The Ninth Tide {index}", "pov": "CHR-0001", "summary": "She goes down again."}
                for index in range(first, last + 1)
            ]})
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

    def test_forty_chapters_open_at_the_width_that_answered(self):
        """Eight was the opening width and landfall measured it as too wide: its
        four-chapter slices all answered, its eight-chapter slices were halved."""
        chunks = self.bf._book_design_chunks(40)
        self.assertEqual(len(chunks), 10)
        self.assertEqual([(c["first_order"], c["last_order"]) for c in chunks][:3], [(1, 4), (5, 8), (9, 12)])
        self.assertEqual([self.bf._chunk_slug(c) for c in chunks][:2], ["chapters-1-4", "chapters-5-8"])

    def test_a_short_book_gets_one_slice_and_a_ragged_tail_is_kept(self):
        self.assertEqual([(c["first_order"], c["last_order"]) for c in self.bf._book_design_chunks(3)], [(1, 3)])
        self.assertEqual(self.bf._book_design_chunks(10)[-1]["last_order"], 10)


class TruncationSplitTests(BookDesignSliceFixture):
    """A truncation says the answer asked for does not fit. Repeating the same
    request has no reason to succeed, and each repeat is paid for."""

    def test_a_provider_that_cannot_write_more_than_four_chapters_still_finishes(self):
        provider = SliceProvider(self.bf)
        provider.bf.BOOK_DESIGN_SLICE_SIZE = self.bf.BOOK_DESIGN_SLICE_SIZE
        original = provider._ok

        def limited(role, envelope, attempt_dir):
            task = envelope["payload"]["task"]
            chunk = task.get("chunk") or {}
            if chunk.get("category") == "chapters":
                width = int(chunk["last_order"]) - int(chunk["first_order"]) + 1
                if width > 4:
                    provider.calls += 1
                    provider.chunks.append(chunk)
                    return provider._truncated(envelope)
            return SliceProvider.__call__(provider, role, envelope, attempt_dir)

        self.bf.execute_book_design(self.project, self.book, provider=limited, no_chorus=True, no_post_chorus=True)
        outline = json.loads((self.project / f"books/{self.book}/outline.yaml").read_text())["chapters"]
        self.assertEqual([row["order"] for row in outline], list(range(1, CHAPTER_COUNT + 1)))
        widths = [int(c["last_order"]) - int(c["first_order"]) + 1 for c in provider.chunks if c.get("category") == "chapters"]
        self.assertTrue(any(width <= 4 for width in widths), "the engine must have asked for less")

    def test_halving_walks_down_to_a_single_chapter(self):
        chunk = {"category": "chapters", "part": "1-8", "first_order": 1, "last_order": 8}
        halves = self.bf._halve_chunk(chunk)
        self.assertEqual([(h["first_order"], h["last_order"]) for h in halves], [(1, 4), (5, 8)])
        self.assertEqual([(h["first_order"], h["last_order"]) for h in self.bf._halve_chunk(halves[0])], [(1, 2), (3, 4)])
        self.assertEqual(self.bf._halve_chunk({"category": "chapters", "first_order": 3, "last_order": 3}), [])

    def test_a_non_chapter_chunk_is_not_split(self):
        self.assertEqual(self.bf._halve_chunk({"category": "spine"}), [])

    def test_a_single_chapter_that_keeps_truncating_fails(self):
        def always_truncate(role, envelope, attempt_dir):
            task = envelope["payload"]["task"]
            if (task.get("chunk") or {}).get("category") == "chapters":
                provider.calls += 1
                return provider._truncated(envelope)
            return SliceProvider.__call__(provider, role, envelope, attempt_dir)

        provider = SliceProvider(self.bf, chapter_count=2)
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.execute_book_design(self.project, self.book, provider=always_truncate, no_chorus=True, no_post_chorus=True)
        self.assertIn("failed_length", str(caught.exception))


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
        self.assertEqual(categories[1:5], ["outline"] * 4)
        self.assertEqual(set(categories[5:]), {"chapters"})
        self.assertGreaterEqual(categories.count("chapters"), 5)
        for chunk in provider.chunks[1:]:
            width = int(chunk["last_order"]) - int(chunk["first_order"]) + 1
            ceiling = self.bf.BOOK_OUTLINE_SLICE_SIZE if chunk["category"] == "outline" else self.bf.BOOK_DESIGN_SLICE_SIZE
            self.assertLessEqual(width, ceiling)

    def test_the_spine_is_asked_for_a_number_and_never_for_the_chapters(self):
        """The spine is the one chunk that cannot be halved, so it is the one chunk
        whose answer must not grow with the book: 15822 bytes cut off mid-sentence,
        then twice reasoning 31999 and output 0."""
        provider = SliceProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        spine_capsule = provider.capsules[0]
        self.assertIn("chapter_count", json.dumps(spine_capsule["required_output"]))
        self.assertNotIn("chapter_outline", json.dumps(spine_capsule["required_output"]))

    def test_every_slice_call_carries_the_spine_and_the_outline(self):
        provider = SliceProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        spine_capsule, *slice_capsules = provider.capsules
        self.assertNotIn("spine", spine_capsule)
        for capsule in slice_capsules:
            self.assertEqual(capsule["spine"]["premise"], "A diver must decide whether memory can be owned.")
        for capsule in (row for row in slice_capsules if row["chunk"]["category"] == "chapters"):
            orders = [row["order"] for row in capsule["chapter_outline"]]
            first, last = int(capsule["chunk"]["first_order"]), int(capsule["chunk"]["last_order"])
            self.assertLessEqual(len(orders), self.bf.BOOK_DESIGN_SLICE_SIZE + 2 * self.bf.DESIGN_NEIGHBOURS)
            self.assertLessEqual(min(orders), first)
            self.assertGreaterEqual(max(orders), min(last, CHAPTER_COUNT))

    def test_every_slice_gets_the_same_spine_and_never_another_slice_s_chapters(self):
        provider = SliceProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        spines = [capsule["spine"] for capsule in provider.capsules[1:]]
        chapter_slices = [row for row in provider.capsules[1:] if row["chunk"]["category"] == "chapters"]
        self.assertEqual(len(spines), len(chapter_slices) + 4, "one spine per chapter slice plus the four outline slices")
        for spine in spines:
            self.assertNotIn("chapters", spine)
            self.assertEqual(spine, spines[0])

    def test_a_chapter_slice_envelope_does_not_grow_as_the_book_is_written(self):
        """The spine used to swallow each slice's chapters and the envelope doubled.
        Now the digest and the outline are windows, so the last slice of a book
        costs what the first one did."""
        provider = SliceProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        slices = [row for row in provider.capsules[1:] if row["chunk"]["category"] == "chapters"]
        varying = {"written_so_far", "chunk", "chapter_outline"}
        fixed = [len(json.dumps({k: v for k, v in capsule.items() if k not in varying}, sort_keys=True)) for capsule in slices]
        self.assertEqual(len(set(fixed)), 1, "everything but the windows must stay constant across slices")
        # The first slice has nothing written before it; from the second on every
        # slice carries a full window, and a full window is the same size wherever
        # in the book it sits.
        # A window at the end of the book is clipped by the book's end, so the last
        # slice is a little smaller. What must not happen is the other direction.
        sizes = [len(json.dumps(capsule, sort_keys=True)) for capsule in slices[1:]]
        self.assertLess(max(sizes) - min(sizes), max(sizes) // 4, "slices past the first must all cost about the same")
        self.assertLessEqual(sizes[-1], max(sizes), "the last slice must not be the most expensive one")

    def test_the_merged_proposal_still_gathers_every_slice_in_order(self):
        provider = SliceProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        outline = json.loads((self.project / f"books/{self.book}/outline.yaml").read_text())["chapters"]
        self.assertEqual([row["id"] for row in outline], [f"CH-{index:04d}" for index in range(1, CHAPTER_COUNT + 1)])

    def test_a_slice_sees_the_chapters_just_before_it_and_none_of_its_own(self):
        provider = SliceProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        slices = [row for row in provider.capsules[1:] if row["chunk"]["category"] == "chapters"]
        window = [len(capsule["written_so_far"]) for capsule in slices]
        self.assertEqual(window[0], 0, "the first slice has nothing written before it")
        self.assertTrue(all(size == self.bf.DESIGN_NEIGHBOURS for size in window[1:]), window)
        for capsule in slices:
            seen = {row["id"] for row in capsule["written_so_far"]}
            first = int(capsule["chunk"]["first_order"])
            self.assertNotIn(f"CH-{first:04d}", seen)
            if first > 1:
                self.assertIn(f"CH-{first - 1:04d}", seen)

    def test_the_digest_carries_the_promises_and_never_the_beats(self):
        provider = SliceProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        digest = [row for row in provider.capsules if row["chunk"]["category"] == "chapters"][-1]["written_so_far"]
        self.assertTrue(digest)
        for row in digest:
            self.assertEqual(sorted(row), ["id", "order", "plants", "pov", "reveals", "title"])

    def test_no_call_is_ever_asked_for_the_whole_book(self):
        provider = SliceProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        self.assertTrue(all(chunk is not None for chunk in provider.chunks))

    def test_the_capsule_no_longer_begs_the_model_to_chunk_itself(self):
        provider = SliceProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        for capsule in provider.capsules:
            self.assertNotIn("chunking", capsule)

    def test_a_spine_that_names_no_chapters_blocks_instead_of_designing_nothing(self):
        provider = SliceProvider(self.bf, chapter_count=0)
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        self.assertIn("chapter count", str(caught.exception))

    def test_each_slice_is_accounted_for_separately_in_the_receipt(self):
        provider = SliceProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)
        receipts = [json.loads(path.read_text()) for path in (self.project / ".book-forge" / "runs").rglob("execution-receipt.json")]
        chunked = [row["chunk_telemetry"] for row in receipts if row.get("chunk_telemetry")]
        self.assertEqual(len(chunked), 1)
        slugs = [row["chunk"] for row in chunked[0]]
        self.assertEqual(slugs[:5], [
            "spine", "outline-1-12", "outline-13-24", "outline-25-36", "outline-37-40",
        ])
        # Every chapter accounted for once, however the slices came out: the width
        # is decided from what this book's own slices cost, so the count is not a
        # constant a test may hard-code.
        covered = []
        for slug in slugs[5:]:
            first, last = (int(part) for part in slug.removeprefix("chapters-").split("-"))
            covered.extend(range(first, last + 1))
        self.assertEqual(covered, list(range(1, CHAPTER_COUNT + 1)))



class WrappedAnswerTests(BookDesignSliceFixture):
    """A designer asked for the book's spine replied {"spine": {...}} — the whole
    thing, correct, wrapped in the name of what it was asked for. Forty outline rows
    were produced, paid for and discarded, twice."""

    def test_a_spine_wrapped_in_its_own_name_is_taken(self):
        provider = SliceProvider(self.bf)

        def wrapping(role, envelope, attempt_dir):
            result = SliceProvider.__call__(provider, role, envelope, attempt_dir)
            chunk = (envelope["payload"]["task"].get("chunk") or {})
            if role == "designer" and chunk.get("category") == "spine":
                result = {**result, "text": json.dumps({"spine": json.loads(result["text"])})}
            return result

        self.bf.execute_book_design(self.project, self.book, provider=wrapping, no_chorus=True, no_post_chorus=True)
        outline = json.loads((self.project / f"books/{self.book}/outline.yaml").read_text())["chapters"]
        self.assertEqual(len(outline), CHAPTER_COUNT)

    def test_wrapped_and_bare_answers_agree(self):
        bare = {"premise": "p", "arc": ["a", "b", "c"], "chapter_outline": [{"id": "CH-0001"}]}
        self.assertEqual(self.bf._unwrap_chunk({"spine": bare}, "spine"), bare)
        self.assertEqual(self.bf._unwrap_chunk(bare, "spine"), bare)

    def test_a_capsule_that_legitimately_carries_a_spine_field_is_untouched(self):
        value = {"spine": {"premise": "p"}, "chapters": [{"id": "CH-0001"}]}
        self.assertEqual(self.bf._unwrap_chunk(value, "spine"), value)


class ASliceIsTheWidthTheBookTurnedOutToNeedTests(unittest.TestCase):
    """Landfall's per-chapter output ran 788 tokens at chapters 1-4 and 1558 at
    23-24 — a factor of two inside one book. Any single typed width is a guess that
    is wrong for the next book, and being wrong costs three empty calls per slice
    to find out."""

    def setUp(self):
        self.bf = load_module()

    def test_light_chapters_buy_a_wider_slice_than_heavy_ones(self):
        light = self.bf._design_slice_width([(4, 3151)])
        heavy = self.bf._design_slice_width([(2, 3116)])
        self.assertGreater(light, heavy)
        self.assertEqual((light, heavy), (4, 2))

    def test_the_heaviest_chapter_decides_and_not_the_average(self):
        """The chapter that overruns a slice is the one that had most to say, and
        an average lets it hide behind the light chapters beside it."""
        self.assertEqual(
            self.bf._design_slice_width([(4, 3151), (2, 3116)]),
            self.bf._design_slice_width([(2, 3116)]),
        )

    def test_nothing_measured_yet_leaves_the_opening_width_alone(self):
        self.assertIsNone(self.bf._design_slice_width([]))
        self.assertIsNone(self.bf._design_slice_width([(4, 0)]))

    def test_the_width_never_exceeds_the_opening_one_however_light_the_book(self):
        self.assertEqual(self.bf._design_slice_width([(8, 8)]), self.bf.BOOK_DESIGN_SLICE_SIZE)

    def test_a_slice_holding_a_reveal_is_narrowed_before_it_is_called(self):
        """Landfall split 17-24 to 17-20 and then to 17-18, because CH-0017 and
        CH-0018 carry the first two withheld layers. The withheld rows said so
        before any of those three calls was made."""
        plain = [c["part"] for c in self.bf._book_design_chunks(26)]
        self.assertIn("17-20", plain)
        narrowed = [c["part"] for c in self.bf._book_design_chunks(26, reveal_orders=frozenset({17, 18}))]
        self.assertIn("17-18", narrowed)
        self.assertNotIn("17-20", narrowed)

    def test_a_book_of_light_chapters_is_not_split_more_than_it_needs(self):
        chunks = self.bf._ranged_chunks("chapters", 1, 12, self.bf._design_slice_width([(4, 2000)]))
        self.assertEqual([c["part"] for c in chunks], ["1-4", "5-8", "9-12"])

    def test_the_reveal_orders_come_from_the_withheld_rows(self):
        outline = [{"id": "CH-0001", "order": 1}, {"id": "CH-0017", "order": 17}, {"id": "CH-0018", "order": 18}]
        spine = {"withheld": [{"revealed_in": "CH-0017"}, {"revealed_in": "CH-0018"}, {"revealed_in": ""}]}
        self.assertEqual(self.bf._reveal_orders(spine, outline), frozenset({17, 18}))
        self.assertEqual(self.bf._reveal_orders({}, outline), frozenset())

    def test_every_chapter_is_covered_exactly_once_however_it_is_narrowed(self):
        for width in (1, 2, 3, 4):
            for reveals in (frozenset(), frozenset({5}), frozenset({1, 26})):
                chunks = self.bf._ranged_chunks("chapters", 1, 26, width, reveals)
                covered = [o for c in chunks for o in range(c["first_order"], c["last_order"] + 1)]
                self.assertEqual(covered, list(range(1, 27)), f"width={width} reveals={sorted(reveals)}")


if __name__ == "__main__":
    unittest.main()
