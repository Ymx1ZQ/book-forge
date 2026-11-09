import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from test_translation_review import GOOD_BODY, SOURCE, ScriptedProvider, TranslationReviewFixture, load_module, translation


CH1 = (
    "# The Feast\n\nThe harvest feast was a month and a half away, and Ilse counted the days.\n\n"
    "Behind the barn stood the cones of salt, white in the dusk, and she wore her blue blouse.\n"
)
CH2 = "# The Road\n\nIlse walked to the mill and said nothing to anyone about the salt.\n"
CH3 = (
    "# The Table\n\nThe feast was two months away, Ilse told the cook.\n\n"
    "The pyramids of salt behind the barn had grown in the rain.\n"
)

FACTS = {
    "CH-0001": [
        {"category": "elapsed_time", "subject": "the feast", "fact": "The feast is six weeks away.",
         "quote": "The harvest feast was a month and a half away"},
        {"category": "object_name", "subject": "the salt heaps", "fact": "The heaps are called cones.",
         "quote": "the cones of salt"},
        {"category": "clothing", "subject": "Ilse's top", "fact": "A blue blouse.", "quote": "she wore her blue blouse"},
        {"category": "elapsed_time", "subject": "invented", "fact": "Not in the chapter.", "quote": "a sentence the chapter never contains"},
    ],
    "CH-0002": [],
    "CH-0003": [
        {"category": "elapsed_time", "subject": "the feast", "fact": "The feast is two months away.",
         "quote": "The feast was two months away"},
        {"category": "object_name", "subject": "the salt heaps", "fact": "The heaps are called pyramids.",
         "quote": "The pyramids of salt behind the barn"},
    ],
}
CONTRADICTIONS = {
    "CH-0003": [
        {"earlier_chapter": "CH-0001", "earlier_quote": "The harvest feast was a month and a half away",
         "later_quote": "The feast was two months away", "category": "elapsed_time",
         "reason": "The feast is a month and a half away, then two months away, with no time between."},
        {"earlier_chapter": "CH-0001", "earlier_quote": "the cones of salt",
         "later_quote": "The pyramids of salt behind the barn", "category": "object_name",
         "reason": "The same heaps are cones in one chapter and pyramids in the other."},
        {"earlier_chapter": "CH-0001", "earlier_quote": "words that appear nowhere",
         "later_quote": "The feast was two months away", "category": "elapsed_time", "reason": "Invented quote."},
    ],
}


class LedgerProvider:
    """Stands in for the extractor and the checker; answers per role and chapter."""

    def __init__(self, facts=None, contradictions=None):
        self.facts = FACTS if facts is None else facts
        self.contradictions = CONTRADICTIONS if contradictions is None else contradictions
        self.calls = []
        self.checker_task = None

    def __call__(self, role, envelope, attempt_dir):
        task = envelope["payload"]["task"]
        self.calls.append((role, task["chapter"]))
        if role == "continuity-extractor":
            answer = {"facts": self.facts.get(task["chapter"], [])}
        elif role == "continuity-checker":
            self.checker_task = task
            answer = {"contradictions": self.contradictions.get(task["chapter"], [])}
        else:
            raise AssertionError(f"unexpected role {role}")
        return {
            "text": json.dumps(answer), "provider": "openrouter", "model": envelope["payload"]["model"],
            "variant": envelope["payload"]["variant"], "session_id": f"ses-{len(self.calls)}",
            "tokens": {"input": envelope["estimated_input_tokens"], "output": 100},
            "cost": 0.0, "latency_ms": 10, "finish": "stop",
        }

    def count(self, role):
        return sum(1 for name, _ in self.calls if name == role)


