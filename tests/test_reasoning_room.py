import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MEASURED_ROLES = ("technical-editor", "writer", "translator", "locale-reader", "locale-reviser", "canon-auditor", "continuity-checker", "continuity-extractor", "continuity-reviser")


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_reasoning_room", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReasoningRoomTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.attempt_dir = self.project / ".book-forge" / "runs" / "RUN-0001" / "attempts" / "ATT-0001"
        self.attempt_dir.mkdir(parents=True)

    def _cap(self, role):
        output_budget = self.bf.ROLE_BUDGETS[role][1]
        envelope = {
            "bytes": json.dumps({"schema": 1, "max_output_tokens": output_budget}).encode(),
            "hash": "abc",
            "estimated_input_tokens": 10,
        }
        captured = []

        def fake_run(args, **kwargs):
            if "debug" in args:
                model_id, variant = self.bf._expected_pin(role)
                payload = {"name": role, "model": {"providerID": "openrouter", "modelID": model_id}, "variant": variant}
                return mock.Mock(stdout=json.dumps(payload), stderr="", returncode=0)
            captured.append(kwargs["env"].get(self.bf.OPENCODE_OUTPUT_TOKEN_MAX_ENV))
            return mock.Mock(stdout=json.dumps({"parts": []}), stderr="", returncode=0)

        with mock.patch.object(self.bf, "_verify_opencode_cli", lambda binary: None), \
             mock.patch.object(self.bf, "_run_opencode_process", side_effect=fake_run):
            try:
                self.bf.run_opencode_role(role, envelope, self.attempt_dir)
            except Exception:
                pass
        return int(captured[0])

    def test_measured_roles_get_their_room_above_the_output_budget(self):
        for role in MEASURED_ROLES:
            with self.subTest(role=role):
                self.assertGreaterEqual(self.bf.REASONING_ROOM[role], 64000)
                self.assertEqual(self._cap(role), self.bf.REASONING_ROOM[role] + self.bf.ROLE_BUDGETS[role][1])

    def test_a_role_outside_the_table_keeps_the_provider_default(self):
        role = "cold-reader"
        self.assertNotIn(role, self.bf.REASONING_ROOM)
        self.assertEqual(self._cap(role), self.bf.OPENCODE_OUTPUT_TOKEN_MAX + self.bf.ROLE_BUDGETS[role][1])


if __name__ == "__main__":
    unittest.main()
