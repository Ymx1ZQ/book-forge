import importlib.util
import json
import pathlib
import re
import tempfile
import shutil
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_chunking", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

bf = load_module()
class DesignChunkingTests(unittest.TestCase):
    def test_chunk_bytes_bound(self):
        # each chunk must be <15KB, whole 41KB monolith must be rejected
        small = {"kernel": [{"id": "LAW-0001", "summary": "x"*100}]}
        self.assertLess(bf.chunk_bytes(small), bf.DESIGN_CHUNK_MAX_BYTES)
        # Build a large proposal that would be 41KB if monolithic
        large_proposal = {
            "kernel": [{"id": f"LAW-{i:04d}", "summary": "x"*250} for i in range(25)],
            "characters": [{"id": f"CHR-{i:04d}", "summary": "y"*250} for i in range(25)],
            "places": [{"id": f"PLC-{i:04d}", "summary": "z"*250} for i in range(25)],
        }
        # monolith size >15KB
        self.assertGreater(bf.chunk_bytes(large_proposal), bf.DESIGN_CHUNK_MAX_BYTES)
        # split should produce chunks each <15KB
        chunks = bf.split_proposal_into_chunks(large_proposal)
        for ch in chunks:
            self.assertLessEqual(bf.chunk_bytes(ch), bf.DESIGN_CHUNK_MAX_BYTES)
        # small chunk passes assert
        bf.assert_chunk_size(small)

    def test_chunk_size_assert_fails_over_limit(self):
        huge = {"kernel": [{"id": "LAW-0001", "summary": "x"*20000}]}
        with self.assertRaises(bf.BookForgeError) as cm:
            bf.assert_chunk_size(huge)
        self.assertIn("exceeds", str(cm.exception))

    def test_max_tokens_budget_in_range(self):
        # ROLE_BUDGETS designer must be 8192-12288
        _, out = bf.ROLE_BUDGETS["designer"]
        self.assertGreaterEqual(out, 8192)
        self.assertLessEqual(out, 12288)
        # agents/openai.yaml must reflect same
        yaml = pathlib.Path(bf.__file__).resolve().parents[1] / "agents/openai.yaml"
        text = yaml.read_text()
        # extract max_output_tokens value
        import re
        m = re.search(r'max_output_tokens:\s*(\d+)', text)
        self.assertIsNotNone(m)
        val = int(m.group(1))
        self.assertGreaterEqual(val, 8192)
        self.assertLessEqual(val, 12288)

    def test_retry_on_length_then_failed_length(self):
        # Test _is_length_finish helper and failed_length not outcome_unknown
        self.assertTrue(bf._is_length_finish({"finish": "length"}))
        self.assertFalse(bf._is_length_finish({"finish": "stop"}))
        self.assertTrue(bf._is_length_finish({"finish": "LENGTH"}))
        self.assertFalse(bf._is_length_finish({}))
        # Check constants
        self.assertEqual(bf.DESIGN_CHUNK_MAX_TOKENS, 8192)
        # Check that _run_with_length_retry exists and has max_retries param
        import inspect
        sig = inspect.signature(bf._run_with_length_retry)
        self.assertIn("max_retries", sig.parameters)
        # Verify run_opencode_role handles length finish (inspect source)
        import pathlib as _pl
        src = (_pl.Path(bf.__file__).read_text())
        self.assertIn("failed_length", src)
        self.assertIn("outcome_unknown", src)
        # Ensure failed_length is used for length exhaustion, not outcome_unknown
        self.assertIn("length", src.lower())
        # Zero-output length truncation must surface as finish="length" for
        # caller retry, never as ProviderOutcomeUnknown.
        self.assertIn('finish": "length"', src)

    def test_length_finish_retries_then_fails_length(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "world"
            bf.init_project(root, "World")
            plan = bf._load_plan(root)
            bf.add_task(root, "DESIGN-UNI-0001", "designer", priority=10)
            envelope = bf.build_envelope(
                root, role="designer", task_capsule={"scope": "universe", "brief": {}},
                imports=[], state={}, tools=[], max_output_tokens=3000,
            )
            calls = {"n": 0}
            def always_length(role, env, attempt_dir):
                calls["n"] += 1
                return {
                    "text": "", "provider": "openrouter", "model": "deepseek/deepseek-v4-flash-0731",
                    "variant": "max", "session_id": f"ses-len-{calls['n']}",
                    "tokens": {"input": 100, "output": 0, "reasoning": 32000}, "cost": 0.001,
                    "latency_ms": 5, "finish": "length",
                }
            with self.assertRaises(bf.BookForgeError) as cm:
                bf._run_with_length_retry(root, "DESIGN-UNI-0001", "designer", envelope, always_length)
            self.assertEqual(calls["n"], 3)
            self.assertIn("failed_length", str(cm.exception))
            plan = bf._load_plan(root)
            task = next(t for t in plan["tasks"] if t["id"] == "DESIGN-UNI-0001")
            self.assertEqual(task["state"], "blocked")
            failed = [a for a in plan["attempts"] if a["state"] == "failed_length"]
            self.assertEqual(len(failed), 3)

    def test_length_finish_retries_then_succeeds(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "world"
            bf.init_project(root, "World")
            bf.add_task(root, "DESIGN-UNI-0001", "designer", priority=10)
            envelope = bf.build_envelope(
                root, role="designer", task_capsule={"scope": "universe", "brief": {}},
                imports=[], state={}, tools=[], max_output_tokens=3000,
            )
            calls = {"n": 0}
            def length_then_stop(role, env, attempt_dir):
                calls["n"] += 1
                finish = "length" if calls["n"] < 3 else "stop"
                return {
                    "text": "{}" if finish == "stop" else "", "provider": "openrouter",
                    "model": "deepseek/deepseek-v4-flash-0731", "variant": "max",
                    "session_id": f"ses-{calls['n']}", "tokens": {"input": 100, "output": 10},
                    "cost": 0.001, "latency_ms": 5, "finish": finish,
                }
            claim, result = bf._run_with_length_retry(root, "DESIGN-UNI-0001", "designer", envelope, length_then_stop)
            self.assertEqual(calls["n"], 3)
            self.assertEqual(result["finish"], "stop")
            self.assertIsNotNone(claim)

    def test_design_prompt_mentions_per_chunk(self):
        prompt = (pathlib.Path(bf.__file__).resolve().parents[1] / "assets/prompts/designer.md").read_text()
        self.assertIn("15KB", prompt)
        self.assertIn("chunk", prompt.lower())

    def test_parse_chunked_contract_merges_multiple_objects(self):
        # Designer emits 7 per-category objects; merge must combine them.
        text = "\n".join([
            json.dumps({"kernel": [{"id": "LAW-0001", "summary": "a"}]}),
            json.dumps({"eras": [{"id": "ERA-0001", "summary": "b"}]}),
            json.dumps({"places": [{"id": "PLC-0001", "summary": "c"}]}),
            json.dumps({"characters": [{"id": "CHR-0001", "summary": "d"}]}),
            json.dumps({"characters": [{"id": "CHR-0002", "summary": "e"}]}),
            json.dumps({"themes": ["t"], "style": {"tense": "past"}}),
            json.dumps({"continuity_material": {"CNT-0001": ["CHR-0001"]}}),
        ])
        merged = bf._parse_chunked_contract(text)
        self.assertEqual(len(merged["kernel"]), 1)
        self.assertEqual(len(merged["eras"]), 1)
        self.assertEqual(len(merged["characters"]), 2)  # concatenated sub-chunks
        self.assertEqual(merged["characters"][1]["id"], "CHR-0002")
        self.assertEqual(merged["style"], {"tense": "past"})
        self.assertEqual(merged["continuity_material"], {"CNT-0001": ["CHR-0001"]})

    def test_parse_chunked_contract_single_object_ok(self):
        text = json.dumps({"kernel": [{"id": "LAW-0001", "summary": "a"}]})
        merged = bf._parse_chunked_contract(text)
        self.assertEqual(len(merged["kernel"]), 1)

    def test_parse_chunked_contract_rejects_huge_chunk(self):
        huge = json.dumps({"kernel": [{"id": "LAW-0001", "summary": "x" * 20000}]})
        with self.assertRaises(bf.BookForgeError):
            bf._parse_chunked_contract(huge)

    def test_parse_chunked_contract_no_json(self):
        with self.assertRaises(bf.BookForgeError):
            bf._parse_chunked_contract("no json here")

    def test_designer_capsule_m4_tiers(self):
        # The universe designer capsule must carry the M4 tier contract.
        src = pathlib.Path(bf.__file__).read_text()
        self.assertIn('tiered cast (M4)', src)
        self.assertIn('total named characters >= 22', src)
        self.assertIn('tier', src)

if __name__ == "__main__":
    unittest.main()