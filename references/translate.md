# Translate a book by locale

Use this route only when the user explicitly requests a target locale.

1. `translate add BOOK TAG` creates the isolated locale workspace and makes no
   model call. Never create it implicitly.
2. `translate next BOOK TAG` translates one next chapter; `translate run` walks
   the current source chapters serially.
3. `translate status` is zero-model and reports completion/currentness.

Each chapter receives source prose, its contract, explicit canon, prior
translated boundary, locale style, glossary, and localized metadata. The normal
path is one low-reasoning translator call; validation permits at most one repair.
Source prose remains authoritative. If source, canon, glossary, style, metadata,
or a prior boundary changes, preserve existing translated prose and report the
minimal stale suffix instead of silently regenerating it.

## Reading the translation back

A translation used to be one call that nobody read, while the prose had a cold reader, a technical editor, four style reviewers and a reviser. `translation.review` in `book-forge.yaml` turns the read-back on, and it is on unless the project sets it to `false`.

Half of it costs nothing. The glossary is machine-readable, so a term the source uses whose agreed rendering never reaches the translation is an exact finding — no model is asked. `translations/<locale>/checks.yaml` carries what the locale can state as a rule: `forbidden` is a list of `{pattern, reason}`, checked against the delivered translation before it is accepted, so a form the locale bans sends the chapter back for repair the way a wrong number already does. An absent or empty file is legal; the locale is then checked by the glossary alone.

The other half is the `translation-critic` role: source and translation side by side, plus the style and the glossary, returning findings that each cite the source text, the translated text and the rule broken. A finding citing nothing is set aside and recorded — it names nothing a repair could substitute. Findings at `warning` or `blocking` drive one repair call to the translator, and the repair is held to the same validation the translation was: if it does not pass, the translation that did is kept.

**The critic never runs on the translator's model.** A model rereading its own rendering shares the blind spots that produced it and approves them. `roles.translation-critic` naming the translator's model is refused when the config is read. Left unset, it resolves to the catalogue's judge-grade model, and to another model if the translator already holds that one.

`translate review <book> <locale>` runs the same pass over a translation already on disk, for chapters translated before any of this existed. `--chapter CH-0001` reads back one. It reports, per chapter, the verdict, how many findings by kind, how many were set aside, and whether a repair was applied.

Nothing here stops a run. A critic that cannot be reached, an answer that will not parse, a repair that comes back worse: each is recorded beside the chapter and the run goes on.

### How often the cheap checks are right

The deterministic checks cost nothing and are sometimes wrong: a string rule cannot tell one sense of a word from another, and a glossary row that fixes `trestle` as a jetty has nothing to say about a trestle table. So the findings go to the critic labelled as the machine's, and its answer carries a verdict on each — `holds` when the translation really is missing what the check says, `mistaken` when the check is wrong.

A finding called mistaken is dropped before the repair, so a false positive no longer costs a repair call or risks a needless edit. Silence is not a refutation: a finding the critic does not rule on holds.

`translate review` reports the counts per chapter and across the pass — raised, held, mistaken — and the review file beside each chapter records them with the reason given for each dismissal. When four or more findings are raised and fewer than half hold, the run says so by name, because a check that is mostly wrong is a defect in the check rather than in the book.
