---
name: book-forge
description: Design, write, review, resume, translate, audit, and publish token-efficient fiction projects built around an open-ended shared universe. Use for initializing a universe, adding or relating books, developing canon and characters, producing or revising chapters with OpenCode subagents, recovering interrupted runs, creating opt-in context-aware translations, or exporting EPUB and PDF editions.
---

# Book Forge

## Product contract

- Make the universe the root object and allow it to contain any number of books.
- Model continuities separately from optional series, sagas, cycles, and reading orders.
- Relate books explicitly without forcing standalone, trilogy, or fixed-length modes.
- Pin every OpenCode role to `openrouter/deepseek/deepseek-v4-flash-0731`.
- Minimize tokens through deterministic context packets, explicit imports, and bounded concurrency.
- Let one orchestrator decide work while a deterministic control plane performs every state and canonical write.
- Persist task receipts, hashes, leases, and staged outputs so pause and resume survive process loss.
- Write source manuscripts in English by default.
- Create context-aware translations only when the user explicitly requests a target language.
- Generate EPUB and PDF editions deterministically without model calls.
- Keep Graphify outside the correctness path; use explicit IDs and dependency indexes instead.

## Public command surface

Preserve this compact route set while implementing the plan:

```text
book-forge init [--source-language <bcp47>]
book-forge migrate <check|dry-run|apply|rollback>
book-forge continuity <add|relate> ...
book-forge add-book [--continuity <id>]
book-forge relate <book...> --type <type> [--import <block>...]
book-forge collection <add|remove|order> ...
book-forge design <universe|book> [--book <id>]
book-forge run [--book <id>] [--task <id>] [--next]
book-forge pause [--run <id>] [--emergency]
book-forge resume [--run <id>] [--resolve-unknown <task>:<retry|abandon>]
book-forge status [--book <id>|--run <id>|--locale <tag>] [--repair-view]
book-forge audit [--book <id>|--relation <id>|--continuity <id>] [--max-jobs <n>]
book-forge translate <add|next|run|status> <book> <locale>
book-forge export <book> --lang <tag> --format <epub|pdf|all>
```

Make `run` compose task-specific roles rather than duplicate their instructions.
Keep detailed workflows in one-level `references/` files and load only the route
needed for the current command. Put deterministic state, context, validation,
and publication operations in bundled helpers under `scripts/`.

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
