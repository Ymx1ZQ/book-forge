# Write and close chapters

Use this route only for `run`.

The helper selects the next unfinished chapter from stable chapter contracts.
For an ordinary chapter, the first unit drafts once and the next unit runs two
independent reviews concurrently plus one reviser. A pivotal chapter runs two
blind drafts, one judge, the two reviews, and one reviser in a single bounded
workflow.

- With an explicit `--task`, execute only that task.
- With `--next`, execute one workflow unit and return its state.
- When the user asks to finish one chapter, invoke `run --book BOOK-ID` until
  exactly one new chapter closes, checking the result after each unit.
- When the user asks to continue the book, repeat serially until the requested
  boundary, a block, pause, or no work remains.
- Never retry an `outcome_unknown` call. Never exceed one validated repair call
  or two concurrent review workers.

Do not load a whole manuscript. Context packets contain the chapter contract, explicit canon imports, current state, and only the required previous boundary. The cold-reader receives only the synthetic previous-chapters summary (reader_state compact + previous boundaries synopsis), not the full canon — exactly what a fresh linear reader knows.

## Driving a book to completion

`advance --book <id>` carries a book from where it stands to where it is asked to stop: the design if it is missing, then every chapter, then the translations named by `--locale`, then the editions. `--until` stops it earlier at `design`, `chapters` or `translate`.

Every stage recovers before it dispatches, so the three things that used to need a person at the keyboard no longer do: an attempt whose lease expired and which the provider never accepted is orphaned, a task blocked by a truncated or unparseable answer returns to `pending`, and a run blocked by nothing but those starts again. Each task gets three automatic retries.

It halts on exactly two things, and both are reported by name:

- **An unknown outcome.** The provider accepted the call and we do not know whether it finished, so a retry may pay for it twice. That is a judgement about money: resolve it with `resume --resolve-unknown TASK:retry|abandon`.
- **An exhausted retry budget.** A task failed the same way three times running. Read its last failure before spending a fourth call.

Report the receipt it returns — stages completed, chapter steps taken, editions written — rather than summarizing it.

