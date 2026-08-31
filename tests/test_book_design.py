import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_book_design", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROLE_VARIANTS = {name: spec[1] for name, spec in load_module().ROLE_SPECS.items()}


def proposal(obligation=None):
    chapters = [
        {"id": "CH-0001", "order": 1, "pov": "CHR-0001", "beats": ["A choice opens the conflict"], "plants": ["signal"], "reveals": [], "target_words": 1800, "imports": ["UNI-0001#kernel"], "pivotal": "opener"},
        {"id": "CH-0002", "order": 2, "pov": "CHR-0001", "beats": ["The choice costs an ally"], "plants": [], "reveals": ["signal"], "target_words": 2000, "imports": ["UNI-0001#kernel"], "pivotal": None},
        {"id": "CH-0003", "order": 3, "pov": "CHR-0001", "beats": ["Agency resolves the dilemma"], "plants": [], "reveals": [], "target_words": 2200, "imports": ["UNI-0001#kernel"], "pivotal": "finale"},
    ]
    if obligation:
        chapters[1]["obligations"] = [obligation]
    return {
        "premise": "A diver must decide whether memory can be owned.",
        "entry_state": {"CHR-0001": "isolated"},
        "arc": ["refusal", "cost", "choice"],
        "exit_boundary": {"CHR-0001": "committed"},
        "chapters": chapters,
    }


class DesignProvider:
    def __init__(self, value, audit=None):
        self.value = value
        self.audit = audit if audit is not None else {"findings": []}
        self.calls = []

    def _designer_payload(self, envelope):
        """Answer one design chunk from the fixture proposal.

        The engine drives the book design in slices — a spine call, then one call
        per range of chapters — so a fixture that returns the whole proposal to
        every call no longer describes what the designer is asked for."""
        chunk = envelope["payload"]["task"].get("chunk") or {}
        chapters = list(self.value.get("chapters", []))
        if chunk.get("category") == "spine":
            return {
                **{key: value for key, value in self.value.items() if key != "chapters"},
                "chapter_outline": [
                    {key: row[key] for key in ("id", "order", "pov") if key in row}
                    for row in chapters
                ],
            }
        if chunk.get("category") == "chapters":
            first, last = int(chunk["first_order"]), int(chunk["last_order"])
            return {"chapters": [row for row in chapters if first <= int(row["order"]) <= last]}
        return self.value

    def __call__(self, role, envelope, attempt_dir):
        self.calls.append(role)
        if role.startswith("advisor-") or role == "chorus-synthesizer":
            return {
                "text": json.dumps({"findings": [], "suggestions": []}),
                "provider": "openrouter",
                "model": MODEL,
                "variant": "high",
                "session_id": f"ses-{len(self.calls)}",
                "tokens": {"input": envelope["estimated_input_tokens"], "output": 100},
                "cost": 0.001,
                "latency_ms": 5,
                "finish": "stop",
            }
        payload = self._designer_payload(envelope) if role == "designer" else self.audit
        return {
            "text": json.dumps(payload),
            "provider": "openrouter",
            "model": MODEL,
            "variant": ROLE_VARIANTS[role],
            "session_id": f"ses-{len(self.calls)}",
            "tokens": {"input": envelope["estimated_input_tokens"], "output": 300},
            "cost": 0.001,
            "latency_ms": 5,
            "finish": "stop",
        }


class BookDesignTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        # Disable chorus for deterministic tests.
        import json as _json
        _cfg = _json.loads((self.project / "book-forge.yaml").read_text())
        _cfg["chorus"] = {"enabled": False, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER}
        (self.project / "book-forge.yaml").write_text(_json.dumps(_cfg, indent=2, sort_keys=True) + "\n")

    def brief(self, book):
        path = self.project / f"books/{book}/book-brief.json"
        path.write_text(json.dumps({"schema": 1, "premise": "A diver must decide.", "characters": ["Mara"], "plot": ["dive"], "tone": "quiet"}))
        return path

    def test_designs_unrelated_sequel_and_parallel_books_with_obligations(self):
        a = self.bf.add_book(self.project, "A")["id"]
        b = self.bf.add_book(self.project, "B")["id"]
        c = self.bf.add_book(self.project, "C")["id"]
        sequel = self.bf.add_relation(self.project, "sequel_of", [b, a], obligations=["Carry the signal"])
        parallel = self.bf.add_relation(self.project, "parallel_to", [a, c], obligations=["Share the eclipse"])

        self.assertEqual(self.bf.apply_book_design(self.project, b, proposal(sequel["obligations"][0]["id"]))["state"], "design_clean")
        self.assertEqual(self.bf.apply_book_design(self.project, c, proposal(parallel["obligations"][0]["id"]))["state"], "design_clean")
        unrelated = self.bf.add_book(self.project, "D")["id"]
        self.assertEqual(self.bf.apply_book_design(self.project, unrelated, proposal())["state"], "design_clean")

        outline = json.loads((self.project / f"books/{b}/outline.yaml").read_text())
        self.assertEqual([row["id"] for row in outline["chapters"]], ["CH-0001", "CH-0002", "CH-0003"])
        contract = json.loads((self.project / f"books/{b}/chapters/CH-0002.json").read_text())
        envelope = self.bf.build_envelope(
            self.project, role="writer", task_capsule=contract, imports=contract["imports"],
            state={}, tools=[], max_output_tokens=5000,
        )
        self.assertLessEqual(envelope["estimated_input_tokens"], 12000)

    def test_rejects_missing_relation_target_and_bad_chapter_order(self):
        a = self.bf.add_book(self.project, "A")["id"]
        b = self.bf.add_book(self.project, "B")["id"]
        relation = self.bf.add_relation(self.project, "sequel_of", [b, a], obligations=["Carry the signal"])
        bad = proposal()
        bad["chapters"][1]["order"] = 1
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.apply_book_design(self.project, b, bad)
        self.assertIn(relation["obligations"][0]["id"], str(caught.exception))
        self.assertFalse((self.project / f"books/{b}/chapters").exists())

    def test_executes_book_design_as_two_paid_receipted_calls(self):
        book = self.bf.add_book(self.project, "Agentic Book")["id"]
        self.brief(book)
        provider = DesignProvider(proposal())
        result = self.bf.execute_book_design(self.project, book, provider=provider)
        self.assertEqual(result["state"], "design_clean")
        self.assertEqual(result["calls"], 2)
        # Three chapters are audited in two windows of two and one schedule pass:
        # the window is narrow because the auditor's difficulty, not its payload, is
        # what decides how much it can read at once.
        self.assertEqual(provider.calls, ["designer", "designer"] + ["canon-auditor"] * 3)
        self.assertTrue((self.project / f"books/{book}/chapters/CH-0001.json").is_file())

    def test_binds_book_scoped_proposal_evidence_to_helper_hashes(self):
        book = self.bf.add_book(self.project, "Bound")["id"]
        self.brief(book)
        provider = DesignProvider(
            proposal(),
            audit={"findings": [{
                "id": "F-0001",
                "severity": "note",
                "issue": "Seeded note.",
                "evidence": [
                    {"location": f"{book}#proposal/turns/TURN-0001", "hash": "0" * 64},
                    {"location": f"{book}#proposal/chapters/CH-0001/beats/BEAT-0001"},
                    {"location": f"{book}#proposal/chapters/CH-0001"},
                ],
                "repair_scope": [book],
            }]},
        )
        result = self.bf.execute_book_design(self.project, book, provider=provider)
        self.assertEqual(result["state"], "design_clean")
        audit = json.loads((self.project / f"books/{book}/design-audit.json").read_text())
        evidence = audit["findings"][0]["evidence"]
        design_md = self.project / f"books/{book}/design.md"
        chapter = self.project / f"books/{book}/chapters/CH-0001.json"
        self.assertEqual(evidence[0]["hash"], self.bf._file_hash(design_md))
        self.assertEqual(evidence[0]["location"], f"{book}#proposal/turns/TURN-0001")
        self.assertEqual(evidence[1]["hash"], self.bf._file_hash(chapter))
        self.assertEqual(evidence[2]["hash"], self.bf._file_hash(chapter))

    def test_binds_kernel_block_evidence_to_its_file(self):
        book = self.bf.add_book(self.project, "KernelBound")["id"]
        self.brief(book)
        provider = DesignProvider(
            proposal(),
            audit={"findings": [{
                "id": "F-0001",
                "severity": "note",
                "issue": "Seeded note.",
                "evidence": [{"location": "UNI-0001#kernel"}],
                "repair_scope": [book],
            }]},
        )
        result = self.bf.execute_book_design(self.project, book, provider=provider)
        self.assertEqual(result["state"], "design_clean")
        audit = json.loads((self.project / f"books/{book}/design-audit.json").read_text())
        kernel = self.project / "universe/kernel.md"
        self.assertEqual(audit["findings"][0]["evidence"][0]["hash"], self.bf._file_hash(kernel))

    def test_binds_envelope_scope_evidence_locations(self):
        book = self.bf.add_book(self.project, "EnvelopeBound")["id"]
        self.brief(book)
        provider = DesignProvider(
            proposal(),
            audit={"findings": [{
                "id": "F-0001",
                "severity": "note",
                "issue": "Seeded note.",
                "evidence": [
                    {"location": "task.design_scope.proposal.premise"},
                    {"location": "task.design_scope.chapters.CH-0001.beats.BEAT-0001.cause"},
                    {"location": "task.design_scope.exit_boundary.sleeper"},
                ],
                "repair_scope": [book],
            }]},
        )
        result = self.bf.execute_book_design(self.project, book, provider=provider)
        self.assertEqual(result["state"], "design_clean")
        audit = json.loads((self.project / f"books/{book}/design-audit.json").read_text())
        evidence = audit["findings"][0]["evidence"]
        design_md = self.project / f"books/{book}/design.md"
        chapter = self.project / f"books/{book}/chapters/CH-0001.json"
        reader_state = self.project / f"books/{book}/reader-state.md"
        self.assertEqual(evidence[0]["hash"], self.bf._file_hash(design_md))
        self.assertEqual(evidence[1]["hash"], self.bf._file_hash(chapter))
        self.assertEqual(evidence[2]["hash"], self.bf._file_hash(reader_state))

    def test_binds_book_scoped_entry_exit_state_evidence_to_reader_state(self):
        book = self.bf.add_book(self.project, "BookScopedState")["id"]
        self.brief(book)
        provider = DesignProvider(
            proposal(),
            audit={"findings": [{
                "id": "F-0001",
                "severity": "note",
                "issue": "Seeded note.",
                "evidence": [
                    {"location": f"{book}#entry_state#cradle"},
                    {"location": f"{book}#exit_boundary#book2_hooks"},
                    {"location": f"{book}#proposal/turns/TURN-0001"},
                    {"location": f"{book}#CH-0001"},
                    {"location": "design_scope.premise — Silent Mind description"},
                    {"location": "BEAT-0003 (design_scope.proposal.chapters.CH-0001.beats.BEAT-0001.cause, unhashed in envelope)"},
                ],
                "repair_scope": [book],
            }]},
        )
        result = self.bf.execute_book_design(self.project, book, provider=provider)
        self.assertEqual(result["state"], "design_clean")
        audit = json.loads((self.project / f"books/{book}/design-audit.json").read_text())
        evidence = audit["findings"][0]["evidence"]
        reader_state = self.project / f"books/{book}/reader-state.md"
        design_md = self.project / f"books/{book}/design.md"
        chapter = self.project / f"books/{book}/chapters/CH-0001.json"
        self.assertEqual(evidence[0]["hash"], self.bf._file_hash(reader_state))
        self.assertEqual(evidence[1]["hash"], self.bf._file_hash(reader_state))
        self.assertEqual(evidence[2]["hash"], self.bf._file_hash(design_md))
        self.assertEqual(evidence[3]["hash"], self.bf._file_hash(chapter))
        self.assertEqual(evidence[4]["hash"], self.bf._file_hash(design_md))
        self.assertEqual(evidence[5]["hash"], self.bf._file_hash(chapter))

    def test_foreign_book_scoped_evidence_is_set_aside_and_never_becomes_a_finding(self):
        """Evidence in another book's artifacts is not evidence about this one. It
        used to end the run and ask a person; it is now recorded and the design
        goes on, which is the same refusal without the stop."""
        book = self.bf.add_book(self.project, "Closed")["id"]
        self.brief(book)
        provider = DesignProvider(
            proposal(),
            audit={"findings": [{
                "id": "F-0001",
                "severity": "note",
                "issue": "Seeded note.",
                "evidence": [{"location": "BOOK-0009#proposal/turns/TURN-0001"}],
                "repair_scope": [book],
            }]},
        )
        record = self.bf.execute_book_design(self.project, book, provider=provider)
        self.assertEqual(record["state"], "design_clean")
        self.assertEqual(record["findings"], [])
        self.assertTrue(record["unverifiable"], "the row is kept, with what it cited")
        self.assertTrue(all(row["id"].endswith("F-0001") for row in record["unverifiable"]))
        self.assertIn("BOOK-0009#proposal/turns/TURN-0001", record["unverifiable"][0]["unresolved"])

    def test_resumes_book_audit_alone_when_design_already_promoted(self):
        """A stored verdict written under a different auditor is thrown away and
        asked again. The design is already promoted, so only the audit runs."""
        book = self.bf.add_book(self.project, "Resumed")["id"]
        self.brief(book)
        first = DesignProvider(proposal())
        self.assertEqual(self.bf.execute_book_design(self.project, book, provider=first)["state"], "design_clean")
        self.assertIn("designer", first.calls)

        (self.project / f"books/{book}/design-audit.json").write_text(json.dumps({
            **json.loads((self.project / f"books/{book}/design-audit.json").read_text()),
            "question": "written-under-a-different-auditor",
        }))
        # Forgotten, or the audit is answered from the calls this project already
        # paid for and the resume makes no call at all.
        self.bf._forget_task_calls(self.project, f"AUDIT-{book}")
        rerun = DesignProvider(proposal(), audit={"findings": []})
        result = self.bf.execute_book_design(self.project, book, provider=rerun)
        self.assertEqual(result["state"], "design_clean")
        self.assertEqual(set(rerun.calls), {"canon-auditor"}, "the design is not run again")
        plan = self.bf._load_plan(self.project)
        self.assertEqual(next(row for row in plan["tasks"] if row["id"] == f"DESIGN-{book}")["state"], "succeeded")

    def test_missing_author_brief_fails_closed_before_any_provider_call(self):
        book = self.bf.add_book(self.project, "NoBrief")["id"]
        provider = DesignProvider(proposal())
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.bf.execute_book_design(self.project, book, provider=provider)
        self.assertIn("book-brief.json", str(caught.exception))
        self.assertEqual(provider.calls, [])

    def test_book_designer_envelope_carries_brief_and_full_canon_context(self):
        book = self.bf.add_book(self.project, "FullContext")["id"]
        self.brief(book)
        canon = self.project / "universe/canon/factions"
        canon.mkdir(parents=True, exist_ok=True)
        (canon / "FAC-0001.md").write_text("---\nid: FAC-0001\ncontinuity: CNT-0001\n---\n\n# Guild\n\n<!-- bf:block summary -->\nThe Guild meters memory in candles.\n")
        self.bf.rebuild_indexes(self.project)
        seen = {"capsule": None, "context": [], "worldbuilding": None}
        original = self.bf.build_envelope
        def spy(project, **kwargs):
            envelope = original(project, **kwargs)
            if kwargs.get("role") == "designer":
                payload = envelope["payload"]
                seen["capsule"] = payload["task"]
                seen["worldbuilding"] = payload["task"].get("worldbuilding")
                seen["context"] = [row["id"] for row in payload.get("context", [])]
            return envelope
        self.bf.build_envelope = spy
        try:
            self.bf.execute_book_design(self.project, book, provider=DesignProvider(proposal()))
        finally:
            self.bf.build_envelope = original
        self.assertIsNotNone(seen["capsule"])
        self.assertEqual(seen["capsule"]["brief"]["premise"], "A diver must decide.")
        self.assertIn("UNI-0001#kernel", seen["context"])
        self.assertIn("FAC-0001#summary", seen["context"])

    def test_no_mid_sentence_wrap_in_generated_design_artifacts(self):
        book = self.bf.add_book(self.project, "Nowrap")["id"]
        self.brief(book)
        self.bf.execute_book_design(self.project, book, provider=DesignProvider(proposal()))
        design = (self.project / f"books/{book}/design.md").read_text()
        wrapped = self.bf._wrapped_lines(self.project / f"books/{book}/design.md")
        self.assertEqual(wrapped, [])


