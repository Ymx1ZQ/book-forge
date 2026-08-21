# Book Forge — Completed Milestones

## Phase A — Installable universe foundation

### M1: Ship an installable OpenCode skill shell ✅

**Why:** The development tree needs a reproducible payload before runtime features can land or be tested independently.

**Approach:** Finalize the router and metadata, add an OpenCode-only `install.sh` with `--force` and `--check`, and initialize the `ymx1zq/book-forge` Git repository. Install only the runtime payload; exclude development plans and tests.

**Tasks:**
- [x] Finalize the thin command router and OpenCode-facing metadata
- [x] Add local and remote install, force, and drift-check paths
- [x] Initialize the repository and configure the personal GitHub remote
- [x] Test: integration — install into a temporary OpenCode config directory and detect drift
- [x] Commit & push

**Done when:** A clean checkout installs and validates the minimal payload without touching other assistants.

### M2: Initialize a schema-valid universe ✅

**Depends on:** M1

**Why:** Every later workflow needs a stable project shape without committing the user to a book count.

**Approach:** Add `init`, project templates, and versioned schemas for universe metadata, configurable source language, primary continuity, inherited universe kernel, empty book set, and a static operational-plan shell. Generate immutable IDs independently from names and paths; bind the nearest Git repository or initialize one at the universe root; write through staging and rename.

**Tasks:**
- [x] Define versioned project, universe, continuity, and identifier schemas
- [x] Generate minimal authored and derived directories through staging
- [x] Seed exact provider, model, source-language, and schema-version configuration
- [x] Bind a project-local Git repository without nesting inside an existing checkout
- [x] Reject collisions and partial initialization without changing existing files
- [x] Test: integration — initialize, validate, rerun idempotently, and inject interrupted setup
- [x] Commit & push

**Done when:** `init` creates a valid zero-book universe and leaves a collision or injected failure byte-for-byte unchanged.

### M3: Add books, continuities, collections, and relations ✅

**Depends on:** M2

**Why:** Shared universes need flexible organization and explicit narrative dependencies without duplicated canon ownership.

**Approach:** Implement `continuity`, `add-book`, `relate`, and `collection` over stable IDs. Treat `sequel_of`, `prequel_of`, `adaptation_of`, and `alternate_of` as directed; `parallel_to` as symmetric binary; and `crossover` as symmetric n-ary. Keep sequel, prequel, parallel, and crossover inside one continuity; allow adaptation and alternate links across continuities only through addressable imports.

**Tasks:**
- [x] Create books with one continuity and collection membership stored in one registry
- [x] Create primary or alternate continuities with explicit fork metadata and imports
- [x] Validate direction, inverse semantics, symmetry, arity, endpoints, and allowed cycles
- [x] Give relation obligations and boundary imports stable IDs and hashes
- [x] Preserve IDs when titles, paths, or reading order change
- [x] Test: unit — cover every relation type, ancestry conflict, crossover, and alternate import
- [x] Commit & push

**Done when:** An arbitrary valid book network round-trips without fixed-length assumptions or duplicate membership state.

### M4: Migrate versioned schemas safely ✅

**Depends on:** M2, M3

**Why:** An open-ended universe must survive skill upgrades without corrupting authored canon or machine state.

**Approach:** Add schema compatibility checks, dry-run migrations, durable backups, journaled upgrades, and rollback before promotion. Migrate only the M2–M3 schemas introduced so far; require every later schema-producing milestone to register its own version and migration. Reject unsupported versions and direct machine-state changes with actionable recovery instructions.

**Tasks:**
- [x] Define supported schema window and ordered migration contracts
- [x] Add dry-run, backup, journaled apply, and rollback behavior
- [x] Preserve authored prose and canon bytes unless their schema requires migration
- [x] Detect machine-state or devplan tampering and regenerate the view only on explicit command
- [x] Test: integration — migrate, interrupt, roll back, and reject an unsupported version
- [x] Commit & push

**Done when:** A supported old fixture upgrades recoverably while unsupported or interrupted migrations preserve the original project.

## Phase B — Durable orchestration and bounded context

### M5: Pin and verify the OpenCode role topology ✅

