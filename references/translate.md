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

### When a review is finished

`translate review` always finds something, because that is what the critic is asked to do. Without a stopping condition the decision of when to stop reading falls to whoever is watching, by feel — CH-0001 of the book this was built for was read back four times and returned 17 findings, then 6, then 12, and nothing could tell three improvements from three inventions.

Every pass now records what it found in a form the next pass can compare: a fingerprint per actionable finding — its kind and the span it quotes, with spacing and case flattened — the hash of the text it read, whether a repair was applied, and the count. It lands in `reviews/<chapter>.state.json`, beside the promoted review rather than inside it, because the repair's outcome is only known after that receipt is written.

`--until-clean` reads a chapter back until one of four things happens, and the report says which: **clean**, no actionable finding left; **no-progress**, a count that did not fall from the pass before; **nothing-applied**, a repair that changed nothing, so the next pass would read the same text and ask the same question; or **cap**, `REVIEW_PASS_CAP` passes. Without the flag it reads once, as before.

Two signals are reported whenever they occur, and stay reported for the whole run once they have. A finding that comes back unchanged after a repair that claimed to apply it means the repair did not land — worse than one that refused, because the refusal was at least recorded. And a verdict of `faithful` beside a finding that changes meaning is a critic contradicting itself in one answer: the findings stand, the verdict is recorded as inconsistent, and the run says so.