if __name__ == "__main__":
    unittest.main()



class ChapterTitleMaterializationTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["chorus"] = {"enabled": False, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

    def test_a_beat_prefix_title_is_dropped_and_reported_while_a_real_title_survives(self):
        book = self.bf.add_book(self.project, "Titles")["id"]
        value = proposal()
        value["chapters"][0]["title"] = "The Word Under the Glass"
        value["chapters"][1]["title"] = "The choice costs an ally"

        findings = self.bf.validate_book_design(self.project, book, value)
        self.assertEqual(
            [f for f in findings if f["code"] == "chapter.title-from-beat"],
            [{"code": "chapter.title-from-beat", "severity": "warning", "chapter": "CH-0002", "title": "The choice costs an ally"}],
        )
        self.assertEqual([f for f in findings if f["severity"] == "blocking"], [])

        (self.project / f"books/{book}/book-brief.json").write_text(json.dumps({"schema": 1, "premise": "A diver must decide.", "characters": ["Mara"], "plot": ["dive"], "tone": "quiet"}))
        self.assertEqual(self.bf.apply_book_design(self.project, book, value)["state"], "design_clean")
        first = json.loads((self.project / f"books/{book}/chapters/CH-0001.json").read_text())
        second = json.loads((self.project / f"books/{book}/chapters/CH-0002.json").read_text())
        self.assertEqual(first["title"], "The Word Under the Glass")
        self.assertNotIn("title", second)


class SourceLanguageTests(unittest.TestCase):
    """A book whose source_language is en came back with forty Italian titles: the
    capsule never named the language, so the designer inferred it from the brief."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", "en", chorus_models=[])
        config_path = self.project / "book-forge.yaml"
        config = json.loads(config_path.read_text())
        config["chorus"] = {"enabled": False, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER}
        config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.book = self.bf.add_book(self.project, "A")["id"]
        (self.project / f"books/{self.book}/book-brief.json").write_text(
            json.dumps({"schema": 1, "premise": "Una tuffatrice deve decidere.", "characters": ["Mara"], "plot": ["tuffo"], "tone": "quieto"})
        )

    def test_the_capsule_names_the_language_the_book_is_written_in(self):
        seen = {}
        original = self.bf.build_envelope

        def spy(project, **kwargs):
            envelope = original(project, **kwargs)
            if kwargs.get("role") == "designer" and not seen:
                seen.update(envelope["payload"]["task"])
            return envelope

        self.bf.build_envelope = spy
        try:
            self.bf.execute_book_design(self.project, self.book, provider=DesignProvider(proposal()), no_chorus=True, no_post_chorus=True)
        finally:
            self.bf.build_envelope = original
        self.assertEqual(seen.get("source_language"), "en")

    def test_the_designer_is_told_the_brief_does_not_govern(self):
        prompt = (Path(self.bf.__file__).resolve().parents[1] / "assets" / "prompts" / "designer.md").read_text()
        self.assertIn("source_language", prompt)
        self.assertIn("does not govern the book", prompt)


class ObligationFieldTests(unittest.TestCase):
    """`chapter.obligations` joins a chapter to a promise another book is owed. A
    designer that writes its own foreshadowing there fails the whole design after
    every call has been paid for."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]