**Depends on:** M2

**Why:** Cost and permissions become unpredictable if roles inherit provider defaults or unrestricted filesystem access.

**Approach:** Generate orchestrator, designer, writer, cold-reader, technical-editor, reviser, canon-auditor, translator, and judge roles. Pin model, variant, steps, depth, task permissions, and readable paths; give model roles write access only to attempt-local output. Validate OpenCode version and provider capabilities at boot and reject CLI overrides.

**Tasks:**
- [x] Define a role capability matrix and fail-closed permission templates
- [x] Generate project-local OpenCode agents with exact model pins
- [x] Probe required model, variants, task resume, and usage-reporting capabilities
- [x] Test: unit — deny every forbidden role, delegation, read, and write edge
- [x] Test: live — run one minimal role through existing OpenRouter authentication
- [x] Commit & push

**Done when:** Boot validation proves every configured capability and each role can access only its declared task surface.

### M6: Execute a canonical single-writer task graph ✅

**Depends on:** M2, M5

**Why:** Subagents need a common plan without concurrent edits, lost updates, or unsupported completion claims.

**Approach:** Store the canonical DAG in `.book-forge/plan.json` and render Markdown views from it. Define task, attempt, pre-dispatch intent, execution receipt, promotion receipt, and currentness schemas. Derive idempotency from exact inputs, request envelope, model/variant, skill version, and prompt version; let the model orchestrator decide transitions while the deterministic control plane executes them only with its current fencing token.

**Tasks:**
- [x] Define canonical plan, task, attempt, intent, receipt, and currentness schemas
- [x] Implement stable frontier selection and attempt-local worker capsules
- [x] Render active and completed devplans with tamper hashes
- [x] Distinguish observed execution from committed promotion in skip decisions
- [x] Test: integration — reject direct plan edits, stale fencing, and duplicate promotion
- [x] Commit & push

**Done when:** Two disjoint workers can report results while one fenced orchestrator advances each task exactly once.

### M7: Promote multi-file results through a recovery journal ✅

**Depends on:** M6

**Why:** Canon, prose, state, and receipts cannot be made safe by claiming multi-file atomicity.

**Approach:** Implement promotion inside the deterministic control plane. Persist and sync a prepare record listing base hashes, target hashes, paths, staging files, fencing token, and transaction ID; install each path by containment-checked temporary rename, journal progress, create a path-scoped commit without `git add -A`, then write the promotion receipt and update plan state.

**Tasks:**
- [x] Reject traversal, symlink escape, undeclared paths, and changed base hashes
- [x] Persist prepare, per-path install, commit, receipt, and completion journal states
- [x] Reconcile partial installs by expected and current hashes without blind rollback
- [x] Block all consumers behind recovery or a committed-generation read snapshot
- [x] Separate failed Git sync into `sync_pending` without rerunning creative tasks
- [x] Test: integration — crash at every journal boundary and recover the same final hashes
- [x] Commit & push

**Done when:** Every injected promotion crash completes safely or blocks on a real hash conflict with all staged work preserved.

### M8: Pause, resume, retry, and rate-limit safely ✅

**Depends on:** M6, M7

**Why:** Long model calls must stop and resume predictably without conflating waits, failures, cancellations, and unknown outcomes.

**Approach:** Define run states `planned|running|pausing|paused|blocked|completed|cancelled` and task states `pending|ready|claimed|running|validating|promotion_pending|succeeded|retry_wait|outcome_unknown|orphaned|blocked|cancelled`. Use desired-state generations, leases, heartbeats, fencing, persisted provider-wide eligibility times, and stored OpenCode task/session IDs as best-effort recovery hints.

**Tasks:**
- [x] Make graceful pause stop dispatch, finish accepted calls through promotion, then enter paused
- [x] Make emergency halt record intent before interrupting and preserve partial output
- [x] Persist Retry-After, chosen backoff, wait deadline, and pause-interruptible provider gates
- [x] Query stored task/session IDs before blocking accepted-but-unobserved calls as `outcome_unknown`
- [x] Move pausing runs with unknown outcomes to blocked while preserving pause intent
- [x] Resolve unknowns explicitly: retry re-enters running; abandon blocks descendants; late results become orphans
- [x] Refuse cleanup for active, unpromoted, ambiguous, or orphaned attempts
- [x] Test: integration — exercise every state transition, expired lease, and concurrent resume
- [x] Commit & push

