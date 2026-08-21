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

### M6: Execute a canonical single-writer task graph

**Depends on:** M2, M5

**Why:** Subagents need a common plan without concurrent edits, lost updates, or unsupported completion claims.

**Approach:** Store the canonical DAG in `.book-forge/plan.json` and render Markdown views from it. Define task, attempt, pre-dispatch intent, execution receipt, promotion receipt, and currentness schemas. Derive idempotency from exact inputs, request envelope, model/variant, skill version, and prompt version; let the model orchestrator decide transitions while the deterministic control plane executes them only with its current fencing token.

**Tasks:**
- [ ] Define canonical plan, task, attempt, intent, receipt, and currentness schemas
- [ ] Implement stable frontier selection and attempt-local worker capsules
- [ ] Render active and completed devplans with tamper hashes
- [ ] Distinguish observed execution from committed promotion in skip decisions
- [ ] Test: integration — reject direct plan edits, stale fencing, and duplicate promotion
- [ ] Commit & push

**Done when:** Two disjoint workers can report results while one fenced orchestrator advances each task exactly once.

### M7: Promote multi-file results through a recovery journal

**Depends on:** M6

**Why:** Canon, prose, state, and receipts cannot be made safe by claiming multi-file atomicity.

**Approach:** Implement promotion inside the deterministic control plane. Persist and sync a prepare record listing base hashes, target hashes, paths, staging files, fencing token, and transaction ID; install each path by containment-checked temporary rename, journal progress, create a path-scoped commit without `git add -A`, then write the promotion receipt and update plan state.

**Tasks:**
- [ ] Reject traversal, symlink escape, undeclared paths, and changed base hashes
- [ ] Persist prepare, per-path install, commit, receipt, and completion journal states
- [ ] Reconcile partial installs by expected and current hashes without blind rollback
- [ ] Block all consumers behind recovery or a committed-generation read snapshot
- [ ] Separate failed Git sync into `sync_pending` without rerunning creative tasks
- [ ] Test: integration — crash at every journal boundary and recover the same final hashes
- [ ] Commit & push

**Done when:** Every injected promotion crash completes safely or blocks on a real hash conflict with all staged work preserved.

### M8: Pause, resume, retry, and rate-limit safely

**Depends on:** M6, M7

**Why:** Long model calls must stop and resume predictably without conflating waits, failures, cancellations, and unknown outcomes.

**Approach:** Define run states `planned|running|pausing|paused|blocked|completed|cancelled` and task states `pending|ready|claimed|running|validating|promotion_pending|succeeded|retry_wait|outcome_unknown|orphaned|blocked|cancelled`. Use desired-state generations, leases, heartbeats, fencing, persisted provider-wide eligibility times, and stored OpenCode task/session IDs as best-effort recovery hints.

**Tasks:**
- [ ] Make graceful pause stop dispatch, finish accepted calls through promotion, then enter paused
- [ ] Make emergency halt record intent before interrupting and preserve partial output
- [ ] Persist Retry-After, chosen backoff, wait deadline, and pause-interruptible provider gates
- [ ] Query stored task/session IDs before blocking accepted-but-unobserved calls as `outcome_unknown`
- [ ] Move pausing runs with unknown outcomes to blocked while preserving pause intent
- [ ] Resolve unknowns explicitly: retry re-enters running; abandon blocks descendants; late results become orphans
- [ ] Refuse cleanup for active, unpromoted, ambiguous, or orphaned attempts
- [ ] Test: integration — exercise every state transition, expired lease, and concurrent resume
- [ ] Commit & push

**Done when:** A fresh process reconstructs the exact frontier and exposes every nonterminal attempt without automatic ambiguous retry.

### M9: Build canon indexing and a generic artifact dependency engine

**Depends on:** M3, M4, M6, M8

**Why:** Block-only canon dependencies cannot propagate changes through state, translations, and publication outputs.

**Approach:** Parse addressable blocks such as `CHR-0012#voice` and build a typed dependency engine, initially registering canon, relations, plans, receipts, and state introduced through M8. Require every later artifact producer to register edges and migrations. Reconcile legitimate external authored edits before planning; keep receipts immutable and derive currentness separately.

**Tasks:**
- [ ] Parse and validate IDs, blocks, imports, sources, entities, events, and obligations
- [ ] Build reverse dependencies, appearances, timeline, and generic typed artifact edges
- [ ] Detect duplicates, dangling imports, forbidden continuity edges, and import cycles
- [ ] Reconcile external authored hashes and refuse direct edits to derived machine artifacts
- [ ] Rebuild generated indexes without editing authored files or historical receipts
- [ ] Test: unit — propagate seeded changes through exact transitive consumers only
- [ ] Commit & push

