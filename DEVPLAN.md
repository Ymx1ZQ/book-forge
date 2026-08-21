# Book Forge — Development Plan

## Objective

Build one OpenCode skill that operates an open-ended shared fiction universe
from design through publication. It must produce chapters quickly from bounded
context, preserve accepted work across interruption, manage explicit cross-book
continuity, create only requested context-aware translations, and generate
validated EPUB and PDF editions without model calls.

## Approach

Keep `SKILL.md` as a thin router and load one-level references only for the
active command. Put schemas, indexing, request construction, locking, journals,
receipts, recovery, and publication in deterministic Python helpers bundled with
the skill. Use one orchestrator and isolated OpenCode roles over a shared task
DAG; make repository artifacts, not session memory, authoritative. Prefer stable
IDs and explicit imports over semantic retrieval.

## Definitions

- **Task:** one logical DAG node with fixed inputs, role, output contract, and completion evidence.
- **Attempt:** one execution of a task; repair or continuation creates another attempt.
- **Provider call:** one request accepted by the model provider, including an outcome-unknown request.
- **Execution receipt:** immutable evidence of one attempt and its observed provider outcome.
- **Promotion receipt:** immutable evidence that validated outputs reached canonical paths and a scoped commit.
- **Currentness:** derived comparison between present dependency hashes and historical receipts; receipts are never invalidated or rewritten.

## Binding decisions

- The root object is a universe containing `0..N` books; there is no standalone or trilogy mode.
- A book belongs to one continuity. Shared canon ownership follows continuity, not pairwise book links.
- The universe kernel is inherited by every continuity; all other canon is continuity-scoped unless explicitly imported.
- Collections are optional reading/editorial groupings; membership lives only in `collections.yaml`.
- Books are discovered from their `book.yaml`; `universe.yaml` does not duplicate a manual book list.
- Relations are explicit and typed; obligations and imports are stable addressable blocks.
- Every model role is pinned to `openrouter/deepseek/deepseek-v4-flash-0731` through OpenRouter.
- Routine roles use explicit low or mid reasoning; high is reserved for integration, canon, and judgement.
- `source_language` defaults to `en`, may be selected at init, and becomes immutable after the first source chapter closes.
- Translation workspaces are absent until the user explicitly requests a target locale.
- Graphify is excluded from v1 setup, correctness, retrieval, and audit coverage.
- `.book-forge/plan.json` is the canonical runtime DAG; `DEVPLAN.md` is its orchestrator-rendered shared human view.
- One deterministic control-plane helper is the sole writer of machine state and canonical paths; model roles write attempt-local output only.
- Every public command crosses a transaction-recovery read barrier before reading currentness, building context, dispatching, or publishing.
- Maximum subagent concurrency is two; shared-canon mutation, promotion, and chapter integration remain serial.
- Generated projects contain data and OpenCode configuration, not operational `CLAUDE.md` files or project shell pipelines.
- The system guarantees at-most-once promotion, not exactly-once provider execution.
- A provider call with an unknowable outcome becomes `outcome_unknown` and is never retried automatically.
- EPUB and PDF export is deterministic within a pinned toolchain and consumes no model tokens.

## Acceptance budgets

- Keep installed `SKILL.md` below 300 lines and route references one level deep.
- Count and hash the complete serialized request envelope: role prompt, task capsule, context, tool schema, and output allowance.
- Default ordinary-writer envelope: at most 12,000 estimated input tokens with a model-specific tokenizer and safety margin.
- Successful ordinary chapter path: four provider calls; successful pivotal path: six.
- Automated recovery ceiling: one additional provider call per chapter; otherwise block instead of looping.
- Successful ordinary translation: one provider call; flagged review or repair may raise the chapter ceiling to two.
- Universe or book design slice: two nominal provider calls and at most three including repair.
- Cross-book audit job: one nominal provider call and at most two including repair.
- Audit runs schedule at most eight jobs per wave and block above twenty candidates without a manifest-recorded override.
- Rate-limit waits before provider acceptance do not consume a call or attempt retry budget.
- Record model, variant, complete-envelope hash, provider-reported tokens, latency, attempt outcome, and promotion state.

## Public command selectors

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

Bare `run` aliases `run --next`. With no task selector, it chooses the ready frontier by persisted
priority, dependency depth, book order, chapter order, then stable task ID. A
project permits one active orchestrator run, so an unscoped pause targets it
unambiguously.

## Target repository layout