def make_book(bf, project, chapters):
    book = bf.add_book(project, "Book")["id"]
    manuscript = project / "books" / book / "manuscript" / "chapters"
    for chapter, text in chapters.items():
        (manuscript / f"{chapter}.md").write_text(text, encoding="utf-8")
    state = project / "books" / book / "state.yaml"
    bf._write_json(state, {"schema": 1, "closed_chapters": sorted(chapters)})
    return book


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.bf = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "world"
        self.bf.init_project(self.project, "World", chorus_models=[])
        self.book = make_book(self.bf, self.project, {"CH-0001": CH1, "CH-0002": CH2, "CH-0003": CH3})

    def ledger(self, provider):
        return self.bf.continuity_ledger(self.project, self.book, provider=provider)

    def test_the_two_intervals_and_the_two_names_become_flags_carrying_both_quotes(self):
        result = self.ledger(LedgerProvider())
        self.assertEqual(result["extracted"], ["CH-0001", "CH-0002", "CH-0003"])
        flags = self.bf.continuity_flags(self.project, self.book)
        self.assertEqual(len(flags), 2, "the contradiction whose quote is not in the chapter is set aside")
        interval = next(flag for flag in flags if flag["category"] == "elapsed_time")
        self.assertEqual((interval["earlier_chapter"], interval["chapter"], interval["state"]), ("CH-0001", "CH-0003", "open"))
        quotes = {row["chapter"]: row["quote"] for row in interval["quotes"]}
        self.assertEqual(quotes["CH-0001"], "The harvest feast was a month and a half away")
        self.assertEqual(quotes["CH-0003"], "The feast was two months away")
        self.assertIn("two months", interval["reason"])
        names = next(flag for flag in flags if flag["category"] == "object_name")
        self.assertEqual({row["quote"] for row in names["quotes"]}, {"the cones of salt", "The pyramids of salt behind the barn"})

    def test_a_fact_whose_quote_is_not_in_the_chapter_is_not_stored(self):
        self.ledger(LedgerProvider())
        stored = json.loads((self.project / "books" / self.book / "work/continuity/facts/CH-0001.json").read_text())
        self.assertEqual(len(stored["facts"]), 3)
        self.assertEqual(stored["source_hash"], self.bf._sha256_bytes((self.project / "books" / self.book / "manuscript/chapters/CH-0001.md").read_bytes()))

    def test_the_checker_is_given_the_earlier_chapters_facts(self):
        provider = LedgerProvider()
        self.ledger(provider)
        self.assertEqual(set(provider.checker_task["earlier_facts"]), {"CH-0001"})
        self.assertEqual(provider.checker_task["chapter"], "CH-0003")

    def test_an_unchanged_chapter_is_not_read_again(self):
        provider = LedgerProvider()
        self.ledger(provider)
        first = len(provider.calls)
        again = self.ledger(provider)
        self.assertEqual(len(provider.calls), first, "nothing changed, nothing is asked")
        self.assertEqual(again["reused"], ["CH-0001", "CH-0002", "CH-0003"])
        self.assertEqual(again["new_flags"], [])
        self.assertEqual(len(self.bf.continuity_flags(self.project, self.book)), 2)

    def test_only_the_edited_chapter_is_extracted_again(self):
        provider = LedgerProvider()
        self.ledger(provider)
        path = self.project / "books" / self.book / "manuscript/chapters/CH-0003.md"
        path.write_text(CH3.replace("two months", "six weeks"), encoding="utf-8")
        provider.facts = {**FACTS, "CH-0003": []}
        result = self.ledger(provider)
        self.assertEqual(result["extracted"], ["CH-0003"])
        self.assertEqual(self.bf.continuity_flags(self.project, self.book), [], "the fixed chapter's open flags go")

    def test_a_resolved_flag_stays_resolved_when_the_chapters_are_compared_again(self):
        provider = LedgerProvider()
        self.ledger(provider)
        flag = self.bf.continuity_flags(self.project, self.book)[0]
        self.bf.resolve_continuity_flag(self.project, flag["id"], "Six weeks pass between the chapters.")
        (self.project / "books" / self.book / "manuscript/chapters/CH-0002.md").write_text(CH2 + "\nIt rained.\n", encoding="utf-8")
        self.ledger(provider)
        open_ids = {row["id"] for row in self.bf.continuity_flags(self.project, self.book)}
        self.assertNotIn(flag["id"], open_ids)
        everything = self.bf.continuity_flags(self.project, self.book, include_resolved=True)
        self.assertEqual(len(everything), 2)
        self.assertEqual(next(row for row in everything if row["id"] == flag["id"])["resolved"]["reason"], "Six weeks pass between the chapters.")

    def test_resolve_needs_a_reason_and_a_known_flag(self):
        self.ledger(LedgerProvider())
        flag = self.bf.continuity_flags(self.project, self.book)[0]
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.resolve_continuity_flag(self.project, flag["id"], "  ")
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.resolve_continuity_flag(self.project, "CF-NOPE-0001", "x")

    def test_status_shows_the_open_flags(self):
        self.ledger(LedgerProvider())
        shown = self.bf.status_project(self.project, book_id=self.book)["continuity_flags_open"]
        self.assertEqual(len(shown), 2)
        self.assertEqual({row["chapter"] for row in shown}, {"CH-0003"})
        self.bf.resolve_continuity_flag(self.project, shown[0]["id"], "fixed")
        self.bf.resolve_continuity_flag(self.project, shown[1]["id"], "fixed")
        self.assertNotIn("continuity_flags_open", self.bf.status_project(self.project, book_id=self.book))

    def test_a_chapter_that_cannot_be_read_is_reported_and_the_rest_go_on(self):
        class Broken(LedgerProvider):
            def __call__(self, role, envelope, attempt_dir):
                if role == "continuity-extractor" and envelope["payload"]["task"]["chapter"] == "CH-0002":
                    return {**super().__call__(role, envelope, attempt_dir), "text": "no json here"}
                return super().__call__(role, envelope, attempt_dir)

        result = self.ledger(Broken())
        self.assertEqual([row["chapter"] for row in result["unread"]], ["CH-0002"])
        self.assertEqual(len(self.bf.continuity_flags(self.project, self.book)), 2)

    def test_a_book_with_no_closed_chapter_is_refused(self):
        empty = self.bf.add_book(self.project, "Empty")["id"]
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.continuity_ledger(self.project, empty, provider=LedgerProvider())

    def test_cli_lists_and_resolves(self):
        self.ledger(LedgerProvider())
        flag = self.bf.continuity_flags(self.project, self.book)[0]["id"]
        parsed = self.bf.build_parser().parse_args(["--project", str(self.project), "continuity", "resolve", flag, "--reason", "fixed"])
        self.assertEqual((parsed.continuity_command, parsed.flag_id, parsed.reason), ("resolve", flag, "fixed"))
        parsed = self.bf.build_parser().parse_args(["--project", str(self.project), "translate", "run", "--accept-flags", self.book, "it"])
        self.assertTrue(parsed.accept_flags)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.bf.main(["--project", str(self.project), "continuity", "resolve", flag, "--reason", "fixed"]), 0)
        self.assertEqual(len(self.bf.continuity_flags(self.project, self.book)), 1)

    def test_the_prompts_and_agents_exist_for_both_roles(self):
        prompts = Path(self.bf.__file__).resolve().parents[1] / "assets" / "prompts"
        for role in ("continuity-extractor", "continuity-checker"):
            self.assertIn(role, self.bf.ROLE_SPECS)
            self.assertIn(role, self.bf.ROLE_BUDGETS)
            self.assertTrue((prompts / f"{role}.md").is_file())
            self.assertTrue((self.project / ".opencode" / "agents" / f"{role}.md").is_file())


