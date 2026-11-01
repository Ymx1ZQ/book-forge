import json

from test_review import ReviewTests, ScriptedProvider, SettlementHelpers, cold_answer


class RejectedVerificationDispositionsAreDroppedTests(SettlementHelpers, ReviewTests):
    """A retried reviser is handed the verifier's refused finding as context, not
    as a finding it owes a disposition. When it answers that context anyway the
    stray row is dropped instead of blocking every retry."""

    REJECTED = {"id": "F-0001", "severity": "blocking", "issue": "Mara still does not know the signal"}
    OWED = {"id": "F-001", "dimension": "state", "severity": "warning", "evidence": "final paragraph",
            "issue": "Signal knowledge is thin", "fix_required": False}

    def rejected_path(self):
        return self.project / f"books/{self.book}/work/CH-0001/verification-rejected.json"

    def write_rejected(self):
        self.rejected_path().write_text(json.dumps({
            "schema": 1,
            "attempt": "ATT-0001",
            "revision_attempt": "ATT-0002",
            "verified": False,
            "findings": [self.REJECTED],
        }))

    def disposition(self, finding_id):
        return {"finding": finding_id, "action": "repaired", "evidence": "final paragraph",
                "loss": "none", "supersedes": []}

    def test_a_rejected_id_beside_the_owed_ones_is_dropped(self):
        self.write_rejected()
        provider = ScriptedProvider({
            "cold-reader": [cold_answer([self.OWED])],
            "technical-editor": [{"findings": [], "consequences": []}],
            "reviser": [self.reviser(dispositions=[
                self.disposition("F-001"),
                self.disposition("F-0001"),
            ])],
        })
        result = self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(result["state"], "closed")
        stored = json.loads(
            (self.project / f"books/{self.book}/reviews/CH-0001/dispositions.json").read_text()
        )
        self.assertEqual([row["finding"] for row in stored["dispositions"]], ["F-001"])

    def test_an_id_from_neither_list_still_blocks(self):
        self.write_rejected()
        provider = ScriptedProvider({
            "cold-reader": [cold_answer([self.OWED])],
            "technical-editor": [{"findings": [], "consequences": []}],
            "reviser": [self.reviser(dispositions=[
                self.disposition("F-001"),
                self.disposition("F-9999"),
            ])],
        })
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.review_and_close_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertIn("Revision dispositions a finding that was not raised", str(caught.exception))
