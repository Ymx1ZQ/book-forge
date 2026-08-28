import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_repair", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROLE_VARIANTS = {name: spec[1] for name, spec in load_module().ROLE_SPECS.items()}
FINDING = {
    "id": "F-0001", "severity": "blocking",
    "issue": "The grave holds a man in CH-0002 and a young woman in CH-0004.",
    "repair_scope": ["CH-0002", "CH-0004"],
    "evidence": [{"location": "BOOK-0001#proposal/chapters/CH-0002"}],
}


class RepairProvider:
    """Audits blocking once, then clean. Records what the repair call was asked for."""

    def __init__(self, bf, chapters=6, audits=None):
        self.bf = bf
        self.chapters = chapters
        self.audits = list(audits if audits is not None else [[FINDING], []])
        self.repair_capsules = []
        self.calls = []

    def _ok(self, envelope, payload, role):
        return {
            "text": json.dumps(payload), "provider": "openrouter", "model": MODEL,
            "variant": ROLE_VARIANTS.get(role, "high"), "session_id": f"ses-{len(self.calls)}",
            "tokens": {"input": 100, "output": 200}, "cost": 0.001, "latency_ms": 5, "finish": "stop",
        }

    def _chapter(self, index, grave="a man"):
        return {
            "id": f"CH-{index:04d}", "order": index, "title": "The Ninth Tide", "pov": "CHR-0001",
            "beats": [f"Mara visits the grave of {grave} and the warden will not open the log"],
            "plants": [], "reveals": [], "target_words": 900,
            "imports": ["UNI-0001#kernel"], "obligations": [], "pivotal": None,
        }

    def __call__(self, role, envelope, attempt_dir):
        self.calls.append(role)
        task = envelope["payload"]["task"]
        if role == "canon-auditor":
            # A book longer than one window is audited in several passes, and the
            # fixture's list is one verdict per round, not per call: the opening pass
            # carries it and the rest of the round is clean.
            scope = task["design_scope"]
            rows = scope.get("proposal", {}).get("chapters", [])
            opening = "pass" not in scope or ("book_digest" in scope and rows and int(rows[0].get("order") or 0) == 1)
            if not opening:
                return self._ok(envelope, {"findings": []}, role)
            findings = self.audits.pop(0) if self.audits else []
            return self._ok(envelope, {"findings": findings}, role)
        chunk = task.get("chunk") or {}
        if chunk.get("category") == "spine":
            return self._ok(envelope, {
                "premise": "A diver decides.", "entry_state": {"CHR-0001": "isolated"},
                "arc": ["refusal", "cost", "choice"], "exit_boundary": {"CHR-0001": "committed"},
                "chapter_outline": [{"id": f"CH-{i:04d}", "order": i, "title": "The Ninth Tide", "pov": "CHR-0001", "summary": "s"} for i in range(1, self.chapters + 1)],
            }, role)
        if chunk.get("category") == "repair":
            self.repair_capsules.append(task)
            ids = [int(str(value)[3:]) for value in task["repair"]["rewrite_only"]]
            return self._ok(envelope, {"chapters": [self._chapter(i, "the drowned girl") for i in ids]}, role)
        first, last = int(chunk["first_order"]), int(chunk["last_order"])
        return self._ok(envelope, {"chapters": [self._chapter(i) for i in range(first, last + 1)]}, role)


class DesignRepairTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]
        (self.project / f"books/{self.book}/book-brief.json").write_text(
            json.dumps({"schema": 1, "premise": "A diver decides.", "characters": ["Mara"], "plot": ["dive"], "tone": "quiet"})
        )

    def run_design(self, provider):
        return self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)

    def test_a_blocking_finding_repairs_exactly_the_chapters_it_names(self):
        provider = RepairProvider(self.bf)
        self.run_design(provider)
        self.assertEqual(len(provider.repair_capsules), 1)
        capsule = provider.repair_capsules[0]
        self.assertEqual(capsule["repair"]["rewrite_only"], ["CH-0002", "CH-0004"])
        self.assertEqual([row["id"] for row in capsule["chapters_to_rewrite"]], ["CH-0002", "CH-0004"])

    def test_the_repaired_chapters_replace_the_originals_on_disk(self):
        self.run_design(RepairProvider(self.bf))
        repaired = json.loads((self.project / f"books/{self.book}/chapters/CH-0002.json").read_text())
        untouched = json.loads((self.project / f"books/{self.book}/chapters/CH-0003.json").read_text())
        self.assertIn("the drowned girl", repaired["beats"][0])
        self.assertIn("a man", untouched["beats"][0])

    def test_the_repair_call_does_not_see_the_chapters_it_is_rewriting(self):
        provider = RepairProvider(self.bf)
        self.run_design(provider)
        digest = {row["id"] for row in provider.repair_capsules[0]["written_so_far"]}
        self.assertNotIn("CH-0002", digest)
        self.assertNotIn("CH-0004", digest)
        self.assertIn("CH-0003", digest)

    def test_a_clean_audit_never_triggers_a_repair(self):
        provider = RepairProvider(self.bf, audits=[[]])
        self.run_design(provider)
        self.assertEqual(provider.repair_capsules, [])

    def test_an_audit_that_keeps_blocking_stops_after_the_bounded_rounds(self):
        provider = RepairProvider(self.bf, audits=[[FINDING]] * 6)
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.run_design(provider)
        self.assertEqual(len(provider.repair_capsules), self.bf.MAX_DESIGN_REPAIR_ROUNDS)
        self.assertIn("F-0001", str(caught.exception))

    def test_a_finding_that_names_no_chapter_is_left_to_a_person(self):
        finding = {**FINDING, "repair_scope": []}
        provider = RepairProvider(self.bf, audits=[[finding], []])
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.run_design(provider)
        self.assertEqual(provider.repair_capsules, [], "nothing to scope means nothing to repair")
        self.assertIn("blocking issues", str(caught.exception))


