import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_draft", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, role, envelope, attempt_dir):
        self.calls.append((role, envelope["hash"], attempt_dir))
        return {
            "text": self.responses.pop(0),
            "provider": "openrouter",
            "model": MODEL,
            "variant": "low",
            "session_id": f"ses-{len(self.calls)}",
            "tokens": {"input": envelope["estimated_input_tokens"], "output": 500},
            "cost": 0.001,
            "latency_ms": 100,
            "finish": "stop",
        }


def valid_response(words=700):
    prose = " ".join(["memory"] * words)
    return json.dumps({
        "prose_markdown": f"# The Signal\n\n{prose}",
        "beat_map": [{"beat": "Find the signal", "evidence": "The signal is found."}],
        "consequences": [{"scope": "book", "fact": "The signal is known.", "entities": ["CHR-0001"]}],
    })


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        self.book = self.bf.add_book(self.project, "Book")["id"]
        chapter_dir = self.project / f"books/{self.book}/chapters"
        chapter_dir.mkdir()
        self.contract = {
            "schema": 1, "book": self.book, "id": "CH-0001", "order": 1,
            "pov": "CHR-0001", "beats": ["Find the signal"], "plants": [], "reveals": [],
            "target_words": 700, "imports": ["UNI-0001#kernel"], "pivotal": None,
        }
        (chapter_dir / "CH-0001.json").write_text(json.dumps(self.contract))

    def test_happy_path_uses_one_call_and_materializes_receipted_draft(self):
        provider = FakeProvider(["Result follows:\n" + valid_response() + "\nEnd of result."])
        result = self.bf.draft_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(result["calls"], 1)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0][0], "writer")
        self.assertTrue((self.project / f"books/{self.book}/work/CH-0001/draft.md").is_file())
        receipt = result["receipt"]
        self.assertEqual(receipt["model"], MODEL)
        self.assertEqual(receipt["variant"], "low")
        self.assertRegex(receipt["envelope_hash"], r"^[0-9a-f]{64}$")

    def test_one_repair_is_allowed_then_workflow_blocks(self):
        repaired = FakeProvider(["not json", valid_response()])
        result = self.bf.draft_chapter(self.project, self.book, "CH-0001", provider=repaired)
        self.assertEqual(result["calls"], 2)

        second_project = Path(self.temp.name) / "second"
        self.bf.init_project(second_project, "Second")
        book = self.bf.add_book(second_project, "Book")["id"]
        directory = second_project / f"books/{book}/chapters"
        directory.mkdir()
        contract = dict(self.contract, book=book)
        (directory / "CH-0001.json").write_text(json.dumps(contract))
        broken = FakeProvider(["bad", "still bad"])
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.draft_chapter(second_project, book, "CH-0001", provider=broken)
        self.assertEqual(len(broken.calls), 2)
        self.assertEqual(self.bf.status_project(second_project)["tasks"]["blocked"], 1)


if __name__ == "__main__":
    unittest.main()


class RawControlCharacterTests(unittest.TestCase):
    """A finished 14988-character chapter was discarded for one raw newline inside a
    JSON string, among thousands of correctly escaped ones."""

    def setUp(self):
        self.bf = load_module()

    def test_a_raw_newline_reads_as_the_newline_it_is(self):
        escaped = self.bf._parse_contract_json('{"prose":"a\\n\\nb"}')
        raw = self.bf._parse_contract_json('{"prose":"a\n\nb"}')
        self.assertEqual(raw, escaped)
        self.assertEqual(raw["prose"], "a\n\nb")

    def test_a_raw_newline_survives_the_chunked_decoder_too(self):
        value = self.bf._parse_chunked_contract('{"chapters":[{"id":"CH-0001","prose":"one\ntwo"}]}')
        self.assertEqual(value["chapters"][0]["prose"], "one\ntwo")

    def test_output_that_is_not_json_still_fails(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf._parse_contract_json("I am afraid I cannot help with that.")

    def test_a_truncated_object_still_fails(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf._parse_contract_json('{"prose":"unterminated')

    def test_a_non_object_contract_still_fails(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf._parse_contract_json('["a list is not a contract"]')
