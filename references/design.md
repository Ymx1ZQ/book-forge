# Design universe or book

Use this route only for `design`.

- `design universe` makes one high-reasoning designer call followed by one
  independent canon-auditor call. It creates stable world rules, chronology,
  places, factions, characters, themes, and style blocks.
- `design book --book BOOK-ID` makes the same two-call pattern for premise,
  causal arc, entry/exit state, chapter contracts, relation imports, and exact
  obligation targets.
- Run the helper once. It constructs bounded context, invokes the pinned
  OpenCode agents, validates their JSON contracts, and promotes outputs.
- If validation or the independent audit blocks, report the evidence and stop.
  Never fabricate a clean audit or directly repair canonical files.

The model, variants, maximum steps, and provider are project-pinned. Do not
forward user-supplied model or variant overrides.
