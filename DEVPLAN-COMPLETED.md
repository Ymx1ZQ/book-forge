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
