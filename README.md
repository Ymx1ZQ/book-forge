# book-forge

book-forge is an OpenCode skill for designing, writing, reviewing, resuming, translating, auditing, and publishing long-form fiction in a shared universe. It keeps the universe as the root object, lets it hold any number of books, and moves every state and canonical write through one deterministic control plane while OpenCode agents do the model work. Design and prose calls are bounded by explicit contracts, chapter work is checkpointed in receipts, interrupted runs can be resumed, and translations and editions are derived only when you ask for them.

## Requirements

- OpenCode 1.18.18 or newer, installed and on `PATH`.
- Python 3, to run the control plane at `<skill>/scripts/book_forge.py`.

The installer refuses to continue when OpenCode is missing or too old, and the engine checks the OpenCode capabilities it needs before the first dispatch.

## Install and update

Run `./install.sh` from a checkout. It copies the skill into the OpenCode skills directory and installs the global orchestrator and `/book-forge` command entrypoints; if any of those already exist it asks before replacing them.

- `./install.sh` installs or asks before replacing an existing installation.
- `./install.sh --force` replaces an existing installation without prompting. Use it to update an installed copy from a newer checkout.
- `./install.sh --check` compares the installed payload with the source checkout and reports drift without installing anything.

Set `BOOK_FORGE_CONFIG_HOME` to override the OpenCode config root, or `BOOK_FORGE_REPO_URL` to install from a different repository.

## First project

Create a project directory and initialize it:

```sh
python3 <skill>/scripts/book_forge.py --project <dir> init --title "<title>"
```

`init` writes the universe, the project config, and the OpenCode runtime files, and asks for the chorus models when run interactively. It creates no translation, no book, and no provider key. After `init`, answer the brief questions before designing; `--skip-brief` bypasses that gate.

If you change the model pins or role configuration, regenerate the runtime surface:

```sh
python3 <skill>/scripts/book_forge.py --project <dir> runtime sync
```

`runtime sync` rewrites `opencode.json` and `.opencode/agents/` from the pins. It touches neither `book-forge.yaml` nor any control-plane or canonical state.

## Main commands

Run every command as `python3 <skill>/scripts/book_forge.py --project <dir> <command> ...`; the global `--project` option comes before the selector.

| Command | What it does |
|---|---|
| `design` | `design universe` or `design book --book BOOK-NNNN` creates the world rules, or a book's premise, arc, and chapter contracts, through designer and independent canon-auditor calls. |
| `run` | `run --book BOOK-NNNN` drafts, reviews, and closes chapters; `--next` executes one workflow unit and returns its state. |
| `advance` | Drives a book from where it stands through design, chapters, translations, and export, stopping earlier with `--until design\|chapters\|translate\|export`. |
| `status` | Reports task and run state, recovery, accepted calls, tokens, and cost from immutable receipts, making no model calls. |
| `pause` | Drains accepted work safely; `--emergency` stops immediately and leaves accepted unfinished calls as `outcome_unknown`. |
| `resume` | Resumes a paused run after each unknown task is settled with `--resolve-unknown TASK:retry\|abandon`. |
| `reset` | Returns a book to its pre-writing state; it is destructive and requires `--book` and `--yes`. |
| `audit` | Derives and runs bounded canon-auditor jobs over a book, relation, or continuity, and schedules repairs. |
| `translate` | `translate add\|next\|run\|status BOOK LOCALE` creates an isolated locale workspace and advances its translation. |
| `export` | `export BOOK --lang TAG --format epub\|pdf\|all` writes a validated edition to `dist/` with no model calls. |
| `chorus` | Runs or inspects the advisory ensemble; synthesis and applying its output remain manual and never rewrite canon automatically. |
| `revise` | `revise --book BOOK-NNNN --chapter CH-XXXX --note TEXT` rewrites only the paragraphs a note names in an already promoted chapter. |

## What a project keeps

- `book-forge.yaml` — project identity, source language, model pins, context budgets, chorus settings, and style settings.
- `universe/` — the shared universe: kernel, continuities, collections, relations, timeline, and canon by topic, character, place, and faction.
- `books/BOOK-NNNN/` — one book's metadata, brief, chapter contracts, manuscript, and per-chapter work and review state.
- `dist/` — exported EPUB and PDF editions and their manifests.
- `.book-forge/` — machine state: project metadata, receipts, runs, locks, chorus output, and the advance lock.

## Where to read next

- `SKILL.md` — the agent-facing entry point, route table, requirements, and public command surface.
- `references/` — one reference per route, with the exact flags and behaviour of each command.
- `DEVPLAN.md` — the development plan and milestone history.
