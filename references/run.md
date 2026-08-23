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
