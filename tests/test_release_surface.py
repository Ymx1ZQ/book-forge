import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "book_forge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_release_surface", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseSurfaceTests(unittest.TestCase):
    def test_skill_is_a_thin_one_level_router_with_every_public_route(self):
        skill = (ROOT / "SKILL.md").read_text()
        self.assertLess(len(skill.splitlines()), 300)
        routes = {"init", "catalog", "design", "run", "lifecycle", "audit", "translate", "export", "chorus"}
        for route in routes:
            reference = ROOT / "references" / f"{route}.md"
            self.assertTrue(reference.is_file(), route)
            self.assertIn(f"references/{route}.md", skill)
            self.assertNotIn("references/", reference.read_text())

        bf = load_module()
        parser = bf.build_parser()
        subcommands = next(action for action in parser._actions if action.dest == "command").choices
        self.assertEqual(
            set(subcommands),
            {"init", "runtime", "migrate", "continuity", "add-book", "relate", "collection", "design", "run", "pause", "resume", "status", "translate", "audit", "chorus", "export"},
        )

    def test_fresh_project_has_agent_config_but_no_claude_or_project_shell_dependency(self):
        bf = load_module()
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "world"
            bf.init_project(project, "World")
            self.assertTrue((project / ".opencode/agents/book-forge-orchestrator.md").is_file())
            self.assertTrue((project / ".opencode/commands/book-forge.md").is_file())
            self.assertFalse(any(path.name.upper() == "CLAUDE.MD" for path in project.rglob("*")))
            self.assertFalse(any(path.suffix == ".sh" for path in project.rglob("*")))

    def test_skill_and_routes_expose_complete_usage_surface_without_auxiliary_docs(self):
        self.assertFalse((ROOT / "README.md").exists())
        guidance = (ROOT / "SKILL.md").read_text() + "\n" + "\n".join(
            (ROOT / "references" / name).read_text()
            for name in ("init.md", "design.md", "run.md", "translate.md", "export.md")
        )
        for required in (
            "openrouter/deepseek/deepseek-v4-flash-0731",
            "init",
            "design universe",
            "run",
            "translate add",
            "export",
        ):
            self.assertIn(required, guidance)


if __name__ == "__main__":
    unittest.main()
