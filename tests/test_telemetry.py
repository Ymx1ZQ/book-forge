import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_telemetry", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")

    def execute(self, task_id, role, *, estimated=1000, provider_input=1060, cost=0.001):
        self.bf.add_task(self.project, task_id, role)
        claim = self.bf.claim_task(self.project, task_id, request_hash="a" * 64)
        self.bf.mark_provider_accepted(self.project, claim["attempt"], f"ses-{task_id}")
        self.bf.stage_outputs(self.project, claim["attempt"], {})
        receipt = self.bf.record_execution(
            self.project,
            claim["attempt"],
            claim["fence"],
            output_hash="b" * 64,
            telemetry={
                "provider": "openrouter",
                "model": MODEL,
                "variant": self.bf.ROLE_SPECS[role][1],
                "session_id": f"ses-{task_id}",
                "tokens": {"input": provider_input, "output": 200, "total": provider_input + 200},
                "cost": cost,
                "latency_ms": 25,
                "finish": "stop",
                "envelope_hash": "a" * 64,
                "estimated_input_tokens": estimated,
                "call_number": 1,
            },
        )
        self.bf.promote_task(self.project, claim["attempt"], claim["fence"])
        return Path(claim["capsule"]).parent / "execution-receipt.json"

    def test_status_aggregates_paid_requests_without_model_calls(self):
        self.execute("DRAFT-BOOK-0001-CH-0001", "writer", cost=0.003)
        self.execute("REVIEW-COLD-BOOK-0001-CH-0001", "cold-reader", cost=0.001)
        report = self.bf.telemetry_report(self.project, strict=True)

        self.assertTrue(report["valid"])
        self.assertEqual(report["calls"]["accepted"], 2)
        self.assertEqual(report["calls"]["with_receipts"], 2)
        self.assertEqual(report["usage"]["provider_input_tokens"], 2120)
        self.assertEqual(report["usage"]["estimated_input_tokens"], 2000)
        self.assertAlmostEqual(report["usage"]["cost"], 0.004)
        self.assertEqual(report["by_role"]["writer"]["calls"], 1)
        self.assertEqual(self.bf.status_project(self.project)["telemetry"]["calls"]["accepted"], 2)

    def test_strict_validation_rejects_envelope_call_concurrency_and_fanout_breaches(self):
        receipts = []
        for task_id, role in [
            ("DRAFT-BOOK-0001-CH-0001", "writer"),
            ("REVIEW-COLD-BOOK-0001-CH-0001", "cold-reader"),
            ("REVIEW-TECH-BOOK-0001-CH-0001", "technical-editor"),
            ("REVISE-BOOK-0001-CH-0001", "reviser"),
            ("VERIFY-BOOK-0001-CH-0001", "canon-auditor"),
            ("EXTRA-BOOK-0001-CH-0001", "writer"),
        ]:
            receipts.append(self.execute(task_id, role))
        bad = json.loads(receipts[0].read_text())
        bad.update({"estimated_input_tokens": 13000, "variant": "high"})
        bad["tokens"]["input"] = 30000
        receipts[0].write_text(json.dumps(bad))

        plan = self.bf._load_plan(self.project)
        for index in range(5):
            plan["attempts"].append({
                "id": f"SEEDED-{index}",
                "task": plan["tasks"][index]["id"],
                "role": plan["tasks"][index]["role"],
                "run": "RUN-SEEDED",
                "state": "running",
                "provider_accepted": False,
            })
        self.bf._save_plan(self.project, plan)
        self.bf._write_json(
            self.project / ".book-forge/currentness.json",
            {"schema": 1, "artifacts": {f"STALE-{index}": {"current": False, "causes": ["seed"]} for index in range(21)}},
        )

        report = self.bf.telemetry_report(self.project)
        codes = {row["code"] for row in report["violations"]}
        self.assertTrue({"envelope_budget", "variant_pin", "provider_overhead", "chapter_call_budget", "concurrency", "invalidation_fanout"} <= codes)
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.telemetry_report(self.project, strict=True)


if __name__ == "__main__":
    unittest.main()