**Done when:** Seeded existing artifacts yield a deterministic minimal stale set and a later producer can register a new type without engine changes.

### M10: Build bounded complete request envelopes

**Depends on:** M5, M9

**Why:** Packet size alone omits role prompts, task instructions, tool schemas, and output allowance that the provider actually charges.

**Approach:** Assemble the complete serialized request envelope from role contract, task capsule, explicit imports, state, tools, and output limit. Close transitively only through `imports`, deduplicate, order, count with a pinned tokenizer plus safety margin, and hash the exact payload; apply distinct visibility and budgets per role.

**Tasks:**
- [ ] Implement stable request assembly and model-specific token estimation
- [ ] Enforce per-role input, output, and total workflow budgets
- [ ] Exclude canon from cold-reader packets and author history from reviewers and judges
- [ ] Hard-fail overflow with ranked contributors instead of truncation
- [ ] Test: live — compare estimates with provider-reported usage within a declared tolerance
- [ ] Commit & push

**Done when:** Repeated envelopes are byte-stable, visibility tests pass, and provider usage stays within the configured safety margin.

## Phase C — Universe and book design

### M11: Design and validate an evolving universe

**Depends on:** M7, M8, M9, M10

**Why:** Writing should begin from coherent world rules, story space, and characters while canon remains incrementally extensible.

**Approach:** Add `design universe` for kernel invariants, eras, events, places, factions, characters, themes, and style. Use structured designer proposals and canon-auditor findings; promote only schema-valid changes with every imported block recorded.

**Tasks:**
- [ ] Add guided and autonomous universe-design task contracts
- [ ] Separate universal, continuity-scoped, and book-local material
- [ ] Validate world rules, chronology, identity, and unresolved questions
- [ ] Produce compact addressable summaries for later requests
- [ ] Test: integration — design a fixture universe and reject a seeded contradiction
- [ ] Commit & push

**Done when:** The fixture reaches `design_clean` with every fixed validator and blocking-audit oracle satisfied.

### M12: Design related books and chapter contracts

**Depends on:** M3, M7, M8, M10, M11

**Why:** Each book needs an autonomous arc while honoring only shared history and relations that constrain it.

**Approach:** Add `design book` for premise, cast, entry boundary, arc, outline, and compact chapter contracts. Convert relation imports into addressable obligations and assign POV, beats, plants, reveals, target length, and required canon blocks to stable chapter IDs.

**Tasks:**
- [ ] Build premise, entry state, arc, and intended exit boundary
- [ ] Convert relation boundaries and shared events into explicit obligations
- [ ] Generate schema-valid chapter contracts with deterministic order
- [ ] Audit pacing, causality, agency, and unresolved dependencies
- [ ] Test: integration — design sequel, parallel, and unrelated fixtures within budgets
- [ ] Commit & push

**Done when:** Every fixture chapter packetizes independently and every blocking relation obligation has one assigned target.

## Phase D — Fast chapter production

### M13: Draft an ordinary chapter in one provider call

**Depends on:** M8, M10, M12

**Why:** The common path must turn one approved contract into prose without variant proliferation or whole-book rereads.

**Approach:** Let a fresh writer consume the configured-language envelope and emit one staged draft, beat self-map, and consequence disclosure. Pre-review validation remains mechanical—materialization, structure, placeholders, bounds, and hashes—while the technical editor later judges semantic contract coverage.

**Tasks:**
- [ ] Implement deterministic `run --next` selection and writer capsules
- [ ] Produce one source-language draft for ordinary chapters
- [ ] Validate output materialization and request/output bounds before review
- [ ] Permit at most one separately receipted continuation or repair attempt
- [ ] Test: live — draft one fixture chapter and verify envelope and call budgets
- [ ] Commit & push

**Done when:** The happy path materializes one reviewable draft in one provider call and any recovery remains inside the declared ceiling.

### M14: Review, revise, and close a chapter

**Depends on:** M13

**Why:** A fast draft still needs independent reader response, canon checking, controlled revision, and recorded consequences.

**Approach:** Run cold-reader and technical-editor calls in parallel with isolated envelopes, then let one reviser disposition every finding and produce a replacement. Make objective blockers fix-required. If any semantic blocker existed, spend the single recovery call on an independent changed-span verification; one failed verification blocks the chapter without another loop.

