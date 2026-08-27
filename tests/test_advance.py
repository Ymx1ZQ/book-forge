import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_advance", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROLE_VARIANTS = {name: spec[1] for name, spec in load_module().ROLE_SPECS.items()}
def _prose(words=700):
    """A stub chapter that meets the contract's word count."""
    body = " ".join(f"Mara counted the stone at step {index} and the warden said nothing." for index in range(words // 12 + 2))
    return f'# The Ninth Tide\n\nMara set the lamp on the stone. "Open it," she said.\n\n{body}\n\nThe warden did not move.\n'


PROSE = _prose()


class ScriptedProvider:
    """A provider that answers every role, and can be told to fail a role N times."""

    def __init__(self, bf, chapters=2, fail=None):
        self.bf = bf
        self.chapters = chapters
        self.fail = dict(fail or {})
        self.calls = []

    def _envelope(self, value, role, finish="stop"):
        return {
            "text": json.dumps(value),
            "provider": "openrouter", "model": MODEL, "variant": ROLE_VARIANTS.get(role, "high"),
            "session_id": f"ses-{len(self.calls)}", "tokens": {"input": 100, "output": 200},
            "cost": 0.001, "latency_ms": 5, "finish": finish,
        }

    def _designer(self, task):
        chunk = task.get("chunk") or {}
        spine = {
            "premise": "A diver must decide whether memory can be owned.",
            "entry_state": {"CHR-0001": "isolated"},
            "arc": ["refusal", "cost", "choice"],
            "exit_boundary": {"CHR-0001": "committed"},
        }
        if chunk.get("category") == "chapters":
            first, last = int(chunk["first_order"]), int(chunk["last_order"])
            return {"chapters": [{
                "id": f"CH-{index:04d}", "order": index, "title": "The Ninth Tide", "pov": "CHR-0001",
                "beats": ["Mara wants the log and the warden will not open it"],
                "plants": [], "reveals": [], "target_words": 700,
                "imports": ["UNI-0001#kernel"], "obligations": [], "pivotal": None,
            } for index in range(first, last + 1)]}
        return {**spine, "chapter_outline": [
            {"id": f"CH-{i:04d}", "order": i, "title": "The Ninth Tide", "pov": "CHR-0001", "summary": "She goes down."}
            for i in range(1, self.chapters + 1)]}

    def __call__(self, role, envelope, attempt_dir):
        self.calls.append(role)
        remaining = self.fail.get(role, 0)
        if remaining:
            self.fail[role] = remaining - 1
            return self._envelope({}, role, finish="length")
        task = envelope["payload"]["task"]
        if role.startswith("advisor-") or role == "chorus-synthesizer":
            return self._envelope({"findings": [], "suggestions": []}, role)
        if role == "designer":
            return self._envelope(self._designer(task), role)
        if role == "canon-auditor":
            return self._envelope({"findings": []}, role)
        if role == "writer":
            return self._envelope({"prose_markdown": PROSE, "beat_map": [{"beat": "Mara wants the log and the warden will not open it", "evidence": "Open it, she said."}], "consequences": []}, role)
        if role in {"cold-reader"}:
            return self._envelope({"findings": []}, role)
        if role == "technical-editor":
            return self._envelope({"findings": [], "consequences": []}, role)
        if role == "reviser":
            return self._envelope({"prose_markdown": PROSE, "beat_map": [{"beat": "Mara wants the log and the warden will not open it", "evidence": "Open it, she said."}], "consequences": [], "dispositions": [], "reader_state": "Mara asked."}, role)
        if role == "translator":
            return self._envelope({"translated_markdown": PROSE.replace("Open it", "Aprilo"), "glossary_updates": [], "boundary": "Mara ha chiesto."}, role)
        raise AssertionError(role)


class AdvanceFixture(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["chorus"] = {"enabled": False, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER, "style_review": {"enabled": False}}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.book = self.bf.add_book(self.project, "A")["id"]
        (self.project / f"books/{self.book}/book-brief.json").write_text(
            json.dumps({"schema": 1, "premise": "A diver must decide.", "characters": ["Mara"], "plot": ["dive"], "tone": "quiet"})
        )

    def plan(self):
        return self.bf._load_plan(self.project)

    def task(self, task_id):
        return next(row for row in self.plan()["tasks"] if row["id"] == task_id)


class AdvanceEndToEndTests(AdvanceFixture):
    def test_a_book_goes_from_an_empty_design_to_closed_chapters_in_one_command(self):
        result = self.bf.advance_book(self.project, self.book, until="chapters", provider=ScriptedProvider(self.bf))
        self.assertEqual(result["stages"], ["design", "chapters"])
        chapters = sorted((self.project / f"books/{self.book}/manuscript/chapters").glob("CH-*.md"))
        self.assertEqual(len(chapters), 2)
        self.assertIn("Mara set the lamp", chapters[0].read_text())

    def test_it_skips_the_design_when_the_book_already_has_one(self):
        provider = ScriptedProvider(self.bf)
        self.bf.advance_book(self.project, self.book, until="design", provider=provider)
        again = ScriptedProvider(self.bf)
        result = self.bf.advance_book(self.project, self.book, until="design", provider=again)
        self.assertEqual(result["stages"], [])
        self.assertEqual(again.calls, [])

    def test_a_truncated_answer_costs_a_retry_and_not_a_human(self):
        provider = ScriptedProvider(self.bf, fail={"writer": 1})
        result = self.bf.advance_book(self.project, self.book, until="chapters", provider=provider)
        self.assertEqual(result["stages"], ["design", "chapters"])
        self.assertEqual(len(list((self.project / f"books/{self.book}/manuscript/chapters").glob("CH-*.md"))), 2)

    def test_an_unknown_stage_is_refused(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.advance_book(self.project, self.book, until="publish", provider=ScriptedProvider(self.bf))


class StageRetryTests(AdvanceFixture):
    """A failure inside a stage used to reach the caller as the engine's own message
    with the run left blocked and nothing said about what to do next."""

    def test_a_stage_that_fails_once_and_then_succeeds_is_never_surfaced(self):
        provider = ScriptedProvider(self.bf, fail={"designer": 3})
        result = self.bf.advance_book(self.project, self.book, until="design", provider=provider)
        self.assertEqual(result["stages"], ["design"])
        self.assertTrue((self.project / f"books/{self.book}/chapters/CH-0001.json").is_file())

    def test_a_stage_that_keeps_failing_halts_naming_the_failure(self):
        provider = ScriptedProvider(self.bf, fail={"designer": 999})
        with self.assertRaises(self.bf.AdvanceHalted) as caught:
            self.bf.advance_book(self.project, self.book, until="design", provider=provider)
        message = str(caught.exception)
        self.assertIn("design", message)
        self.assertTrue("DESIGN" in message or "failed" in message)

    def test_a_halt_always_says_what_to_do_next(self):
        self.bf.add_task(self.project, "DRAFT-Q", "writer", deps=[], priority=50, outputs=[])
        plan = self.plan()
        next(row for row in plan["tasks"] if row["id"] == "DRAFT-Q")["state"] = "outcome_unknown"
        self.bf._save_plan(self.project, plan)
        with self.assertRaises(self.bf.AdvanceHalted) as caught:
            self.bf.advance_book(self.project, self.book, until="design", provider=ScriptedProvider(self.bf))
        self.assertIn("resolve-unknown", str(caught.exception))


class RecoveryTests(AdvanceFixture):
    def test_a_task_blocked_by_a_length_failure_returns_to_pending(self):
        self.bf.add_task(self.project, "DRAFT-X", "writer", deps=[], priority=50, outputs=[])
        plan = self.plan()
        task = next(row for row in plan["tasks"] if row["id"] == "DRAFT-X")
        task["state"] = "blocked"
        plan["attempts"].append({"id": "ATT-9001", "task": "DRAFT-X", "role": "writer", "state": "failed_length", "failure": "finish_reason==length after retries", "provider_accepted": False})
        self.bf._save_plan(self.project, plan)

        state = self.bf.recover_before_dispatch(self.project)

        self.assertEqual(state["recovered"], ["DRAFT-X"])
        self.assertEqual(self.task("DRAFT-X")["state"], "pending")
        self.assertEqual(self.task("DRAFT-X")["auto_retries"], 1)

    def test_recovery_gives_up_after_three_tries_and_names_the_task(self):
        self.bf.add_task(self.project, "DRAFT-Y", "writer", deps=[], priority=50, outputs=[])
        plan = self.plan()
        task = next(row for row in plan["tasks"] if row["id"] == "DRAFT-Y")
        task["state"] = "blocked"
        task["auto_retries"] = self.bf.MAX_AUTO_RETRIES
        plan["attempts"].append({"id": "ATT-9002", "task": "DRAFT-Y", "role": "writer", "state": "failed_length", "failure": "truncated again", "provider_accepted": False})
        self.bf._save_plan(self.project, plan)

        state = self.bf.recover_before_dispatch(self.project)

        self.assertEqual(state["recovered"], [])
        self.assertEqual(state["exhausted"][0]["task"], "DRAFT-Y")
        self.assertEqual(self.task("DRAFT-Y")["state"], "blocked")

    def test_an_unknown_outcome_is_never_recovered_because_a_retry_may_pay_twice(self):
        self.bf.add_task(self.project, "DRAFT-Z", "writer", deps=[], priority=50, outputs=[])
        plan = self.plan()
        task = next(row for row in plan["tasks"] if row["id"] == "DRAFT-Z")
        task["state"] = "blocked"
        plan["attempts"].append({"id": "ATT-9003", "task": "DRAFT-Z", "role": "writer", "state": "outcome_unknown", "failure": "provider accepted, result unknown", "provider_accepted": True})
        self.bf._save_plan(self.project, plan)

        state = self.bf.recover_before_dispatch(self.project)

        self.assertEqual(state["recovered"], [])
        self.assertIn("DRAFT-Z", state["needs_a_person"])
        self.assertEqual(self.task("DRAFT-Z")["state"], "blocked")

    def test_a_claim_the_provider_accepted_and_never_finished_becomes_a_decision(self):
        self.bf.add_task(self.project, "DRAFT-A", "writer", deps=[], priority=50, outputs=[])
        plan = self.plan()
        next(row for row in plan["tasks"] if row["id"] == "DRAFT-A")["state"] = "running"
        plan["attempts"].append({
            "id": "ATT-9101", "task": "DRAFT-A", "role": "writer", "state": "running",
            "provider_accepted": True, "lease_expires_at": 1.0, "run": "RUN-0001",
        })
        self.bf._save_plan(self.project, plan)

        state = self.bf.recover_before_dispatch(self.project)

        self.assertIn("DRAFT-A", state["needs_a_person"])
        self.assertEqual(self.task("DRAFT-A")["state"], "outcome_unknown")

    def test_a_claim_the_provider_never_accepted_just_goes_back_to_pending(self):
        self.bf.add_task(self.project, "DRAFT-B", "writer", deps=[], priority=50, outputs=[])
        plan = self.plan()
        next(row for row in plan["tasks"] if row["id"] == "DRAFT-B")["state"] = "running"
        plan["attempts"].append({
            "id": "ATT-9102", "task": "DRAFT-B", "role": "writer", "state": "running",
            "provider_accepted": False, "lease_expires_at": 1.0, "run": "RUN-0001",
        })
        self.bf._save_plan(self.project, plan)

        state = self.bf.recover_before_dispatch(self.project)

        self.assertIn("DRAFT-B", state["recovered"])
        self.assertEqual(state["needs_a_person"], [])
        self.assertEqual(self.task("DRAFT-B")["state"], "pending")

    def test_the_driver_halts_on_a_stale_accepted_claim_and_names_the_resolution(self):
        self.bf.add_task(self.project, "DRAFT-C", "writer", deps=[], priority=50, outputs=[])
        plan = self.plan()
        next(row for row in plan["tasks"] if row["id"] == "DRAFT-C")["state"] = "running"
        plan["attempts"].append({
            "id": "ATT-9103", "task": "DRAFT-C", "role": "writer", "state": "running",
            "provider_accepted": True, "lease_expires_at": 1.0, "run": "RUN-0001",
        })
        self.bf._save_plan(self.project, plan)

        with self.assertRaises(self.bf.AdvanceHalted) as caught:
            self.bf.advance_book(self.project, self.book, until="chapters", provider=ScriptedProvider(self.bf))

        self.assertIn("DRAFT-C", str(caught.exception))
        self.assertIn("resolve-unknown", str(caught.exception))

    def test_the_driver_halts_and_says_who_must_decide(self):
        self.bf.add_task(self.project, "DRAFT-W", "writer", deps=[], priority=50, outputs=[])
        plan = self.plan()
        next(row for row in plan["tasks"] if row["id"] == "DRAFT-W")["state"] = "outcome_unknown"
        self.bf._save_plan(self.project, plan)
        with self.assertRaises(self.bf.AdvanceHalted) as caught:
            self.bf.advance_book(self.project, self.book, until="chapters", provider=ScriptedProvider(self.bf))
        self.assertIn("DRAFT-W", str(caught.exception))
        self.assertIn("resolve-unknown", str(caught.exception))


class BudgetTests(AdvanceFixture):
    def test_an_envelope_over_the_advisory_budget_proceeds(self):
        config_path = self.project / "book-forge.yaml"
        config = json.loads(config_path.read_text())
        config["context"] = {"writer_max_input_tokens": 200}
        config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        envelope = self.bf.build_envelope(
            self.project, role="writer",
            task_capsule={"id": "CH-0001", "book": self.book, "beats": ["b" * 4000], "target_words": 900},
            imports=[], state={}, tools=[], max_output_tokens=1000,
        )
        self.assertGreater(envelope["estimated_input_tokens"], 200)

    def test_enforce_budgets_restores_the_wall(self):
        config_path = self.project / "book-forge.yaml"
        config = json.loads(config_path.read_text())
        config["context"] = {"writer_max_input_tokens": 200, "enforce_budgets": True}
        config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        with self.assertRaises(self.bf.ContextOverflowError):
            self.bf.build_envelope(
                self.project, role="writer",
                task_capsule={"id": "CH-0001", "book": self.book, "beats": ["b" * 4000], "target_words": 900},
                imports=[], state={}, tools=[], max_output_tokens=1000,
            )

    def test_the_wall_is_what_the_model_can_accept(self):
        window = self.bf._model_input_window("writer", 1000)
        self.assertGreater(window, 100000)
        with self.assertRaises(self.bf.ContextOverflowError):
            self.bf.build_envelope(
                self.project, role="writer",
                task_capsule={"id": "CH-0001", "book": self.book, "beats": ["b" * (window * 4)], "target_words": 900},
                imports=[], state={}, tools=[], max_output_tokens=1000,
            )


if __name__ == "__main__":
    unittest.main()