class TranslationGateTests(TranslationReviewFixture):
    def setUp(self):
        super().setUp()
        manuscript = self.project / f"books/{self.book}/manuscript/chapters"
        (manuscript / "CH-0002.md").write_text(SOURCE.replace("Dawn Barge", "Low Tide"), encoding="utf-8")
        (self.project / f"books/{self.book}/chapters/CH-0002.json").write_text(json.dumps({**self.contract, "id": "CH-0002", "order": 2}))

    def flag(self, chapter, earlier, state="open"):
        path = self.project / f"books/{self.book}/work/continuity/flags.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.bf._write_json(path, {"schema": 1, "book": self.book, "checked": {}, "flags": [{
            "id": f"CF-{self.book}-0001", "state": state, "chapter": chapter, "earlier_chapter": earlier,
            "category": "elapsed_time", "reason": "two intervals for one feast", "signature": "s",
            "quotes": [{"chapter": earlier, "quote": "a month and a half"}, {"chapter": chapter, "quote": "two months"}],
        }]})

    def test_a_chapter_with_an_open_flag_is_refused_and_the_refusal_names_the_way_out(self):
        self.flag("CH-0001", "CH-0001")
        provider = ScriptedProvider([translation(GOOD_BODY)])
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.translate(provider)
        message = str(caught.exception)
        self.assertIn(f"CF-{self.book}-0001", message)
        self.assertIn("continuity resolve", message)
        self.assertIn("--accept-flags", message)
        self.assertEqual(provider.calls, [], "nothing is paid for")
        self.assertFalse((self.locale_root / "chapters" / "CH-0001.md").exists())

    def test_a_flag_on_a_later_chapter_does_not_hold_an_earlier_one_but_holds_the_later(self):
        self.flag("CH-0002", "CH-0001")
        provider = ScriptedProvider([translation(GOOD_BODY), translation(GOOD_BODY)])
        self.translate(provider)
        self.assertTrue((self.locale_root / "chapters" / "CH-0001.md").is_file())
        with self.assertRaises(self.bf.BookForgeError) as caught:
            self.translate(provider)
        self.assertIn("CH-0002 is held back", str(caught.exception))
        self.assertFalse((self.locale_root / "chapters" / "CH-0002.md").exists())

    def test_run_stops_at_the_held_chapter_instead_of_setting_it_aside(self):
        self.flag("CH-0002", "CH-0001")
        provider = ScriptedProvider([translation(GOOD_BODY), translation(GOOD_BODY)])
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.translate_next(self.project, self.book, "it", provider=provider, run_all=True)
        self.assertTrue((self.locale_root / "chapters" / "CH-0001.md").is_file())

    def test_accept_flags_lets_the_chapter_through(self):
        self.flag("CH-0001", "CH-0001")
        provider = ScriptedProvider([translation(GOOD_BODY)])
        self.bf.translate_next(self.project, self.book, "it", provider=provider, run_all=False, accept_flags=True)
        self.assertTrue((self.locale_root / "chapters" / "CH-0001.md").is_file())

    def test_a_resolved_flag_holds_nothing(self):
        self.flag("CH-0001", "CH-0001", state="resolved")
        provider = ScriptedProvider([translation(GOOD_BODY)])
        self.translate(provider)
        self.assertTrue((self.locale_root / "chapters" / "CH-0001.md").is_file())

    def test_the_lock_wrapper_carries_the_flag(self):
        self.flag("CH-0001", "CH-0001")
        with self.assertRaises(self.bf.BookForgeError):
            self.bf.run_translate_locked(self.project, self.book, "it", run_all=False)


if __name__ == "__main__":
    unittest.main()
