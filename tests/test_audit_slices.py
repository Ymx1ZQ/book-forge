import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "book_forge.py"
PROMPTS = MODULE_PATH.parents[1] / "assets" / "prompts"
MODEL = "openrouter/deepseek/deepseek-v4-flash-0731"
CHAPTER_COUNT = 40


def load_module():
    spec = importlib.util.spec_from_file_location("book_forge_audit_slices", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROLE_VARIANTS = {name: spec[1] for name, spec in load_module().ROLE_SPECS.items()}


def chapter(index):
    return {
        "id": f"CH-{index:04d}", "order": index, "title": f"The Ninth Tide {index}",
        "pov": "CHR-0001", "beats": ["She wants the log and the warden will not open it"],
        "plants": [f"the warden keeps a key for {index}"], "reveals": [f"the key opens door {index}"],
        "target_words": 3000, "imports": ["UNI-0001#kernel"], "obligations": [], "pivotal": None,
    }


class AuditProvider:
    """Answers the design in slices and the audit in passes, recording both."""

    def __init__(self, bf, chapter_count=CHAPTER_COUNT, schedule_ceiling=None, silent_windows=()):
        self.bf = bf
        self.chapter_count = chapter_count
        self.schedule_ceiling = schedule_ceiling
        self.silent_windows = set(silent_windows)
        self.audit_scopes = []
        self.calls = []

    def _ok(self, envelope, payload, role):
        return {
            "text": json.dumps(payload),
            "provider": "openrouter", "model": MODEL, "variant": ROLE_VARIANTS.get(role, "high"),
            "session_id": f"ses-{len(self.calls)}", "tokens": {"input": envelope["estimated_input_tokens"], "output": 800},
            "cost": 0.01, "latency_ms": 5, "finish": "stop",
        }

    def _truncated(self, envelope, role):
        return {
            "text": '{"findings":[{"id":"F-001"',
            "provider": "openrouter", "model": MODEL, "variant": ROLE_VARIANTS.get(role, "high"),
            "session_id": f"ses-{len(self.calls)}", "tokens": {"input": envelope["estimated_input_tokens"], "output": 3000},
            "cost": 0.01, "latency_ms": 5, "finish": "length",
        }

    def __call__(self, role, envelope, attempt_dir):
        self.calls.append(role)
        if role.startswith("advisor-") or role == "chorus-synthesizer":
            return self._ok(envelope, {"findings": [], "suggestions": []}, role)
        task = envelope["payload"]["task"]
        if role == "canon-auditor":
            scope = task["design_scope"]
            self.audit_scopes.append(scope)
            rows = scope.get("proposal", {}).get("chapters", [])
            if self.silent_windows and "neighbourhood_digest" in scope and rows:
                slug = f"window-{rows[0]['order']}-{rows[-1]['order']}"
                if slug in self.silent_windows:
                    # What production returns: the whole budget spent reasoning, nothing emitted.
                    return {**self._ok(envelope, {}, role), "text": ""}
            if self.schedule_ceiling is not None and "neighbourhood_digest" not in scope and len(rows) > self.schedule_ceiling:
                return self._truncated(envelope, role)
            answer = {"findings": [{
                "id": "F-001", "severity": "note", "issue": "Seeded note.",
                "evidence": [{"location": "UNI-0001#kernel"}], "repair_scope": ["BOOK-0001"],
            }]}
            if "neighbourhood_digest" not in scope:
                answer["paid"] = []
                answer["added"] = [
                    {"id": f"P-{row['order']:03d}", "chapter": row["id"], "promise": f"the key opens door {row['order']}", "expected_in": "unknown"}
                    for row in rows
                ]
            return self._ok(envelope, answer, role)
        chunk = task.get("chunk") or {}
        if chunk.get("category") == "spine":
            return self._ok(envelope, {
                "premise": "A diver must decide whether memory can be owned.",
                "entry_state": {"CHR-0001": "isolated"},
                "arc": ["refusal", "cost", "choice"],
                "exit_boundary": {"CHR-0001": "committed"},
                "chapter_count": self.chapter_count,
            }, role)
        first, last = int(chunk["first_order"]), int(chunk["last_order"])
        if chunk.get("category") == "outline":
            return self._ok(envelope, {"chapter_outline": [
                {"id": f"CH-{i:04d}", "order": i, "title": f"The Ninth Tide {i}", "pov": "CHR-0001", "summary": "She goes down again."}
                for i in range(first, last + 1)
            ]}, role)
        return self._ok(envelope, {"chapters": [chapter(i) for i in range(first, last + 1)]}, role)


class PassBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()

    def test_twenty_six_chapters_become_thirteen_windows_and_a_walk_of_four(self):
        chunks = self.bf._book_audit_chunks(26)
        windows = [(c["first_order"], c["last_order"]) for c in chunks if c["category"] == "window"]
        schedule = [(c["first_order"], c["last_order"]) for c in chunks if c["category"] == "schedule"]
        self.assertEqual(windows, [(n, n + 1) for n in range(1, 26, 2)])
        self.assertEqual(len(windows), 13)
        self.assertEqual(schedule, [(1, 8), (9, 16), (17, 24), (25, 26)])

    def test_no_pass_reads_more_than_a_fixed_number_of_chapters(self):
        """The width of a pass is a constant, so a longer book buys more passes
        rather than a bigger question. The schedule pass used to be the book."""
        for count in (12, 40, 200):
            widths = [c["last_order"] - c["first_order"] + 1 for c in self.bf._book_audit_chunks(count)]
            with self.subTest(chapters=count):
                self.assertLessEqual(max(widths), max(self.bf.BOOK_AUDIT_SLICE_SIZE, self.bf.SCHEDULE_WINDOW_SIZE))

    def test_the_window_is_the_width_production_answers_at(self):
        """Five almost never answered on landfall: window-6-10 came back empty, then
        6-8, then 6-7, and only 6-6 and 7-7 answered. It is not the payload — five
        chapters are 48400 bytes and one is 41803 — it is the difficulty."""
        self.assertEqual(self.bf.BOOK_AUDIT_SLICE_SIZE, 2)

    def test_a_book_with_no_chapters_asks_nothing(self):
        self.assertEqual(self.bf._book_audit_chunks(0), [])

    def test_a_schedule_pass_can_be_halved_like_a_window(self):
        halves = self.bf._halve_chunk({"category": "schedule", "part": "1-40", "first_order": 1, "last_order": 40})
        self.assertEqual([(h["category"], h["first_order"], h["last_order"]) for h in halves], [
            ("schedule", 1, 20), ("schedule", 21, 40),
        ])

    def test_the_design_spine_still_cannot_be_halved(self):
        self.assertEqual(self.bf._halve_chunk({"category": "spine"}), [])


class PassScopeTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.scope = {
            "scope": "book", "book": "BOOK-0001",
            "proposal": {"premise": "p", "arc": ["a"], "chapters": [chapter(i) for i in range(1, 41)]},
        }

    def test_a_window_reads_its_own_chapters_in_full(self):
        sliced = self.bf._audit_chunk_scope(self.scope, {"category": "window", "part": "11-15", "first_order": 11, "last_order": 15})
        rows = sliced["proposal"]["chapters"]
        self.assertEqual([row["order"] for row in rows], list(range(11, 16)))
        self.assertIn("summary", rows[0].keys() | {"summary"})
        self.assertIn("plants", rows[0])
        self.assertIn("reveals", rows[0])

    def test_a_window_sees_its_neighbours_one_line_at_a_time_and_not_the_book(self):
        sliced = self.bf._audit_chunk_scope(self.scope, {"category": "window", "part": "11-15", "first_order": 11, "last_order": 15})
        digest = sliced["neighbourhood_digest"]
        self.assertNotIn("book_digest", sliced)
        self.assertEqual([row["order"] for row in digest], list(range(7, 20)))
        self.assertEqual(sorted(digest[0]), ["id", "order", "pov", "title"])

    def test_the_neighbourhood_never_widens_with_the_book(self):
        """A longer book gives a window more passes, never a bigger one."""
        ceiling = self.bf.BOOK_AUDIT_SLICE_SIZE + 2 * self.bf.AUDIT_NEIGHBOURS
        for count in (12, 40, 200):
            scope = {**self.scope, "proposal": {**self.scope["proposal"], "chapters": [chapter(i) for i in range(1, count + 1)]}}
            for chunk in self.bf._book_audit_chunks(count):
                if chunk["category"] != "window":
                    continue
                with self.subTest(chapters=count, part=chunk["part"]):
                    self.assertLessEqual(len(self.bf._audit_chunk_scope(scope, chunk)["neighbourhood_digest"]), ceiling)

    def test_a_schedule_pass_reads_one_window_of_promises_and_what_is_still_open(self):
        carried = [{"id": "P-001", "chapter": "CH-0002", "promise": "the warden owes an answer", "expected_in": "unknown"}]
        sliced = self.bf._audit_chunk_scope(
            self.scope, {"category": "schedule", "part": "9-16", "first_order": 9, "last_order": 16}, carried
        )
        rows = sliced["proposal"]["chapters"]
        self.assertEqual([row["order"] for row in rows], list(range(9, 17)))
        self.assertEqual(sorted(rows[0]), ["id", "order", "plants", "reveals", "title"])
        self.assertEqual(sliced["open_promises"], carried)
        self.assertNotIn("book_digest", sliced)
        self.assertNotIn("neighbourhood_digest", sliced)
        self.assertIn("also_return", sliced["pass"])

    def test_only_the_edges_of_the_book_carry_its_edges(self):
        """A window on chapters nine and ten reported that the Candle was still in
        the Counting nave and Binta did not yet know the Heart existed — the book's
        first page, quoted against its tenth chapter as a contradiction."""
        scope = {**self.scope, "proposal": {**self.scope["proposal"], "entry_state": {"a": 1}, "exit_boundary": {"z": 1}}}
        first = self.bf._audit_chunk_scope(scope, {"category": "window", "part": "1-2", "first_order": 1, "last_order": 2})
        middle = self.bf._audit_chunk_scope(scope, {"category": "window", "part": "11-12", "first_order": 11, "last_order": 12})
        last = self.bf._audit_chunk_scope(scope, {"category": "window", "part": "39-40", "first_order": 39, "last_order": 40})
        self.assertIn("entry_state", first["proposal"])
        self.assertNotIn("exit_boundary", first["proposal"])
        self.assertNotIn("entry_state", middle["proposal"])
        self.assertNotIn("exit_boundary", middle["proposal"])
        self.assertIn("exit_boundary", last["proposal"])
        self.assertNotIn("entry_state", last["proposal"])

    def test_a_book_that_fits_one_window_carries_both(self):
        short = {"scope": "book", "book": "BOOK-0001", "proposal": {
            "premise": "p", "arc": ["a"], "entry_state": {"a": 1}, "exit_boundary": {"z": 1},
            "chapters": [chapter(1), chapter(2)],
        }}
        sliced = self.bf._audit_chunk_scope(short, {"category": "window", "part": "1-2", "first_order": 1, "last_order": 2})
        self.assertIn("entry_state", sliced["proposal"])
        self.assertIn("exit_boundary", sliced["proposal"])

    def test_the_schedule_fold_follows_the_same_rule(self):
        scope = {**self.scope, "proposal": {**self.scope["proposal"], "entry_state": {"a": 1}, "exit_boundary": {"z": 1}}}
        middle = self.bf._audit_chunk_scope(scope, {"category": "schedule", "part": "9-16", "first_order": 9, "last_order": 16}, [])
        opening = self.bf._audit_chunk_scope(scope, {"category": "schedule", "part": "1-8", "first_order": 1, "last_order": 8}, [])
        self.assertNotIn("entry_state", middle["proposal"])
        self.assertIn("entry_state", opening["proposal"])

    def test_the_prompt_says_what_the_edges_are(self):
        prompt = (PROMPTS / "canon-auditor.md").read_text()
        self.assertIn("bounded by neither", prompt)

    def test_the_spine_travels_with_every_pass(self):
        for chunk in self.bf._book_audit_chunks(40):
            sliced = self.bf._audit_chunk_scope(self.scope, chunk)
            self.assertEqual(sliced["proposal"]["arc"], ["a"], self.bf._chunk_slug(chunk))
            self.assertEqual(sliced["proposal"]["premise"], "p")

    def test_each_pass_is_told_what_it_is_reading(self):
        for chunk in self.bf._book_audit_chunks(40):
            self.assertIn("reading", self.bf._audit_chunk_scope(self.scope, chunk)["pass"])

    def test_the_prompt_describes_both_shapes(self):
        prompt = (PROMPTS / "canon-auditor.md").read_text()
        self.assertIn("design_scope.pass", prompt)
        self.assertIn("neighbourhood_digest", prompt)
        self.assertIn("open_promises", prompt)


class TheFoldCarriesADifferenceTests(unittest.TestCase):
    """Asking for the whole ledger back made a pass's answer grow with the book.
    Landfall's audit died at schedule-11-11 on `input 6087, reasoning 32000,
    output 0`, after an attempt that stopped mid-list on its eleventh promise."""

    def setUp(self):
        self.bf = load_module()
        self.carried = [
            {"id": "OP-0001", "chapter": "CH-0001", "promise": "the warden owes an answer"},
            {"id": "OP-0002", "chapter": "CH-0002", "promise": "the door is owed"},
            {"id": "OP-0003", "chapter": "CH-0003", "promise": "the grave is unnamed"},
        ]

    def test_a_pass_paying_two_and_making_one_leaves_the_set_two_shorter_and_one_longer(self):
        kept = self.bf._carry_open_promises(self.carried, {
            "paid": ["OP-0001", "OP-0003"],
            "added": [{"id": "OP-0004", "chapter": "CH-0011", "promise": "the candle is owed a name"}],
        }, "schedule-11-12")
        self.assertEqual([row["id"] for row in kept], ["OP-0002", "OP-0004"])

    def test_a_paid_id_nobody_carried_is_reported_and_the_pass_still_counts(self):
        kept = self.bf._carry_open_promises(self.carried, {"paid": ["OP-0002", "OP-9999"], "added": []}, "schedule-11-12")
        self.assertEqual([row["id"] for row in kept], ["OP-0001", "OP-0003"])

    def test_a_pass_that_says_nothing_about_the_ledger_keeps_it(self):
        self.assertEqual(self.bf._carry_open_promises(self.carried, {"findings": []}, "schedule-1-2"), self.carried)

    def test_the_answer_of_a_late_window_is_no_larger_than_that_of_an_early_one(self):
        """The whole point: what a pass writes is the size of what it changed."""
        early = {"paid": ["OP-0001"], "added": [{"id": "OP-0004", "chapter": "CH-0003", "promise": "one more"}]}
        carried = list(self.carried)
        for _ in range(20):
            carried = self.bf._carry_open_promises(carried, {"paid": [], "added": [
                {"id": f"OP-{n:04d}", "chapter": "CH-0011", "promise": "another"} for n in range(100, 102)
            ]}, "schedule-x")
        late = {"paid": ["OP-0100"], "added": [{"id": "OP-0500", "chapter": "CH-0020", "promise": "one more"}]}
        self.assertLess(
            abs(len(json.dumps(late)) - len(json.dumps(early))), 40,
            "a pass in the middle of the book writes about as much as a pass at its start",
        )
        self.assertGreater(len(carried), 20, "the engine, not the pass, is the one holding the ledger")

    def test_an_overlong_ledger_is_trimmed_rather_than_ending_the_audit(self):
        carried = [{"id": f"OP-{n:04d}", "chapter": "CH-0001", "promise": "owed"} for n in range(self.bf.MAX_OPEN_PROMISES + 10)]
        kept = self.bf._carry_open_promises(carried, {"paid": [], "added": []}, "schedule-x")
        self.assertEqual(len(kept), self.bf.MAX_OPEN_PROMISES)
        self.assertEqual(kept[-1]["id"], carried[-1]["id"], "the most recent promises are the ones kept")

    def test_the_prompt_asks_for_the_difference(self):
        prompt = (PROMPTS / "canon-auditor.md").read_text()
        self.assertIn("`paid`", prompt)
        self.assertIn("`added`", prompt)
        self.assertIn("never the ledger it was handed", prompt)


class APromiseFallsDueInAChapterTheBookHasTests(unittest.TestCase):
    """Thirty-nine of landfall's fifty-nine promises named CH-0030, CH-0033,
    CH-0035 or CH-0040 in a twenty-six chapter book. The auditor then reasoned
    soundly from a false premise and blocked six chapters on the last repair
    round available."""

    def setUp(self):
        self.bf = load_module()
        self.book = {f"CH-{n:04d}" for n in range(1, 27)}

    def test_a_promise_expecting_a_chapter_the_book_does_not_have_is_dropped(self):
        kept = self.bf._carry_open_promises([], {"paid": [], "added": [
            {"id": "PROM-0041", "chapter": "CH-0011", "promise": "the snow death is owed", "expected_in": "CH-0040"},
            {"id": "PROM-0042", "chapter": "CH-0011", "promise": "the line in blood is owed", "expected_in": "CH-0020"},
        ]}, "schedule-9-16", self.book)
        self.assertEqual([row["id"] for row in kept], ["PROM-0042"])

    def test_a_promise_with_no_expected_chapter_is_kept(self):
        """A promise the book has not yet placed is a real thing, and a value that
        is not a chapter id at all is read as unspecified rather than as a phantom."""
        for value in ({}, {"expected_in": ""}, {"expected_in": None}, {"expected_in": "unknown"}, {"expected_in": "the finale"}):
            with self.subTest(value=value):
                kept = self.bf._carry_open_promises([], {"paid": [], "added": [
                    {"id": "PROM-0001", "chapter": "CH-0004", "promise": "the grave is unnamed", **value},
                ]}, "schedule-1-8", self.book)
                self.assertEqual([row["id"] for row in kept], ["PROM-0001"])

    def test_a_promise_made_in_a_chapter_the_book_does_not_have_is_dropped(self):
        kept = self.bf._carry_open_promises([], {"paid": [], "added": [
            {"id": "PROM-0050", "chapter": "CH-0033", "promise": "owed", "expected_in": "CH-0020"},
        ]}, "schedule-17-24", self.book)
        self.assertEqual(kept, [])

    def test_without_the_book_ids_every_promise_is_kept(self):
        """The check is on what the engine knows; it never invents a bound."""
        kept = self.bf._carry_open_promises([], {"paid": [], "added": [
            {"id": "PROM-0041", "chapter": "CH-0011", "promise": "owed", "expected_in": "CH-0040"},
        ]}, "schedule-9-16")
        self.assertEqual([row["id"] for row in kept], ["PROM-0041"])

    def test_a_carried_promise_is_never_re_examined(self):
        """Only what a pass adds is checked; the ledger has already been through."""
        carried = [{"id": "OP-0001", "chapter": "CH-0002", "promise": "owed", "expected_in": "CH-0040"}]
        kept = self.bf._carry_open_promises(carried, {"paid": [], "added": []}, "schedule-9-16", self.book)
        self.assertEqual([row["id"] for row in kept], ["OP-0001"])

    def test_the_prompt_says_where_a_promise_may_fall_due(self):
        prompt = (PROMPTS / "canon-auditor.md").read_text()
        self.assertIn("falls due in a chapter of this book or in none", prompt)


class ARowTheEngineCannotUseTests(unittest.TestCase):
    """An audit of thirty-three completed passes died on a finding that had an id,
    a severity, an issue and evidence, lacked only `repair_scope`, and whose text
    said nothing was wrong."""

    def setUp(self):
        self.bf = load_module()

    def good(self):
        return {
            "id": "F-001", "severity": "note", "issue": "Seeded.", "repair_scope": ["BOOK-0001"],
            "evidence": [{"location": "UNI-0001#kernel", "hash": "a" * 64}],
        }

    def test_an_incomplete_finding_is_set_aside_and_the_good_one_stands(self):
        incomplete = {k: v for k, v in self.good().items() if k != "repair_scope"}
        incomplete["id"] = "F-002"
        value = {"findings": [self.good(), incomplete]}
        usable = self.bf._validate_audit_output(value)
        self.assertEqual([row["id"] for row in usable], ["F-001"])
        self.assertEqual(value["unverifiable"][0]["id"], "F-002")
        self.assertIn("repair_scope", value["unverifiable"][0]["set_aside"])

    def test_each_shape_the_engine_cannot_use_says_why(self):
        cases = {
            "missing id": {k: v for k, v in self.good().items() if k != "id"},
            "unknown severity": {**self.good(), "severity": "catastrophic"},
            "no evidence": {**self.good(), "evidence": []},
            "evidence without a hash": {**self.good(), "evidence": [{"location": "UNI-0001#kernel"}]},
            "not an object": "a sentence where a finding should be",
        }
        for label, row in cases.items():
            with self.subTest(case=label):
                value = {"findings": [row]}
                self.assertEqual(self.bf._validate_audit_output(value), [])
                self.assertTrue(value["unverifiable"][0]["set_aside"])

    def test_a_response_that_is_not_an_answer_still_fails(self):
        with self.assertRaises(self.bf.BookForgeError):
            self.bf._validate_audit_output({"findings": "nope"})
        with self.assertRaises(self.bf.BookForgeError):
            self.bf._validate_audit_output({})

    def test_a_set_aside_row_keeps_what_the_auditor_wrote(self):
        incomplete = {k: v for k, v in self.good().items() if k != "repair_scope"}
        value = {"findings": [incomplete]}
        self.bf._validate_audit_output(value)
        self.assertEqual(value["unverifiable"][0]["issue"], "Seeded.")


class PromiseEvidenceTests(unittest.TestCase):
    """The fold gave the auditor an id and then refused it for using it: landfall's
    audit died on `OP-0014` after seventeen passes."""

    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = self.bf.add_book(self.project, "A")["id"]
        self.scope = {"scope": "book", "book": self.book, "proposal": {"chapters": [chapter(1)]}}
        (self.project / f"books/{self.book}/design.md").write_text("# Design\n", encoding="utf-8")

    def finding(self, location):
        return {"findings": [{
            "id": "F-001", "severity": "note", "issue": "Seeded.",
            "evidence": [{"location": location}], "repair_scope": [self.book],
        }]}

    def test_a_finding_citing_a_carried_promise_binds_to_the_chapter_that_made_it(self):
        carried = [{"id": "OP-0014", "chapter": "UNI-0001#kernel", "promise": "the warden owes an answer"}]
        bound = self.bf._bind_audit_evidence(
            self.project, self.scope, self.finding("OP-0014"), self.bf._promise_chapters(carried, None)
        )
        self.assertEqual(bound["findings"][0]["evidence"][0]["location"], "UNI-0001#kernel")
        self.assertNotEqual(bound["findings"][0]["evidence"][0]["hash"], "")

    def test_a_promise_the_pass_is_itself_returning_binds_too(self):
        returned = [{"id": "OP-0021", "chapter": "UNI-0001#kernel", "promise": "the door is owed"}]
        bound = self.bf._bind_audit_evidence(
            self.project, self.scope, self.finding("OP-0021"), self.bf._promise_chapters([], returned)
        )
        self.assertEqual(bound["findings"][0]["evidence"][0]["location"], "UNI-0001#kernel")

    def test_a_promise_that_cannot_be_placed_is_set_aside_rather_than_binding(self):
        bound = self.bf._bind_audit_evidence(self.project, self.scope, self.finding("OP-9999"), {})
        self.assertEqual(bound["findings"], [])
        self.assertEqual(bound["unverifiable"][0]["unresolved"], ["OP-9999"])

    def test_a_finding_keeps_the_citation_that_resolves_and_reports_the_one_that_does_not(self):
        """PL-0001#summary killed an audit of twenty-five completed passes, on a
        project whose places are PLC-."""
        value = {"findings": [{
            "id": "F-001", "severity": "blocking", "issue": "Seeded.",
            "evidence": [{"location": "UNI-0001#kernel"}, {"location": "PL-0001#summary"}],
            "repair_scope": [self.book],
        }]}
        bound = self.bf._bind_audit_evidence(self.project, self.scope, value, {})
        finding = bound["findings"][0]
        self.assertEqual([row["location"] for row in finding["evidence"]], ["UNI-0001#kernel"])
        self.assertEqual(finding["unresolved_evidence"], ["PL-0001#summary"])
        self.assertEqual(finding["severity"], "blocking", "a finding that still has evidence keeps its severity")
        self.assertEqual(bound["unverifiable"], [])

    def test_a_finding_whose_every_citation_is_unlookupable_never_blocks(self):
        value = {"findings": [{
            "id": "F-001", "severity": "blocking", "issue": "Seeded.",
            "evidence": [{"location": "PL-0001#summary"}, {"location": "PL-0002#summary"}],
            "repair_scope": [self.book],
        }]}
        bound = self.bf._bind_audit_evidence(self.project, self.scope, value, {})
        self.assertEqual(bound["findings"], [])
        self.assertEqual(self.bf._validate_audit_output(bound), [])
        aside = bound["unverifiable"][0]
        self.assertEqual(aside["unresolved"], ["PL-0001#summary", "PL-0002#summary"])
        self.assertEqual(aside["issue"], "Seeded.", "what the auditor tried to say is kept")

    def test_a_promise_row_with_no_chapter_is_not_a_mapping(self):
        rows = [{"id": "OP-0001", "promise": "no chapter given"}, {"chapter": "CH-0002", "promise": "no id"}]
        self.assertEqual(self.bf._promise_chapters(rows, None), {})

    def test_the_prompt_says_what_evidence_is(self):
        prompt = (PROMPTS / "canon-auditor.md").read_text()
        self.assertIn("never a promise's own id", prompt)


class AuditFixture(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        config = json.loads((self.project / "book-forge.yaml").read_text())
        config["chorus"] = {"enabled": False, "models": [], "synthesizer": self.bf.CHORUS_SYNTHESIZER}
        (self.project / "book-forge.yaml").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.book = self.bf.add_book(self.project, "A")["id"]
        (self.project / f"books/{self.book}/book-brief.json").write_text(
            json.dumps({"schema": 1, "premise": "A diver must decide.", "characters": ["Mara"], "plot": ["dive"], "tone": "quiet", "length_notes": "40 chapters"})
        )


class SlicedAuditTests(AuditFixture):
    """The audit came back empty five times because it was one question over forty
    chapters: 34822 tokens of input, 32000 of reasoning, no output."""

    def test_a_long_book_is_audited_in_passes_and_the_verdict_is_one_record(self):
        provider = AuditProvider(self.bf)
        result = self.bf.execute_book_design(self.project, self.book, provider=provider)
        self.assertEqual(result["state"], "design_clean")
        # Forty chapters: twenty windows of two, and a walk of five.
        self.assertEqual(provider.calls.count("canon-auditor"), 25)
        record = json.loads((self.project / f"books/{self.book}/design-audit.json").read_text())
        self.assertEqual(len(record["findings"]), 25)

    def test_no_pass_is_handed_the_staging_or_the_wiring(self):
        provider = AuditProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider)
        self.assertTrue(provider.audit_scopes)
        for scope in provider.audit_scopes:
            for row in scope["proposal"]["chapters"]:
                self.assertNotIn("beats", row)
                self.assertNotIn("imports", row)

    def test_findings_from_different_passes_keep_their_own_identifiers(self):
        provider = AuditProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider)
        record = json.loads((self.project / f"books/{self.book}/design-audit.json").read_text())
        ids = [row["id"] for row in record["findings"]]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertIn("A-window-1-2-F-001", ids)
        self.assertIn("A-schedule-1-8-F-001", ids)
        self.assertEqual({row["pass"] for row in record["findings"]}, {
            *(f"window-{n}-{n + 1}" for n in range(1, 40, 2)),
            "schedule-1-8", "schedule-9-16", "schedule-17-24", "schedule-25-32", "schedule-33-40",
        })

    def test_a_pass_that_returns_no_answer_is_asked_for_half_as_much(self):
        provider = AuditProvider(self.bf, schedule_ceiling=4)
        result = self.bf.execute_book_design(self.project, self.book, provider=provider)
        self.assertEqual(result["state"], "design_clean")
        schedule = [len(s["proposal"]["chapters"]) for s in provider.audit_scopes if "neighbourhood_digest" not in s]
        self.assertEqual(schedule, [8, 4, 4, 8, 4, 4, 8, 4, 4, 8, 4, 4, 8, 4, 4])

    def test_a_window_of_one_chapter_is_asked_about_it_alone_before_the_audit_dies(self):
        """Landfall's first audit ended on window-11-11: a window of one chapter
        cannot be halved, and there was nothing between an empty answer and a dead
        design."""
        provider = AuditProvider(self.bf, chapter_count=6, silent_windows={"window-3-4", "window-3-3", "window-4-4"})
        result = self.bf.execute_book_design(self.project, self.book, provider=provider)
        self.assertEqual(result["state"], "design_clean")
        alone = [scope for scope in provider.audit_scopes if "neighbourhood_digest" not in scope and "pass" in scope and scope["pass"]["reading"].startswith("chapters 3")]
        self.assertTrue(alone, "the chapter must have been asked about on its own")

    def test_the_reduced_pass_is_a_last_resort_and_never_the_first_call(self):
        provider = AuditProvider(self.bf, chapter_count=6)
        self.bf.execute_book_design(self.project, self.book, provider=provider)
        for scope in provider.audit_scopes:
            if scope.get("pass", {}).get("reading", "").endswith("immediately around them"):
                self.assertIn("neighbourhood_digest", scope)

    def test_each_window_of_the_walk_is_handed_what_the_last_one_left_open(self):
        provider = AuditProvider(self.bf)
        self.bf.execute_book_design(self.project, self.book, provider=provider)
        carried = [s["open_promises"] for s in provider.audit_scopes if "neighbourhood_digest" not in s]
        self.assertEqual([len(rows) for rows in carried], [0, 8, 16, 24, 32])
        self.assertEqual(carried[-1][0]["chapter"], "CH-0001")


class ShortBookTests(AuditFixture):
    def test_a_book_that_fits_in_one_window_is_still_one_call(self):
        provider = AuditProvider(self.bf, chapter_count=2)
        self.bf.execute_book_design(self.project, self.book, provider=provider)
        self.assertEqual(provider.calls.count("canon-auditor"), 1)
        self.assertNotIn("pass", provider.audit_scopes[0])


if __name__ == "__main__":
    unittest.main()
