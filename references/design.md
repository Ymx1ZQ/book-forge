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

## Author brief is mandatory for books

`design book` fails closed without `books/<book>/book-brief.json`. Create it
with `--brief '<json>'` or by editing the file directly. The brief must state
premise, characters, plot, tone, and length notes — the designer must not
invent a story the author never agreed to. The brief fields:

```json
{"schema": 1, "premise": "...", "characters": ["..."], "plot": ["..."], "tone": "...", "length_notes": "..."}
```

## Full canon context

The book designer's envelope carries the whole canon — kernel laws, places,
factions, characters, style summaries — plus the authored
`universe/worldbuilding.md` when present, not just the kernel. The envelope
input budget still bounds the context; overflow hard-fails rather than
truncating.

## Line wrapping

Generated artifacts never soft-wrap prose: one sentence per line, no width
limit, never a break mid-sentence. The helper writes JSON with `indent=2`
(structural) and markdown as single long lines. `status` reports
`wrapped_lines` if a generated markdown artifact contains a mid-sentence
break — fix at the source, never auto-rewrap.

The model, variants, maximum steps, and provider are project-pinned. Do not
forward user-supplied model or variant overrides.
