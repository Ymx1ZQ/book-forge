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


class WireDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.attempt_dir = self.project / ".book-forge" / "runs" / "RUN-0001" / "attempts" / "ATT-0001"
        self.attempt_dir.mkdir(parents=True)
        payload = {"schema": 1, "role": "writer", "task": {"beats": ["z" * 40000]}, "tools": []}
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

        with mock.patch.object(self.bf.subprocess, "run", side_effect=fake_run):
            try:
                self.bf.run_opencode_role("writer", self.envelope, self.attempt_dir)
            except Exception:
                pass
        return next(args for args in captured if "run" in args)

    def test_the_attached_file_is_the_wire_rendering_not_the_canonical_one(self):
        argv = self._argv()
        attached = Path(argv[argv.index("--file") + 1])
        self.assertEqual(attached.name, "envelope.wire.json")
        self.assertLessEqual(max(len(line) for line in attached.read_text().split("\n")), self.bf.WIRE_MAX_LINE)

    def test_the_canonical_envelope_is_still_written_unchanged_for_the_audit(self):
        self._argv()
        self.assertEqual((self.attempt_dir / "envelope.json").read_bytes(), self.canonical)

    def test_the_wire_file_decodes_back_to_the_canonical_envelope(self):
        self._argv()
        wire = json.loads((self.attempt_dir / "envelope.wire.json").read_text())
        self.assertEqual(self.bf._wire_decode(wire), json.loads(self.canonical))

    def test_the_prompt_tells_the_role_how_a_split_value_reassembles(self):
        argv = self._argv()
        prompt = next(arg for arg in argv if arg.startswith("Process the attached envelope"))
        self.assertIn(self.bf.WIRE_CHUNK_KEY, prompt)
        self.assertLess(argv.index(prompt), argv.index("--file"))


if __name__ == "__main__":
    unittest.main()
