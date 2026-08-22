import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_audit", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROLE_VARIANTS = {name: spec[1] for name, spec in load_module().ROLE_SPECS.items()}


class AuditProvider:
    def __init__(self):
        self.calls = []
    def __call__(self, role, envelope, attempt_dir):
        self.calls.append(envelope["payload"]["task"])
        job = envelope["payload"]["task"]["job"]
        evidence = job["evidence"][0]
        value = {"findings": [{"id": f"F-{job['id']}", "severity": "blocking", "issue": "Seeded boundary mismatch", "evidence": [{"location": evidence["location"], "hash": evidence["hash"]}], "repair_scope": job["books"]}]}
        return {"text": json.dumps(value), "provider": "openrouter", "model": MODEL, "variant": ROLE_VARIANTS[role], "session_id": f"ses-{len(self.calls)}", "tokens": {}, "cost": 0, "latency_ms": 1, "finish": "stop"}


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        self.books = [self.bf.add_book(self.project, title)["id"] for title in ("A", "B", "Unrelated")]
        self.relation = self.bf.add_relation(self.project, "sequel_of", self.books[:2], obligations=["Carry state"])
        for index, book in enumerate(self.books[:2], start=1):
            state_path = self.project / f"books/{book}/state.yaml"
            state = json.loads(state_path.read_text())
            state["consequences"] = [{"scope": "continuity", "fact": f"Mara state {index}", "entities": ["CHR-0001"]}]
            state_path.write_text(json.dumps(state))

    def test_generates_bounded_non_all_pairs_jobs_and_schedules_repairs(self):
        jobs = self.bf.generate_audit_jobs(self.project)
        self.assertTrue(any(job["kind"] == "relation-boundary" for job in jobs))
        self.assertTrue(any(job["kind"] == "entity-transition" for job in jobs))
        self.assertFalse(any(self.books[2] in job["books"] for job in jobs))

        provider = AuditProvider()
        result = self.bf.audit_continuity(self.project, relation_id=self.relation["id"], provider=provider)
        self.assertEqual(result["calls"], 1)
        self.assertEqual(len(result["findings"]), 1)
        plan = json.loads((self.project / ".book-forge/plan.json").read_text())
        self.assertTrue(any(task["id"].startswith("REPAIR-") and task["state"] == "pending" for task in plan["tasks"]))

    def test_enforces_wave_and_candidate_override_gates(self):
        for index in range(21):
            a = self.bf.add_book(self.project, f"X{index}")["id"]
            b = self.bf.add_book(self.project, f"Y{index}")["id"]
            self.bf.add_relation(self.project, "parallel_to", [a, b])
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.audit_continuity(self.project, provider=AuditProvider(), max_jobs=8)
        jobs = self.bf.generate_audit_jobs(self.project, override=True)
        self.assertGreater(len(jobs), 20)
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.audit_continuity(self.project, provider=AuditProvider(), max_jobs=9, override=True)


if __name__ == "__main__":
    unittest.main()
