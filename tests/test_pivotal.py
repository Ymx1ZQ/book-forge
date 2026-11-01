import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4.1-flash-1017"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_pivotal", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prose(word):
    return "# Finale\n\n" + " ".join([word] * 700)


class PivotalProvider:
    def __init__(self):
        self.calls = []
        self.writer_count = 0
        self.lock = threading.Lock()

    def __call__(self, role, envelope, attempt_dir):
        with self.lock:
            self.calls.append(role)
            number = len(self.calls)
            if role == "writer":
                self.writer_count += 1
                payload = {"prose_markdown": prose("glass" if self.writer_count == 1 else "tide"), "beat_map": [{"beat": "Choose", "evidence": "chosen"}], "consequences": []}
            elif role == "judge":
                labels = sorted(envelope["payload"]["task"]["candidates"])
                payload = {"ranking": [labels[1], labels[0]], "evidence": [{"dimension": "causality", "winner": labels[1], "reason": "The choice lands."}]}
            elif role == "cold-reader":
                payload = {
                    "findings": [],
                    "events": ["Mara makes the choice."],
                    "undefined_terms": [],
                    "stakes": "Mara can lose what the choice buys.",
                }
            elif role == "technical-editor":
                payload = {"findings": [], "consequences": []}
            elif role == "reviser":
                payload = {"prose_markdown": prose("tide"), "beat_map": [{"beat": "Choose", "evidence": "chosen"}], "consequences": [], "dispositions": [], "reader_state": "The choice is made."}
            else:
                raise AssertionError(role)
        variants = {"writer": "low", "judge": "max", "cold-reader": "low", "technical-editor": "high", "reviser": "low"}
        return {"text": json.dumps(payload), "provider": "openrouter", "model": MODEL, "variant": variants[role], "session_id": f"ses-{number}", "tokens": {"input": envelope["estimated_input_tokens"], "output": 300}, "cost": .001, "latency_ms": 10, "finish": "stop"}


class ReviewOnlyProvider(PivotalProvider):
    """Fails the test if the dispatch reaches for the judge or the writer again."""

    def __call__(self, role, envelope, attempt_dir):
        if role in {"writer", "judge"}:
            raise AssertionError(f"{role} must not be called when the draft already exists")
        return super().__call__(role, envelope, attempt_dir)


class JudgeRetryProvider(PivotalProvider):
    """Answers the judge with the next scripted text; `None` is the valid ranking."""

    def __init__(self, answers):
        super().__init__()
        self.answers = list(answers)
        self.judge_calls = 0

    def __call__(self, role, envelope, attempt_dir):
        result = super().__call__(role, envelope, attempt_dir)
        if role == "judge":
            answer = self.answers[self.judge_calls] if self.judge_calls < len(self.answers) else None
            self.judge_calls += 1
            if answer is not None:
                result["text"] = answer
        return result


class PivotalTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        self.book = self.bf.add_book(self.project, "Book")["id"]
        chapters = self.project / f"books/{self.book}/chapters"
        chapters.mkdir()
        (chapters / "CH-0001.json").write_text(json.dumps({
            "schema": 1, "book": self.book, "id": "CH-0001", "order": 1,
            "pov": "CHR-0001", "beats": ["Choose"], "plants": [], "reveals": [],
            "target_words": 700, "imports": ["UNI-0001#kernel"], "pivotal": "finale",
        }))

    def test_blind_selects_and_closes_in_six_calls(self):
        provider = PivotalProvider()
        result = self.bf.produce_pivotal_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(result["calls"], 6)
        self.assertEqual(provider.calls.count("writer"), 2)
        self.assertEqual(provider.calls.count("judge"), 1)
        variants = self.project / f"books/{self.book}/work/CH-0001/variants"
        self.assertTrue((variants / "A/draft.md").is_file())
        self.assertTrue((variants / "B/draft.md").is_file())
        decision = json.loads((self.project / f"books/{self.book}/reviews/CH-0001/judgement.json").read_text())
        self.assertNotIn("A", json.dumps(decision["anonymous_candidates"]))
        self.assertLessEqual(len(decision["anchors"]), 2)
        self.assertTrue((self.project / f"books/{self.book}/manuscript/chapters/CH-0001.md").is_file())

    def test_succeeded_variants_resume_at_the_judge(self):
        contract_path = self.project / f"books/{self.book}/chapters/CH-0001.json"
        contract = json.loads(contract_path.read_text())
        contract.update({"want": "Mara wants the truth.", "obstacle": "The truth costs her the life she has.", "turn": {"kind": "decision", "text": "Mara chooses."}})
        contract_path.write_text(json.dumps(contract))
        variants = self.project / f"books/{self.book}/work/CH-0001/variants"
        for label, word in (("A", "glass"), ("B", "tide")):
            prefix = f"books/{self.book}/work/CH-0001/variants/{label}"
            self.bf.add_task(
                self.project,
                f"PIVOT-{label}-{self.book}-CH-0001",
                "writer",
                priority=45,
                outputs=[f"{prefix}/draft.md", f"{prefix}/beat-map.json", f"{prefix}/consequences.json"],
            )
            target = variants / label
            target.mkdir(parents=True)
            (target / "draft.md").write_text(prose(word) + "\n")
            (target / "beat-map.json").write_text(json.dumps({"schema": 1, "beats": [{"beat": "Choose", "evidence": "chosen"}]}))
            (target / "consequences.json").write_text(json.dumps({"schema": 1, "consequences": []}))
        plan = self.bf._load_plan(self.project)
        for task in plan["tasks"]:
            if task["id"].startswith("PIVOT-"):
                task["state"] = "succeeded"
        self.bf._save_plan(self.project, plan)
        self.bf.add_task(
            self.project,
            f"JUDGE-{self.book}-CH-0001",
            "judge",
            deps=[f"PIVOT-A-{self.book}-CH-0001", f"PIVOT-B-{self.book}-CH-0001"],
            priority=50,
            outputs=[f"books/{self.book}/reviews/CH-0001/judgement.json"],
        )
        provider = PivotalProvider()
        result = self.bf.run_next(self.project, book_id=self.book, provider=provider)
        self.assertNotIn("writer", provider.calls)
        self.assertEqual(provider.calls.count("judge"), 1)
        self.assertEqual(result["calls"], 4)
        self.assertEqual(result["state"], "closed")
        self.assertTrue((self.project / f"books/{self.book}/manuscript/chapters/CH-0001.md").is_file())

    def test_pivotal_draft_resumes_at_review_without_judge_or_writer(self):
        contract_path = self.project / f"books/{self.book}/chapters/CH-0001.json"
        contract = json.loads(contract_path.read_text())
        contract.update({"want": "Mara wants the truth.", "obstacle": "The truth costs her the life she has.", "turn": {"kind": "decision", "text": "Mara chooses."}})
        contract_path.write_text(json.dumps(contract))
        variants = self.project / f"books/{self.book}/work/CH-0001/variants"
        for label, word in (("A", "glass"), ("B", "tide")):
            prefix = f"books/{self.book}/work/CH-0001/variants/{label}"
            self.bf.add_task(
                self.project,
                f"PIVOT-{label}-{self.book}-CH-0001",
                "writer",
                priority=45,
                outputs=[f"{prefix}/draft.md", f"{prefix}/beat-map.json", f"{prefix}/consequences.json"],
            )
            target = variants / label
            target.mkdir(parents=True)
            (target / "draft.md").write_text(prose(word) + "\n")
            (target / "beat-map.json").write_text(json.dumps({"schema": 1, "beats": [{"beat": "Choose", "evidence": "chosen"}]}))
            (target / "consequences.json").write_text(json.dumps({"schema": 1, "consequences": []}))
        self.bf.add_task(
            self.project,
            f"JUDGE-{self.book}-CH-0001",
            "judge",
            deps=[f"PIVOT-A-{self.book}-CH-0001", f"PIVOT-B-{self.book}-CH-0001"],
            priority=50,
            outputs=[f"books/{self.book}/reviews/CH-0001/judgement.json"],
        )
        reviews = self.project / f"books/{self.book}/reviews/CH-0001"
        reviews.mkdir(parents=True)
        (reviews / "judgement.json").write_text(json.dumps({"schema": 1, "chapter": "CH-0001", "ranking": ["tide", "glass"], "evidence": [], "winner": "tide", "anchors": []}))
        work = self.project / f"books/{self.book}/work/CH-0001"
        self.bf.add_task(
            self.project,
            f"DRAFT-{self.book}-CH-0001",
            "writer",
            deps=[f"JUDGE-{self.book}-CH-0001"],
            priority=55,
            outputs=[f"books/{self.book}/work/CH-0001/draft.md", f"books/{self.book}/work/CH-0001/beat-map.json", f"books/{self.book}/work/CH-0001/consequences.json"],
        )
        (work / "draft.md").write_text(prose("tide") + "\n")
        (work / "beat-map.json").write_text(json.dumps({"schema": 1, "chapter": "CH-0001", "beats": [{"beat": "Choose", "evidence": "chosen"}]}))
        (work / "consequences.json").write_text(json.dumps({"schema": 1, "chapter": "CH-0001", "consequences": []}))
        plan = self.bf._load_plan(self.project)
        for task in plan["tasks"]:
            if task["id"].startswith(("PIVOT-", "JUDGE-", "DRAFT-")):
                task["state"] = "succeeded"
        self.bf._save_plan(self.project, plan)
        provider = ReviewOnlyProvider()
        result = self.bf.run_next(self.project, book_id=self.book, provider=provider)
        self.assertNotIn("judge", provider.calls)
        self.assertNotIn("writer", provider.calls)
        self.assertIn("cold-reader", provider.calls)
        self.assertEqual(result["state"], "closed")
        self.assertTrue((self.project / f"books/{self.book}/manuscript/chapters/CH-0001.md").is_file())

    def test_judge_that_answers_no_json_once_is_asked_again(self):
        provider = JudgeRetryProvider(["no json here"])
        self.bf.produce_pivotal_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(provider.calls.count("judge"), 2)
        self.assertTrue((self.project / f"books/{self.book}/manuscript/chapters/CH-0001.md").is_file())
        self.assert_the_run_was_not_blocked()

    def test_judge_that_never_answers_json_raises_without_blocking(self):
        provider = JudgeRetryProvider(["no json here", "still no json"])
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.produce_pivotal_chapter(self.project, self.book, "CH-0001", provider=provider)
        self.assertEqual(provider.calls.count("judge"), 2, "the second failure must not buy a third call")
        self.assert_the_run_was_not_blocked()

    def assert_the_run_was_not_blocked(self):
        tasks = self.bf._load_plan(self.project)["tasks"]
        self.assertEqual([task for task in tasks if task["state"] == "outcome_unknown"], [])
        run = self.bf.status_project(self.project)["run"]
        self.assertIsNotNone(run)
        self.assertNotEqual(run["state"], "blocked")

    def test_rejects_unmarked_chapter(self):
        contract_path = self.project / f"books/{self.book}/chapters/CH-0001.json"
        contract = json.loads(contract_path.read_text())
        contract["pivotal"] = None
        contract_path.write_text(json.dumps(contract))
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.produce_pivotal_chapter(self.project, self.book, "CH-0001", provider=PivotalProvider())


if __name__ == "__main__":
    unittest.main()