if __name__ == "__main__":
    unittest.main()


class PromotedDesignRepairTests(unittest.TestCase):
    """A design whose audit blocks after the design task is already promoted used to
    be refused outright: the resume path audited, raised, and never offered the
    repair the first pass would have run."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]
        (self.project / f"books/{self.book}/book-brief.json").write_text(
            json.dumps({"schema": 1, "premise": "A diver decides.", "characters": ["Mara"], "plot": ["dive"], "tone": "quiet"})
        )
        # Design the book cleanly, then put only its audit back in play — the state a
        # long run reaches when the design promoted hours before the audit ran.
        self.bf.execute_book_design(self.project, self.book, provider=RepairProvider(self.bf, audits=[[]]), no_chorus=True, no_post_chorus=True)
        self.bf._reopen_task(self.project, f"AUDIT-{self.book}")

    def resume(self, provider):
        return self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)

    def test_a_promoted_design_is_repaired_rather_than_refused(self):
        provider = RepairProvider(self.bf)
        result = self.resume(provider)
        self.assertEqual(result["state"], "design_clean")
        self.assertEqual(len(provider.repair_capsules), 1)
        self.assertEqual(provider.repair_capsules[0]["repair"]["rewrite_only"], ["CH-0002", "CH-0004"])

    def test_the_repair_sees_the_same_world_the_first_pass_did(self):
        provider = RepairProvider(self.bf)
        self.resume(provider)
        capsule = provider.repair_capsules[0]
        for key in ("scope", "book", "brief", "source_language", "available_blocks", "obligations", "required_output"):
            self.assertIn(key, capsule, key)
        self.assertEqual(capsule["scope"], "book")
        self.assertTrue(capsule["available_blocks"])

    def test_the_repaired_chapters_reach_disk_on_this_path_too(self):
        self.resume(RepairProvider(self.bf))
        repaired = json.loads((self.project / f"books/{self.book}/chapters/CH-0002.json").read_text())
        self.assertIn("the drowned girl", repaired["beats"][0])

    def test_an_audit_that_keeps_blocking_still_halts(self):
        provider = RepairProvider(self.bf, audits=[[FINDING]] * 6)
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.resume(provider)
        self.assertEqual(len(provider.repair_capsules), self.bf.MAX_DESIGN_REPAIR_ROUNDS)
        self.assertIn("F-0001", str(caught.exception))

    def test_the_repair_writes_beside_its_telemetry_not_in_a_design_attempt(self):
        self.resume(RepairProvider(self.bf))
        round_dir = self.project / ".book-forge" / "repairs" / self.book / "round-1"
        self.assertTrue((round_dir / "envelope-repair.json").is_file())
        self.assertTrue((round_dir / "raw-repair.txt").is_file())


class BlockedRecordTests(unittest.TestCase):
    """A blocked audit used to be terminal: every later run short-circuited on the
    stored verdict and never reached the repair."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]
        (self.project / f"books/{self.book}/book-brief.json").write_text(
            json.dumps({"schema": 1, "premise": "A diver decides.", "characters": ["Mara"], "plot": ["dive"], "tone": "quiet"})
        )

    def run_design(self, provider):
        return self.bf.execute_book_design(self.project, self.book, provider=provider, no_chorus=True, no_post_chorus=True)

    def test_a_blocked_verdict_is_tried_again_and_repaired(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.run_design(RepairProvider(self.bf, audits=[[FINDING]] * 6))
        record = json.loads((self.project / f"books/{self.book}/design-audit.json").read_text())
        self.assertEqual(record["state"], "blocked")

        second = RepairProvider(self.bf)
        result = self.run_design(second)
        self.assertEqual(result["state"], "design_clean")
        self.assertGreater(second.calls.count("canon-auditor"), 0)

    def test_a_clean_verdict_still_costs_nothing_to_re_run(self):
        self.run_design(RepairProvider(self.bf, audits=[[]]))
        again = RepairProvider(self.bf, audits=[[]])
        result = self.run_design(again)
        self.assertEqual(result["calls"], 0)
        self.assertEqual(again.calls, [])
