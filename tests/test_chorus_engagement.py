import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
PROMPT_PATH = Path(__file__).parents[1] / "assets" / "prompts" / "chorus-bestseller.md"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_chorus_engagement", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def chapter(index, *, kind=None, reason=None):
    return {
        "id": f"CH-{index:04d}",
        "order": index,
        "title": f"The Ninth Tide {index}",
        "pov": "CHR-0001",
        "beats": ["Mara forces the harbour door before the tide turns."],
        "want": "Mara wants the harbour log before the tide turns.",
        "obstacle": "The warden will not open the door.",
        "turn": {"kind": "decision", "text": "She breaks the lock herself."},
        "chapter_kind": kind,
        "exempt_reason": reason,
        "plants": [],
        "reveals": [],
        "target_words": 900,
        "imports": [],
        "obligations": [],
        "pivotal": None,
    }


def proposal(rows):
    return {
        "premise": "A diver must decide whether memory can be owned.",
        "entry_state": {"CHR-0001": "isolated"},
        "arc": ["refusal", "cost", "choice"],
        "exit_boundary": {"CHR-0001": "committed"},
        "chapters": rows,
    }


class ChorusEngagementPromptTests(unittest.TestCase):
    def test_the_prompt_carries_each_finding_code_and_its_severity(self):
        text = PROMPT_PATH.read_text(encoding="utf-8")
        expected = {
            "FLAT-": "warning",
            "TALK-": "warning",
            "RUN-": "blocking",
            "SHAPE-": "warning",
            "OPEN-": "blocking",
            "ANTAGONIST-": "blocking",
            "TAIL-": "warning",
            "SPOIL-": "blocking",
        }
        for code, severity in expected.items():
            self.assertRegex(text, rf"{re.escape(code)}`?\s*{severity}\b")


class ChorusEngagementEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]
        self.rows = [
            chapter(1),
            chapter(2, kind="interlude", reason="The interlude is the sea between acts."),
            chapter(3),
        ]
        self.captured = []

    def test_the_post_design_scope_and_advisor_envelope_keep_the_engagement_fields(self):
        def provider(role, envelope, attempt_dir):
            if role.startswith("advisor-"):
                self.captured.append(envelope)
            return {"text": json.dumps({"findings": [], "suggestions": []}), "provider": "openrouter", "model": role}

        self.bf.run_chorus_post_design(
            self.project,
            {"scope": "book", "book": self.book, "imports": []},
            proposal(self.rows),
            ["openrouter/deepseek/deepseek-v4.1-flash-1017"],
            provider=provider,
        )

        self.assertEqual(len(self.captured), 1)
        capsule = self.captured[0]["payload"]["task"]
        rows = capsule["chorus_scope"]["product"]["chapters"]
        self.assertEqual(rows, self.rows)
        for row in rows:
            for field in ("want", "obstacle", "turn", "chapter_kind", "exempt_reason"):
                self.assertIn(field, row)


if __name__ == "__main__":
    unittest.main()
