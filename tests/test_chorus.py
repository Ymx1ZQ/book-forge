import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"

def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_chorus", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def mock_runner_for(role_map):
    def runner(role, envelope, attempt_dir):
        if role.startswith("advisor-"):
            return {"text": json.dumps({"findings": [{"id": "W-0001", "severity": "note", "issue": f"issue from {role}", "evidence": [], "suggestion": "sug"}], "suggestions": ["s"]}), "session_id": "s", "provider": "openrouter", "model": role}
        if role == "chorus-synthesizer":
            return {"text": json.dumps({"patches": [{"finding": "W-0001", "patch": "p", "location": "universe/worldbuilding.md"}], "ranked_findings": []}), "session_id": "s", "provider": "openrouter", "model": role}
        # designer/auditor fallback
        val = role_map.get(role, {"findings": []})
        return {"text": json.dumps(val), "session_id": "s", "provider": "openrouter", "model": "openrouter/deepseek/deepseek-v4-flash-0731", "variant": "max", "tokens": {"input": 100, "output": 100}, "cost": 0, "latency_ms": 1, "finish": "stop"}
    return runner

class ChorusTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        (self.project / "universe" / "design-brief.json").write_text(json.dumps({"schema": 1, "answers": {"kernel": "k", "chronology": "c", "places": "p", "factions": "f", "characters": "ch", "themes": ["t"], "style": "s"}, "scope": ["kernel"]}))

    def test_chorus_run_standalone_produces_report(self):
        envelope = self.bf.build_envelope(self.project, role="designer", task_capsule={"scope": "universe"}, imports=["UNI-0001#kernel"], state={}, tools=[], max_output_tokens=2000)
        res = self.bf.run_chorus(self.project, {"scope": "universe"}, envelope, ["openrouter/deepseek/deepseek-v4-flash-0731", "openrouter/x-ai/grok-4.6"], provider=mock_runner_for({}))
        self.assertEqual(res["total_findings"], 2)
        self.assertTrue((Path(res["dir"]) / "chorus-report.md").exists())
        st = self.bf.chorus_status(self.project)
        self.assertTrue(any(s["scope"] == "universe" and s["latest"] for s in st["scopes"]))

    def test_no_chorus_skips_advisors(self):
        calls = []
        def runner(role, envelope, attempt_dir):
            calls.append(role)
            if role.startswith("advisor-"):
                raise AssertionError("should not be called")
            return {"text": json.dumps({"kernel": [{"id": "LAW-0001", "summary": "s"}], "eras": [], "events": [], "places": [], "factions": [], "characters": [], "themes": ["t"], "style": {"tense": "past", "person": "third-limited"}, "continuity_material": {}, "book_local": {}, "unresolved_questions": []}), "session_id": "s", "provider": "openrouter", "model": "openrouter/deepseek/deepseek-v4-flash-0731", "variant": "medium", "tokens": {"input": 100, "output": 100}, "cost": 0, "latency_ms": 1, "finish": "stop"}
        # Need to also mock auditor
        orig = runner
        def wrapped(role, envelope, attempt_dir):
            if role == "canon-auditor":
                return {"text": json.dumps({"findings": []}), "session_id": "s", "provider": "openrouter", "model": "openrouter/deepseek/deepseek-v4-flash-0731", "variant": "max", "tokens": {"input": 100, "output": 100}, "cost": 0, "latency_ms": 1, "finish": "stop"}
            return orig(role, envelope, attempt_dir)
        # Disable via flag
        self.bf.execute_universe_design(self.project, provider=wrapped, no_chorus=True)
        self.assertNotIn("advisor-grok-4-6", calls)

    def test_malformed_advisor_does_not_kill_run(self):
        calls = []
        def runner(role, envelope, attempt_dir):
            calls.append(role)
            if role == "advisor-grok-4-6":
                return {"text": json.dumps({"findings": [{"severity": "warning", "issue": "no id here"}]}), "session_id": "s", "provider": "openrouter", "model": role}
            return {"text": json.dumps({"findings": [{"id": "W-0001", "severity": "note", "issue": f"issue from {role}", "evidence": [], "suggestion": "sug"}], "suggestions": ["s"]}), "session_id": "s", "provider": "openrouter", "model": role}
        envelope = self.bf.build_envelope(self.project, role="designer", task_capsule={"scope": "universe"}, imports=["UNI-0001#kernel"], state={}, tools=[], max_output_tokens=2000)
        res = self.bf.run_chorus(self.project, {"scope": "universe"}, envelope, ["openrouter/deepseek/deepseek-v4-flash-0731", "openrouter/x-ai/grok-4.6"], provider=runner)
        self.assertEqual(res["total_findings"], 1)
        report = (Path(res["dir"]) / "chorus-report.md").read_text()
        self.assertIn("FAILED (non-blocking)", report)
        self.assertIn("Chorus finding missing id", report)

    def test_with_chorus_context_injects_report(self):
        # First run chorus to create a report
        envelope = self.bf.build_envelope(self.project, role="designer", task_capsule={"scope": "universe"}, imports=["UNI-0001#kernel"], state={}, tools=[], max_output_tokens=2000)
        self.bf.run_chorus(self.project, {"scope": "universe"}, envelope, ["openrouter/deepseek/deepseek-v4-flash-0731"], provider=mock_runner_for({}))
        self.bf.chorus_synthesize(self.project, provider=mock_runner_for({}))
        # Now design with with_chorus_context should inject
        seen = {}
        orig_build = self.bf.build_envelope
        def capture(*args, **kwargs):
            env = orig_build(*args, **kwargs)
            if kwargs.get("role") == "designer":
                seen["capsule"] = kwargs.get("task_capsule")
            return env
        self.bf.build_envelope = capture
        try:
            # Provide designer that succeeds
            def provider(role, envelope, attempt_dir):
                if role == "designer":
                    return {"text": json.dumps({"kernel": [{"id": "LAW-0001", "summary": "s"}], "eras": [], "events": [], "places": [], "factions": [], "characters": [], "themes": ["t"], "style": {"tense": "past", "person": "third-limited"}, "continuity_material": {}, "book_local": {}, "unresolved_questions": []}), "session_id": "s", "provider": "openrouter", "model": "openrouter/deepseek/deepseek-v4-flash-0731", "variant": "high", "tokens": {"input": 100, "output": 100}, "cost": 0, "latency_ms": 1, "finish": "stop"}
                if role.startswith("advisor-"):
                    return {"text": json.dumps({"findings": [], "suggestions": []}), "session_id": "s", "provider": "openrouter", "model": role}
                return {"text": json.dumps({"findings": []}), "session_id": "s", "provider": "openrouter", "model": role, "variant": "max", "tokens": {"input": 100, "output": 100}, "cost": 0, "latency_ms": 1, "finish": "stop"}
            # Need a fresh project to avoid already succeeded
            import tempfile as tf
            with tf.TemporaryDirectory() as td2:
                proj2 = Path(td2) / "w2"
                self.bf.init_project(proj2, "W2")
                (proj2 / "universe" / "design-brief.json").write_text(json.dumps({"schema": 1, "answers": {"kernel": "k", "chronology": "c", "places": "p", "factions": "f", "characters": "ch", "themes": ["t"], "style": "s"}, "scope": ["kernel"]}))
                # Copy chorus from first project to second for test (simulate prior run)
                import shutil
                src = self.project / ".book-forge" / "chorus"
                dst = proj2 / ".book-forge" / "chorus"
                if src.exists():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                # Patch build to capture
                self.bf.build_envelope = capture
                try:
                    self.bf.execute_universe_design(proj2, provider=provider, with_chorus_context=True)
                except Exception:
                    pass
                self.assertIn("chorus_report", seen.get("capsule", {}))
        finally:
            self.bf.build_envelope = orig_build

    def test_chorus_synthesize_deduplicates(self):
        envelope = self.bf.build_envelope(self.project, role="designer", task_capsule={"scope": "universe"}, imports=["UNI-0001#kernel"], state={}, tools=[], max_output_tokens=2000)
        # Two advisors with same issue text
        def dup_runner(role, envelope, attempt_dir):
            return {"text": json.dumps({"findings": [{"id": "W-1", "severity": "warning", "issue": "Same issue", "evidence": [], "suggestion": "s"}], "suggestions": []}), "session_id": "s", "provider": "openrouter", "model": role}
        self.bf.run_chorus(self.project, {"scope": "universe"}, envelope, ["openrouter/deepseek/deepseek-v4-flash-0731", "openrouter/x-ai/grok-4.6"], provider=dup_runner)
        syn = self.bf.chorus_synthesize(self.project, provider=mock_runner_for({}))
        # Deduplicated to 1 finding (same issue)
        self.assertEqual(len(syn["findings"]), 1)

if __name__ == "__main__":
    unittest.main()
