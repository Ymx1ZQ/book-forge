---
name: book-forge
description: Design, write, review, resume, translate, audit, and publish token-efficient fiction projects built around an open-ended shared universe. Use for initializing a universe, adding or relating books, developing canon and characters, producing or revising chapters with OpenCode subagents, recovering interrupted runs, creating opt-in context-aware translations, or exporting EPUB and PDF editions.
---

# Book Forge

## Route protocol

Resolve the directory containing this loaded `SKILL.md` as `SKILL_ROOT`. The
only state-writing executable is `SKILL_ROOT/scripts/book_forge.py`. Invoke it
as `python3 SKILL_ROOT/scripts/book_forge.py --project PROJECT ...`; place the
global `--project` option before the selector.

Choose exactly one route for the current command and read only that one-level
reference before acting:

| Selector | Reference |
|---|---|
| `init` | `references/init.md` |
| `migrate`, `continuity`, `add-book`, `relate`, `collection` | `references/catalog.md` |
| `design` | `references/design.md` |
| `brief` | `references/brief.md` |
| `run` | `references/run.md` |
| `pause`, `resume`, `status`, `reset` | `references/lifecycle.md` |
| `audit` | `references/audit.md` |
| `translate` | `references/translate.md` |
| `chorus` | `references/chorus.md` |
| `export` | `references/export.md` |

For a multi-command request, finish and checkpoint one command before loading
the next route. Do not read the development plan, unrelated references, whole
manuscripts, or provider logs unless the active route explicitly requires it.
Return the helper's result in concise user-facing language. On an error, stop;
never bypass a block by editing canonical files.

## Product contract

- Make the universe the root object and allow it to contain any number of books.
- Model continuities separately from optional series, sagas, cycles, and reading orders.
- Relate books explicitly without forcing standalone, trilogy, or fixed-length modes.
- Pin primary OpenCode roles to `openrouter/deepseek/deepseek-v4-flash-0731` on a reasoning
  effort that model declares: `low`, `high`, or `max`; chorus advisors use the configured ensemble
  (`flash`, `pro`, `glm-5.3-flash`, `qwen3.8-max`, `kimi-k3`, `grok-4.6`, `gemini-3.7-flash`, `luna`) and the
  synthesizer uses `openrouter/deepseek/deepseek-v4-pro-0813` on `max`; `init` asks which models to use and persists the choice in `book-forge.yaml:chorus.models`.
- Minimize tokens through deterministic context packets, explicit imports, and bounded concurrency.
- Let one orchestrator decide work while a deterministic control plane performs every state and canonical write.
- Persist task receipts, hashes, leases, and staged outputs so pause and resume survive process loss.
- Write source manuscripts in English by default.
- Create context-aware translations only when the user explicitly requests a target language.
- Generate EPUB and PDF editions deterministically without model calls.
- Use explicit IDs and dependency indexes for all correctness; no graph retrieval.

## Public command surface

Preserve this compact route set while implementing the plan:

```text
book-forge init [--title <title>] [--source-language <bcp47>] [--chorus-models <csv>]  # asks interactively when omitted and TTY
book-forge runtime sync
book-forge chorus <status|synthesize|apply> [--book <id>]
book-forge migrate <check|dry-run|apply|rollback>
book-forge continuity add <name> [--kind <primary|alternate>] [--fork-from <id>] [--import <block>...]
book-forge add-book <title> [--continuity <id>]
book-forge relate <book...> --type <type> [--import <block>...] [--obligation <text>...]
book-forge collection <add|remove|order> ...
book-forge design <universe|book> [--book <id>] [--brief '<json>'] [--skip-brief] [--no-chorus] [--no-post-chorus] [--chorus-models <csv> [--with-chorus-context]]  # runs pre-chorus + post-chorus (default-on) with per-chapter verification
book-forge brief <universe|book> [--book <id>] [--skip-brief]
book-forge run [--book <id>] [--task <id>] [--next]
book-forge pause [--run <id>] [--emergency]
book-forge resume [--run <id>] [--resolve-unknown <task>:<retry|abandon>] [--resolve-blocked <task>:<retry>]
book-forge status [--book <id>|--run <id>|--locale <tag>] [--repair-view]
book-forge artifacts backfill [--book <id>] [--locale <tag>]
book-forge reset --book <id> [--scope <prose|design>] --yes
book-forge audit [--book <id>|--relation <id>|--continuity <id>] [--max-jobs <n>]
book-forge translate <add|next|run|status> <book> <locale>
book-forge export <book> --lang <tag> --format <epub|pdf|all>
```

## Operational invariants

- Let subagents consume task capsules derived from the shared plan; never let them edit it.
- Permit at most two concurrent subagents and only for disjoint declared outputs.
- Treat OpenCode session IDs as an optimization, never as durable completion evidence.
- Suppress redispatch when a matching execution receipt and validated staged output exist; resume promotion instead.
- Declare a task succeeded and current only when its matching promotion receipt exists.
- Treat accepted calls with unknowable outcomes as blocked; never retry them automatically.
- Hard-fail an oversized context packet with a contribution report; never truncate silently.
- Preserve staged and orphaned output until promotion or explicit safe cleanup.
- Keep source prose authoritative and mark derived translations or publications stale after relevant changes.
- Require zero open blocking findings, current state, and a valid receipt before closing a chapter.
