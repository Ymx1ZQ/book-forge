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
