# Design universe or book

Use this route only for `design`.

- `design universe` makes one high-reasoning designer call followed by one
  independent canon-auditor call. It creates stable world rules, chronology,
  places, factions, characters, themes, and style blocks.
- `design book --book BOOK-ID` makes the same two-call pattern for premise,
  causal arc, entry/exit state, chapter contracts, relation imports, and exact
  obligation targets.
- `design sync-outline --book BOOK-ID` copies each contract's `beats`, `want`, `obstacle`, `turn`, `chapter_kind`, `exempt_reason`, `plants` and `obligations` into the matching `outline.yaml` row, keeps the file's JSON formatting, creates no task or receipt, and reports how many fields changed.
- `design reshape --book BOOK-ID --plan <file>` changes the chapter count of a designed book without redesigning it. The plan is `{"chapters": [...]}`, in the new reading order. An entry is `{"from": "CH-0023"}` to keep a chapter (optionally with `set` fields to change in its contract and `absorbs: [ids]` to take over what dropped chapters carried), or `{"new": {...}}` for a chapter inserted. Ids and `order` are renumbered, `outline.yaml`, the contracts, `design.md` and `withheld[].revealed_in` follow, and contract files past the new end are removed. A chapter that is closed or already drafted keeps its id and position and takes no `set`: the plan is refused, naming it. A withheld reveal that points at a dropped chapter nobody absorbs is refused. `reader-state.md` is left as it is. The design audit reopens, so run `design book` afterwards. When a book alternates point of view, insert chapters in pairs.
- Run the helper once. It constructs bounded context, invokes the pinned
  OpenCode agents, validates their JSON contracts, and promotes outputs.
- If validation or the independent audit blocks, report the evidence and stop.
  Never fabricate a clean audit or directly repair canonical files.

## Chapter engagement fields

Every chapter row of a new book carries `want` (what the POV character wants in the chapter), `obstacle` (what stands in the way) and `turn` (`{"kind":"decision|loss|danger|question|reveal","text":"..."}`, how the chapter ends); a `prologue`, `interlude` or `epilogue` may set `chapter_kind` and a non-empty `exempt_reason` instead, and a `chapter_kind` without a reason is refused. A contract without them stops `run` until it is repaired, naming the chapter and the missing fields.

A beat is one thing that happens on the page, in one or two sentences, with a person as its subject, in plain active prose; what the character wants and what stands in the way live in `want` and `obstacle`, not in the beats, and a chapter whose beats use "want" more than once is refused. A beat longer than 450 characters is refused with `chapter.beat-too-long`, and bookkeeping is still refused by `_beat_shape_problems`, including its 900-character limit. A chapter may carry `new_terms`, an optional list of at most three `{"term":"...","definition":"one plain sentence"}` objects naming the coined words the chapter introduces; a value that is not a list, has more than three entries, or lacks a non-empty `term` and `definition` in an entry is refused with `chapter.new-terms`.

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

## Chorus (default-on, pre + post)

Every `design` runs the chorus ensemble **twice** unless opted out: **pre-design** (before the designer, same full canon + worldbuilding + brief envelope, advisory-only) and **post-design** (after the auditor, on the designer product — kernel/places/factions/characters/themes for universe; premise/arc/chapters per-chapter beats/POV for book — at per-chapter granularity). Post-design blocks on `blocking|warning` (advisory for `note`). Prints the confirmed model list per pass. Override with `--chorus-models <csv>`; skip pre+post with `--no-chorus`, skip only post with `--no-post-chorus`. To make the designer see the latest chorus report, add `--with-chorus-context` (opt-in). For a standalone pass without designing, use `chorus run [universe|book --book ID]` (pre) or `chorus run --post-design` (post on last product).

## Per-chunk generation (<15KB per chunk)

The designer never emits a 41KB monolith. Output is chunked: each chunk JSON
must be <15KB (`DESIGN_CHUNK_MAX_BYTES=15360`). The helper validates `chunk_bytes(chunk) < 15360`
and `split_proposal_into_chunks` groups kernel/eras/events/places/factions/characters
plus tail (themes/style/continuity_material) into per-category chunks. `max_output_tokens`
is 8192–20000 (see `ROLE_BUDGETS` designer 20000 and envelope 8192). On `finish_reason==length`
the helper retries up to 2 times, then marks the attempt `failed_length` (not `outcome_unknown`).
## Brief gate

`design` is gated by 00-BRIEF (7 questions) — default ON. Provide `universe/design-brief.json` or `books/<book>/book-brief.json` with all 7 answers, or pass `--skip-brief` / "usa default" to bypass. See the brief reference.

## Anti-laziness tiered cast/places

The designer must produce a dense, non-lazy canon:

- **Characters tiered**: L1 1–3 protagonists 250–350w each (combined across summary+voice+appearance+past+want+need+flaw+wound+arc+secret joined with space, word-boundary regex as in `validate.py`; must include want/need/flaw/wound/arc/voice/secret), L2 4–7 secondaries 150–200w combined same count, L3 6–12 ricorrenti 60–90w combined, L4 10–20 comparse 1 line (<20w combined). Total named characters >=22 for 80k (scaled linearly with `length_notes`), e.g. 40k→11, 120k→33.
- **Places tiered**: L1 3–5, L2 5–8, L3 6–12, total >=14.
- **Validation**: `scripts/validate.py` asserts each tier count and word range, checks total thresholds, and runs graph connectivity (every character/place must be reachable via `continuity_material` or textual reference; otherwise `graph.disconnected`).
- **Chunking**: Characters are split into 2 sub-chunks (L1+L2 and L3+L4) each <15KB, validated by `split_proposal_into_chunks` and `split_characters_tiered`.

Proposals failing any tier or graph check are blocked (`tier.*`, `graph.disconnected`).

