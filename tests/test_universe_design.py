import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_universe_design", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clean_proposal():
    return {
        "kernel": [{"id": "LAW-0001", "summary": "Memory cannot be manufactured."}],
        "eras": [{"id": "ERA-0001", "name": "Afterlight", "order": 1}],
        "events": [{"id": "EVT-0001", "era": "ERA-0001", "order": 1, "summary": "The archive opens."}],
        "places": [{"id": "PLC-0001", "name": "Glass Harbor", "summary": "A tidal archive."}],
        "factions": [{"id": "FAC-0001", "name": "Keepers", "summary": "Guard inherited memories."}],
        "characters": [{"id": "CHR-0001", "name": "Mara", "summary": "A skeptical diver.", "voice": "Precise and dry."}],
        "themes": ["memory and consent"],
        "style": {"tense": "past", "person": "third-limited"},
        "continuity_material": {"CNT-0001": ["EVT-0001"]},
        "book_local": {},
        "unresolved_questions": ["Who first sealed the archive?"],
    }


class UniverseDesignTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")

    def test_schedules_two_bounded_roles_and_promotes_clean_design(self):
        tasks = self.bf.schedule_universe_design(self.project, guided_answers={"tone": "hopeful"})
        self.assertEqual([(task["role"], task["deps"]) for task in tasks], [("designer", []), ("canon-auditor", ["DESIGN-UNI-0001"])])

        report = self.bf.apply_universe_design(self.project, clean_proposal())
        self.assertEqual(report["state"], "design_clean")
        self.assertTrue((self.project / "universe/canon/characters/CHR-0001.md").is_file())
        index = self.bf.rebuild_indexes(self.project)
        self.assertIn("CHR-0001#voice", index["blocks"])
        self.assertIn("LAW-0001#summary", index["blocks"])
        audit = json.loads((self.project / "universe/design-audit.json").read_text())
        self.assertEqual(audit["blocking"], [])

    def test_rejects_contradiction_without_mutating_design(self):
        proposal = clean_proposal()
        proposal["events"].append({"id": "EVT-0002", "era": "ERA-9999", "order": 1, "summary": "Impossible"})
        before = (self.project / "universe/kernel.md").read_bytes()
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.apply_universe_design(self.project, proposal)
        self.assertEqual((self.project / "universe/kernel.md").read_bytes(), before)
        self.assertFalse((self.project / "universe/design.json").exists())


if __name__ == "__main__":
    unittest.main()
