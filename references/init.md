# Initialize a universe

Use this route only for `init`.

1. Confirm the target directory. The source language is English (`en`) unless
   the user explicitly chooses another valid BCP 47 tag.
2. Run the deterministic helper with `--project TARGET init`, adding
   `--source-language TAG` only when requested. Add `--title TITLE` when the
   requested title differs from the directory name.
3. Report the created project path, source language, and the next useful
   command (`design universe`).

Initialization is idempotent only for matching identity. Never create a
translation, book count mode, graph, provider key, `CLAUDE.md`, or project shell
pipeline during setup.
## 00-BRIEF gate (default ON)

After `init`, answer the 00-BRIEF 7 questions (see `references/brief.md`) before `design`. Default ON; bypass with `--skip-brief` or answer "usa default". The helper enforces the gate (`scripts/brief.py`).