    def test_free_text_in_obligations_is_blocking(self):
        value = proposal()
        value["chapters"][0]["obligations"] = ["The screen must wake once more at the book's end."]
        findings = self.bf.validate_book_design(self.project, self.book, value)
        unknown = [row for row in findings if row["code"] == "obligation.unknown"]
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]["severity"], "blocking")

    def test_a_book_with_no_registered_obligations_wants_empty_lists(self):
        value = proposal()
        for chapter in value["chapters"]:
            chapter["obligations"] = []
        blocking = [row for row in self.bf.validate_book_design(self.project, self.book, value) if row["severity"] == "blocking"]
        self.assertEqual(blocking, [])

    def test_the_designer_is_told_what_the_field_is_for(self):
        prompt = (Path(self.bf.__file__).resolve().parents[1] / "assets" / "prompts" / "designer.md").read_text()
        self.assertIn("`obligations` is not one of those fields", prompt)
        self.assertIn("plants", prompt)
        self.assertIn("reveals", prompt)


class DesignAsksForTitlesTests(unittest.TestCase):
    """Naming the chapters is the pipeline's job, so the contract must ask for it."""

    class CapturingProvider(DesignProvider):
        def __init__(self, value, audit=None):
            super().__init__(value, audit)
            self.envelopes = []

        def __call__(self, role, envelope, attempt_dir):
            self.envelopes.append((role, envelope["payload"]))
            return super().__call__(role, envelope, attempt_dir)

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["chorus"] = {"enabled": False, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

    def test_the_designer_is_asked_for_a_title_and_told_what_one_is(self):
        book = self.bf.add_book(self.project, "Named")["id"]
        (self.project / f"books/{book}/book-brief.json").write_text(json.dumps({"schema": 1, "premise": "A diver must decide.", "characters": ["Mara"], "plot": ["dive"], "tone": "quiet"}))
        provider = self.CapturingProvider(proposal())
        self.bf.execute_book_design(self.project, book, provider=provider)

        payload = next(payload for role, payload in provider.envelopes if role == "designer")
        chapter_shape = payload["task"]["required_output"]["chapters"][0]
        self.assertIn("title", chapter_shape)
        self.assertIn("never the opening words of a beat", chapter_shape["title"])
        self.assertIn("never the opening words of a beat", payload["role_prompt"])

    def test_the_writer_is_told_what_to_invent_when_the_contract_has_no_title(self):
        writer_prompt = (Path(self.bf.__file__).parents[1] / "assets/prompts/writer.md").read_text()
        self.assertIn("otherwise invent one: two to six words", writer_prompt)
        self.assertIn("never a chapter number or numeral prefix", writer_prompt)



class ASetAsideRowIsANoteNotAStopTests(unittest.TestCase):
    """A verdict of `needs_review` stopped a finished audit to ask a person, and
    the driver could not leave it: the gate that clears a design accepts only
    `design_clean`, so the design stage was re-dispatched to be audited into the
    same state again."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World")
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["chorus"] = {"enabled": False, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

    def book(self, title="A"):
        book = self.bf.add_book(self.project, title)["id"]
        (self.project / f"books/{book}/book-brief.json").write_text(json.dumps(
            {"schema": 1, "premise": "A diver must decide.", "characters": ["Mara"], "plot": ["dive"], "tone": "quiet"}
        ))
        return book

    def run_with(self, findings, title="A"):
        book = self.book(title)
        record = self.bf.execute_book_design(
            self.project, book, provider=DesignProvider(proposal(), audit={"findings": findings})
        )
        return book, record

    def unbindable(self, severity="note"):
        return {
            "id": "F-0001", "severity": severity, "issue": "Seeded.",
            "evidence": [{"location": "nowhere/not-a-file.md"}], "repair_scope": ["BOOK-0001"],
        }

    def test_a_row_the_engine_cannot_bind_leaves_the_verdict_clean_and_does_not_raise(self):
        _, record = self.run_with([self.unbindable()])
        self.assertEqual(record["state"], "design_clean")
        self.assertTrue(record["unverifiable"], "the row is kept, with what it cited")
        self.assertTrue(all(row["id"].endswith("F-0001") for row in record["unverifiable"]))
        self.assertIn("nowhere/not-a-file.md", record["unverifiable"][0]["unresolved"])

    def test_a_blocking_finding_beside_a_set_aside_row_still_blocks(self):
        """The verdict is taken on the findings the engine could bind, and a
        blocking one among them is still blocking."""
        book = self.book("B")
        blocking = {
            "id": "F-0002", "severity": "blocking", "issue": "The arc has no cost.",
            "evidence": [{"location": "UNI-0001#kernel"}], "repair_scope": [book],
        }
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.execute_book_design(
                self.project, book,
                provider=DesignProvider(proposal(), audit={"findings": [self.unbindable(), blocking]}),
            )
        record = json.loads((self.project / f"books/{book}/design-audit.json").read_text())
        self.assertEqual(record["state"], "blocked")
        self.assertTrue(record["unverifiable"], "the set-aside row is recorded beside the blocking one")

    def test_a_design_whose_audit_set_a_row_aside_is_a_finished_design(self):
        """What the driver reads: an audit that asked nobody anything is done."""
        book, _ = self.run_with([self.unbindable()], title="C")
        self.assertFalse(self.bf._advance_needs_design(self.project, book))

    def test_no_path_writes_a_verdict_the_gate_cannot_clear(self):
        for index, findings in enumerate(([], [self.unbindable()], [self.unbindable(severity="warning")])):
            with self.subTest(findings=findings):
                _, record = self.run_with(findings, title=f"D{index}")
                self.assertEqual(record["state"], "design_clean")
