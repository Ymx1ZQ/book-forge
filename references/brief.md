# 00-BRIEF gate (default ON)

Use this route before any `design` call. The designer must not invent a story
the author never agreed to.

## Gate

- Default ON: every `design universe` and `design book` requires a brief.
- Bypass only via `--skip-brief` flag or when the brief answer contains "usa default" (case-insensitive).
- Without bypass and without a brief, `design` fails closed with `brief.missing`.

## 7 questions (00-BRIEF)

Answer all 7; each expects 1–3 sentences or a short list. The helper validates
that each answer is non-empty.

1. **length/format** — Target length and format (e.g. 80k novel, 12-chapter, standalone vs series).
2. **genre/world** — Genre and world premise (what kind of world, what rules).
3. **protagonists** — Who are the protagonists (names/traits/arcs seed).
4. **premise/conflict/ending** — Premise, central conflict, and intended ending or question.
5. **themes** — Core themes and what the story is really about.
6. **style/POV/register** — Style notes, POV, register (e.g. past tense, third-limited, lyrical).
7. **constraints/audience** — Constraints, audience, what to avoid or lean into.

## Storage

- `universe/design-brief.json` for universe scope (written by `init` or `brief` command, or via `design --brief`).
- `books/<book>/book-brief.json` for book scope.
- Schema `{schema:1, answers:{...}, scope:"universe"|"book", bypass?:bool}`.

## Helper

`scripts/brief.py` exports `BRIEF_QUESTIONS`, `is_brief_complete`, `should_gate`, and `validate_brief`.
The control plane calls `should_gate(project, scope, skip_flag)` before constructing the designer envelope.