```text
SKILL.md
agents/openai.yaml
references/
scripts/
assets/
tests/
install.sh
DEVPLAN.md
DEVPLAN-COMPLETED.md       # created when the first milestone closes
```

## Generated universe layout

```text
book-forge.yaml
opencode.json
DEVPLAN.md                 # derived active work view, orchestrator-only
DEVPLAN-COMPLETED.md
universe/
  universe.yaml
  kernel.md
  continuities.yaml
  collections.yaml
  relations.yaml
  timeline/
  canon/
books/<book-id>/
  book.yaml
  design.md
  outline.yaml
  state.yaml
  continuity.yaml
  reader-state.md
  manuscript/chapters/
  translations/<bcp47>/   # absent until explicitly requested
.book-forge/
  plan.json                # canonical runtime DAG
  state.json
  artifact-deps.json
  currentness.json
  index.json
  revdeps.json
  appearances.json
  control.json
  provider.json
  transactions/
  runs/
dist/<book-id>/<bcp47>/
```

## Risks

- Same-model roles share biases; isolate sessions and reserve blind judgement for high-leverage gates.
- A provider may finish during a local crash without exposing a retrievable result; block the ambiguous attempt rather than silently paying twice.
- Multi-file publication cannot be intrinsically atomic; use a fenced journal and reconcile every installed path.
- Canon growth can inflate requests; address blocks directly and hard-fail with ranked size contributors.
- Undeclared shared consequences can evade deterministic indexing; require writer disclosure plus independent technical extraction, while acknowledging non-mathematical completeness.
- Translation changes can propagate through boundary state; walk dependencies until boundary hashes converge.
- Publication reproducibility depends on tools and fonts; pin and record the complete toolchain.

## Phase A — Installable universe foundation

## Phase B — Durable orchestration and bounded context

## Phase C — Universe and book design

## Phase D — Fast chapter production

## Phase E — Opt-in translation

## Phase F — Cross-book assurance and publication

## Phase G — Measured reliability

### M24: Prove the recovery and transaction matrix hermetically

**Depends on:** M7, M8, M18, M20, M21, M22

**Why:** Recovery claims require deterministic fault injection independent from provider credentials or timing.

**Approach:** Build fake provider, clock, filesystem, and Git adapters. Enumerate crash points for dispatch intent, result materialization, each promotion journal state, commit, receipt, plan render, rate-limit wait, translation propagation, and publication; assert exact states, hashes, and permitted next actions.

**Tasks:**
- [ ] Inject crash-before-send, outcome-unknown, late-result, and malformed-result cases
- [ ] Inject duplicate resume, expired lease, stale worker, conflict, and failed sync
- [ ] Inject every per-path promotion and derived-state write boundary
- [ ] Verify cleanup refusal and preservation of ambiguous or orphaned output
- [ ] Test: hermetic — run the enumerated matrix with fixed clocks and provider responses
- [ ] Commit & push

**Done when:** Every enumerated fault has one deterministic observed state and recovery action with no duplicate promotion or lost artifact.

### M25: Forward-test the complete skill before release

**Depends on:** M11–M24

**Why:** Fresh agents must operate the skill correctly without access to the design conversation or hidden assumptions.

**Approach:** Create a disposable fixture universe with unrelated, sequel, parallel, crossover, and alternate-continuity books. Run realistic commands in fresh OpenCode sessions, translate one edition, export both formats, validate installation drift, and compare observed budgets with hermetic expectations.

**Tasks:**
- [ ] Exercise every public route and selector with fresh agents
- [ ] Verify generated projects have no project shell or Claude instruction dependency
- [ ] Run skill validation, automated suites, install drift check, and live smoke tests
- [ ] Record measured budgets and resolve every blocking evaluation finding
- [ ] Test: end-to-end — complete the fixture lifecycle from init through both exports
- [ ] Commit & push

**Done when:** A clean install completes the fixture lifecycle within all contracts and no blocking forward-test finding remains.

## Out of scope

- Graphify or semantic graph retrieval in the v1 execution path.
- Guaranteed detection of undeclared facts that both writer disclosure and technical review miss.
- Automatic translation creation or unrequested bulk translation.
- Multi-provider or multi-model ensembles; creative roles use the pinned DeepSeek model.
- Implicit multiverse inheritance; alternate continuities import shared material explicitly.
- Changing source language after the first source chapter closes.
- Audiobook or cover generation, ISBN procurement, DRM, storefront upload, or print-on-demand integration.
- Automatic source-prose rewriting after canon changes; the system schedules evidence-backed repair tasks.
