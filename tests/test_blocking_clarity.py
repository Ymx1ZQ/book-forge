import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_blocking_clarity", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BlockingClarityAndPacingCannotBeDismissedTests(unittest.TestCase):
    """The reviewer is the model that wrote the chapter. A blocking finding about
    clarity or pacing is the one thing it may not wave away."""

    def setUp(self):
        self.bf = load_module()
        self.contract = {
            "id": "CH-0001", "book": "BOOK-0001", "target_words": 20,
            "beats": ["Mara opens the log"], "pov": "CHR-0001",
        }

    def finding(self, finding_id, dimension):
        return {
            "id": finding_id, "severity": "blocking", "dimension": dimension,
            "evidence": "the opening line", "issue": "the reader cannot follow it",
            "fix_required": True,
        }

    def revision(self, findings, action):
        dispositions = [
            {"finding": finding["id"], "action": action, "evidence": "cut the clause", "loss": "none"}
            for finding in findings
        ]
        return {
            "prose_markdown": "# The Ninth Tide\n\n" + " ".join(
                ["Mara opened the log and the warden said nothing."] * 2
            ),
            "beat_map": [{"beat": "Mara opens the log", "evidence": "Mara opened the log"}],
            "consequences": [], "dispositions": dispositions, "reader_state": "Mara opened it.",
        }

    def test_a_dismissed_blocking_clarity_finding_is_refused_and_names_it(self):
        findings = [self.finding("F-1", "clarity")]
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf._validate_revision(self.contract, self.revision(findings, "dismissed"), findings, [])
        self.assertIn("F-1", str(caught.exception))
        self.assertIn("clarity", str(caught.exception))

    def test_a_repaired_blocking_clarity_finding_is_accepted(self):
        findings = [self.finding("F-1", "clarity")]
        value = self.bf._validate_revision(self.contract, self.revision(findings, "repaired"), findings, [])
        self.assertEqual([row["finding"] for row in value["dispositions"]], ["F-1"])

    def test_a_dismissed_blocking_pacing_finding_is_refused_and_names_it(self):
        findings = [self.finding("F-2", "pacing")]
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf._validate_revision(self.contract, self.revision(findings, "dismissed"), findings, [])
        self.assertIn("F-2", str(caught.exception))
        self.assertIn("pacing", str(caught.exception))

    def test_a_repaired_blocking_pacing_finding_is_accepted(self):
        findings = [self.finding("F-2", "pacing")]
        value = self.bf._validate_revision(self.contract, self.revision(findings, "repaired"), findings, [])
        self.assertEqual([row["finding"] for row in value["dispositions"]], ["F-2"])

    def test_a_dismissed_blocking_continuity_gap_is_still_accepted(self):
        findings = [self.finding("F-3", "continuity-gap")]
        value = self.bf._validate_revision(self.contract, self.revision(findings, "dismissed"), findings, [])
        self.assertEqual(value["dispositions"][0]["action"], "dismissed")


class StyleReviewMayBlockOnlyTwoNamedShapesTests(unittest.TestCase):
    """A style reviewer can stop a chapter only when nobody wants anything or when
    invented terms outrun what the prose makes concrete."""

    def setUp(self):
        self.bf = load_module()

    def result(self, severity="blocking", kind=None):
        finding = {
            "id": "01", "severity": severity, "issue": "the chapter has no want",
            "evidence": [{"location": "CH-0001.md", "hash": "0"}],
            "suggestion": "give Mara something to lose",
        }
        if kind is not None:
            finding["kind"] = kind
        return {"findings": [finding]}

    def test_blocking_no_want_is_accepted(self):
        self.bf._validate_style_review_result(self.result(kind="no-want"))

    def test_blocking_without_a_kind_is_refused(self):
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf._validate_style_review_result(self.result())
        self.assertIn("kind", str(caught.exception))

    def test_blocking_with_another_kind_is_refused(self):
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf._validate_style_review_result(self.result(kind="other"))
        self.assertIn("kind", str(caught.exception))

    def test_warning_needs_no_kind(self):
        self.bf._validate_style_review_result(self.result(severity="warning"))


if __name__ == "__main__":
    unittest.main()
