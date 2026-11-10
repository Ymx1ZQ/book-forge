import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_universe_context", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ChunkPriorTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.merged = {
            "eras": [{"id": "ERA-0001", "name": "Dry", "when": "1900", "summary": "dust", "material": ["a"]}],
            "characters": [{"id": "CHR-0009", "name": "Lupe", "tier": "L1", "voice": "x"}],
            "places": [{"id": "PLC-0001"}],
        }

    def test_events_see_the_eras_already_decided(self):
        prior = self.bf._chunk_prior({"category": "events"}, self.merged)
        self.assertEqual(prior["eras"], [{"id": "ERA-0001", "name": "Dry", "when": "1900", "summary": "dust"}])

    def test_the_second_half_of_the_cast_sees_the_first_names(self):
        prior = self.bf._chunk_prior({"category": "characters", "part": "L3+L4"}, self.merged)
        self.assertEqual(prior["characters_so_far"], [{"id": "CHR-0009", "name": "Lupe", "tier": "L1"}])

    def test_the_first_half_and_other_chunks_get_no_prior(self):
        self.assertEqual(self.bf._chunk_prior({"category": "characters", "part": "L1+L2"}, self.merged), {})
        self.assertEqual(self.bf._chunk_prior({"category": "places"}, self.merged), {})

    def test_the_tail_sees_every_id_that_exists(self):
        prior = self.bf._chunk_prior({"category": "tail"}, self.merged)
        self.assertEqual(prior["ids"]["eras"], ["ERA-0001"])
        self.assertEqual(prior["ids"]["characters"], ["CHR-0009"])
        self.assertNotIn("events", prior["ids"])


def row_text(category, rows):
    return json.dumps({category: rows})


class UniverseRepairTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.root = self.bf._project_root(self.project)
        self.proposal = {
            "kernel": [{"id": "LAW-0001", "summary": "Memory cannot be manufactured."}],
            "eras": [
                {"id": "ERA-0001", "name": "Before", "when": "1900", "material": ["a", "b", "c"]},
                {"id": "ERA-0002", "name": "After", "when": "2000", "material": ["a", "b", "c"]},
            ],
            "events": [{"id": "EVT-0001", "era": "ERA-0001", "order": 1, "summary": "Wrong era."}],
            "places": [{"id": "PLC-0001", "name": "Harbor", "summary": "A harbor."}],
            "factions": [{"id": "FAC-0001", "name": "Keepers", "summary": "Guard."}],
            "characters": [
                {"id": "CHR-0001", "name": "Lupe", "summary": "A diver.", "voice": "dry"},
                {"id": "CHR-0002", "name": "Lupe", "summary": "The same diver.", "voice": "dry"},
            ],
            "themes": ["t"],
            "style": {"tense": "past", "person": "third-limited"},
            "continuity_material": {},
            "book_local": {},
            "unresolved_questions": [],
        }
        self.bf.validate_universe_design = lambda root, proposal: []
        self.bf._design_audit_record = self._audit
        self.bf._reopen_task = lambda *a, **k: None
        self.bf._forget_task_calls = lambda *a, **k: 0
        self.bf.rebuild_indexes = lambda root: {}
        self.bf.build_envelope = lambda root, role, task_capsule, imports, state, tools, max_output_tokens: {
            "bytes": json.dumps({"task_capsule": task_capsule}).encode(), "hash": "h", "estimated_input_tokens": 10,
        }
        self.bf._sweep_orphaned_canon = lambda root, proposal: []
        self.audits = []
        self.asked = []

    def _audit(self, root, task_id, scope, imports, runner, path, **kwargs):
        self.audits.append(scope["proposal"])
        events = scope["proposal"]["events"]
        blocked = events[0]["era"] != "ERA-0002"
        return {"state": "blocked" if blocked else "design_clean", "findings": (
            [{"id": "F-1", "severity": "blocking", "issue": "event in wrong era", "repair_scope": ["EVT-0001", "CHR-0002"]}] if blocked else []
        )}

    def runner(self, text):
        def call(role, envelope, attempt_dir):
            self.asked.append(json.loads(envelope["bytes"]))
            return {"text": text, "tokens": {}, "provider": "p", "model": "m", "variant": "v", "session_id": "s", "cost": 0, "latency_ms": 1, "finish": "stop"}
        return call

    def blocked(self):
        return {"state": "blocked", "findings": [
            {"id": "F-1", "severity": "blocking", "issue": "event in wrong era", "repair_scope": ["EVT-0001", "CHR-0002"]}]}

    def test_only_the_rows_a_finding_names_are_rewritten_and_the_audit_runs_again(self):
        text = json.dumps({"events": [{"id": "EVT-0001", "era": "ERA-0002", "order": 1, "summary": "Right era."}], "remove": ["CHR-0002"]})
        proposal, audit = self.bf._repair_blocked_universe(self.root, self.proposal, self.blocked(), self.runner(text))
        self.assertEqual(audit["state"], "design_clean")
        self.assertEqual(proposal["events"][0]["era"], "ERA-0002")
        self.assertEqual([row["id"] for row in proposal["characters"]], ["CHR-0001"])
        self.assertEqual(proposal["eras"], self.proposal["eras"])
        self.assertTrue((self.root / "universe" / "design.json").is_file())
        self.assertEqual(len(self.audits), 1)

    def test_the_repair_call_sees_the_rest_of_the_world_but_not_the_rows_it_rewrites(self):
        text = json.dumps({"events": [{"id": "EVT-0001", "era": "ERA-0002", "order": 1, "summary": "ok"}]})
        self.bf._repair_blocked_universe(self.root, self.proposal, self.blocked(), self.runner(text))
        capsule = self.asked[0]
        body = json.dumps(capsule)
        self.assertIn("ERA-0002", body)
        self.assertEqual(sorted(row["id"] for row in capsule["task_capsule"]["rows_to_rewrite"]), sorted(["EVT-0001", "CHR-0002"]))

    def test_a_clean_audit_makes_no_call(self):
        proposal, audit = self.bf._repair_blocked_universe(self.root, self.proposal, {"state": "design_clean", "findings": []}, self.runner("{}"))
        self.assertEqual(self.asked, [])

    def test_a_finding_that_names_no_universe_row_is_left_for_the_caller(self):
        audit = {"state": "blocked", "findings": [{"id": "F", "severity": "blocking", "issue": "x", "repair_scope": ["CH-0001"]}]}
        _, result = self.bf._repair_blocked_universe(self.root, self.proposal, audit, self.runner("{}"))
        self.assertEqual(self.asked, [])
        self.assertEqual(result, audit)

    def test_rounds_are_bounded(self):
        text = json.dumps({"events": [{"id": "EVT-0001", "era": "ERA-0001", "order": 1, "summary": "still wrong"}]})
        _, audit = self.bf._repair_blocked_universe(self.root, self.proposal, self.blocked(), self.runner(text))
        self.assertEqual(audit["state"], "blocked")
        self.assertEqual(len(self.asked), self.bf.UNIVERSE_REPAIR_ROUNDS)

    def test_a_row_the_validator_refuses_is_sent_back_with_the_reason_before_the_round_is_lost(self):
        refusal = {"code": "tier.L3.words", "expected": "60-90", "id": "CHR-0002", "severity": "blocking", "words": 102}
        verdicts = [[refusal], []]
        self.bf.validate_universe_design = lambda root, proposal: verdicts.pop(0)
        text = json.dumps({"events": [{"id": "EVT-0001", "era": "ERA-0002", "order": 1, "summary": "ok"}]})
        _, audit = self.bf._repair_blocked_universe(self.root, self.proposal, self.blocked(), self.runner(text))
        self.assertEqual(audit["state"], "design_clean")
        self.assertEqual(len(self.asked), 2)
        self.assertNotIn("validation_errors", self.asked[0]["task_capsule"]["repair"])
        self.assertEqual(self.asked[1]["task_capsule"]["repair"]["validation_errors"], [refusal])

    def test_a_row_still_refused_after_the_second_answer_stops_the_run(self):
        refusal = {"code": "tier.L3.words", "id": "CHR-0002", "severity": "blocking"}
        self.bf.validate_universe_design = lambda root, proposal: [refusal]
        text = json.dumps({"events": [{"id": "EVT-0001", "era": "ERA-0002", "order": 1, "summary": "ok"}]})
        with self.assertRaises(self.bf.BookForgeError):
            self.bf._repair_blocked_universe(self.root, self.proposal, self.blocked(), self.runner(text))
        self.assertEqual(len(self.asked), self.bf.UNIVERSE_REPAIR_VALIDATION_ATTEMPTS)

    def test_an_answer_naming_no_requested_row_is_refused(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf._repair_blocked_universe(self.root, self.proposal, self.blocked(), self.runner(json.dumps({"events": [{"id": "EVT-9999"}]})))


if __name__ == "__main__":
    unittest.main()


class ChunkedRunPassesWhatIsDecidedTests(unittest.TestCase):
    def test_each_chunk_is_given_the_merge_of_the_ones_before_it(self):
        bf = load_module()
        seen = []
        bf.claim_task = lambda root, task_id, request_hash=None: {"capsule": "/x/attempt/capsule.json"}

        def fake(root, task_id, claim, attempt_dir, base, chunk, imports, runner, tokens, merged=None):
            seen.append((chunk["category"], sorted((merged or {}).keys())))
            return {chunk["category"]: [{"id": "X-1"}]}, {}, []

        bf._run_design_chunk = fake
        bf._run_design_chunked(Path("."), "T", {}, [], None, chunks=[{"category": "eras"}, {"category": "events"}])
        self.assertEqual(seen, [("eras", []), ("events", ["eras"])])