**Tasks:**
- [ ] Define evidence, severity, disposition, loss, fix, and supersession fields
- [ ] Make the technical editor independently extract shared consequences from the draft
- [ ] Prevent revisers from dismissing objective blocking findings without repair
- [ ] Verify repaired semantic blockers independently within the recovery-call ceiling
- [ ] Update prose and derived state through one promotion transaction
- [ ] Test: integration — detect a seeded undisclosed consequence and block incomplete state
- [ ] Commit & push

**Done when:** The fixture closes in four happy-path calls with no unresolved blocker records and all expected hashes promoted.

### M15: Judge only explicitly pivotal chapters

**Depends on:** M13, M14

**Why:** Selective competition can improve high-leverage scenes without imposing ensemble cost on ordinary chapters.

**Approach:** Mark opener, midpoint, climax, finale, or user-selected chapters as pivotal. Generate two isolated drafts with complementary briefs, randomize identities, select one through a blind judge, retain at most two low-risk anchors, then reuse the two-review and one-revision closure path.

**Tasks:**
- [ ] Add explicit and policy-driven pivotal classification
- [ ] Generate two variants without shared session history
- [ ] Implement blind rank-only judgement and winner promotion
- [ ] Preserve losing output while limiting anchor integration
- [ ] Test: live — close a pivotal fixture in six happy-path calls
- [ ] Commit & push

**Done when:** The fixture promotes one blind-selected winner within the nominal and recovery call ceilings.

## Phase E — Opt-in translation

### M16: Create a canonical locale workspace on request

**Depends on:** M2, M7, M8, M9, M10

**Why:** Translation needs persistent terminology and voice decisions but must add no files or tokens until requested.

**Approach:** Add `translate add` for canonicalized, path-safe BCP 47 tags, creating locale config, style blocks, glossary blocks, boundary state, localized metadata, and an empty chapter directory. Treat the configured source language as authoritative and isolate each locale.

**Tasks:**
- [ ] Canonicalize language tags and reject aliases, traversal, collisions, and source duplication
- [ ] Generate locale style, glossary, metadata, and state only on explicit request
- [ ] Address names, honorifics, register, dialogue voice, and do-not-translate terms
- [ ] Keep locale state separate from source canon and other locales
- [ ] Test: integration — create aliasing and distinct locales without touching source prose
- [ ] Commit & push

**Done when:** Requested locale paths are canonical and safe while an untouched book has no translation artifacts.

### M17: Translate and validate one chapter at a time

**Depends on:** M14, M16

**Why:** Chapter-local translation preserves voice and terminology without repeatedly loading the whole book.

**Approach:** Build a translator envelope from source prose, imported voice/canon blocks, locale style and glossary blocks, localized metadata, and the preceding translated boundary. Use one call by default, deterministic omission and terminology checks, and one review or repair only for flagged or pivotal output.

**Tasks:**
- [ ] Register locale-scoped tasks under the shared run, status, pause, and resume state machine
- [ ] Validate names, numbers, scene structure, omissions, and source leakage
- [ ] Update glossary blocks and translated boundary state through promotion
- [ ] Preserve stale and partial translations as historical attempts
- [ ] Test: live — translate two consecutive fixture chapters within call budgets
- [ ] Commit & push

**Done when:** A requested locale advances serially with precise dependencies and one normal provider call per chapter.

### M18: Propagate translation changes until boundaries converge

**Depends on:** M9, M17

**Why:** Source, voice, glossary, style, metadata, or prior-boundary edits can affect later translated chapters.

**Approach:** Record every translation input in the artifact DAG. Mark direct consumers stale, recompute each affected boundary, and continue forward only while the boundary hash changes; never overwrite existing translation prose automatically. Refuse publication from stale, missing, or incomplete locale state.

**Tasks:**
- [ ] Add source, canon, locale, glossary, metadata, and boundary dependency edges
- [ ] Implement forward invalidation with boundary-hash convergence
- [ ] Distinguish stale prose from boundary-audit-only work
- [ ] Explain exact invalidation causes before scheduling model calls
- [ ] Test: integration — cover converging and cascading translation edits
- [ ] Commit & push

**Done when:** Each seeded change produces the minimal proven stale suffix and no current translation is regenerated unnecessarily.

## Phase F — Cross-book assurance and publication

### M19: Audit continuity from bounded evidence

**Depends on:** M9, M14

**Why:** Cross-book assurance should follow actual shared evidence rather than comparing every book pair.

**Approach:** Generate jobs from explicit relations, consecutive appearances, overlapping intervals, shared events, crossover obligations, and technical-editor consequence disclosures. Feed only relation metadata, boundary snapshots, involved blocks, and cited prose; schedule confirmed repairs rather than rewriting automatically.

