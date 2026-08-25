import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_e2e", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def universe_proposal():
    return {
        "kernel": [{"id": "LAW-0001", "name": "Memory Law", "summary": "Memory cannot be manufactured."}],
        "eras": [{"id": "ERA-0001", "name": "Afterlight", "order": 1}],
        "events": [{"id": "EVT-0001", "era": "ERA-0001", "order": 1, "summary": "The archive opens."}],
        "places": [{"id": "PLC-0001", "name": "Glass Harbor", "summary": "A tidal archive."}],
        "factions": [{"id": "FAC-0001", "name": "Keepers", "summary": "They guard inherited memories."}],
        "characters": [{"id": "CHR-0001", "name": "Mara", "summary": "A skeptical diver.", "voice": "Precise and dry."}],
        "themes": ["memory and consent"],
        "style": {"tense": "past", "person": "third-limited"},
        "continuity_material": {"CNT-0001": ["EVT-0001"]},
        "book_local": {},
        "unresolved_questions": [],
    }


def book_proposal():
    return {
        "premise": "Mara must decide whether one memory can belong to a city.",
        "entry_state": {"CHR-0001": "isolated"},
        "arc": ["refusal", "cost", "choice"],
        "exit_boundary": {"CHR-0001": "committed"},
        "chapters": [{
            "id": "CH-0001",
            "order": 1,
            "pov": "CHR-0001",
            "beats": ["Mara chooses to open the archive"],
            "plants": [],
            "reveals": [],
            "target_words": 700,
            "imports": ["UNI-0001#kernel", "CHR-0001#voice"],
            "obligations": [],
            "pivotal": None,
        }],
    }


def prose(word):
    return "# The Archive\n\n" + " ".join([word] * 700)


class FixtureProvider:
    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, role, envelope, attempt_dir):
        with self.lock:
            task = envelope["payload"]["task"]
            if role == "designer":
                value = universe_proposal() if task["scope"] == "universe" else book_proposal()
            elif role == "canon-auditor":
                value = {"findings": []}
            elif role == "writer":
                value = {"prose_markdown": prose("memory"), "beat_map": [{"beat": "Mara chooses to open the archive", "evidence": "She opens it."}], "consequences": []}
            elif role == "cold-reader":
                value = {"findings": []}
            elif role == "technical-editor":
                value = {"findings": [], "consequences": []}
            elif role == "reviser":
                value = {"prose_markdown": prose("memory"), "beat_map": [{"beat": "Mara chooses to open the archive", "evidence": "She opens it."}], "consequences": [], "dispositions": [], "reader_state": "Mara opened the archive."}
            elif role == "translator":
                value = {"translated_markdown": prose("memoria").replace("The Archive", "L'Archivio"), "glossary_updates": [], "boundary": "Mara ha aperto l'archivio."}
            else:
                raise AssertionError(role)
            self.calls.append(role)
            number = len(self.calls)
        variants = {"designer": "medium", "canon-auditor": "max", "writer": "low", "cold-reader": "low", "technical-editor": "high", "reviser": "high", "translator": "low"}
        return {
            "text": json.dumps(value),
            "provider": "openrouter",
            "model": MODEL,
            "variant": variants[role],
            "session_id": f"ses-{number}",
            "tokens": {"input": envelope["estimated_input_tokens"], "output": 300},
            "cost": 0.001,
            "latency_ms": 5,
            "finish": "stop",
        }


class EndToEndTests(unittest.TestCase):
    def test_fixture_lifecycle_from_universe_network_to_translated_exports(self):
        bf = load_module()
        provider = FixtureProvider()
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "world"
            bf.init_project(project, "World")
            self.assertEqual(bf.execute_universe_design(project, provider=provider)["calls"], len(bf.UNIVERSE_DESIGN_CHUNKS) + 1)

            a, b, c, local = [bf.add_book(project, title)["id"] for title in ("Origin", "Sequel", "Parallel", "Local")]
            alternate = bf.add_continuity(project, "Ash Timeline", fork_from="CNT-0001", imports=["UNI-0001#kernel"])["id"]
            alt_book = bf.add_book(project, "Alternate", continuity=alternate)["id"]
            for book_id in (a, b, c, local, alt_book):
                (project / f"books/{book_id}").mkdir(parents=True, exist_ok=True)
                (project / f"books/{book_id}/book-brief.json").write_text(json.dumps({"schema": 1, "premise": "A diver must decide.", "characters": ["Mara"], "plot": ["dive"], "tone": "quiet"}))
            alt_book = bf.add_book(project, "Alternate", continuity=alternate)["id"]
            sequel = bf.add_relation(project, "sequel_of", [b, a], obligations=["Carry the archive choice"])
            bf.add_relation(project, "parallel_to", [a, c])
            bf.add_relation(project, "crossover", [a, b, c])
            bf.add_relation(project, "alternate_of", [a, alt_book], imports=["UNI-0001#kernel"])
            collection = bf.collection_add(project, "Harbor Cycle", [a, b, c])
            bf.collection_order(project, collection["id"], [a, c, b])

            self.assertEqual(bf.execute_book_design(project, local, provider=provider)["calls"], 2)
            self.assertEqual(bf.run_next(project, book_id=local, provider=provider)["state"], "drafted")
            self.assertEqual(bf.run_next(project, book_id=local, provider=provider)["state"], "closed")
            self.assertGreaterEqual(bf.audit_continuity(project, relation_id=sequel["id"], provider=provider)["calls"], 1)

            bf.add_translation(project, local, "it-IT")
            translated = bf.translate_next(project, local, "it-IT", provider=provider, run_all=True)
            self.assertEqual(translated["state"], "current")
            epub = bf.export_epub(project, local, "it-IT")
            pdf = bf.export_pdf(project, local, "it-IT")
            self.assertTrue(Path(epub["path"]).is_file())
            self.assertTrue(Path(pdf["path"]).is_file())

            bf.add_task(project, "MAINTENANCE-CHECKPOINT", "designer")
            bf.claim_task(project, "MAINTENANCE-CHECKPOINT", request_hash="a" * 64)
            self.assertEqual(bf.pause_run(project, emergency=True)["state"], "paused")
            self.assertEqual(bf.resume_run(project)["state"], "running")
            self.assertTrue(bf.migrate_project(project, "check")["compatible"])
            report = bf.telemetry_report(project, strict=True)
            self.assertTrue(report["valid"])
            # The chunked universe design folds 8 per-category calls into one
            # accepted attempt, so accepted counts attempts, not provider calls.
            self.assertEqual(report["calls"]["accepted"], len(provider.calls) - (len(bf.UNIVERSE_DESIGN_CHUNKS) - 1))
            self.assertFalse(any(path.name.upper() == "CLAUDE.MD" for path in project.rglob("*")))
            self.assertFalse(any(path.suffix == ".sh" for path in project.rglob("*")))


if __name__ == "__main__":
    unittest.main()
