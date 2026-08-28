import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_wire", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WireRoundTripTests(unittest.TestCase):
    """opencode truncates every line of an attached file at 2000 characters, so the
    envelope is handed over in a rendering whose lines are bounded for any content."""

    def setUp(self):
        self.bf = load_module()

    def _check(self, payload):
        wire = self.bf._wire_bytes(payload)
        lines = wire.decode().split("\n")
        self.assertLessEqual(max(map(len, lines)), self.bf.WIRE_MAX_LINE)
        self.assertEqual(self.bf._wire_decode(json.loads(wire)), payload)
        return lines

    def test_a_long_markdown_block_survives_byte_for_byte(self):
        block = "\n".join(f"## Section {index}\n\nA paragraph about salt and light." for index in range(900))
        self.assertGreater(len(block), 30000)
        self._check({"context": [{"id": "CHR-0001#voice", "content": block}]})

    def test_a_single_value_with_no_newlines_at_all_is_still_bounded(self):
        self._check({"task": {"blob": "x" * 85000}})

    def test_unicode_and_escapes_round_trip(self):
        value = ('"quoted" \\ backslash\ttab\nnewline · ﬀ ligature — dash ' * 400)
        lines = self._check({"task": {"note": value}})
        self.assertGreater(len(lines), 1)

    def test_short_strings_are_left_as_strings(self):
        wire = json.loads(self.bf._wire_bytes({"role": "designer", "task": {"id": "CH-0001"}}))
        self.assertEqual(wire["role"], "designer")
        self.assertEqual(wire["task"]["id"], "CH-0001")

    def test_a_list_of_short_strings_is_not_mistaken_for_a_split_value(self):
        payload = {"arc": ["refusal", "cost", "choice"]}
        wire = json.loads(self.bf._wire_bytes(payload))
        self.assertEqual(wire["arc"], ["refusal", "cost", "choice"])
        self.assertEqual(self.bf._wire_decode(wire), payload)

    def test_a_split_value_is_marked_and_reassembles_by_concatenation(self):
        value = "y" * 5000
        wire = json.loads(self.bf._wire_bytes({"task": {"blob": value}}))
        parts = wire["task"]["blob"][self.bf.WIRE_CHUNK_KEY]
        self.assertGreater(len(parts), 1)
        self.assertEqual("".join(parts), value)

    def test_empty_and_scalar_values_are_untouched(self):
        payload = {"state": {}, "tools": [], "max_output_tokens": 12288, "flag": True, "none": None, "text": ""}
        self.assertEqual(self.bf._wire_decode(json.loads(self.bf._wire_bytes(payload))), payload)

    def test_a_rendering_that_does_not_decode_is_refused(self):
        with mock.patch.object(self.bf, "_wire_encode", side_effect=lambda value, chunk: {"tampered": True}):
            with self.assertRaises(self.bf.BookForgeError):
                self.bf._wire_bytes({"role": "writer"})