**Tasks:**
- [ ] Implement relation, boundary, entity-transition, overlap, crossover, and timeline jobs
- [ ] Generate candidates deterministically from the artifact indexes
- [ ] Enforce per-job calls, eight-job waves, and the twenty-candidate override gate
- [ ] Require evidence locations and new hashes for repeated findings
- [ ] Preserve immutable receipts while deriving impacted currentness
- [ ] Test: integration — find every seeded indexed defect without unrelated book context
- [ ] Commit & push

**Done when:** Fixture audits cover every declared shared edge, avoid all-pairs loading, and schedule only evidence-backed work.

### M20: Assemble and export deterministic EPUB editions

**Depends on:** M9, M14

**Why:** Source manuscripts need a validated publication representation before format-specific rendering.

**Approach:** Assemble one normalized source-language document from current chapters, metadata, front/back matter, cover, and typography assets. Pin dependencies; normalize identifiers, ZIP order, timestamps, locale, timezone, and metadata; record input and toolchain hashes before rendering EPUB.

**Tasks:**
- [ ] Define publication assembly, freshness, metadata, matter, order, and asset contracts
- [ ] Refuse stale, missing, incomplete, or mixed-language inputs
- [ ] Build navigation, language metadata, stylesheet, and embedded assets
- [ ] Validate EPUB structure, links, images, fonts, and chapter completeness
- [ ] Test: integration — produce byte-identical rebuilds in the pinned environment
- [ ] Commit & push

**Done when:** Repeated fixture builds have identical EPUB bytes and a complete verifiable build manifest.

### M21: Export deterministic source PDF editions

**Depends on:** M20

**Why:** PDF has a separate rendering and metadata surface that must not weaken EPUB reproducibility guarantees.

**Approach:** Reuse the normalized publication assembly, pin renderer and font bytes, fix locale, timezone, and source epoch, and normalize document identifiers and metadata. Validate page geometry, typography, breaks, headers, numbering, embedded fonts, and image resolution.

**Tasks:**
- [ ] Render PDF only from a current normalized assembly
- [ ] Pin and hash renderer, dependencies, fonts, styles, and environment inputs
- [ ] Normalize timestamps, identifiers, metadata, and nondeterministic ordering
- [ ] Validate readability, page structure, links, images, and font embedding
- [ ] Test: integration — produce byte-identical rebuilds in the pinned environment
- [ ] Commit & push

**Done when:** Repeated fixture builds have identical PDF bytes and fail closed when any toolchain input drifts.

### M22: Publish current translated editions

**Depends on:** M18, M20, M21

**Why:** Requested locales should reuse the proven publication toolchains without allowing stale or incomplete translations into release artifacts.

**Approach:** Extend normalized assembly to locale-specific chapter trees, metadata, front/back matter, typography, and language declarations. Require current M18 dependency state before either renderer starts, and register both edition formats in the artifact DAG with exact locale and toolchain inputs.

**Tasks:**
- [ ] Assemble translated editions only from one canonical locale workspace
- [ ] Reject stale boundaries, mixed languages, missing chapters, and incomplete metadata
- [ ] Render translated EPUB and PDF through the existing pinned toolchains
- [ ] Register locale publication inputs, outputs, manifests, and currentness edges
- [ ] Test: integration — publish a current locale and refuse each seeded stale condition
- [ ] Commit & push

**Done when:** A requested current locale produces both validated formats and every stale fixture fails before rendering.

## Phase G — Measured reliability

### M23: Enforce token and workflow telemetry at every route

**Depends on:** M10, M15, M19, M22

**Why:** Efficiency must be measured on complete paid requests and guarded as each expensive workflow lands.

**Approach:** Aggregate immutable receipt telemetry by role, chapter, book, locale, and run. M10, M13, M15, and M17 enforce local budgets when introduced; this milestone adds cross-route regressions, invalidation fan-out reports, latency and retry analysis, and explicit manifest-recorded overrides.

**Tasks:**
- [ ] Produce status and cost summaries without model calls
- [ ] Compare estimated and provider-reported input/output usage
- [ ] Enforce workflow call, concurrency, variant, and invalidation budgets
- [ ] Report retries, ambiguous calls, waits, and stale causes separately
- [ ] Test: regression — fail seeded envelope, call, and fan-out budget breaches
- [ ] Commit & push

**Done when:** Every accepted provider call is attributable and the end-to-end artifact DAG validates all registered source, translation, audit, and publication edges.

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