**Done when:** A fresh process reconstructs the exact frontier and exposes every nonterminal attempt without automatic ambiguous retry.

### M9: Build canon indexing and a generic artifact dependency engine ✅

**Depends on:** M3, M4, M6, M8

**Why:** Block-only canon dependencies cannot propagate changes through state, translations, and publication outputs.

**Approach:** Parse addressable blocks such as `CHR-0012#voice` and build a typed dependency engine, initially registering canon, relations, plans, receipts, and state introduced through M8. Require every later artifact producer to register edges and migrations. Reconcile legitimate external authored edits before planning; keep receipts immutable and derive currentness separately.

**Tasks:**
- [x] Parse and validate IDs, blocks, imports, sources, entities, events, and obligations
- [x] Build reverse dependencies, appearances, timeline, and generic typed artifact edges
- [x] Detect duplicates, dangling imports, forbidden continuity edges, and import cycles
- [x] Reconcile external authored hashes and refuse direct edits to derived machine artifacts
- [x] Rebuild generated indexes without editing authored files or historical receipts
- [x] Test: unit — propagate seeded changes through exact transitive consumers only
- [x] Commit & push

**Done when:** Seeded existing artifacts yield a deterministic minimal stale set and a later producer can register a new type without engine changes.

### M10: Build bounded complete request envelopes ✅

**Depends on:** M5, M9

**Why:** Packet size alone omits role prompts, task instructions, tool schemas, and output allowance that the provider actually charges.

**Approach:** Assemble and hash the complete byte-stable application envelope from role contract, task capsule, explicit imports, state, tools, and output limit. Close transitively only through `imports`, deduplicate, order, estimate with a pinned conservative DeepSeek-specific estimator plus an explicit OpenCode-provider overhead allowance, and calibrate that allowance from reported usage; apply distinct visibility and budgets per role.

**Tasks:**
- [x] Implement stable request assembly and model-specific token estimation
- [x] Enforce per-role input, output, and total workflow budgets
- [x] Exclude canon from cold-reader packets and author history from reviewers and judges
- [x] Hard-fail overflow with ranked contributors instead of truncation
- [x] Test: live — compare estimates with provider-reported usage within a declared tolerance
- [x] Commit & push

**Done when:** Repeated envelopes are byte-stable, visibility tests pass, and provider usage stays within the configured safety margin.

## Phase C — Universe and book design

### M11: Design and validate an evolving universe ✅

**Depends on:** M7, M8, M9, M10

**Why:** Writing should begin from coherent world rules, story space, and characters while canon remains incrementally extensible.

**Approach:** Add `design universe` for kernel invariants, eras, events, places, factions, characters, themes, and style. Use structured designer proposals and canon-auditor findings; promote only schema-valid changes with every imported block recorded.

**Tasks:**
- [x] Add guided and autonomous universe-design task contracts
- [x] Separate universal, continuity-scoped, and book-local material
- [x] Validate world rules, chronology, identity, and unresolved questions
- [x] Produce compact addressable summaries for later requests
- [x] Test: integration — design a fixture universe and reject a seeded contradiction
- [x] Commit & push

**Done when:** The fixture reaches `design_clean` with every fixed validator and blocking-audit oracle satisfied.

### M12: Design related books and chapter contracts ✅

**Depends on:** M3, M7, M8, M10, M11

**Why:** Each book needs an autonomous arc while honoring only shared history and relations that constrain it.

**Approach:** Add `design book` for premise, cast, entry boundary, arc, outline, and compact chapter contracts. Convert relation imports into addressable obligations and assign POV, beats, plants, reveals, target length, and required canon blocks to stable chapter IDs.

