import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_audit_budget", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuditBudgetTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        # Ensure indexes built for envelope
        self.bf.rebuild_indexes(self.project)

    def _estimate_for_size(self, size, role="canon-auditor"):
        # Helper to build envelope with a payload of approximate size
        # Use task_capsule with large string to reach target estimated_input
        # Estimate includes overhead 768 + (len+2)//3*1.15
        capsule = {"scope": "book", "proposal": "x" * size, "canon": "y" * (size // 2)}
        env = self.bf.build_envelope(
            self.project,
            role=role,
            task_capsule=capsule,
            imports=[],
            state={},
            tools=[],
            max_output_tokens=3500,
        )
        return env

    def test_19_8k_passes(self):
        # 19.8k capsule should pass with new default 32000 (old 16k would fail)
        # Find a size that yields ~19800 estimated_input
        # Calibrate by brute force: try sizes until estimate in [18000, 21000]
        # Use helper to avoid brittle hard-coded byte size
        size = 40000
        env = None
        for trial in [30000, 35000, 40000, 45000, 50000]:
            try:
                candidate = self._estimate_for_size(trial)
                est = candidate["estimated_input_tokens"]
                if 18000 <= est <= 21000:
                    env = candidate
                    size = trial
                    break
            except self.bf.ContextOverflowError:
                continue
        if env is None:
            # fallback: use 35000 and check it passes under 32k but would fail under 16k
            env = self._estimate_for_size(35000)
        est = env["estimated_input_tokens"]
        budget = env["input_budget"]
        # Must be default 32000 and estimate < budget
        self.assertEqual(budget, 32000)
        self.assertLessEqual(est, 32000)
        self.assertGreater(est, 16000, "19.8k test should exceed old 16k budget to prove raise")
        # Also check ROLE_BUDGETS default
        self.assertEqual(self.bf.ROLE_BUDGETS["canon-auditor"][0], 32000)
        # Also check _envelope_input_budget returns 32000
        self.assertEqual(self.bf._envelope_input_budget(self.project, "canon-auditor"), 32000)
        # max_output_tokens unchanged
        self.assertEqual(self.bf.ROLE_BUDGETS["canon-auditor"][1], 3500)

    def test_33k_fails_hard(self):
        # 33k capsule should hard-fail with explicit message estimated_input X > budget Y
        # Find size that exceeds 32000
        found = False
        for trial in [60000, 70000, 80000, 90000]:
            try:
                self._estimate_for_size(trial)
            except self.bf.ContextOverflowError as exc:
                msg = str(exc)
                # Must contain estimated_input > budget pattern and budget 32000
                self.assertIn("estimated_input", msg)
                self.assertIn("> budget", msg)
                self.assertIn("32000", msg)
                self.assertIn("exceeds", msg)  # keep legacy substring
                # also check attributes
                self.assertGreater(exc.estimated, 32000)
                self.assertEqual(exc.budget, 32000)
                found = True
                break
        self.assertTrue(found, "33k capsule should overflow 32k budget")

    def test_knob_override(self):
        # Test audit.input_budget knob override - same pattern as test_context design_max_input_tokens
        import json as _json
        config = _json.loads((self.project / "book-forge.yaml").read_text())
        # Override to 20000 -> 19.8k should still pass but 33k still fails, and budget reflects knob
        config.setdefault("audit", {})["input_budget"] = 20000
        (self.project / "book-forge.yaml").write_text(_json.dumps(config, indent=2))
        self.assertEqual(self.bf._envelope_input_budget(self.project, "canon-auditor"), 20000)
        # 19.8k capsule with 20000 budget should pass (if we pick 18000-20000)
        # Try small size that fits 20000 but exceeds old 16k conceptually
        # Use 30000 size which yields ~18257 -> should pass with 20000
        try:
            env = self._estimate_for_size(30000)
            self.assertEqual(env["input_budget"], 20000)
            self.assertLessEqual(env["estimated_input_tokens"], 20000)
        except self.bf.ContextOverflowError:
            self.fail("18k should pass with 20000 override")

        # Now set to 50000 -> 33k should pass
        config["audit"]["input_budget"] = 50000
        (self.project / "book-forge.yaml").write_text(_json.dumps(config, indent=2))
        self.assertEqual(self.bf._envelope_input_budget(self.project, "canon-auditor"), 50000)
        # 33k estimate should now pass (trial 70000)
        try:
            # 60000 yields ~35507 which is under 50000, 70000 yields 41257 also under 50000
            env = self._estimate_for_size(60000)
            self.assertEqual(env["input_budget"], 50000)
            self.assertLessEqual(env["estimated_input_tokens"], 50000)
        except self.bf.ContextOverflowError as exc:
            self.fail(f"35k should pass with 50000 override, got {exc}")

        # Validation: malformed knob fails closed
        config["audit"]["input_budget"] = "huge"
        (self.project / "book-forge.yaml").write_text(_json.dumps(config, indent=2))
        with self.assertRaises(self.bf.BookForgeError) as cm:
            self.bf._envelope_input_budget(self.project, "canon-auditor")
        self.assertIn("audit.input_budget", str(cm.exception))

        # max_output_tokens unchanged after knob changes
        self.assertEqual(self.bf.ROLE_BUDGETS["canon-auditor"][1], 3500)

if __name__ == "__main__":
    unittest.main()
