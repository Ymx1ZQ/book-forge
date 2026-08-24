# Initialize a universe

Use this route only for `init`.

1. Confirm the target directory. The source language is English (`en`) unless
   the user explicitly chooses another valid BCP 47 tag.
2. At the start of setup, ask which chorus models to use. The helper prompts interactively (TTY) with the 8-model catalog (`flash`, `pro`, `glm-5.3`, `qwen3.8-max`, `kimi-k3`, `grok-4.6`, `gemini-3.7-flash`, `luna`; default `all`), accepts `1,3,5` / `all` / `none` or a CSV, confirms, and persists the choice in `book-forge.yaml:chorus.models` (drives `opencode.json` + `.opencode/agents/`). Non-TTY or `--chorus-models <csv>` skips the prompt; `--chorus-models` also works as one-shot override on `design`/`chorus`.
3. Run the deterministic helper with `--project TARGET init`, adding
   `--source-language TAG` only when requested. Add `--title TITLE` when the
   requested title differs from the directory name. Pass `--chorus-models <csv>` to pre-select without prompting.
4. Report the created project path, source language, selected chorus models, and the next useful
   command (`design universe`).

Initialization is idempotent only for matching identity. Never create a
translation, book count mode, graph, provider key, `CLAUDE.md`, or project shell
pipeline during setup.
## 00-BRIEF gate (default ON)

After `init`, answer the 00-BRIEF 7 questions (see `brief.md`) before `design`. Default ON; bypass with `--skip-brief` or answer "usa default". The helper enforces the gate (`brief.py`).