**Tasks:**
- [x] Build premise, entry state, arc, and intended exit boundary
- [x] Convert relation boundaries and shared events into explicit obligations
- [x] Generate schema-valid chapter contracts with deterministic order
- [x] Audit pacing, causality, agency, and unresolved dependencies
- [x] Test: integration — design sequel, parallel, and unrelated fixtures within budgets
- [x] Commit & push

**Done when:** Every fixture chapter packetizes independently and every blocking relation obligation has one assigned target.

## Phase D — Fast chapter production

### M13: Draft an ordinary chapter in one provider call ✅

**Depends on:** M8, M10, M12

**Why:** The common path must turn one approved contract into prose without variant proliferation or whole-book rereads.

**Approach:** Let a fresh writer consume the configured-language envelope and emit one staged draft, beat self-map, and consequence disclosure. Pre-review validation remains mechanical—materialization, structure, placeholders, bounds, and hashes—while the technical editor later judges semantic contract coverage.

**Tasks:**
- [x] Implement deterministic `run --next` selection and writer capsules
- [x] Produce one source-language draft for ordinary chapters
- [x] Validate output materialization and request/output bounds before review
- [x] Permit at most one separately receipted continuation or repair attempt
- [x] Test: live — draft one fixture chapter and verify envelope and call budgets
- [x] Commit & push

**Done when:** The happy path materializes one reviewable draft in one provider call and any recovery remains inside the declared ceiling.

### M14: Review, revise, and close a chapter ✅

**Depends on:** M13

**Why:** A fast draft still needs independent reader response, canon checking, controlled revision, and recorded consequences.

**Approach:** Run cold-reader and technical-editor calls in parallel with isolated envelopes, then let one reviser disposition every finding and produce a replacement. Make objective blockers fix-required. If any semantic blocker existed, spend the single recovery call on an independent changed-span verification; one failed verification blocks the chapter without another loop.

**Tasks:**
- [x] Define evidence, severity, disposition, loss, fix, and supersession fields
- [x] Make the technical editor independently extract shared consequences from the draft
- [x] Prevent revisers from dismissing objective blocking findings without repair
- [x] Verify repaired semantic blockers independently within the recovery-call ceiling
- [x] Update prose and derived state through one promotion transaction
- [x] Test: integration — detect a seeded undisclosed consequence and block incomplete state
- [x] Commit & push

**Done when:** The fixture closes in four happy-path calls with no unresolved blocker records and all expected hashes promoted.

### M15: Judge only explicitly pivotal chapters ✅

**Depends on:** M13, M14

**Why:** Selective competition can improve high-leverage scenes without imposing ensemble cost on ordinary chapters.

**Approach:** Mark opener, midpoint, climax, finale, or user-selected chapters as pivotal. Generate two isolated drafts with complementary briefs, randomize identities, select one through a blind judge, retain at most two low-risk anchors, then reuse the two-review and one-revision closure path.

**Tasks:**
- [x] Add explicit and policy-driven pivotal classification
- [x] Generate two variants without shared session history
- [x] Implement blind rank-only judgement and winner promotion
- [x] Preserve losing output while limiting anchor integration
- [x] Test: live — close a pivotal fixture in six happy-path calls
- [x] Commit & push

**Done when:** The fixture promotes one blind-selected winner within the nominal and recovery call ceilings.

## Phase E — Opt-in translation

### M16: Create a canonical locale workspace on request ✅

**Depends on:** M2, M7, M8, M9, M10

**Why:** Translation needs persistent terminology and voice decisions but must add no files or tokens until requested.

**Approach:** Add `translate add` for canonicalized, path-safe BCP 47 tags, creating locale config, style blocks, glossary blocks, boundary state, localized metadata, and an empty chapter directory. Treat the configured source language as authoritative and isolate each locale.

**Tasks:**
- [x] Canonicalize language tags and reject aliases, traversal, collisions, and source duplication
- [x] Generate locale style, glossary, metadata, and state only on explicit request
- [x] Address names, honorifics, register, dialogue voice, and do-not-translate terms
- [x] Keep locale state separate from source canon and other locales
- [x] Test: integration — create aliasing and distinct locales without touching source prose
- [x] Commit & push

**Done when:** Requested locale paths are canonical and safe while an untouched book has no translation artifacts.
