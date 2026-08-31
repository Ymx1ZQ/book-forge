import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_design_bounds", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROLE_VARIANTS = {name: spec[1] for name, spec in load_module().ROLE_SPECS.items()}


class RecordingProvider:
    """Answers every chunk the design and the audit ask for, and remembers the size
    of each envelope it was handed."""

    def __init__(self, bf, chapter_count):
        self.bf = bf
        self.chapter_count = chapter_count
        self.envelopes = []

    def _ok(self, envelope, payload, role):
        self.envelopes.append({
            "role": role,
            "chunk": self.bf._chunk_slug(envelope["payload"]["task"].get("chunk") or {"category": role}),
            "tokens": envelope["estimated_input_tokens"],
            "bytes": len(envelope["bytes"]),
        })
        return {
            "text": json.dumps(payload), "provider": "openrouter", "model": MODEL,
            "variant": ROLE_VARIANTS.get(role, "high"), "session_id": f"ses-{len(self.envelopes)}",
            "tokens": {"input": envelope["estimated_input_tokens"], "output": 400},
            "cost": 0.001, "latency_ms": 5, "finish": "stop",
        }

    def __call__(self, role, envelope, attempt_dir):
        if role.startswith("advisor-") or role == "chorus-synthesizer":
            return self._ok(envelope, {"findings": [], "suggestions": []}, role)
        task = envelope["payload"]["task"]
        if role == "canon-auditor":
            answer = {"findings": []}
            if "neighbourhood_digest" not in task["design_scope"]:
                answer["open_promises"] = []
            return self._ok(envelope, answer, role)
        chunk = task.get("chunk") or {}
        if chunk.get("category") == "spine":
            return self._ok(envelope, {
                "premise": "A diver must decide whether memory can be owned.",
                "entry_state": {"CHR-0001": "isolated"},
                "arc": ["refusal", "cost", "choice"],
                "exit_boundary": {"CHR-0001": "committed"},
                "chapter_count": self.chapter_count,
            }, role)
        first, last = int(chunk["first_order"]), int(chunk["last_order"])
        if chunk.get("category") == "outline":
            return self._ok(envelope, {"chapter_outline": [
                {"id": f"CH-{i:04d}", "order": i, "title": f"The Ninth Tide {i}", "pov": "CHR-0001", "summary": "She goes down again."}
                for i in range(first, last + 1)
            ]}, role)
        return self._ok(envelope, {"chapters": [
            {
                "id": f"CH-{i:04d}", "order": i, "title": f"The Ninth Tide {i}", "pov": "CHR-0001",
                "beats": ["She wants the log and the warden will not open it"],
                "plants": [f"the warden keeps a key for {i}"], "reveals": [f"the key opens door {i}"],
                "target_words": 3000, "imports": ["UNI-0001#kernel"], "obligations": [], "pivotal": None,
            }
            for i in range(first, last + 1)
        ]}, role)


class BookLengthTests(unittest.TestCase):
    """A design call is bounded by construction, not by the book.

    Landfall's spine failed three times because its answer carried one row per
    chapter: 15822 bytes cut off mid-sentence, then twice `input 42241,
    reasoning 31999, output 0`. Nothing in the suite measured that, so it was
    found by a design failing against a paid provider. This measures it.
    """

    def design(self, chapter_count):
        bf = load_module()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        project = Path(temp.name) / "world"
        bf.init_project(project, "World", chorus_models=[])
        config = json.loads((project / "book-forge.yaml").read_text())
        config["chorus"] = {"enabled": False, "models": [], "synthesizer": bf.CHORUS_SYNTHESIZER}
        (project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        book = bf.add_book(project, "A")["id"]
        (project / f"books/{book}/book-brief.json").write_text(json.dumps({
            "schema": 1, "premise": "A diver must decide.", "characters": ["Mara"],
            # Zero-padded so the two briefs are byte-identical in length: the spine
            # test asserts the call does not grow with the book, and a brief that is
            # one character longer for a longer book is the book leaking in by the
            # back door. Padding removes the confound instead of widening the assert.
            "plot": ["dive"], "tone": "quiet", "length_notes": f"{chapter_count:03d} chapters",
        }))
        provider = RecordingProvider(bf, chapter_count)
        result = bf.execute_book_design(project, book, provider=provider, no_chorus=True, no_post_chorus=True)
        self.assertEqual(result["state"], "design_clean")
        return provider.envelopes

    def test_a_two_hundred_chapter_book_asks_no_bigger_question_than_a_forty_chapter_one(self):
        short = self.design(40)
        long = self.design(200)
        self.assertGreater(len(long), len(short), "a longer book must buy more calls")
        widest_short = max(row["tokens"] for row in short)
        widest_long = max(row["tokens"] for row in long)
        self.assertLess(
            widest_long, widest_short * 1.25,
            f"the widest call grew from {widest_short} to {widest_long} tokens between a 40- and a 200-chapter book",
        )

    def test_the_spine_is_the_same_size_whatever_the_book_is(self):
        spines = {}
        for count in (40, 200):
            spines[count] = next(row["tokens"] for row in self.design(count) if row["chunk"] == "spine")
        self.assertEqual(spines[40], spines[200])

    def test_no_single_call_of_a_long_book_carries_more_than_the_bound(self):
        bf = load_module()
        ceiling = bf.CHUNK_PAYLOAD_TOKEN_BOUND
        for row in self.design(200):
            with self.subTest(chunk=row["chunk"], role=row["role"]):
                self.assertLess(row["tokens"], ceiling * 3, f"{row['chunk']} carried {row['tokens']} tokens")

    def test_every_chapter_of_a_long_book_still_reaches_the_design(self):
        """The split changes the shape of the questions, not the book they build."""
        bf = load_module()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        project = Path(temp.name) / "world"
        bf.init_project(project, "World", chorus_models=[])
        config = json.loads((project / "book-forge.yaml").read_text())
        config["chorus"] = {"enabled": False, "models": [], "synthesizer": bf.CHORUS_SYNTHESIZER}
        (project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        book = bf.add_book(project, "A")["id"]
        (project / f"books/{book}/book-brief.json").write_text(json.dumps({
            "schema": 1, "premise": "A diver must decide.", "characters": ["Mara"], "plot": ["dive"], "tone": "quiet",
        }))
        bf.execute_book_design(project, book, provider=RecordingProvider(bf, 120), no_chorus=True, no_post_chorus=True)
        outline = json.loads((project / f"books/{book}/outline.yaml").read_text())["chapters"]
        self.assertEqual([row["order"] for row in outline], list(range(1, 121)))
        self.assertTrue((project / f"books/{book}/chapters/CH-0120.json").is_file())


if __name__ == "__main__":
    unittest.main()