class WireAttachmentTests(unittest.TestCase):
    """opencode truncates each attachment at about 50 KB and serialises JSON keys in
    sorted order, so on a large envelope `task` — the contract — is what gets cut.
    The envelope is split across attachments, contract first."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def big_payload(self):
        return {
            "schema": 1, "model": "m", "role": "designer", "role_prompt": "Write the design.",
            "max_output_tokens": 12288, "tools": [], "state": {},
            "context": [{"id": f"CHR-{i:04d}#summary", "hash": "h", "content": "A character. " * 40} for i in range(43)],
            "task": {
                "scope": "book", "chunk": {"category": "chapters", "first_order": 9, "last_order": 16},
                "worldbuilding": "\n".join(f"## Region {i}\n\nSalt and light." for i in range(2000)),
                "brief": {"premise": "A diver decides.", "notes": "n" * 18000},
                "chapter_outline": [{"id": f"CH-{i:04d}", "order": i, "title": "The Ninth Tide"} for i in range(1, 28)],
            },
        }

    def test_a_large_envelope_splits_into_parts_that_all_fit(self):
        payload = self.big_payload()
        self.assertGreater(len(json.dumps(payload)), 100000)
        paths = self.bf._wire_attachments(payload, self.dir)
        self.assertGreater(len(paths), 1)
        for path in paths:
            text = path.read_text()
            self.assertLessEqual(len(text), self.bf.WIRE_MAX_ATTACHMENT, path.name)
            self.assertLessEqual(max(len(line) for line in text.split("\n")), self.bf.WIRE_MAX_LINE)
            json.loads(text)

    def test_the_parts_merge_back_to_the_canonical_envelope(self):
        payload = self.big_payload()
        merged = {}
        for path in self.bf._wire_attachments(payload, self.dir):
            merged = self.bf._wire_merge(merged, json.loads(path.read_text()))
        self.assertEqual(self.bf._wire_decode(merged), payload)

    def test_the_first_part_carries_the_contract_and_not_the_bulk(self):
        paths = self.bf._wire_attachments(self.big_payload(), self.dir)
        first = json.loads(paths[0].read_text())
        self.assertIn("role_prompt", first)
        self.assertIn("chunk", first["task"])
        self.assertNotIn("worldbuilding", first["task"])

    def test_a_single_oversized_value_is_split_rather_than_emitted_whole(self):
        payload = {"schema": 1, "task": {"blob": "z" * 300000}}
        paths = self.bf._wire_attachments(payload, self.dir)
        self.assertGreater(len(paths), 1)
        merged = {}
        for path in paths:
            merged = self.bf._wire_merge(merged, json.loads(path.read_text()))
        self.assertEqual(self.bf._wire_decode(merged), payload)

    def test_a_value_too_large_to_split_is_refused_rather_than_truncated(self):
        payload = {"schema": 1, "task": {"beats": ["z" * 200000]}}
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf._wire_attachments(payload, self.dir)
        self.assertIn("cannot be split", str(caught.exception))

    def test_a_small_envelope_still_ships_as_one_file(self):
        paths = self.bf._wire_attachments({"schema": 1, "role": "writer", "task": {"id": "CH-0001"}}, self.dir)
        self.assertEqual([path.name for path in paths], ["envelope.wire.json"])

    def test_a_split_that_loses_content_is_refused(self):
        with mock.patch.object(self.bf, "_wire_partition", side_effect=lambda value, budget: [{"tampered": True}]):
            with self.assertRaises(self.bf.BookForgeError):
                self.bf._wire_attachments({"schema": 1, "role": "writer"}, self.dir)


class WireDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.attempt_dir = self.project / ".book-forge" / "runs" / "RUN-0001" / "attempts" / "ATT-0001"
        self.attempt_dir.mkdir(parents=True)
        payload = {"schema": 1, "role": "writer", "task": {"notes": "z" * 90000}, "tools": []}
        self.canonical = (json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode()
        self.envelope = {"bytes": self.canonical, "hash": "abc", "estimated_input_tokens": 10}

    def _argv(self):
        captured = []

        def fake_run(args, **kwargs):
            captured.append(list(args))
            if "debug" in args:
                model_id, variant = self.bf._expected_pin("writer")
                return mock.Mock(stdout=json.dumps({"name": "writer", "model": {"providerID": "openrouter", "modelID": model_id}, "variant": variant}), stderr="", returncode=0)
            return mock.Mock(stdout=json.dumps({"parts": []}), stderr="", returncode=0)

        # These check how the argv is built, not whether the CLI is capable; the
        # requirement check has its own suite and would consume this mock.
        with mock.patch.object(self.bf, "_verify_opencode_cli", lambda binary: None), \
             mock.patch.object(self.bf.subprocess, "run", side_effect=fake_run):
            try:
                self.bf.run_opencode_role("writer", self.envelope, self.attempt_dir)
            except Exception:
                pass
        return next(args for args in captured if "run" in args)

    def test_the_attached_files_are_the_wire_rendering_not_the_canonical_one(self):
        argv = self._argv()
        attached = [Path(value) for value in argv[argv.index("--file") + 1:]]
        self.assertTrue(attached)
        for path in attached:
            self.assertTrue(path.name.startswith("envelope.wire"), path.name)
            self.assertLessEqual(len(path.read_text()), self.bf.WIRE_MAX_ATTACHMENT)
            self.assertLessEqual(max(len(line) for line in path.read_text().split("\n")), self.bf.WIRE_MAX_LINE)

    def test_the_canonical_envelope_is_still_written_unchanged_for_the_audit(self):
        self._argv()
        self.assertEqual((self.attempt_dir / "envelope.json").read_bytes(), self.canonical)

    def test_the_wire_files_merge_back_to_the_canonical_envelope(self):
        argv = self._argv()
        merged = {}
        for value in argv[argv.index("--file") + 1:]:
            merged = self.bf._wire_merge(merged, json.loads(Path(value).read_text()))
        self.assertEqual(self.bf._wire_decode(merged), json.loads(self.canonical))

    def test_the_prompt_tells_the_role_how_a_split_value_reassembles(self):
        argv = self._argv()
        prompt = next(arg for arg in argv if arg.startswith("Process the attached envelope"))
        self.assertIn(self.bf.WIRE_CHUNK_KEY, prompt)
        self.assertLess(argv.index(prompt), argv.index("--file"))


if __name__ == "__main__":
    unittest.main()
