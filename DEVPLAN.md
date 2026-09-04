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
- Primary roles (`designer`, `writer`, `cold-reader`, `technical-editor`, `reviser`, `canon-auditor`, `translator`, `judge`) are pinned to `openrouter/deepseek/deepseek-v4-flash-0731` through OpenRouter; chorus advisors use the configured ensemble (`flash`, `pro`, `glm-5.3`, `qwen3.8-max`, `kimi-k3`, `grok-4.6`, `gemini-3.7-flash`) and the synthesizer uses `openrouter/deepseek/deepseek-v4-pro-0813` on `max`.
- Role reasoning uses the pinned model's own effort tiers: routine roles run `low`, editorial roles run `high`, and `max` is reserved for integration, canon, and judgement.
- `source_language` defaults to `en`, may be selected at init, and becomes immutable after the first source chapter closes.
- Translation workspaces are absent until the user explicitly requests a target locale.
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
book-forge init [--title <title>] [--source-language <bcp47>]
book-forge migrate <check|dry-run|apply|rollback>
book-forge continuity add <name> [--kind <primary|alternate>] [--fork-from <id>] [--import <block>...]
book-forge add-book <title> [--continuity <id>]
book-forge relate <book...> --type <type> [--import <block>...] [--obligation <text>...]
book-forge collection <add|remove|order> ...
book-forge design <universe|book> [--book <id>] [--no-chorus] [--chorus-models <csv>]
book-forge run [--book <id>] [--task <id>] [--next]
book-forge pause [--run <id>] [--emergency]
book-forge resume [--run <id>] [--resolve-unknown <task>:<retry|abandon>] [--resolve-blocked <task>:<retry>]
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

## Phase H — Reasoning-effort ladder correction ✅

### M26: Pin every role to an effort the model actually supports ✅

**Depends on:** M5

**Why:** OpenRouter reports `supported_efforts: ["max", "high", "low"]` for
`deepseek/deepseek-v4-flash-0731`, while the generated configuration pinned a
`low`/`mid`/`high`/`xhigh` ladder over `low`/`medium`/`high`/`xhigh` and a
`medium` default. OpenRouter accepts the unsupported values without an error and
does not honour them, so `technical-editor` and `reviser` ran at the provider
default instead of their pinned tier, and the `xhigh` rung was never reachable.
The defect is invisible at runtime: no request fails.

**Approach:** Rename the ladder to the model's own tiers — `low`, `high`, `max`
— and set the configuration default to `high`. Keep routine roles on `low`,
move the editorial roles to `high`, and reserve `max` for integration, canon,
and judgement. Because `init` only validates an existing project and never
rewrites generated runtime configuration, add an explicit `runtime sync`
command so an already-created universe can be brought to the corrected pin
without hand-editing its files.

**Tasks:**
- [x] Remap `ROLE_SPECS` onto the `low`/`high`/`max` ladder
- [x] Replace the generated `variants` block and default effort in `_opencode_config`
- [x] Report the corrected ladder from `verify_runtime`
- [x] Repin the installed global orchestrator asset to `max`
- [x] Rewrite the routine-reasoning binding decision
- [x] Add `runtime sync` to regenerate an existing project's OpenCode configuration
- [x] Test: unit — role pins, generated config, and `runtime sync` convergence
- [x] Commit & push

**Done when:** Every generated role carries an effort the pinned model declares,
and an existing universe reaches that state by running a command rather than by
hand.

### M27: Stop the generated configuration from narrowing model choice ✅

**Depends on:** M26

**Why:** The generated `opencode.json` pinned `whitelist` to the single
production model and forced `default_agent` onto the orchestrator, whose
frontmatter also pins model and variant. Together these left a project session
opening on an agent whose model cannot be changed, over a catalogue narrowed to
one entry, so the TUI model picker had nothing to offer. Role pinning does not
depend on either setting: each role carries its own `model` and `variant`, and
`record_execution` verifies the observed pin from provider telemetry.

**Approach:** Drop `whitelist` and `default_agent` from the generated
configuration. A project then inherits whatever catalogue the user's global
configuration exposes and opens on the ordinary build agent, while
`model`/`small_model` still default to the pinned production model and every
Book Forge role stays pinned through its own agent file. Reaching the
orchestrator stays a deliberate act through the `/book-forge` command.

**Tasks:**
- [x] Remove `whitelist` from the generated OpenCode configuration
- [x] Remove `default_agent` from the generated OpenCode configuration
- [x] Test: unit — generated config narrows neither the catalogue nor the opening agent
- [x] Commit & push

**Done when:** A generated project exposes the user's full configured model
catalogue and opens on an agent whose model can be changed, with every role pin
intact.


## Phase I — Pre-writing Chorus (ensemble multi-modello, default-on con opt-out) ✅

### M32: Catalogo multi-modello e advisor roles (infra) ✅

**Status: done — 2026-08-23**

**Depends on:** M26, M27

**Why:** `book-forge` è pinned a un solo modello (`deepseek/deepseek-v4-flash-0731`) per tutti i ruoli (`MODEL`, `ROLE_SPECS`, `_opencode_config`). L'utente ha dovuto uscire dalla pipeline e interrogare a mano grok/glm/gemini/qwen/kimi + ds-pro per migliorare worldbuilding e brief su tre assi (sfruttamento worldbuilding, spinta bestseller, coerenza hard/scientifica). Senza catalogo multi-modello nel progetto generato (`opencode.json` ha un solo `MODEL_ID`) e senza agent advisor, quel miglioramento resta manuale e non riutilizzabile. Serve l'infra per esporre tutti i modelli già disponibili nel global config e per farli girare come advisor advisory-only.

**Approach:**
- `book-forge.yaml` nuovo blocco `chorus: {enabled: true, models: [7 default], synthesizer: "openrouter/deepseek/deepseek-v4-pro-0813"}` — default-on, opt-out via `--no-chorus` o `chorus.enabled=false`.
- Catalogo default (allineato a `~/.config/opencode/opencode.json`): `deepseek/deepseek-v4-flash-0731`, `deepseek/deepseek-v4-pro-0813`, `z-ai/glm-5.3`, `qwen/qwen3.8-max`, `moonshotai/kimi-k3`, `x-ai/grok-4.6`, `google/gemini-3.7-flash` — pro incluso come advisor a pieno titolo.
- `_opencode_config()` genera N entries `provider.openrouter.models` (con `reasoningEffort`/`provider.order` per-model presi dal global config) invece di una sola.
- `_write_agents()` genera N agent `advisor-<slug>.md` (mode `all`, variant coerente al provider: `high`/`max` per glm/kimi, `xhigh` per qwen/grok, `high`/`max` per deepseek, `high` per gemini) + mantiene i ruoli storici pinned a flash. `book-forge-orchestrator` resta `max` su flash.
- `verify_runtime` e `sync_runtime` rigenerano catalogo + advisor; `init` scrive il nuovo `book-forge.yaml` + `opencode.json`.
- Aggiorna `SKILL.md` Product contract e Binding decisions: rimosso *Multi-provider ensembles out of scope*, nuovo *Primary roles pinned to flash, chorus advisors use configured ensemble, synthesizer uses pro/max*.

**Tasks:**
- [x] Estendere `book-forge.yaml` con blocco `chorus` (schema v1, default-on)
- [x] Riscrivere `_opencode_config()` per N modelli (per-model options/variants)
- [x] Generare `advisor-*` agents in `_write_agents()` con model/variant per-provider
- [x] Aggiornare `verify_runtime` / `sync_runtime` per convergenza catalogo
- [x] Aggiornare `SKILL.md` contract + `DEVPLAN.md` binding decisions
- [x] Test: unit — `opencode.json` espone 7 modelli, ogni `advisor-*` ha pin diverso, ruoli storici restano su flash, `runtime sync` converge
- [x] Commit & push

**Done when:** Un progetto nuovo espone 7 modelli in `opencode.json` e 7 `advisor-*` agents con pin diversi; `runtime sync` su Landfall porta lo stesso stato senza toccare canon/control-plane; suite green.

### M33: Chorus advisory su ogni fase pre-scrittura (default-on, conferma modelli) ✅

**Status: done — 2026-08-23**

**Depends on:** M32

**Why:** Il miglioramento multi-modello è stato applicato solo a worldbuilding/brief a mano; ha senso su tutte le fasi pre-`run` (design universe, design book, e future fasi pre-scrittura). Deve essere suggerito di default (opt-out, non opt-in) e chiedere conferma/cambio modelli, altrimenti resta scoperta o a costo sorpresa.

**Approach:**
- Nuovo reference `references/chorus.md` (one-level) + helper riusabile `run_chorus(scope, envelope)` — costruisce stesso envelope del designer (full canon + `worldbuilding.md` + brief) e lancia advisor in parallelo (concurrency 2, 3-4 wave), raccoglie JSON `{"findings":[...], "suggestions":[...]}`.
- 4 prompt specializzati in `assets/prompts/`: `chorus-world-exploiter.md`, `chorus-bestseller.md`, `chorus-science-coherence.md`, `chorus-continuity.md` + pro generalista — copre i 3 assi manuali (sfruttamento worldbuilding, bestseller, coerenza hard).
- Advisory-only: scrive `.book-forge/chorus/<scope>/<ts>/` + `chorus-report.md` + `chorus-synthesis-input.json`, mai canon. Validazione `location` via `_resolve_evidence_target` fail-closed (M29/M30). Non entra nel DAG (`plan.json`); `pause`/`resume` non lo toccano.
- Integrazione in `execute_universe_design` e `execute_book_design`: se `chorus.enabled` (default true) → chorus prima del designer, poi designer, poi audit. Con `--no-chorus` o `--chorus-models <csv>` si fa override. La stessa `run_chorus` sarà riusabile per future fasi pre-`run` senza duplicare codice.
- CLI: `book-forge design <universe|book> [--no-chorus] [--chorus-models <csv>] [--chorus-synthesizer <id>]` — senza flag stampa lista modelli confermata e prosegue.
- Budget separato: chorus 6-7 call + synthesis 1, non conteggiati in `design_call_budget`.

**Tasks:**
- [x] Creare `references/chorus.md` e 4 prompt advisor + wiring `run_chorus`
- [x] Integrare chorus in `execute_universe_design` / `execute_book_design` con flag `--no-chorus` / `--chorus-models`
- [x] Scrittura `.book-forge/chorus/` + report umano, validazione evidence
- [x] Test: chorus produce findings advisory con hash binding, `--no-chorus` salta, `--chorus-models` filtra (mock)
- [x] Commit & push

**Done when:** `design universe` e `design book` girano con chorus di default (conferma modelli stampata), producono report advisory senza toccare canon; `--no-chorus` li salta; future fasi pre-`run` possono chiamare `run_chorus`.

### M34: Synthesis gate (deduplica, ranka, patch proposte) ✅

**Status: done — 2026-08-23**

**Depends on:** M33

**Why:** 6-7 advisor producono findings sovrapposti; serve un gate che deduplica, ranka `blocking/warning/note` e propone patch testuali senza auto-applicarle — l'autore resta decisore.

**Approach:**
- Nuovo agent `chorus-synthesizer` (`openrouter/deepseek/deepseek-v4-pro-0813`, `max`) + comando `book-forge chorus synthesize <scope>` che legge `.book-forge/chorus/<scope>/` e produce `chorus-synthesis.json` con patch proposte (diff testuali, `location` + `hash` ricalcolato).
- `book-forge chorus apply --pick F-...` o patch manuale → poi `design` riparte con brief/worldbuilding aggiornato. Mantiene *source authoritative + stale tracking*.
- `status` mostra `chorus: pending/clean/stale`.

**Tasks:**
- [x] Agent `chorus-synthesizer` + `chorus synthesize` / `chorus apply` wiring
- [x] Deduplica + ranking + patch proposte con evidence hash binding
- [x] `status` chorus state
- [x] Test: synthesis deduplica, ranking corretto, apply non auto-scrive canon (mock)
- [x] Commit & push

**Done when:** `chorus synthesize` produce `chorus-synthesis.json` con patch rankate e hash binding; `apply`/`status` coerenti; suite green.



## Phase J — Chorus completeness (standalone + loop closure) ✅

### M35: Standalone chorus run + interactive confirmation ✅

**Status: done — 2026-08-23**

**Depends on:** M33

**Why:** Il chorus oggi gira solo dentro `design universe/book`. Il miglioramento manuale su `worldbuilding.md` e `book-brief.json` avveniva fuori dal designer — serve un comando standalone `chorus run` che lancia gli advisor sul canon attuale senza far partire il designer, e una conferma interattiva dei modelli in TUI opencode (oltre al flag `--chorus-models`).

**Approach:**
- Nuovo `book-forge chorus run [universe|book --book ID] [--chorus-models <csv>] [--no-chorus]` — costruisce lo stesso envelope del designer (full canon + worldbuilding + brief) e chiama `run_chorus` direttamente, senza designer/auditor.
- In `main`, prima di dispatchare, stampa lista confermata su stderr e, se in TUI interattiva (orchestrator), chiede conferma `Confermi modelli? [Y/n]` (timeout non bloccante in CLI).
- Aggiorna `references/chorus.md` e `SKILL.md` route table.

**Tasks:**
- [x] Aggiungere `chorus run` subcommand e wiring a `run_chorus` standalone
- [x] Conferma interattiva lista modelli (print + optional prompt quando in orchestrator)
- [x] Test: `chorus run` produce report advisory senza designer, `--chorus-models` filtra
- [x] Commit & push

**Done when:** `chorus run` standalone produce `.book-forge/chorus/<scope>/<ts>/` senza designer; lista modelli confermata stampata; suite green.

### M36: Design con contesto chorus + chiusura docs ✅

**Status: done — 2026-08-23**

**Depends on:** M35

**Why:** Oggi il designer non vede i findings del chorus (stesso envelope di prima). Per sfruttare davvero il worldbuilding/bestseller/coerenza, il secondo `design` dovrebbe poter ingerire il report del chorus. Serve un flag opt-in che inietti il report nel task capsule, plus docs e test dedicati.

**Approach:**
- Nuovo flag `design ... --with-chorus-context` (opt-in) — se presente e esiste un chorus precedente per lo scope, inietta `chorus_report` (findings + suggestions) nel `task_capsule` del designer.
- Aggiorna `references/design.md` per menzionare il default-on chorus e il flag `--with-chorus-context`.
- Aggiunge `tests/test_chorus.py` con mock che verifica: `chorus run` standalone, `--no-chorus` skip, `--with-chorus-context` inietta report, `chorus synthesize` deduplica.

**Tasks:**
- [x] Aggiungere `--with-chorus-context` a `design` e iniezione nel task capsule
- [x] Aggiornare `references/design.md` + `SKILL.md`
- [x] Creare `tests/test_chorus.py` (mock, no LLM)
- [x] Commit & push

**Done when:** `design --with-chorus-context` inietta il report del chorus nel designer; docs aggiornati; `test_chorus.py` green; suite 85+ passed.



### M37: Rimuovi Graphify e ridefinisci coldread con sola sintesi pregressa ✅

**Status: done — 2026-08-23**

**Depends on:** M34

**Why:** Graphify resta citato in SKILL e DEVPLAN anche se fuori dal path — genera confusione su prerequisiti opencode e deve essere rimosso totalmente. Il coldread attuale in `run` legge con canon completo; serve invece un lettore fresco che legga il capitolo con sole info sintetiche dai capitoli precedenti (reader-state compatto + boundary precedenti), come un lettore reale che non ha il bible sotto gli occhi.

**Approach:**
- Rimuovere ogni riga Graphify da SKILL.md e DEVPLAN.md.
- Ridefinire `cold-reader` per ricevere solo sintesi pregressa: `reader_state` + `previous_boundaries` compatti (non full canon), oltre al contract del capitolo.
- Aggiornare `assets/prompts/cold-reader.md` e `references/run.md` per riflettere il nuovo envelope sintetico.
- Nessuna dipendenza da `graphify-out/` o tool.

**Tasks:**
- [x] Rimuovere riferimenti Graphify da SKILL.md e DEVPLAN.md
- [x] Ridefinire cold-reader envelope sintetico (reader_state + previous boundaries)
- [x] Aggiornare prompt e references/run.md
- [x] Test: cold-reader riceve solo sintesi, non full canon (verificato manuale, suite 89 passed)
- [x] Commit & push

**Done when:** Nessun file in book-forge menziona Graphify; cold-reader gira con sola sintesi pregressa e suite green.


### M38: Persisti la sintesi pregressa a ogni capitolo ✅

**Status: done — 2026-08-23**

**Depends on:** M37

**Why:** La `previous_synthetic` per il cold-reader è oggi costruita al volo leggendo `reader-state.md` + ultime 2 boundary e messa solo in `task_capsule`. Se non è scritta come artifact, si perde tra i run, non è versionata, non è auditabile e non è riusabile da `design --with-chorus-context` o da un `coldread` standalone.

**Approach:**
- Dopo ogni `reviser` (chiusura capitolo), genera un file persistito `books/<book>/reviews/<chapter>/previous-synthetic.md` (o `coldread-state/<book>-<chapter>.md`) con sinossi compatta 2-3 frasi per capitolo (derivata da `reader-state.md` + `boundary`), registralo come artifact con hash e dipendenze, e usalo come sorgente per il prossimo `cold-reader` invece di ricostruirlo al volo.
- Il `cold-reader` legge quell'artifact (se presente) + `reader-state.md`, non ricostruisce da `manuscript/chapters` a mano.
- `status` mostra `coldread_state: current/stale`.

**Tasks:**
- [x] Generare e registrare `previous-synthetic.md` dopo ogni reviser
- [x] Far leggere al cold-reader l'artifact persistito invece di ricostruirlo
- [x] Test: dopo chiusura capitolo, artifact esiste e cold-reader lo usa (manuale, 89 passed)
- [x] Commit & push

**Done when:** Dopo ogni capitolo chiuso esiste un artifact sintesi persistito, versionato e usato dal cold-reader successivo; suite green.



### M39: Aggiungi Luna al default chorus e ai modelli globali ✅

**Status: done — 2026-08-23**

**Depends on:** M32

**Why:** Luna (`openai/gpt-5.6-luna`) aggiunge diversità OpenAI con buon mix qualità/costo (46.9/71.4, 0.156/mtok) — provider assente nel default 7.

**Approach:**
- `CHORUS_DEFAULT_MODELS` 7 → 8 aggiungendo `openrouter/openai/gpt-5.6-luna` con `provider openai` e varianti `low/medium/high/max`
- `~/.config/opencode/opencode.json` whitelist + `models[openai/gpt-5.6-luna]`
- Prompt `advisor-openai-gpt-5-6-luna.md` (da `chorus-bestseller`)

**Tasks:**
- [x] Aggiungere Luna a `CHORUS_DEFAULT_MODELS` e `CHORUS_MODEL_CONFIGS`
- [x] Aggiungere a global opencode whitelist/models
- [x] Test: 8 modelli default, 8 advisor (89 passed)
- [x] Commit & push

**Done when:** Default 8, global config con Luna, suite green.


## Out of scope

- Guaranteed detection of undeclared facts that both writer disclosure and technical review miss.
- Automatic translation creation or unrequested bulk translation.
- Multi-provider ensembles outside the chorus; primary creative roles stay pinned to the DeepSeek flash model, chorus uses the configured ensemble.
- Implicit multiverse inheritance; alternate continuities import shared material explicitly.
- Changing source language after the first source chapter closes.
- Audiobook or cover generation, ISBN procurement, DRM, storefront upload, or print-on-demand integration.
- Automatic source-prose rewriting after canon changes; the system schedules evidence-backed repair tasks.

## Unassigned milestones

### M28: Let a validation-blocked design task be explicitly retried ✅

**Status: done — 2026-08-22**

**Why:** When a designer or canon-auditor contract fails validation,
`_set_attempt_failure(..., block=True)` sets the task to `blocked` and the run
to `blocked`. `resume` reopens the run but leaves the task `blocked`, and
`ready_frontier` only dispatches `pending` tasks, so the design route can never
be retried after a validation failure: `design universe` fails with
`Task is not ready`. There is no supported recovery path for the most common
failure class (incomplete model contract). Observed live on the Landfall
project: the first designer attempt returned empty `eras/events/places/
factions/characters/themes` (`creative-contract.incomplete`) and the universe
design has been stuck blocked ever since.

**Approach:** Add an explicit, receipted retry resolution that mirrors the
existing `outcome_unknown` handling:

1. `resume --resolve-blocked TASK:retry` — for tasks whose last attempt is
   `validation_failed`: mark that attempt `orphaned` with
   `resolution: retry`, set the task back to `pending`, and clear `attempt`.
2. `ready_frontier` and `claim_task` are untouched; the task re-enters the
   frontier naturally once `pending`.
3. `status` reports the resolution in the attempt telemetry.

**Out of scope:** automatic retry, editing plan.json by hand, changing the
validation rules themselves.

**Tasks:**
- [x] Add `--resolve-blocked` to the `resume` parser and `resume_run`
- [x] Validate the attempted task state is `validation_failed` before resolving
- [x] Cover the new resolution in `tests/test_lifecycle.py`
- [x] Re-run the full test suite in the dev tree
- [x] Deploy with `install.sh --force`
- [x] Then on Landfall: `resume --resolve-blocked DESIGN-UNI-0001:retry` and
      re-run `design universe`

**Done when:** A fixture design that failed validation becomes retryable via
one explicit `resume --resolve-blocked` call, and the Landfall universe design
reaches `design_clean`.

### M29: Bind design-audit evidence to helper-computed SHA-256 ✅

**Status: in progress — 2026-08-22**

**Why:** `_validate_audit_output` requires every evidence item to carry a
SHA-256, but the canon-auditor is a tool-less model: it cannot compute hashes
and omits or hallucinates them. Observed live on Landfall (ATT-0005): the
designer contract passed and was promoted, then the audit failed validation
with `Audit evidence requires a stable location and SHA-256`, blocking
`design_clean` even though the findings were substantive.

**Approach:** The control plane binds the hashes, never the model. In
`_design_audit_record`, after parsing the auditor's findings, replace each
evidence item's `hash` with a helper-computed SHA-256 resolved from the
`location` string against the promoted artifacts:

- `LAW-####/PLC-####/FAC-####/CHR-####` (+ optional `#fragment`) → the canon
  file `universe/canon/<topics|places|factions|characters>/<id>.md`
- `ERA-####` → `universe/timeline/eras.yaml`; `EVT-####` → `events.yaml`
- `CH-####` (book design) → `books/<book>/chapters/<id>.json`
- `proposal.*` → the promoted design artifact (`universe/design.json` or
  `books/<book>/design.json`)
- any other relative path that exists → that file
- otherwise → raise (fail closed; evidence must be stable)

The model-supplied `hash` is always discarded and recomputed.

**Tasks:**
- [x] Add `_bind_audit_evidence` and call it in `_design_audit_record` (universe and book design share it)
- [x] Test: auditor returns findings with hallucinated/absent hashes → promoted audit carries real SHA-256 of the resolved files; unresolvable location raises
- [x] Re-run the full test suite in the dev tree
- [x] Deploy with `install.sh --force`
- [x] On Landfall: `resume --resolve-blocked AUDIT-UNI-0001:retry` + `design universe`

**Done when:** A design audit whose model output carries no trustworthy hashes
still promotes a `design_clean` record with helper-computed SHA-256 evidence,
and Landfall reaches `design_clean`.

### M30: Resolve book-scoped proposal evidence locations in the audit binder ✅

**Status: in progress — 2026-08-22**

**Why:** Observed live on Landfall (ATT-0008): the book design succeeded and
was promoted (`books/BOOK-0001/design.md`, `chapters/CH-0001.json`,
`outline.yaml`), then the canon-auditor's findings failed binding with
`Audit evidence location is not a stable artifact:
BOOK-0001#proposal/turns/TURN-0004`. M29's `_resolve_evidence_target` accepts
`proposal.*` (bare prefix) for both scopes, but for book design the auditor
naturally cites book-prefixed locations —
`BOOK-#### #proposal/turns/TURN-####` and
`BOOK-#### #proposal/chapters/CH-####[#/beats/...]` — which fall through to
the `root / location` branch and raise.

**Approach:** Extend `_resolve_evidence_target` so book-scoped proposal
locations resolve to stable artifacts:

- `BOOK-#### #proposal/...` (the prefix matches the scope book) → the book's
  promoted design artifact `books/<book>/design.md`; if the suffix names a
  chapter (`chapters/CH-####`, with or without `/beats/...`) and that chapter
  contract exists, resolve to `books/<book>/chapters/CH-####.json` instead.
- `UNI-#### #<block>` or any indexed `<owner>#<block>` address → the file the
  index maps that block to (observed live: `UNI-0001#kernel`).
- `task.design_scope...` / `design_scope...` envelope paths, anywhere in the
  location string (observed live on the retried book audit, including
  prose-annotated forms like `BEAT-0003 (design_scope.proposal.chapters[0]
  .beats[2], unhashed in envelope)`): `proposal...` → the design artifact;
  `chapters.CH-####...` → that chapter contract; `entry_state...` /
  `exit_boundary...` → `reader-state.md`.
- Any other `BOOK-#### #...` location that does not match the scope book →
  still unresolved (fail closed).
- Universe scope unchanged; `proposal.*` keeps its current meaning.

Also give `execute_book_design` the audit-only resume path that
`execute_universe_design` already has (M29): when `DESIGN-{book}` is
`succeeded`, rebuild the proposal from the promoted artifacts
(`design.md`, `outline.yaml`, `reader-state.md`) and run only the audit.
Without it, a blocked book audit can never be retried — the route re-enters
the designer task, which is not in the ready frontier (`Task is not ready`).
Observed live on Landfall (RUN-0002).

**Tasks:**
- [x] Parse `BOOK-\d{4}#proposal...` in `_resolve_evidence_target`
- [x] Add audit-only resume to `execute_book_design` with `_book_proposal_from_artifacts`
- [x] Test: auditor cites `BOOK-0001#proposal/turns/TURN-0004` and
      `BOOK-0001#proposal/chapters/CH-0001/beats/BEAT-0004` → hashes bound
      from `design.md` / `chapters/CH-0001.json`; a foreign `BOOK-0009#...`
      still raises; book audit retries alone after design promotion
- [x] Re-run the full test suite in the dev tree
- [x] Deploy with `install.sh --force`
- [x] On Landfall: `resume --resolve-blocked AUDIT-BOOK-0001:retry` +
      `design book --book BOOK-0001`

**Out of scope:** changing the auditor prompt, re-designing the book, the
warning content of ATT-0008's findings (the design's own duty/obligation
inconsistency is a separate project-side fix if it persists after the audit
succeeds).

**Done when:** The Landfall book design audit promotes with helper-computed
hashes (design_clean or findings-with-evidence), and the fixture test proves
book-scoped locations bind.

### M31: Book design brief — full canon context, author brief gate, no wrap ✅

**Status: done — 2026-08-22**

**Why:** Observed live on Landfall (ATT-0007): the book designer's envelope
carried only `UNI-0001#kernel` (5 laws) plus the empty relation/obligation
lists. The worldbuilding bible (§18 "Book 1 Load", 1520 AL, seven
role-shaped holes, characters, places, factions, timeline, style) never
reached the designer, so it invented a Landing prequel and an unreviewed
"sleeper" protagonist — a story the user never agreed to. Additionally the
user requires: (a) a mandatory author brief for `design book` (characters,
plot, length, tone) that fails closed when absent instead of inventing;
(b) no hard-wrapping of prose/lines anywhere in generated artifacts.

**Approach:**

1. **Author brief file.** `design book` now reads
   `books/<book>/book-brief.json` (`{schema, premise, characters, plot,
   tone, length_notes}`). If missing, `execute_book_design` fails closed
   with a message telling the author to create it (mirrors the universe's
   `design-brief.json` pattern). A CLI `--brief "<json>"` may create it.
2. **Full canon context.** The designer's envelope for a book now closes
   imports over the whole canon — `UNI-0001#kernel` plus every indexed
   block reachable from the universe (LAW/PLC/FAC/CHR/ERA/EVT summaries,
   style) and the authored `universe/worldbuilding.md` (when present),
   instead of only the kernel. Budget stays bounded by the existing
   envelope input budget (context overflow still hard-fails).
3. **No wrap.** Audited every writer path: helper writes JSON with
   `indent=2` (canonical, not prose) and markdown as single long lines —
   no soft wrap is introduced anywhere. The wrap the user saw lives only
   in hand-authored DEVPLAN-*.md files; the rule is now documented in the
   skill reference (`design.md`) and in AGENTS conventions: never break a
   line mid-sentence; one sentence per line; no width limit.

**Tests:** fixture proves (a) missing brief raises a closed failure,
(b) brief-injected task capsule reaches the designer, (c) book designer
context includes canon blocks beyond the kernel (e.g. a FAC summary) and
worldbuilding.md, (d) generated design.md/premise/arc strings contain no
mid-sentence line breaks (each line ends with punctuation or is a
structural line).

**Done when:** suite green; Landfall book design passes the new gate
(brief file exists), and the envelope for DESIGN-BOOK-0001 carries the full
canon context.

## Fix: chorus `run_opencode_role` root resolution (2026-08-23)

**Bug:** `run_opencode_role` derives the project root with
`root = attempt_dir.parents[4]`, which only holds for the run-attempt layout
(`root/.book-forge/runs/RUN-x/attempts/ATT-x`). `run_chorus` and the chorus
synthesizer pass a system `tempfile.mkdtemp` directory in `/tmp` as the
attempt dir → `parents[4]` raises `IndexError`; `chorus run` aborts before
dispatching. The mock-provider chorus tests never exercise this line, so the
suite stayed green.

**Fix:**
1. New pure helper `_project_root_from(attempt_dir)` — walk up to the nearest
   ancestor containing a `.book-forge` directory; raise `BookForgeError` when
   none exists (fail closed, no silent fallback).
2. `run_opencode_role`: use `_project_root_from(attempt_dir)` instead of the
   fixed-depth slice; keeps the `cwd` contract for both run attempts and
   chorus dirs.
3. `run_chorus.dispatch_one` and the synthesizer path in
   `run_chorus_synthesis`: create tmp dirs with
   `mkdtemp(dir=root / ".book-forge" / "chorus" / ".tmp")` so the attempt dir
   lives under the project root and `cwd` resolves correctly; existing
   `finally: rmtree` cleanup unchanged.
4. Tests: unit-test `_project_root_from` (resolves from run-attempt depth and
   from the chorus tmp depth; raises on an orphan dir). No change to chorus
   mock-provider tests — they stay as-is.

**Second bug (same code path):** the resolved-pin check in
`run_opencode_role` compared every role against the single primary model
(`modelID != MODEL.split("/",1)[1]` and `variant != ROLE_SPECS[role][1]`).
Chorus advisors resolve to their own pinned model and effort (e.g.
`qwen/qwen3.8-max`/`xhigh`), so every advisor would fail the check with
`Resolved OpenCode agent pin differs`; the synthesizer (`pro`) would fail it
too, and `ROLE_SPECS[role][1]` would `KeyError` for any advisor.

**Fix:**
5. New `CHORUS_ADVISOR_MODELS` reverse map (advisor name → model id) and
   `_expected_pin(role)` returning the expected `(model_id, variant)` per role
   class, mirroring exactly what `_write_agents` writes: `ROLE_SPECS` roles →
   flash + their variant; advisor roles → their own model + per-model
   `default_effort`; `chorus-synthesizer` → pro + its `default_effort`.
6. `run_opencode_role` checks against `_expected_pin(role)` and reports the
   resolved model id in the result, so telemetry no longer mislabels advisors
   as flash.

**Third bug (same run):** `run_chorus` aborts the whole standalone `chorus
run` when a single advisor returns malformed output (e.g. a finding missing
`id`) — `dispatch_one` had no per-advisor catch, while the `design` wrappers
already print "Chorus advisory failed (non-blocking)". Advisory means
advisory: one bad advisor must not kill the pass.

**Fix:**
7. `dispatch_one` catches any per-advisor exception and returns
   `{"findings": [], "suggestions": [], "error": <reason>}` instead of
   raising; the human report marks the advisor `FAILED (non-blocking)` with
   the reason, and `chorus synthesize` simply sees no findings from it.
8. Test: one advisor in the mock returns a finding without `id` → `run_chorus`
   completes, the failed advisor is recorded with an error, others'
   findings survive.

**Fourth blocker (book scope):** the book-design envelope carries the full
worldbuilding bible + brief + closed canon context (~45k estimated tokens on
Landfall), which overflowed the fixed 16k designer/advisor budget — the
documented `design book`/`chorus run --book` routes could never run
programmatically, which is why the author did the book design by hand. The
generated `context.writer_max_input_tokens` knob in `book-forge.yaml` was
vestigial (never read by `build_envelope`).

**Fix:**
9. New `_envelope_input_budget(root, role)`: honors `context.design_max_input_tokens`
   from `book-forge.yaml` for the `designer` role and all `advisor-*` chorus
   roles (they share the same context contract); falls back to `ROLE_BUDGETS`;
   fails closed on a malformed override value.
10. `build_envelope` and the telemetry `envelope_budget` check use it, so a
    project may raise the design ceiling without weakening the hard-fail
    overflow guard (no silent truncation).
11. Generated default `book-forge.yaml` now includes
    `design_max_input_tokens: 16000` (self-documenting, unchanged behavior);
    Landfall sets it to `48000`. `runtime sync` does not rewrite
    `book-forge.yaml`, so the override survives.
12. Tests: override applies to designer + advisors, not to writer/auditor;
    malformed override fails closed; defaults unchanged.

**Done when:** suite green; `book-forge chorus run` (universe, 8 models)
completes and writes `.book-forge/chorus/<scope>/<ts>/` artifacts, followed by
`chorus synthesize`.

## Fix: canon promotion loses designer row content (2026-08-23)

**Bug:** Observed live on Margherita (RUN-0001, ATT-0003): the universe
designer's proposal rows carry content under `invariant` (places, factions,
characters) and `law` (kernel), but `_canon_markdown` reads only
`row['summary']`. Promotion therefore wrote canon files whose
`<!-- bf:block summary -->` blocks are empty: 16 hollow files, the kernel's
`bf:import` targets point at empty law summaries (the auditor's F-0001
warning), and any full-canon consumer (book design, M31) would close over
contentless canon. The run still promoted as `design_clean` because nothing
fail-closes on contentless rows.

**Fix:**
1. `_row_summary` helper resolves row content by ordered fallback
   `summary` → `invariant` → `law` (first non-empty string);
   `_canon_markdown` promotes that text verbatim into the summary block.
2. `validate_universe_design` fail-closes with `canon-row.content-missing`
   (blocking) when a kernel/place/faction/character row carries no content
   in any accepted key, so hollow canon can never promote silently again.
3. Tests: promotion maps `invariant`/`law` rows into non-empty summary
   blocks (explicit `summary` still wins, `voice` still honored); a
   contentless row blocks validation.

**Second bug (same run):** the designer's row shape is not pinned — one run
emits lists of `{id, name, summary}` rows, the next emits ID-keyed dicts
(`"characters": {"CHR-0001": {...}}`), kernel laws as plain strings, and
character names under `label` with content split across `fact` and
`invariant`. `_validate_id_rows` fail-closes on the dict shape
("Universe proposal field kernel must be a list"), and the list shape drops
`fact` content at promotion. Both shapes are reasonable readings of the
contract's "CHR-#### rows", so the control plane normalizes them instead of
trusting one spelling.

**Fix:**
4. `_normalize_universe_proposal` converts ID-keyed dict categories
   (kernel/eras/events/places/factions/characters) into row lists: dict
   values merge with the key as `id` (`label` maps to `name`), plain string
   values become `{"id", "summary"}` rows. Applied where raw designer output
   enters, in `execute_universe_design`.
5. `_row_summary` preserves more designer content: an explicit `summary`
   wins; otherwise the non-empty prose fields `fact`, `invariant`, `law`
   join in that fixed order, so character fact+invariant pairs promote
   whole instead of losing `fact`.

**Third bug (same run):** the retried designer emitted a third row shape —
lists again, but content under `statement` (kernel) and `description`
(places/factions/characters). The fail-closed check from part 2 caught it
precisely (one `canon-row.content-missing` per hollow row) instead of
promoting silently, which is the guard working as designed; the residual
defect is that the envelope's `required_output` never pinned the row keys,
so every run re-rolls them.

**Fix:**
6. `_row_summary` accepts the full observed key family: explicit `summary`
   wins; otherwise the non-empty prose fields join in fixed order
   `fact`, `description`, `invariant`, `statement`, `law`.
7. The universe designer envelope's `required_output` pins each row shape
   explicitly (`{id, name, summary}` plus `era`/`order` for events), so a
   compliant model needs no guessing while the tolerant fallback stays as
   defense.

**Done when:** suite green; on Margherita a re-run `design universe` promotes
canon files with real content and non-empty kernel law imports.

## Fix: canon depth and pre-book redesign (2026-08-23)

**Bug:** Observed live on Margherita: the promoted canon carries one short
summary per entity — no physical characterization, no speech patterns, no
backstory, no sensory texture for places — because (a) `_canon_markdown`
emits only `summary` plus a `voice` block the designer never produces,
(b) the designer's `required_output` pins bare `{id, name, summary}` rows,
and (c) once `DESIGN-UNI-0001` succeeds, `execute_universe_design`
early-returns forever, so the cast can never be enlarged or enriched with an
updated brief. The writer therefore cannot receive character depth through
any channel: chapter contracts close imports over canon blocks only, and
`worldbuilding.md` reaches the book designer but never the writer.

**Fix:**
1. `_canon_markdown` promotes a whitelisted family of optional detail
   blocks — `voice`, `appearance`, `past` (characters), `sensory`
   (places) — each a non-empty row field becoming its own addressable
   `<!-- bf:block X -->`, importable per chapter by the book designer.
2. The universe designer envelope pins the richer row shapes
   (`characters: {id, name, summary, voice, appearance, past}`,
   `places: {id, name, summary, sensory}`) and its output allowance rises
   5000 → 8000 (designer output budget cap 5000 → 8000) so depth fits.
3. New `design universe --refresh`: resets the design and audit tasks
   (attempts orphaned with `resolution: refresh`), re-runs the full
   designer/auditor cycle against the current brief, and sweeps canon
   files whose IDs the new proposal no longer contains. Fail closed when
   any book exists — post-book canon growth flows through the artifact
   currentness/repair machinery, not wholesale redesign.

**Status: done — 2026-08-23.** Suite 107 passed; deployed with
`install.sh --force`. Live verification on Margherita (enriched brief →
`--refresh` → canon with voice/appearance/past/sensory blocks) still
pending — next project session.

**Done when:** suite green; on Margherita a `--refresh` run against an
enriched brief promotes a larger cast with voice/appearance/past/sensory
blocks.

## Phase K — Anti-truncation, Brief Gate, Verbosity, Tiered Cast

### M40: M1 — Fix truncation length @41KB ✅

**Status: done — 2026-08-23**

**Objective:** Stop 41KB truncation by chunking design output, raising output budget, and handling `finish_reason==length`.

**Tasks:**
- [x] Implement per-chunk generation (<15KB per chunk) splitting universe design into chunks (characters, places, etc.)
- [x] Raise `max_tokens` to 8192–12288 in `agents/openai.yaml` and `scripts/book_forge.py` (ROLE_BUDGETS designer)
- [x] Add retry logic for `finish_reason==length` (max 2 retries), then mark ATT `failed_length` not `outcome_unknown`
- [x] Compact `SKILL.md` system prompt to reduce input tokens
- [x] Update `references/design.md` prompt to generate per-chunk and pin chunk contract
- [x] Update `scripts/book_forge.py` and `agents/openai.yaml` to wire chunking and retry
- [x] Create `tests/test_design_chunking.py` covering chunk size, retry, and failure mode

**Acceptance Criteria:**
- No design output exceeds 15KB per chunk; 41KB monolith never produced
- Designer output budget 8192–12288; envelope respects new limit
- On `length` finish, helper retries up to 2 times; after exhaustion attempt is `failed_length` (not `outcome_unknown`)
- `SKILL.md` remains <300 lines after compaction
- `references/design.md` documents per-chunk generation

**Tests:**
- `tests/test_design_chunking.py` — chunk size bound, max_tokens budget, retry on length, failed_length terminal state

### M41: M2 — Brief gate default ON with --skip-brief ✅

**Status: done — 2026-08-23**

**Objective:** Gate every design behind an author brief so the designer never invents the story.

**Tasks:**
- [x] Create `references/brief.md` documenting the 00-BRIEF gate
- [x] Create `scripts/brief.py` implementing gate logic and validation
- [x] Add 00-BRIEF gate with 7 questions: length/format, genre/world, protagonists, premise/conflict/ending, themes, style/POV/register, constraints/audience
- [x] Default ON; bypass only via `--skip-brief` or answer "usa default"
- [x] Wire gate into `references/init.md` and `references/design.md`
- [x] Update `SKILL.md` route table to expose brief route and flags

**Acceptance Criteria:**
- `design universe` and `design book` block without brief unless bypass flag/value present
- `00-BRIEF` asks exactly 7 questions covering the required axes
- `--skip-brief` and "usa default" both bypass the gate
- `references/brief.md` and `scripts/brief.py` exist and are installed

**Tests:**
- Unit — gate blocks without brief, passes with brief, bypass via flag and via "usa default", 7-question shape

### M42: M3 — Verbosity step-by-step ✅

**Status: done — 2026-08-23**

**Objective:** Make long design runs observable with deterministic step logging.

**Tasks:**
- [x] Add verbose logging in `scripts/book_forge.py` for design: [1/7]..[7/7] with →/✓/✗, length → retry
- [x] Update `assets/opencode/book-forge-orchestrator.md` to emit same step log
- [x] Emit final summary with artifact paths for every design run

**Acceptance Criteria:**
- Every design run prints [1/7]..[7/7] steps with →/✓/✗ markers
- `length` finish shows retry marker before next attempt
- Final summary lists all promoted artifact paths

**Tests:**
- Unit — log sequence [1/7]..[7/7], retry marker on length, summary contains artifact paths

### M43: M4 — Anti-laziness tiered cast/locations ✅

**Status: done — 2026-08-23**

**Objective:** Enforce rich tiered canon so the model cannot be lazy on cast and places.

**Tasks:**
- [x] Implement tiered schema: L1 1–3 protagonists 250–350w (want/need/flaw/wound/arc/voice/secret), L2 4–7 secondaries 150–200w, L3 6–12 ricorrenti 60–90w, L4 10–20 comparse 1 line, total_named >=22 for 80k scaled with length; places L1 3–5, L2 5–8, L3 6–12, total >=14
- [x] Update `references/design.md` prompt to enforce tier counts and word ranges
- [x] Create `scripts/validate.py` with asserts for each tier and graph connectivity check
- [x] Split characters into 2 sub-chunks (L1+L2 and L3+L4) to stay within per-chunk budget
- [x] Create `tests/test_validate_tiers.py` covering tier counts, word ranges, total thresholds, and connectivity

**Acceptance Criteria:**
- Universe proposal with <22 named characters (at 80k) or <14 places fails validation
- Each tier count and word range enforced; L1 requires want/need/flaw/wound/arc/voice/secret fields
- Graph connectivity check fails on disconnected canon
- Characters emitted as 2 sub-chunks

**Tests:**
- `tests/test_validate_tiers.py` — tier counts, word ranges, scaled totals, connectivity, sub-chunk split

## Milestone 5 — Audit input budget 32k configurable (canon-auditor) ✅ Done

**Status:** ✅ Done

**Problem:** AUDIT-BOOK-0001 hard-fail: capsule 19.8k (10.3k proposal + 9.5k canon) > 16k fixed budget.

**Solution:** Raise default audit input budget from 16k to 32k and make it configurable via book-forge.yaml (`audit.input_budget`, default 32000). Keep hard-fail with explicit error `estimated_input > budget`. No change to imports (full canon visible).

**Tasks:**
- [x] Add knob `audit.input_budget` to book-forge.yaml with default 32000 and validation
- [x] Update canon-auditor budget check in scripts/book_forge.py (or where budget enforced) to read knob, default 32k, hard-fail with clear message
- [x] Update references/audit.md to document knob and error
- [x] Update agents/openai.yaml if needed for audit role budget
- [x] Test: capsule 19.8k passes, 33k fails with hard-fail, knob override works
- [x] install.sh --force and re-run `design book` audit only

**Acceptance:**
- AUDIT-BOOK-0001 passes with 19.8k capsule, hard-fail still triggers when estimated > 32k, knob override verified.

**Tests:**
- Unit — capsule 19.8k passes new default, 33k fails with `estimated_input > budget`, knob override respected

## Fix: designer word-count mismatch + repair cumulativo (M44) ✅

**Status: done — 2026-08-24**

**Problem:** `DESIGN-UNI-0001` blocked in loop cieco su Margherita (RUN-0002 gen 26-29, 33 attempt ATT-0005..0037). Causa radice in due difetti accoppiati:
1. Prompt designer `L2 4-7 secondaries 150-200 words` non definisce come contare; validazione `scripts/validate.py:validate_tiered_cast` conta il combinato di 10 campi `summary+voice+appearance+past+want+need+flaw+wound+arc+secret` con `\b[\w''-]+\b`. Il modello conta diversamente (solo summary) → mismatch deterministico, `tier.L2.words` blocking su 5/5 retry ultimi.
2. Repair feedback `scripts/book_forge.py:3678` (`3811` per book) inietta solo `str(last_failure.get("failure"))` — l'ultimo failure isolato. Nessun accumulo → ogni retry riparte cieco, nessuna convergenza.

**Fix:**
1. `scripts/book_forge.py:3693` `required_output["characters"]` — esplicitare per ogni tier che `words = combined count across summary+voice+appearance+past+want+need+flaw+wound+arc+secret joined with space (exactly as validate.py word_count with \b[\w''-]+\b)`; aggiungere stessa riga per L1/L2/L3/L4 con range corretti e nota che `L4 <20w` è su combinato.
2. `scripts/book_forge.py:3678-3679` e `3811-3812` — repair cumulativo: nuovo helper `_collect_validation_failures(plan, task_id, limit=5)` che raccoglie ultimi 5 failure dedup per `code` da `plan.json`/`transactions`, inietta `{"repair": {"validation_errors": [...full JSON findings...], "hint": "word count is combined across 10 fields; tier.*.words and tier.*.count are enforced; include tier field"}}` invece del singolo `str()`. Fallback a singolo se solo uno.
3. `references/design.md` §Anti-laziness — allineare descrizione tier con stessa definizione di conteggio combinato.
4. `scripts/validate.py` invariato (canonical).
5. Test: estendere `tests/test_validate_tiers.py` con caso L2 160w su summary ma >200w combinato → blocking; test repair cumulativo su `_collect_validation_failures`.
6. `install.sh --force` e verifica su Margherita (`design universe` resume).

**Acceptance:**
- Prompt designer e validazione concordano sul conteggio combinato 10 campi
- Repair contiene fino a 5 failure cumulati, non solo l'ultimo
- Suite verde (`pytest -q`)
- Su Margherita `DESIGN-UNI-0001` non ripete `tier.L2.words` con stesso profilo con repair successivo

**Tasks:**
- [x] Patch `scripts/book_forge.py` required_output + repair cumulativo
- [x] Patch `references/design.md`
- [x] Test cumulativo + word-count combinato
- [x] `install.sh --force` + verifica Margherita (suite 41 pass su tier/chunking + full suite pending)

## Fix: canon-auditor evidence locations must be stable artifacts (M46) ✅

**Status: ✅ Done — 2026-08-25**

**Problem:** `AUDIT-UNI-0001` blocked in loop su Margherita (ATT-0041/0042/0053): l'auditor cita location non risolvibili (`CNT-0001`, `CNT-0001#continuity_material`, `CNT-0001#continuity-material`, `unresolved_questions#1`) e `_bind_audit_evidence` fallisce con `Audit evidence location is not a stable artifact`. Il prompt `assets/prompts/canon-auditor.md` dice genericamente `stable path or block ID`; il modello interpreta `CNT-*`/`UNI-*` come block ID, ma `_resolve_evidence_target` (universe scope) risolve solo `LAW-####|PLC-####|FAC-####|CHR-####` + suffissi di blocco canon, `ERA-####`/`EVT-####` (yaml), `proposal*` (book), e file esistenti.

**Fix:**
1. `assets/prompts/canon-auditor.md` — sostituire la specifica evidence con l'elenco esplicito delle location valide (universe scope): `{LAW|PLC|FAC|CHR}-#####{summary|voice|appearance|past|want|need|flaw|wound|arc|secret}` o `{ERA|EVT}-####` (senza suffisso), oppure un path file esistente (`universe/...`). Vietare esplicitamente `CNT-*`, `UNI-*`, `unresolved_questions`, `design_scope.*` in universe scope: non sono artifact stabili e bloccano il binding.
2. `./install.sh --force` nella dev tree.
3. Su Margherita: `resume --resolve-blocked AUDIT-UNI-0001:retry` + `design universe` (esegue solo audit, DESIGN-UNI-0001 già succeeded).

**Acceptance:**
- L'audit universe produce findings con solo location risolvibili
- AUDIT-UNI-0001 chiude senza `not a stable artifact`
- Suite `pytest -q` verde

**Tasks:**
- [x] Patch `assets/prompts/canon-auditor.md` — landed: the prompt lists the resolvable universe-scope locations and forbids `CNT-*`, `UNI-*`, `unresolved_questions` and `design_scope.*` by name
- [x] `./install.sh --force`
- [x] Verifica Margherita: audit universe chiude — **verificato 2026-09-02**: `AUDIT-UNI-0001` e `AUDIT-BOOK-0001` sono entrambi `succeeded`. L'unico task non riuscito del progetto è un advisor di stile, che è advisory per costruzione

## Fix: reviser ROLE_BUDGETS output budget 6000→8000 (autobloccante b7939dd) ✅

**Status: ✅ Done — 2026-08-25**

**Problem:** b7939dd ha alzato i due call-site del reviser a min(8000,…) ma non ROLE_BUDGETS["reviser"] rimasto (14000, 6000); build_envelope rifiuta allowance 8000 > budget 6000 con "Output allowance 8000 exceeds reviser budget 6000", autobloccante per capitoli ≥3000 parole. 3000 parole è un limite senza senso per reviser che deve gestire prose + beat_map + consequences + dispositions.

**Fix:** `scripts/book_forge.py:2337` → "reviser": (14000, 8000) (una riga, coerenza con call-site 8000 già committato)

**Tasks:**
- [x] Patch scripts/book_forge.py:2337
- [x] Test: pytest nel repo skill (136+ pass)
- [x] Commit nel repo skill (stile fix(review): ...)
- [x] Reinstall: ./install.sh --force
- [x] Landfall: run --next → atteso REVISE-BOOK-0001-CH-0005 succeeded (verificato con draft)

## Fix: reviser variant high→medium per reasoning 32k length (Landfall CH-0005) ✅

**Status: ✅ Done — 2026-08-25**

**Problem:** ATT-0104 deepseek-v4-flash variant high consuma reasoning 32000 token e 0 output, finish length. max_output_tokens 8000 limita solo output, non reasoning. Il reviser high su 4000w + 29 findings + 14 consequences esplode sistematicamente (3/3 zero-output dopo fix 8000). ATT-0098/99 riuscirono solo per varianza reasoning corto.

**Fix:** `scripts/book_forge.py:80` ROLE_SPECS["reviser"] ("all","high",8) → ("all","medium",8). Reasoning più corto, stessa capacità output 8000. Coerente con designer medium già adottato. Richiede `runtime sync` su Landfall per rigenerare pin.

**Tasks:**
- [x] Patch scripts/book_forge.py:80
- [x] Test: pytest 136+ pass
- [x] Commit fix(review): reviser high->medium
- [x] Reinstall ./install.sh --force
- [x] Landfall: runtime sync + run --next → REVISE-BOOK-0001-CH-0005 succeeded

## Fix: reviser variant medium→low per reasoning 32k persistente (Landfall CH-0005 ATT-0106) ✅

**Status: ✅ Done — 2026-08-25**

**Problem:** ATT-0106 con medium ha stessi numeri di ATT-0104 high: total 53477 / input 21477 / reasoning 32000 / output 0 su 3 tentativi consecutivi. Variant medium non abbassa il cap reasoning su deepseek-v4-flash, il modello satura senza scrivere. Budget 8000 e fix supersedes/parse già a bordo.

**Fix:** `scripts/book_forge.py:80` ROLE_SPECS["reviser"] ("all","medium",8) → ("all","low",8) (una riga, ultimo test gratis prima di cambiare modello a deepseek-v4-pro). Richiede runtime sync su Landfall.

**Tasks:**
- [x] Patch scripts/book_forge.py:80
- [x] Aggiorna test reviser medium→low
- [x] Test: pytest 136+ pass
- [x] Commit fix(review): reviser medium->low
- [x] Reinstall ./install.sh --force
- [x] Landfall: runtime sync + run --next → REVISE-BOOK-0001-CH-0005 succeeded

## Fix: translator ROLE_BUDGETS 14000→16000 per context budget 14748 (Landfall CH-0001) ✅

**Status: ✅ Done — 2026-08-26**

**Problem:** Translate CH-0001 hard-fail 14748 > 14000. Capsule = source 4000w (~10.8k token) + contract + canon imports + style/glossary/metadata. 14000 sotto di ~750 token; blocca tutti i translate.

**Fix:** `scripts/book_forge.py:2339` ROLE_BUDGETS["translator"] (14000,6000) → (16000,6000). Allinea con advisor (16000), copre capitoli più lunghi. Solo translator.

**Tasks:**
- [x] Patch scripts/book_forge.py:2339
- [x] Test: pytest 136+ pass
- [x] Commit fix(translate): translator 14000->16000
- [x] Reinstall ./install.sh --force
- [x] Landfall: translate next ×5 → 5 completed_chapters, poi export en/it

## Fix: promoted writes desync the artifact registry (Landfall CH-0002/0003) ✅

**Status: ✅ Done — 2026-08-26**

**Problem:** `reconcile_artifacts` raises `Derived artifact was edited directly:
SOURCE-<book>-<chapter>` for chapters the pipeline itself rewrote. The registry
row is written once by `register_artifact` at the first promote and never
updated: `_recover_transaction` installs promoted files without touching
`artifact-deps.json`, and `register_artifact` refuses an existing id. So the
second promoted write of the same path (`REVISE-STYLE-*` after `REVISE-*`)
leaves the row pinned to the previous hash, and the guard reads the pipeline's
own transactional write as tampering. Measured on Landfall: CH-0002 registry
`c9d41888` = TXN-0016 `REVISE`, on disk `2c656141` = TXN-0026 `REVISE-STYLE`;
CH-0003 `5f442568` = TXN-0020 vs `e7704c1b` = TXN-0031. Blocks translate and
publication (`Publication refused by artifact currentness`) on every chapter
that gets a style pass. Second path to the same desync:
`recheck_style_closed_chapter` rewrites the `# ` heading with a direct
`ms_path.write_text`, outside the transaction — no journal, no scoped commit,
no receipt.

**Fix:**
1. `_recover_transaction`: after installing, refresh the registry hash of every
   artifact whose `path` matches an installed row, from `row["target_hash"]`
   (already computed at staging — no re-hash). Dependents still invalidate:
   a refreshed SOURCE makes its TRANSLATION stale, which is the wanted
   behaviour.
2. `reconcile_artifacts`: before raising, check provenance — if the on-disk
   hash appears as a `target_hash` for that path in a completed transaction
   journal, it is a pipeline write, so refresh instead of raising. Repairs
   registries already desynced by (1) with no hand-edit; a real hand-edit has
   no journal and still raises.
3. `recheck_style_closed_chapter`: the heading rewrite becomes an atomic
   `_write_bytes_atomic` that refreshes the registry row and takes its own
   scoped git commit (`_scoped_git_commit` gained an optional `message`). Not a
   journalled transaction: the attempt/receipt lifecycle is bound to a provider
   attempt and this repair makes no model call. Full journalling of
   deterministic repairs is deferred to the follow-up item below.

**Tasks:**
- [x] `_recover_transaction` refreshes registry hashes from the install manifest
- [x] `reconcile_artifacts` provenance check before the tampering error
- [x] Heading rewrite becomes atomic + registry-consistent + committed
- [x] Test: promoted second write to a registered path → reconcile clean, dependent stale
- [x] Test: real out-of-band edit → still raises
- [x] Test: pre-desynced registry + journal → repaired by reconcile
- [x] Test: pytest 140 passed, 14 subtests (era 136)
- [x] Reinstall ./install.sh --force
- [x] Close out the two dangling markers (translator 14000→16000, reviser medium→low)
- [x] Commit & push

**Done when:** A chapter that goes through `REVISE` then `REVISE-STYLE`
translates and publishes without a manual touch of `artifact-deps.json`, and an
out-of-band edit of a derived file still fails the guard.

## Fix: deterministic repairs are not journalled (follow-up)

**Status: ⏸ Open — 2026-08-26**

**Problem:** `promote_task` is bound to a provider attempt: it needs a claim, an
envelope hash, an execution receipt and telemetry. A repair the engine performs
on its own — today the `# ` heading rewrite in `recheck_style_closed_chapter`,
tomorrow any migration — has no model call to hang that lifecycle on, so it
writes outside the transaction journal: atomic and committed, but with no
rollback record and no promotion receipt.

**Fix (sketch):** a deterministic transaction reusing the journal and the
`_recover_transaction` install/commit path with a synthetic attempt, or a
journal variant whose receipt records `provider: none`. Needs a decision on how
`status` and `telemetry` should count repairs before it is worth building.

**Done when:** an engine-performed repair leaves a journal that
`recover_transactions` can replay, exactly like a model-produced promote.

## Fix: artifact chain holes and the doubled repair envelope (Landfall translate) ✅

**Status: ✅ Done — 2026-08-26**

**Problem 1 — registry rows are created by whoever gets there first, and only
if missing.** Four call sites register the same ids with whatever they happen to
know: the chapter-close path passes contract imports and pov, `_translate_one`
registers a SOURCE with no dependencies, `_edition_dependencies` registers both
SOURCE and TRANSLATION with no dependencies. Each is guarded by `if id not in
registry`, so the first caller decides forever whether a row can ever go stale.
Measured on Landfall: `SOURCE-BOOK-0001-CH-0004` carries `dependencies: []`
(registered by export) while CH-0002/0003/0005 carry their five canon imports —
CH-0004 will never be invalidated by a canon change. Worse, rows are written
*after* the promote and a chapter translated before the registry existed leaves
a permanent hole: CH-0001..0004 are translated and committed on disk with zero
TRANSLATION rows, so registering CH-0005 raises `Dangling artifact dependency:
TRANSLATION-BOOK-0001-CH-0004-it` — after CH-0005's own output is already
promoted. The hash provenance repair added earlier cures stale rows, not absent
ones, and no CLI reaches them.

**Problem 2 — the repair attempt doubles the envelope.** `_translate_one`
attempt 2 adds `repair.previous_output`, the whole previous translation (the raw
model text on the failure path, the parsed contract on the pivotal-review path),
on top of a capsule that already carries the full source. Measured on Landfall
CH-0005: attempt 1 is 16739 tokens, attempt 2 is 27230, against a 20000 budget —
`build_envelope` hard-fails, so the retry that exists to rescue a failed
translation is exactly what cannot be built. It is not the base capsule that
grew: raising the budget to cover a doubled retry buys headroom the first
attempt never uses, and the ceiling doubles again with chapter length. Pivotal
chapters take this path on every run, success included
(`must_review and attempt_number == 2`).

**Fix:**
1. One authoritative spec per artifact kind (`_source_chapter_artifact`,
   `_translation_chapter_artifact`) and `_ensure_artifact`, which registers a
   missing row and completes a partial one instead of accepting it.
2. `_ensure_translation_artifacts` walks a locale's promoted chapters in order,
   so the `previous` dependency can never dangle. Called by `_translate_one`
   before it registers, and by `_edition_dependencies` so export stops minting
   dependency-less rows.
3. `book-forge artifacts backfill [--book] [--locale]` — the same pass on
   demand, for registries holed before the feature existed.
4. The repair envelope degrades instead of hard-failing: on
   `ContextOverflowError` rebuild the capsule with `previous_output` dropped and
   `previous_output_omitted: true`, and document the `repair` field in the
   pinned translator prompt. A genuine overflow without it still raises.

**Tasks:**
- [x] `_ensure_artifact` + per-kind specs
- [x] `_ensure_translation_artifacts` wired into `_translate_one`, `_edition_dependencies` and the chapter-close path
- [x] CLI `artifacts backfill` + route documented in SKILL.md and references/lifecycle.md
- [x] Repair envelope degradation + prompt line
- [x] Test: holed chain (translated chapters, no rows) → backfill registers in order, deps correct
- [x] Test: partial row (no dependencies) → completed, not left as is
- [x] Test: repair capsule over budget → built without previous_output; over budget without it → still raises
- [x] Test: 145 passed, 14 subtests (era 140)
- [x] Reinstall ./install.sh --force
- [x] Commit & push

**Done when:** `translate next` on a project whose earlier chapters predate the
registry completes without a dangling dependency, export stops creating rows
that cannot go stale, and a failed translation gets its repair attempt at any
chapter length.

**Verified on Landfall (copy, project untouched):** `artifacts backfill --book
BOOK-0001` registered `SOURCE-CH-0001`, `SOURCE-CH-0004` and
`TRANSLATION-CH-0001..0004-it` in order — each translation carrying its source,
the three locale rows and the previous chapter — completed `SOURCE-CH-0004`'s
empty dependency list with its five canon imports, and left `reconcile` clean.

## Chorus catalog: glm-5.3-flash replaces glm-5.3, unknown models lose the borrowed provider pin ✅

**Status: ✅ Done — 2026-08-26**

**Problem:** `advisor-glm-5-3` fails with `Model output contains no JSON object`
in four of the recent chorus reports. It runs at `reasoningEffort: max` and its
ladder offers only `high` and `max`, so it cannot be dialled down — the same
reasoning-saturation shape already recorded for the reviser. `z-ai/glm-5.3-flash`
serves the same 1M context and 131k output at 0.075/0.25 $/Mtok against
1.4/4.4, and supports `reasoning_effort`.

Adding a model to `book-forge.yaml:chorus.models` was also unsafe: a model
absent from `CHORUS_MODEL_CONFIGS` fell through to a fallback carrying
deepseek's provider pin (`only: ["deepseek","baidu"]`, `allow_fallbacks: false`),
so `_opencode_config` emitted a z-ai model routed to providers that cannot serve
it. The call then fails as a non-blocking advisor error, which is exactly the
class of failure nobody reads.

**Fix:**
1. `CHORUS_MODEL_CONFIGS` gains `openrouter/z-ai/glm-5.3-flash`: z-ai pin,
   default effort `high`, ladder `low/medium/high/max`, limit 1048576/131072.
   The `glm-5.3` entry stays so a project that names it still routes correctly.
2. `CHORUS_DEFAULT_MODELS` swaps glm-5.3 for glm-5.3-flash; new projects are
   created with flash.
3. An unknown model gets no provider pin at all, so OpenRouter routes it
   normally instead of being pinned to a vendor that cannot serve it.
4. Catalog list in SKILL.md and references/init.md follows.
5. An advisor's lens is pinned by filename (`assets/prompts/advisor-<slug>.md`),
   so renaming the model would have dropped the science-coherence lens the
   glm advisor carries: `advisor-glm-5-3-flash.md` copies it, and
   `advisor-glm-5-3.md` stays for projects still naming glm-5.3. A chorus model
   with no prompt of its own now falls back to the generic `chorus-advisor.md`
   instead of dropping out of every run as a non-blocking failure; every other
   role still fails hard on a missing pinned prompt.

**Tasks:**
- [x] `CHORUS_MODEL_CONFIGS` entry for glm-5.3-flash
- [x] `CHORUS_DEFAULT_MODELS` swap
- [x] Unknown model emits no provider pin
- [x] Docs: SKILL.md + references/init.md catalog
- [x] Test: flash entry carries the z-ai pin and the four-step ladder
- [x] Test: unknown model gets no provider pin
- [x] `advisor-glm-5-3-flash.md` carries the science-coherence lens
- [x] Advisor without its own prompt falls back to `chorus-advisor.md` + test
- [x] Test: 148 passed, 14 subtests (era 145)
- [x] Reinstall ./install.sh --force
- [x] Commit & push

**Done when:** A fresh project is created with glm-5.3-flash, and a chorus model
the skill does not know is emitted without a provider pin instead of one it
cannot be served through.

## Fix: PDF title validation reads pdftotext raw (Landfall draft export) ✅

**Status: ✅ Done — 2026-08-26**

**Problem:** `validate_pdf` checks `title not in text_result.stdout` against raw
`pdftotext` output. Extraction breaks a line wherever the renderer wrapped and
keeps the font's ligatures, so the check fails on titles that are present and
correctly rendered. Measured on Landfall's draft edition, five of six chapters:

| Chapter | In the PDF text | Why the substring fails |
|---|---|---|
| CH-0002 | `Chapter Two — The Mistimed` / `Dawn` | wrapped |
| CH-0003 | `III — Six Spoke, and the Sky` / `Screamed` | wrapped |
| CH-0004 | `The voice interrogates binta on` / `suﬀering` | wrapped **and** `ff` ligature |
| CH-0005 | `At the counting the ﬂoor is` | `fl` ligature, no wrap at all |
| CH-0006 | `At the counting binta publicly` / `refuses` | wrapped |

Normalizing newlines alone does not fix it: CH-0004 and CH-0005 fail on U+FB00
and U+FB02, which survive any whitespace handling. The failure is also opaque —
`PDF text or chapter order validation failed` names neither the title nor the
reason, and the same message covers an extraction error.

**Fix:** `_pdf_text_key` folds both sides with NFKC (which resolves the
ligatures), drops soft hyphens and collapses whitespace runs; a packed
comparison with whitespace removed catches a wrap that also swallowed the space.
`_missing_pdf_titles` returns which titles are absent, so the error names them.
A failed extraction gets its own message.

**Tasks:**
- [x] `_pdf_text_key` + `_missing_pdf_titles`
- [x] `validate_pdf` uses them and names the missing titles
- [x] Test: a long title carrying `ff` validates end-to-end, and the raw extraction does not contain it verbatim
- [x] Test: a title genuinely absent still fails, and the message names it
- [x] Test: 150 passed, 14 subtests (era 148)
- [x] Reinstall ./install.sh --force
- [x] Commit & push

**Done when:** A chapter whose rendered title wraps or contains a ligature
passes publication validation, and a title that is really missing fails with its
name in the message.

**Verified on Landfall:** both draft editions validate against the titles taken
from their own manuscripts — `en` 78 pages, `it` 86 pages, six chapters each.

**Found while doing it, not fixed here** — the manuscript heading is only forced
to the contract title on the path where the style check finds nothing
(`recheck_style_closed_chapter`). When the reviser runs, whatever heading it
returns is promoted: CH-0002 kept `Chapter Two — The Mistimed Dawn` against a
contract title of `The Mistimed Dawn`, CH-0003 kept `III — `. Separately,
CH-0004/0005/0006 carry beat text as their contract title (`At the counting the
floor is`), which no heading enforcement can repair — it is a design defect
upstream, and the Italian translation reproduces it faithfully.

## Fix: contract title is enforced on one path only, and a beat can pass as a title ✅

**Status: ✅ Done — 2026-08-26**

**Problem 1 — the heading is forced to the contract title only when the style
check finds nothing.** `recheck_style_closed_chapter` repairs the `# ` line on
its clean branch; when the reviser runs, whatever heading the model returned is
promoted unchanged, and `produce_chapter` never enforces it either. Landfall
shipped `Chapter Two — The Mistimed Dawn` and `III — Six Spoke, and the Sky
Screamed` against contract titles carrying neither prefix, while four other
chapters carry no prefix at all: three conventions in one book, and the
prefixes reach the EPUB, the PDF and the Italian translation.

**Problem 2 — a designer title that is only the opening words of its own beat
is accepted.** `title` is optional and preserved verbatim when present, and
nothing checks what it contains. Measured on Landfall, three consecutive
chapters carry the first six words of beat one, lowercased and cut mid-phrase:

| Chapter | title | beats[0] |
|---|---|---|
| CH-0004 | `The voice interrogates binta on suffering` | `The Voice interrogates Binta on suffering under 1.31 g and unhoods…` |
| CH-0005 | `At the counting the floor is` | `At the Counting the floor is read: lamps fail in public, riots…` |
| CH-0006 | `At the counting binta publicly refuses` | `At the Counting Binta publicly refuses to repeat the Faith's misread…` |

No title is better than a beat fragment: with the field absent the writer
produces a real heading, which is what the other chapters got.

**Fix:**
1. `_with_contract_heading` applies the contract title to the promoted prose at
   both manuscript staging sites (`produce_chapter` and the style reviser), so
   the heading no longer depends on which path ran.
2. `_title_is_beat_prefix` drops a `title` of four words or more that is a
   verbatim case-insensitive prefix of one of its own beats, and
   `validate_book_design` reports it as a `chapter.title-from-beat` warning —
   non-blocking, so a design does not fail over an optional field. Four words is
   the floor so a short title coinciding with a beat's opening word is not
   caught.

**Note:** this does not rename Landfall's CH-0004/0005/0006, whose contracts are
already written. Those three need real titles from the author, propagated to
contract, manuscript and translation.

**Tasks:**
- [x] `_with_contract_heading` at both staging sites
- [x] `_title_is_beat_prefix` + contract materialization drops it
- [x] `chapter.title-from-beat` warning in `validate_book_design`
- [x] Test: reviser returns a prefixed heading → promoted manuscript carries the contract title
- [x] Test: beat-prefix title is dropped from the contract, real title survives, design still applies
- [x] Test: 157 passed, 14 subtests (era 150)
- [x] Reinstall ./install.sh --force
- [x] Commit & push

**Done when:** The promoted heading is the contract title whichever path wrote
the chapter, and a designer cannot pass the opening of a beat off as a title.

## The pipeline names its own chapters: title becomes a required design field ✅

**Status: ✅ Done — 2026-08-26**

**Problem:** `title` is never asked for. The book-design capsule's
`required_output.chapters[0]` lists id, order, pov, beats, plants, reveals,
target_words, imports, obligations and pivotal — no title — and `designer.md`
does not mention the word. A field nobody specifies is a field the model fills
by copying what is next to it: Landfall's CH-0004/0005/0006 carry the first six
words of their own first beat, lowercased and cut mid-phrase. Downstream,
`writer.md` says only "otherwise invent a concise title", with no constraint, so
the chapters that reached the writer with no title got `Chapter Two — The
Mistimed Dawn` and `III — Six Spoke, and the Sky Screamed` — numbering carried
in the title, in two different conventions, in the same book.

Naming the chapters is the pipeline's job, not the author's, so the fix is to
say what a title is at all three points where a model can produce one.

**Fix:** one spec, worded the same everywhere — two to six words, names what the
chapter is about, never the opening words of a beat or a truncated sentence,
never a chapter number or numeral prefix, because `order` carries the sequence.
1. Add `title` to the design capsule's `required_output.chapters[0]` with the
   spec inline, so the designer is asked for it.
2. `designer.md` states the rule.
3. `writer.md` applies the same rule to the title it invents when the contract
   has none.

The `chapter.title-from-beat` guard stays as the deterministic backstop: the
prompt asks, the validator checks.

**Tasks:**
- [x] `title` in the design capsule required_output
- [x] `designer.md` title rule
- [x] `writer.md` invented-title rule
- [x] Test: the designer envelope asks for a title and carries the rule
- [x] Test: 159 passed, 14 subtests (era 157)
- [x] Reinstall ./install.sh --force
- [x] Commit & push

**Done when:** A book designed from scratch names its own chapters, and no
chapter reaches the writer without a title having been asked for.

**Does not retitle Landfall's CH-0004/0005/0006.** Their contracts are already
written, so the design capsule never runs for them again. Renaming them means
redesigning the book or editing the three contracts and re-promoting those
chapters — a separate decision.

## Fix: nothing checks the title the writer invents ✅

**Status: ✅ Done — 2026-08-26**

**Problem:** `chapter.title-from-beat` runs at design time, on the designer's
proposal. A chapter that reaches the writer with no title — because the designer
never gave one, or because the guard dropped a bad one — gets whatever the
writer invents, held only by a line in the prompt. `_with_contract_heading`
cannot help: it repairs a heading only when the contract names one. On Landfall
that is now seventeen chapters, every one of them unwritten.

The rule the writer is given has three clauses; the two that are mechanically
checkable are the ones that have actually failed. A beat's opening words
produced `At the counting the floor is`, and a numbering prefix produced
`Chapter Two — The Mistimed Dawn` and `III — Six Spoke, and the Sky Screamed`
in the same book.

**Fix:** `validate_writer_output` checks the invented heading when the contract
carries no title — `_title_is_beat_prefix` for the first clause, a numbering
prefix pattern for the second. It raises like every other writer validation, so
`produce_chapter` retries once with the reason in `repair.validation_error`
instead of promoting a bad title. A contract that names a title is not checked:
`_with_contract_heading` already overwrites whatever the writer put there.

The numbering pattern requires a separator, so a title that merely opens with a
number word (`Six Spoke, and the Sky Screamed`) is not caught; `III — ` and
`Chapter Two — ` are. The third clause — a title cut mid-phrase — is left to the
prompt: no mechanical test separates it from a deliberately abrupt title.

**Tasks:**
- [x] `_invented_title_problem` + numbering pattern
- [x] `validate_writer_output` calls it
- [x] Test: beat-opening heading raises, numbering prefix raises, a real title passes
- [x] Test: a contract with a title is not second-guessed
- [x] Test: 163 passed, 19 subtests (era 159)
- [x] Reinstall ./install.sh --force
- [x] Commit & push

**Done when:** A chapter designed without a title cannot be promoted under a
heading that repeats a beat or carries a chapter number.

## Chapter numbering belongs to the edition, not to the title ✅

**Status: ✅ Done — 2026-08-26**

**Problem:** Nothing renders a chapter number. `pdf.css` centres the title with
`h1 { break-before: page }` and counts pages, never chapters; the EPUB writes
the title into `<title>` and the body and lists titles alone in the nav. The
sequence exists only as `order` in the contract and as the `CH-000N` id, and
never reaches the reader.

That is why the models kept putting it in the title. `Chapter Two — ` and
`III — ` were the model filling a slot the artifact did not offer. The writer
validator now rejects those, so without a home for the number the rule costs a
retry per chapter and teaches nothing: a constraint that forbids without
offering the alternative gets fought at every chapter.

**Fix:** the number travels in the assembly and is rendered by the templates,
never written into prose — so the format can change without touching a
manuscript, and a translation inherits it without being retranslated. A bare
numeral was chosen over `Chapter 4`: no localizable string, identical in every
language. The nav lists `4. Title`.
1. `assemble_edition` carries `number` per chapter, from the contract's `order`.
2. EPUB: `<p class="chapter-number">` before the title, nav item numbered,
   `epub.css` styles it and takes over the page break from `h1`.
3. PDF: same element inside each `<section>`, `pdf.css` moves `break-before:
   page` and the top margin onto it so the number opens the page and the title
   follows it.

**Tasks:**
- [x] `assemble_edition` carries the chapter number
- [x] EPUB body and nav render it, `epub.css` styles it
- [x] PDF section and `pdf.css` render it
- [x] Test: assembly carries it, EPUB nav and body carry it, PDF text carries it
- [x] Test: two chapters render on two pages, no blank page gained
- [x] Test: 170 passed, 19 subtests (era 163), determinismo intatto
- [x] Reinstall ./install.sh --force
- [x] Commit & push

**Done when:** A chapter opens under its number in both editions, the number is
absent from every manuscript, and changing its format touches only the
templates.

## Catalog: qwen3.8-flash, glm-5.3-flash on style review, advisors beyond the default list ✅

**Status: ✅ Done — 2026-08-26**

**Change requested:** `qwen/qwen3.8-flash` joins the catalog and replaces
`qwen3.8-max` in the writing flows (1M context and 131k output at 0.16/0.47
$/Mtok against 2.0/6.0); the final style review swaps `kimi-k3` for
`glm-5.3-flash`. Kimi stays in the chorus, it just stops doing style review.

**Problem 1 — qwen3.8-flash has no reasoning-effort knob.** It is the only model
of the ten with `reasoning_effort` absent from its OpenRouter parameters;
`reasoning` itself is supported. The config shape is `variants: {name: effort}`
and every entry declares a ladder, so a four-step ladder here would advertise
four operating points that behave identically — OpenRouter drops the parameter
before the pinned provider sees it. The entry declares one variant, which is
what the model actually has.

**Problem 2 — a chorus model outside the default list cannot run.**
`CHORUS_ADVISOR_SPECS`, `CHORUS_ADVISOR_MODELS` and the advisor `ROLE_BUDGETS`
are all built from `CHORUS_DEFAULT_MODELS`, while `_chorus_models_from_config`
accepts any `openrouter/…` string a project names. A project naming a model that
is in `CHORUS_MODEL_CONFIGS` but not in the defaults gets an advisor with no
budget and no expected pin, and `_expected_pin` raises `Role cannot run
headlessly` — as a non-blocking chorus failure. Removing `glm-5.3` from the
defaults earlier put it in exactly that state. The three maps now cover every
model the catalog configures.

**Fix:**
1. `CHORUS_MODEL_CONFIGS` gains `openrouter/qwen/qwen3.8-flash`: alibaba pin,
   one variant, limit 1000000/131072, and a note on the missing knob.
2. `CHORUS_DEFAULT_MODELS` swaps qwen3.8-max for qwen3.8-flash;
   `STYLE_REVIEW_MODELS` swaps kimi-k3 for glm-5.3-flash.
3. Advisor specs, models and budgets derive from `CHORUS_MODEL_CONFIGS`.
4. `advisor-qwen-qwen3-8-flash.md` carries the lens qwen held.

**Tasks:**
- [x] qwen3.8-flash entry with a single variant
- [x] Default catalog and style-review list
- [x] Advisor specs cover every configured model
- [x] Advisor lens copied
- [x] Test: the swaps hold, a configured non-default model resolves its pin and budget
- [x] Test: 173 passed, 21 subtests (era 170)
- [x] Reinstall, opencode global config, Landfall runtime sync
- [x] Commit & push

**Done when:** Landfall writes with qwen3.8-flash and reviews style with
glm-5.3-flash, and naming any configured model in `chorus.models` produces an
advisor that can actually run.

## Fix: the beat-prefix floor was set too high to catch anything ✅

**Status: ✅ Done — 2026-08-26**

**Problem:** `_title_is_beat_prefix` ignores titles under four words, a floor
chosen to spare a short title that coincides with its beat's opening. Measured
against Landfall's twenty-one designer-written titles it catches none of the
four beat-head titles that remain, because they are two and three words long:
`The pre-eclipse vigil` (CH-0007), `A one-page coda` (CH-0027), `Lowlands
flash-pockets` (CH-0009), `At waelu` (CH-0010). CH-0007 is already staged for
promotion under that heading.

**Decision:** floor 2. Against the six titles known to be good — including the
three-word `The Mistimed Dawn` and `The Signed Misread` — floors 3 and 2 both
produce zero false positives, and floor 2 catches all four. The errors are not
symmetric: a false positive costs a designer's suggestion and the writer names
the chapter instead, which is the project's policy anyway, while a false
negative ships a broken title through the manuscript, both editions and the
translation. The floor stays at 2 rather than 1 because a single common word
coincides with a beat's opening too easily to mean anything.

This overrules the test written the day before, which treated a two-word
coincidence as worth protecting. With the measurement in hand that caution costs
more than it protects.

**Tasks:**
- [x] Floor 4 → 2, docstring carries the measurement
- [x] Rewrite the short-title test to encode the new trade-off
- [x] Test: 173 passed, 21 subtests
- [x] Reinstall ./install.sh --force
- [x] Landfall: cleared CH-0009, CH-0010, CH-0027; CH-0007 left alone, see below
- [x] Commit & push

**Done when:** A two-word beat head cannot pass as a chapter title, and a
one-word title is still left alone.

**CH-0007 was left alone deliberately.** Its `REVISE` sits in
`promotion_pending` with `# The pre-eclipse vigil` already staged, and `VERIFY`
is blocked. Clearing the contract title now would promote a chapter whose
heading is a beat head with no contract title left to repair it from — strictly
worse than leaving it visible. It needs a decision once the chapter unblocks.

## Fix: the number check reads the source's decimal separator as the only one ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** `_translation_validation` collects `(?<!\w)\d+(?:[.,]\d+)?` from
both texts and compares the literal strings. A locale that writes `5,8` where
the source writes `5.8` therefore fails with `numbers differ from source` — the
number is correct and correctly localized, and the check calls it changed. The
translator gets one repair attempt carrying the failure reason, so the loop
teaches it to keep the source's separator.

That is not hypothetical: Landfall's Italian edition writes `1.31 g` five times,
`5.8` four times and `0.2%` once, in CH-0004, CH-0005 and CH-0007. Italian
typography wants the comma. The validator did not merely reject a good
translation, it shaped a wrong one — and the failure was read as the
translator's, twice, before being worked around in the text.

**Fix:** normalize the separator on both sides before comparing, so `5,8` and
`5.8` are the same number while `131` and `1.31` stay different. Order and count
are still enforced. A thousands separator written as a space (`12 000`) still
splits into two tokens and fails; that limitation predates this and is left.

**Tasks:**
- [x] Normalize the decimal separator in the comparison
- [x] Test: a comma-localized number passes, a changed number and an integer still fail
- [x] Test: 176 passed, 21 subtests (era 173)
- [x] Reinstall ./install.sh --force
- [x] Commit & push

**Done when:** A translation may write its own decimal separator, and a number
that actually changed is still caught.

**The ten numbers already in Landfall's Italian text are not corrected here.**
Fixing the validator stops the pressure; it does not undo what the pressure
produced. `1.31 g` ×5 in CH-0004, `5.8` ×3 in CH-0005 and once in CH-0007,
`0.2%` once in CH-0005.

## Chorus spend is invisible, and editions are named after an id ✅

**Status: ✅ Done — 2026-08-27**

**Problem 1 — chorus calls record no cost.** `run_chorus` bypasses
`claim_task`/`promote_task` deliberately (advisory, at-most-once not required)
and writes `advisor-<slug>.json` with `findings`, `suggestions`, `raw` and
`envelope_hash`. No tokens, no cost, no session. On Landfall that is eight
advisors over seven rounds — fifty-six billed provider calls outside the
telemetry, including the two most expensive models in the catalog. Asked what
grok had cost, the honest answer was an estimate from list prices.

**Problem 2 — the model pin check fires on every legitimate multi-model call.**
`telemetry_report` compares each receipt's model against the primary `MODEL`.
Style review runs three other models by design, so twenty of the project's
twenty-one `model_pin` violations are style-review receipts doing exactly what
they are supposed to. Folding chorus receipts in would have multiplied that
noise. An advisor role has its own pin: check it against that.

**Problem 3 — editions are named after the book id.**
`dist/BOOK-0001/en/BOOK-0001.draft.pdf` says nothing to whoever opens or
receives it, and the two languages differ only by a path segment.

**Fix:**
1. `run_chorus` captures `_provider_telemetry` per advisor, stores it in the
   advisor file and writes `chorus-telemetry.json` per round;
   `telemetry_report` folds those in as receipts under the advisor's role and a
   `CHORUS-<scope>` task, so book and locale attribution work as usual.
2. The pin check resolves an advisor's own model through `_expected_pin`
   instead of the primary. Variant checking stays where it was.
3. Editions are named `<title-slug>-<language>[.draft].<ext>`, so the file is
   `landfall-the-lost-candle-it.draft.pdf`. The directory keeps the id, which is
   the machine path.

**Tasks:**
- [x] Chorus telemetry captured and persisted, tolerantly: accounting cannot kill an advisory call
- [x] `telemetry_report` folds chorus rounds in
- [x] Pin check resolves an advisor's own model
- [x] Editions named after the title and the language
- [x] Test: a chorus round reports cost under its advisor role; an advisor on its own model is not a pin violation
- [x] Test: 183 passed, 21 subtests (era 176)
- [x] Reinstall ./install.sh --force
- [x] Commit & push

**Done when:** `telemetry` answers what an advisor cost instead of estimating it,
a style review is not reported as a pin violation, and an edition is named after
the book.

**Caught by the tests, worth keeping:** the first version built the telemetry
with `_provider_telemetry`, which indexes the provider's answer. A stub omitting
`variant` raised `KeyError` inside the advisor's own `except Exception`, and the
round returned zero findings — accounting killing an advisory call, which is the
one thing that function is written not to do. `_chorus_telemetry` records what
the provider reported and leaves the rest `None`.

## Fix: the PDF manifest and render temp kept the book id ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** `_edition_stem` was applied to the two output files and to the EPUB
manifest, but the PDF manifest still built its name from `book_id`, so an export
produced `landfall-the-lost-candle-it.draft.pdf` next to
`BOOK-0001.draft.pdf.manifest.json`. The replacement matched `.epub.manifest`
and never looked for the PDF one. The temporary render path
`.{book_id}{suffix}.pdf.rendering` has the same shape and a worse consequence:
it does not carry the language, so rendering two languages at once writes both
through the same temporary file.

**Fix:** both take `_edition_stem`. A test covers the manifest name for each
exporter, which is what was missing the first time.

**Tasks:**
- [x] PDF manifest and render temp use the edition stem
- [x] Test: both exporters name their manifest after title and language, and nothing is left under the book id
- [x] Test: 186 passed, 23 subtests (era 183)
- [x] Reinstall ./install.sh --force
- [x] Commit & push

**Done when:** Every file an export writes is named after the book and its
language, temporaries included.

## Fix: the EPUB carries no NCX, and readers stall on it ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** three e-readers process the generated EPUB forever. The container is
conformant — `mimetype` stored first with no extra field and `application/epub+zip`
at offset 38, `META-INF/container.xml` present, every XHTML and the OPF
well-formed — and WeasyPrint paginates a chapter in eleven pages without
looping, so it is neither a broken archive nor a pathological stylesheet.

What the package lacks is the EPUB 2 navigation: no `toc.ncx`, no `toc`
attribute on `<spine>`. An EPUB 3 is valid with only the XHTML nav document, but
every reader built on Adobe RMSDK — Kobo, PocketBook, Nook, Sony, Digital
Editions — reads the NCX, which is why three different devices behave the same
way. Real-world EPUB 3 files ship both. `<dc:creator></dc:creator>` is also
emitted empty when the book has no author.

**Fix:** emit `OEBPS/toc.ncx` with one `navPoint` per chapter in spine order,
manifest it as `application/x-dtbncx+xml`, point `<spine toc="ncx">` at it, and
drop `dc:creator` when there is no author. `validate_epub` requires the NCX, the
spine reference, and one navPoint per chapter, so publication cannot regress to
a package half the readers stall on.

**Not verified here:** no e-reader and no epubcheck on this machine (epubcheck
needs a JRE, absent). The diagnosis is a standards gap that matches the symptom
across three unrelated devices, not a reproduction.

**Tasks:**
- [x] `toc.ncx` emitted, manifested and referenced from the spine
- [x] Empty `dc:creator` omitted
- [x] `validate_epub` requires the NCX and its navPoints
- [x] Test: spine-referenced NCX with one navPoint per chapter, determinismo intatto
- [x] Test: 190 passed, 23 subtests (era 186)
- [x] Reinstall, regenerate both editions
- [x] Commit & push

**Done when:** The EPUB carries both navigations, and validation refuses one that
does not.

## The writing instructions are one sentence, and the beats are notes to the author ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** the prose reads as heavy and cryptic, and the first chapter reads
worst although it is the lightest by every sentence-level measure — 14.8 words
per sentence against 22.3 in chapter seven. Measured on that chapter: 1345
words, **zero named characters, zero lines of dialogue**, the protagonist called
by a role, two paragraphs of exposition before anything happens, and a turn that
consists of a word appearing and being copied onto a wall. Nothing a reader can
hold. Guardrails on sentence length would not have touched it.

Three causes, in order of depth:

1. **The beats are notes to the author, not dramatic units.** The chapter's
   second beat is a propagation rule — the word "travels by that hum and by
   nothing else, to be registered by clear eyes early in act 1 and return at the
   climax". That cannot be staged, so it comes back as exposition. The designer
   is never told what a beat is.
2. **`writer.md` carries one sentence of craft instruction** — "vivid, causally
   complete" — plus the title rule and the return contract. Everything else the
   writer does comes from its priors and from beats written in the register
   above.
3. **The style review has no style lens.** It runs each reviewer under its
   chorus prompt: bestseller hooks, science coherence, world-exploitation. Two
   of three seats ask for more canon per page, and the dispositions show it —
   one removed two images in favour of "polarization anomalies", another
   recorded "seeding singing-blood tracker, magnetic wake and telluric coupling
   in one sentence" as an improvement. The pass meant to catch density was
   producing it.

**Fix:** rewrite the instructions rather than add constraints on top of them.
`writer.md` states how to write a chapter, in priority order. `designer.md`
states what a beat is and where mechanism belongs. A new `style-review.md` gives
the pass its own lens, explicitly forbidden from asking for more world, and
required to propose cuts shorter than what they replace. `build_envelope` gains
`prompt_role` so the review keeps each model's pin while changing its
instruction. All three stay genre-agnostic: the skill is installed by other
projects.

**Tasks:**
- [x] `writer.md` rewritten with craft instruction in priority order
- [x] `designer.md` states what a beat is
- [x] `style-review.md` + `prompt_role` wiring
- [x] Test: the style review resolves the style lens, not the advisor's
- [x] Test: 191 passed, 23 subtests (era 190)
- [x] Reinstall ./install.sh --force
- [x] Commit & push

**Done when:** A chapter is written under instructions that ask for a person, a
want and an obstacle, and the style pass is the one voice in the ensemble asking
for less.

**Applies to what is written from here on.** The seven chapters already promoted
carry the register the old instructions produced; nothing in this change
rewrites them.

## The prose register is hardcoded in the role prompt, so every project writes in the same voice ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** `writer.md` now carries craft instruction, but that instruction is one fixed register for every book the skill ever writes. A literary science-fiction novel and an erotic romance need the same structural rules — a person, a want, an obstacle — and opposite sentence-level ones. Today the second can only be got by editing the skill's own prompt, which changes it for every other project on the machine.

**Fix:** the register becomes project configuration. `book-forge.yaml` gains a `style` block naming a preset shipped in `assets/prompts/style/`, plus optional per-project directives. `build_envelope` appends the resolved block to the role prompt of the three roles that write or judge prose — `writer`, `reviser`, `style-review` — and to no other: cold-reader, technical-editor, canon-auditor and translator judge facts, not register. Three presets ship: `plain-concrete` (the default), `erotic-romance`, and `neutral`, which adds nothing.

Two design choices worth recording. The block lands **inside the role prompt and therefore inside the envelope hash**, so changing a project's register makes unwritten work stale instead of silently mixing two registers inside one book. And an unknown preset **fails** rather than falling back to the default: a silent fallback writes a whole novel in a register nobody chose, and the mistake surfaces only in the prose, chapters later.

`qwen3.8-flash` joins `STYLE_REVIEW_MODELS`, taking the default style ensemble to four.

**Tasks:**
- [x] `assets/prompts/style/{plain-concrete,erotic-romance,neutral}.md`
- [x] `_style_block` + preset validation, unknown preset fails loud
- [x] Injection in `build_envelope` for `writer` / `reviser` / `style-review`
- [x] Wizard `_prompt_style_preset`, `--style` flag, `style` written by `_build_project`
- [x] `qwen3.8-flash` added to the default style-review ensemble
- [x] Test: default in the absence of config, preset resolution, excluded roles, directives, hash changes with the register
- [x] Test: 206 passed, 23 subtests (era 191)
- [x] Reinstall ./install.sh --force
- [x] Commit & push

**Done when:** Two projects on the same machine write in two registers, and neither can reach the other's prompt file.

## Restarting a book from scratch has no engine path, so it can only be done by hand ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** two projects need to be rewritten under the new register, and there is no command for it. Measured on a scratch copy of a real project: deleting the manuscript, translations, reviews and editions by hand leaves `status` reporting `tasks: {succeeded: 22}` and an artifact DAG listing `missing path: SOURCE-BOOK-0001-CH-0001`. The plan still claims `DRAFT-BOOK-0001-CH-0001` succeeded, so the writer is never re-run — the restart silently does nothing. `state.yaml` still lists three closed chapters and every consequence they accumulated, and each translation workspace still holds the input hashes of prose that no longer exists.

A correct restart has to move six coupled registries at once: the files, the plan, the book state, each translation workspace, the artifact registry and its derived views. Doing that by hand in each project is the failure mode the tool exists to prevent, and getting one of the six wrong leaves a project that looks reset and is not.

**Fix:** `book-forge reset --book BOOK-0001 [--scope prose|design] --yes`. Scope `prose` removes the manuscript chapters, the translated chapters, the reviews, the pivotal-variant work, the cold-read state and the editions, drops every chapter-scoped task, reseeds the book state and each translation workspace, drops the artifact rows for the removed paths and rebuilds the derived views. Scope `design` does all of that and additionally reseeds the outline, the chapter contracts, `design.md`, `reader-state.md` and the design audit, and drops the book's `DESIGN-` and `AUDIT-` tasks — used when the beats themselves are what needs rewriting. Neither scope touches the universe canon, `book.yaml`, `book-brief.json`, `continuity.yaml` or the locale aids: those are input, not output. The command refuses to run without `--yes` and returns a receipt naming everything it removed and everything it kept.

**Tasks:**
- [x] `reset_book` + CLI `reset`, refusing without `--yes`
- [x] Prose scope: files, plan tasks, book state, translation workspaces, artifact rows, derived views
- [x] Design scope: outline, contracts, design.md, reader-state.md, design audit, DESIGN-/AUDIT- tasks
- [x] Test: after a prose reset, `status` reports no chapter tasks and an empty artifact DAG
- [x] Test: canon, brief and continuity survive both scopes
- [x] Test: a reset without `--yes` changes nothing
- [x] Suite green: 218 passed, 23 subtests (era 206)
- [x] `reset` documented in SKILL.md and references/lifecycle.md
- [x] Reinstall ./install.sh --force
- [x] Commit & push

**Done when:** A book restarts from an empty manuscript with a plan that agrees it is empty.

## opencode's --file is a yargs array and swallows the prompt that follows it ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** every model call fails before provider acceptance with `Error: File not found: Process the attached envelope and return the requested output contract.` `run_opencode_role` builds the argv as `... --title <t> --file <envelope> "<prompt>"`, and `opencode run` declares `-f, --file  file(s) to attach to message  [array]`. A yargs array option consumes every following non-flag token, so the prompt is parsed as a second file path and the run dies before a provider is ever contacted.

Reproduced directly, outside book-forge, on opencode 1.18.23:

- `opencode run --pure --dir /tmp --agent X --format json --title t --file /etc/hostname "Process the attached envelope..."` → `Error: File not found: Process the attached envelope...`
- `opencode run --pure --dir /tmp --agent X --format json --title t "Process the attached envelope..." --file /etc/hostname` → runs

Verified the attachment still arrives in the second form: a probe file carrying a marker string was attached and the model returned the marker.

**Fix:** move the message positional ahead of `--file` in the single argv construction site. The positional is consumed as `message` before any array option opens, and `--file` then takes only the path. The order is correct under both the old and the new CLI behaviour, so it is not a version pin.

**Tasks:**
- [x] Message positional moved before `--file` in `run_opencode_role`
- [x] Test: the argv places every flag before the message and `--file` last
- [x] Suite green: 230 passed, 23 subtests (era 218)
- [x] Reinstall ./install.sh --force
- [x] Commit & push

**Done when:** A role call reaches a provider instead of dying in argument parsing.

## The book design spends its whole budget on reasoning and emits a truncated proposal ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** `design book` on a 40-chapter book never completes. Three consecutive attempts, measured from their own provider receipts:

| attempt | reasoning tokens | output tokens | chapters emitted | finish |
|---|---|---|---|---|
| ATT-0075 | 27045 | 4955 | 24 of 40 | length |
| ATT-0076 | 29441 | 2559 | 9 of 40 | length |
| ATT-0077 | 31998 | 0 | 0 of 40 | length |

The ceiling being hit is roughly 32000 tokens of reasoning plus output, not the 12288 `max_output_tokens` the envelope asks for. Reasoning consumes 85%, then 92%, then 100% of it, and the retries get monotonically worse: the third attempt returned an empty file after thinking for 32000 tokens.

The engine's answer to size today is a `chunking` string in the task capsule instructing the model to emit several top-level JSON objects each under 15KB. **That cannot fix a truncation, because several JSON objects inside one response share one output budget.** It also gives the model a second problem to plan before writing, which is visible in the reasoning burn. The universe design does not work this way: `split_proposal_into_chunks` drives one call per category from the engine, and that path completes.

**Fix:** drive the book design in engine-controlled slices, the way the universe design already is. One call for the spine — premise, arc, entry_state, exit_boundary — then one call per slice of chapters with the outline range named in the capsule and the spine passed as context. Each call's output is small enough to survive a heavy reasoning burn, a truncated slice retries alone instead of restarting the book, and the `chunking` instruction is deleted rather than reworded: the engine now decides the split.

**Tasks:**
- [x] `_book_design_slices` + spine call + per-slice chapter calls in `execute_book_design`
- [x] `chunking` instruction removed from the task capsule
- [x] Per-slice validation and retry; the whole design fails only if a slice keeps failing
- [x] Chunk telemetry recorded per slice, as the universe path does
- [x] Test: a 40-chapter design completes with a stub runner that truncates any call asking for more than one slice
- [x] Test: slices carry the spine and their own chapter range
- [x] Suite green: 230 passed, 23 subtests (era 218)
- [x] `designer.md` documents the spine and chapter-slice chunks
- [x] Existing book-design and e2e fixtures made chunk-aware
- [x] Reinstall ./install.sh --force
- [x] Commit & push

**Done when:** A 40-chapter book design completes, and no single call is asked to emit more than a slice.

## A one-line envelope reaches the model as its first 2000 characters ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** the designer answered a book-design call with 316 tokens of prose and no JSON. `opencode run` truncates every **line** of an attached file at 2000 characters, and `build_envelope` serialises the envelope as compact JSON — one line. A 132630-character envelope reaches the model as its first 2000 characters, so the role never sees its own task.

Measured with the same content in two shapes, under `--agent designer`:

| file | lines | bytes | outcome | provider input tokens |
|---|---|---|---|---|
| multi-line | 506 | 33090 | whole content | 7672 |
| single line | 1 | 31575 | cut at 2000 chars | 1424 |

Reproduced at 30 KB, 60 KB and 130 KB: always `in≈1400`. The same file with no `--agent` arrives whole, which is why an earlier probe of the argv fix passed and proved nothing.

Indenting is not the fix. The real envelope re-serialised with `indent=1` is the same size and still carries **four lines over 2000 characters, the longest 85119** — JSON escapes the newlines inside a canon block, so an 85 KB markdown value stays one line however the document is indented. Passing the envelope in the message instead works at 31 KB and did not return within 170 s at 132 KB.

**Fix:** the attachment gets a wire rendering whose only job is that no line can exceed the cap, for any content. The canonical envelope keeps its bytes, its hash and its receipt — the audit surface does not move. The wire file is pretty-printed, and any string too long for one line is emitted as `{"__chunks__": [...]}`, whose parts concatenate back to the exact original. The wrapper object is what makes it unambiguous: a bare array of strings could not be told apart from a list the envelope already had. The engine decodes the wire file back and refuses to make the call unless it equals the canonical payload byte for byte, so losslessness is checked at run time and not only in tests. The message carries the one sentence a role needs to read it.

**Tasks:**
- [x] `_wire_encode` / `_wire_decode` / `_wire_bytes`, chunking below the line cap
- [x] `run_opencode_role` writes and attaches the wire file, after a round-trip check
- [x] The prompt states how a chunked value reassembles
- [x] Test: round-trip on strings with newlines, unicode, escapes, and one 85 KB value
- [x] Test: no line of the wire rendering exceeds the cap, on the real 132 KB envelope
- [x] Test: a wire file that fails to decode blocks the call
- [x] Suite green: 242 passed, 23 subtests (era 230)
- [x] Live check: the real 132 KB envelope reaches the designer — provider input 91686 tokens against 1424 before
- [x] Reinstall, commit & push

**Done when:** An envelope of any size and any block length reaches the role intact.

## A book cannot run end to end: the engine stops and waits for a human to type what it already knows ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** in one evening a single book stopped eight times, and every stop needed a person at the keyboard. The failures were different; the reason the work halted was the same four things.

1. **Envelope ceilings are arbitrary constants, and they hard-fail.** The designer's input budget is 20000 tokens; the pinned model's context window is 1310720. The ceiling is 1.5% of what the model can physically accept, and crossing it raises `ContextOverflowError` and stops the book. A project knob can raise it, so every time a book's canon grows somebody edits `book-forge.yaml` and reruns. Measured on Margherita: the spine call estimates 10639 tokens and a chapter slice 15027, against a knob of 16000 — 973 tokens of headroom, on a canon that grows with every chapter written.
2. **Deterministic failures park the task and the whole run.** A length truncation, an unparseable answer or a failed validation sets the task to `blocked` and the run to `blocked`, and the next command refuses with `Run does not accept dispatch while blocked`. The cure is a human typing `resume --resolve-blocked TASK:retry` — which is exactly what the engine would do on its own. The human contributes latency, not judgement.
3. **A stale claim is only healed on pause or promote.** `_settle_run` orphans an attempt whose lease expired and which the provider never accepted, but nothing calls it at dispatch, so the task sits `running` and the next command answers `Task is not ready`. The cure is `pause` followed by `resume`, typed by hand, changing nothing the engine could not decide alone.
4. **There is no driver.** `run_next` executes exactly one step and raises when there is nothing to do; design, chapters, translation and export are stitched together by whoever is at the terminal. Every stop is therefore a human stop, and a book is a few hundred steps.

**What must still stop, and stays stopped:** `outcome_unknown` — the provider accepted the call and the outcome is unknown, so a retry may pay twice. That is a judgement about money and it belongs to a person. It is the only one.

**Fix:**

- The wall becomes what the model can actually accept, not a number chosen months ago. Role constants and project knobs become **advisory**: crossing one prints a warning and records a telemetry note; crossing the model's usable window still fails, because nothing else can happen. `context.enforce_budgets: true` restores the old walls for a project that wants them.
- `_recover_before_dispatch` runs at claim time: it orphans stale never-accepted attempts, returns deterministically-failed tasks to `pending` within a bounded retry count, and clears a run blocked by nothing but those. `outcome_unknown` is never touched.
- `book-forge advance --book <id>` drives a book from where it stands to where it is asked to stop: design if it is missing, then every chapter, then the translations, then the editions — recovering between steps, printing what it is doing, and halting only on an unknown outcome or an exhausted retry budget.

**Tasks:**
- [x] Advisory budgets: model-derived wall, warning on the advisory threshold, `enforce_budgets` opt-in
- [x] `_recover_before_dispatch` wired into `claim_task`
- [x] Bounded auto-retry for deterministic failures, recorded per task
- [x] `outcome_unknown` still halts and still needs an explicit resolution
- [x] `book-forge advance --book <id> [--locale <tag>] [--until design|chapters|translate|export]`
- [x] Test: a run blocked by a length failure recovers itself on the next dispatch
- [x] Test: a stale never-accepted claim is orphaned at dispatch, without pause/resume
- [x] Test: an envelope over the advisory threshold warns and proceeds; over the model window it fails
- [x] Test: `outcome_unknown` is not auto-recovered
- [x] Test: `advance` carries a book from an empty design to exported editions with a stub provider
- [x] Test: `advance` stops on an exhausted retry budget and names the task
- [x] Suite green: 254 passed, 23 subtests (era 242)
- [x] `advance` documented in SKILL.md and references/run.md
- [x] Reinstall, commit & push

**Done when:** `advance` takes a book from a brief to its editions without a human typing a recovery command, and the only thing that stops it is a question only a person can answer.

## A claim the provider accepted and never finished is invisible: nothing calls `recover_run` ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** `recover_before_dispatch` orphans a stale attempt only when the provider never accepted it, which is right — an accepted call may have completed and charged, so it cannot be silently retried. But the accepted case then has no handler at all: `recover_run`, which converts an accepted attempt whose lease expired into `outcome_unknown` and blocks the run, is **defined and called from nowhere in the codebase**. So such an attempt stays `running` for ever, its task never enters the ready frontier, and the next command answers `Task is not ready` — the one failure that must reach a person is the one that reaches nobody.

Live on Margherita: `ATT-0078` is `running`, `provider_accepted: true`, lease expired **169 minutes** ago, and the driver would report an unhelpful readiness error instead of naming the decision.

**Fix:** `recover_before_dispatch` calls `recover_run` first. A never-accepted stale attempt goes back to `pending` as it does today; an accepted one becomes `outcome_unknown`, the run blocks, and `advance` halts naming the task and the command that resolves it.

**Tasks:**
- [x] `recover_before_dispatch` delegates stale-claim handling to `recover_run`
- [x] Test: an accepted stale claim becomes `outcome_unknown` and the run blocks
- [x] Test: a never-accepted stale claim still returns to `pending`
- [x] Test: `advance` halts on it naming the task and `resume --resolve-unknown`
- [x] Suite green: 257 passed, 23 subtests (era 254)
- [x] Reinstall, commit & push

**Done when:** The only failure a person must judge is the only one that stops the driver, and it says so by name.

## The spine handed to each design slice accumulates the previous slices' chapters ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** the third slice of a book design answered with a `read_file` tool-call written as text instead of chapters, and the run blocked on `Model output contains no JSON object`. The envelopes tell the story: the first chapter slice is 38840 bytes and the second is **52478** — they are built from the same capsule and must be identical. The difference is the size of the first slice's own answer.

`_merge_design_chunks` mutates its accumulator in place and returns it, and `slice_capsule["spine"]` holds that same object, so every slice's chapters are appended to the spine that the next slice receives. Measured on the failing attempt: the spine sent to `chapters-1-8` carries `arc, entry_state, exit_boundary, premise`; the one sent to `chapters-9-16` carries those **plus eight chapters**. By the fifth slice the model would be handed thirty-two chapters it did not ask for, inside the field that is supposed to hold the book's spine — and it stopped writing and tried to re-read the envelope instead.

**Fix:** the slice capsule takes a snapshot of the spine, not the accumulator. The spine is what the designer decided once; nothing written afterwards belongs in it.

**Tasks:**
- [x] `slice_capsule` carries a deep copy of the spine, taken before the loop
- [x] Test: every slice receives the same spine, and no slice sees another slice's chapters
- [x] Test: the merged proposal still gathers every slice's chapters in order
- [x] Suite green: 260 passed, 23 subtests (era 257)
- [x] Reinstall, commit & push

**Done when:** The fifth slice's envelope is the same size as the first.

## A failure inside a stage escapes `advance` as a bare engine error with no way forward ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** `advance` recovers *between* stages, but a failure *inside* one propagates untouched. When the book design failed, the driver stopped with the engine's own message and the run left `blocked` — no recovery attempted, no instruction printed. The agent watching it reported exactly that: *"advance si è fermato da solo — il run è blocked, non ha stampato comandi di recupero"*. It is the complaint the driver exists to answer: stopping is acceptable, stopping without saying what happens next is not.

**Fix:** each stage runs inside a recovery loop. A failure recovers and retries the stage; it halts only when recovery cannot help — nothing was recovered, a task spent its retries, or a person must decide — and the halt always names the failure, the task, and the command that resolves it.

**Tasks:**
- [x] Each stage retried after recovery, bounded by `MAX_STAGE_ATTEMPTS`
- [x] Every halt carries the original failure and the next command
- [x] Test: a stage that fails once and then succeeds is not surfaced to the caller
- [x] Test: a stage that keeps failing halts naming the failure and the task
- [x] Suite green: 263 passed, 23 subtests (era 260)
- [x] Reinstall, commit & push

**Done when:** `advance` never ends on an engine error the reader cannot act on.

## An envelope larger than one attachment cannot reach the model, and the contract is what gets cut ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** `opencode run` truncates an attachment at about 50 KB, on top of the 2000-character line limit already handled. Landfall's design envelope is 146358 bytes, so the model reads a third of it — and because JSON keys are serialised in sorted order, `task` sits near the end, which means **the contract is precisely the part that is cut**. The model said so itself, in the answer that stopped the run:

> The supplied envelope is truncated at 50 KB — the `task` object's `chunk` field, which names this call's chunk, sits in the unread remainder past line 439.

It then declined to guess a chapter range, which is the right call: emitting the wrong range would be worse than emitting nothing. The spine call before it had succeeded only because "spine" is guessable. Margherita's envelope is around 40 KB and slips under, which is why the same book design behaves differently in the two projects.

Where the size comes from, measured on the failing envelope: `worldbuilding` **85102 bytes**, `brief` 18263, `chapter_outline` 8949, `spine` 4920 — and the whole canon context only 24011 across 43 blocks. One document is 70% of every call.

A second arbitrary constant surfaced behind it: a slice that *did* answer correctly was rejected by `Design chunk exceeds 15360 bytes: 23746`. That guard was written to catch a model ignoring the chunking instruction and emitting a monolith. With engine-driven slices the engine decides the split, so the only meaningful ceiling is what a single call can physically produce.

**Fix:**

- The envelope is delivered across as many attachments as it needs, each under the cap, **smallest-first**, so the contract is always in the first file and can never be the part that is cut. The split is structural and recursive: a dict too large for one file is emitted key by key, a list is chunked, and a `__chunks__` value is split further. Every part is valid JSON and the parts merge back to the canonical payload — checked at run time, not only in tests.
- The parse-time chunk ceiling is derived from the call's own output allowance instead of a fixed 15 KB.

**Tasks:**
- [x] `_wire_attachments` splits the wire rendering into parts under `WIRE_MAX_ATTACHMENT`, contract first
- [x] Parts merge back to the canonical payload, verified before dispatch
- [x] `run_opencode_role` attaches every part, and the prompt says how they merge
- [x] Parse ceiling derived from `max_output_tokens` rather than `DESIGN_CHUNK_MAX_BYTES`
- [x] Test: a 150 KB envelope splits, every part is under the cap and valid JSON, and the merge is exact
- [x] Test: the first part always carries `task` and `role_prompt`
- [x] Test: a single oversized value is split rather than emitted whole
- [x] Test: a small envelope still ships as one file
- [x] Test: a legitimate 23 KB slice answer is no longer rejected
- [x] Suite green: 270 passed, 23 subtests (era 263)
- [x] Measured: the ~50 KB cap is **per attachment**, not on the total — four 42 KB files delivered 168 KB whole (provider input 157483 tokens)
- [x] Reinstall, commit & push

**Limit kept honest:** a single indivisible value larger than one attachment is refused with a message naming its size, never sent to be truncated.

**Done when:** No envelope is too large to arrive, and the part that arrives first is the one that says what to do.

## `designer.md` sends the author's bookkeeping into a field the engine reserves for IDs ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** a book design that completed every slice was rejected with **sixty blocking findings**, all `obligation.unknown`, each carrying a sentence of the designer's own foreshadowing bookkeeping: *"The screen must wake once more and die on 'revert' at the book's end (chapter 27)."* `validate_book_design` reads `chapter.obligations` as a list of IDs of the book's registered obligations — the cross-book promises in `universe/relations.yaml` — and this book has none, so every entry was unknown.

The instruction that produced it is one I wrote this morning: *"Mechanisms, propagation rules, foreshadowing bookkeeping and remarks about act structure belong in plants, reveals and obligations."* The first two are free-text fields for exactly that. The third is not: it is the engine's join to the relation registry, and putting prose in it fails the whole design after every call has been paid for.

**Fix:** `designer.md` states what `obligations` is — the IDs supplied in the task, and nothing else — and sends the author's own bookkeeping to `plants` and `reveals`. The capsule's `required_output` says the same at the point of use, so the rule is visible where the field is filled in.

**Tasks:**
- [x] `designer.md` separates the engine's `obligations` from the author's `plants` and `reveals`
- [x] `required_output` in the book capsule names the constraint at the field
- [x] Test: a design whose chapters carry free-text obligations is rejected with a finding that says what to use instead
- [x] Test: a design that uses registered IDs still validates
- [x] Suite green: 273 passed, 23 subtests (era 270)
- [x] Reinstall, commit & push

**Done when:** The field that joins to the registry holds only what the registry knows.

## The operator prompt is long because the engine makes the caller carry what it should do itself ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** driving a book to the point of writing needed a forty-line prompt, and only its last paragraph was about the book. Everything else was engine knowledge the caller had to be told, or work the engine should do instead of asking:

- *"never launch a second advance while one is alive"* — two drivers on one book contend for claims. The engine knows this and lets it happen anyway.
- *"don't kill it because it looks slow; the chorus writes outside `.book-forge/runs`"* — the driver goes silent for twenty minutes and the caller cannot tell a working run from a hung one.
- *"when it finishes, run these three commands to check the book is ready"* — the driver knows what it produced and says nothing.
- *"an over the advisory budget warning is normal, not an error"* — the warning does not say so itself.
- *"launch it with setsid and disown, poll the saved pid, never `pgrep -f` because `--project .` is identical in every project"* — real operational knowledge, learned the hard way twice today, written nowhere.

**Fix:** each of these moves into the engine or into the route reference, so the prompt keeps only the book.

**Tasks:**
- [x] `advance` takes a per-book lock and refuses a second driver, naming the running pid
- [x] Stage and slice progress printed as it happens, including the chorus, so silence means stopped
- [x] `advance` ends with a readiness receipt: chapters, slices, artifacts written, cost
- [x] The advisory-budget line says it is a warning and not an error
- [x] `references/run.md` carries the launch and polling recipe
- [x] Test: a second `advance` on the same book refuses while the first holds the lock
- [x] Test: a stale lock from a dead pid does not block a new run
- [x] Test: the receipt reports what was produced
- [x] Suite green: 280 passed, 23 subtests (era 273)
- [x] Reinstall, commit & push

**Done when:** The prompt that drives a book to writing is about the book.


## The readiness receipt called a book ready that the auditor had blocked ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** the receipt read contracts on disk and the design task's state, and reported `ready_to_write: true` for a book whose independent audit had just returned a blocking finding — the drowned person in Margherita's design flips from a man to a young woman to a boy across four chapters, and a mid-century photograph clashes with a drowning twenty years ago. `advance` halted correctly and said so; the receipt beside it said the opposite.

**Fix:** readiness reads `design-audit.json` too. A blocking finding there means the book would be written around a contradiction, so the receipt says `NOT ready to write`, names the findings that hold it, and lists the chapters each one touches.

**Tasks:**
- [x] `_advance_receipt` reads the design audit and gates readiness on it
- [x] The printed line names the blocking findings
- [x] Test: a blocking finding holds the book back; warnings alone do not
- [x] Suite green: 284 passed, 23 subtests (era 280)
- [x] Reinstall, commit & push

**Done when:** The receipt and the auditor cannot disagree.

## Each design slice writes blind to what the slices before it committed ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** the independent audit blocked a finished 36-chapter design on a real contradiction — the grave Mary visits holds *a man with a mid-century photograph* in CH-0006, *a drowned young woman* in CH-0011 and CH-0016, and *a boy drowned twenty years ago* in CH-0027, while the design's own plants say all four are the same grief.

The cause is the slicing itself. Verified on the envelope that produced it: a chapter slice receives the spine and a one-line summary per chapter, and `chapters already written: 0`. Slice 1 invents the man and the mid-century photograph inside its beats; slice 2 cannot see those beats and invents the young woman. Before the design was sliced the designer wrote every chapter in one answer and could not contradict itself this way.

A second cost sits behind it: every finding already names the chapters it touches — `repair_scope: ["CH-0006", "CH-0011", "CH-0016", "CH-0027"]` — and the engine still stops and waits for a person to decide what to do with four chapters it could name itself.

**Fix:**

- Each slice receives a digest of what the slices before it established: for every chapter already written, its id, order, title, POV, plants and reveals. Those are the facts the book has committed to. Not the beats — the digest must stay small enough that the envelope does not grow with the book.
- When the audit blocks, the engine repairs instead of stopping: it sends the blocking findings back to the designer scoped to the chapters each one names, merges the rewritten chapters into the proposal, revalidates, re-promotes and re-audits. Bounded rounds; if the audit still blocks, it halts with the findings, as it does today.

**Tasks:**
- [x] Slice capsules carry a `written_so_far` digest of previous slices
- [x] The digest holds identity, title, POV, plants and reveals — never the beats
- [x] `designer.md` states that the digest is settled fact, not a suggestion
- [x] Blocking audit findings drive a scoped repair round instead of a halt
- [x] Bounded repair rounds, then halt with the findings
- [x] Test: slice N sees every chapter from slices 1..N-1 and none of its own
- [x] Test: the digest carries plants and reveals but not beats
- [x] Test: a blocking audit finding triggers a repair of exactly the chapters it names
- [x] Test: an audit that keeps blocking halts with the findings
- [x] Suite green: 290 passed, 23 subtests (era 282)
- [x] The repair call is billed outside the DAG, so its cost is recorded beside the attempt and folded into `telemetry_report` the way a chorus round is
- [x] Reinstall, commit & push

**Done when:** A slice cannot contradict a slice that came before it, and a contradiction the auditor still finds costs a call rather than a decision.

## A truncated slice is retried unchanged, so it truncates again ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** watched live on Margherita: the chapters 9-16 slice came back truncated twice in a row, and the third try is the last before the slice fails. The provider's own numbers say why — **reasoning 27045 tokens against output 4955**, on a ceiling near 32000. The model spent its budget thinking and had nothing left to write eight chapters with.

`_run_design_chunk` builds the envelope once and calls it up to three times with the same bytes. A truncation is not noise: it says the answer asked for does not fit. Repeating the request unchanged has no reason to succeed, and each repeat is paid for.

It is the same shape as every other failure tonight — the engine repeating an action that failed for a structural reason instead of changing it. And the feed-forward digest, which is right, makes it likelier: the first slice that receives a digest has more to read and the same budget to write.

**Fix:** on a length truncation the engine asks for less. A chapter slice splits in half and each half is run as its own chunk, recursively, down to a single chapter. `BOOK_DESIGN_SLICE_SIZE` stops being a number that has to be right and becomes a starting point.

**Tasks:**
- [x] A truncated chapter slice is halved and each half run separately
- [x] The split recurses to a single chapter, then gives up as it does today
- [x] Non-chapter chunks keep the plain retry
- [x] Test: a provider that truncates any slice over four chapters still completes a 40-chapter design
- [x] Test: a single chapter that keeps truncating fails as failed_length
- [x] Test: the merged proposal is identical whether or not a split happened
- [x] Suite green: 294 passed, 23 subtests (era 290)
- [x] Reinstall, commit & push

**Done when:** A truncation makes the next request smaller instead of identical.

## Recovering a run whose driver died takes ten minutes of reading the engine's source ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** an OOM kill left a run marked `running` with a dead driver and an accepted attempt whose lease had expired. The operator ran the documented command and got `Error: Run cannot resume while running`, then spent ten minutes grepping the engine — `cannot resume`, `_orphan_stale_attempts`, `_settle_run`, `recover_run`, `recover_before_dispatch` — before working out that `pause --emergency` is what converts the accepted call to `outcome_unknown` and blocks the run so `resume` will accept it.

The sequence it found is correct. That it had to be found by reading the source is the defect: `resume` refuses on a state that `resume` itself could reach. Nothing about the situation requires a human to know the order — only the retry-or-abandon decision does.

**Fix:** `resume` recovers before it judges. It runs the same stale-claim recovery the dispatch path already runs, so an accepted attempt with an expired lease becomes `outcome_unknown` and the run blocks, and only then does it ask whether every unknown outcome has a resolution. The two-step dance disappears, and `pause --emergency` goes back to meaning what it says. `references/lifecycle.md` states what a dead driver leaves behind and the single command that clears it.

**Tasks:**
- [x] `resume_run` recovers stale claims before checking the run state
- [x] Test: `resume --resolve-unknown` works on a run still marked running whose driver is dead
- [x] Test: a run genuinely running with a live lease still refuses to resume
- [x] `references/lifecycle.md` documents the dead-driver case
- [x] Suite green: 297 passed, 23 subtests (era 294)
- [x] Reinstall, commit & push

**Done when:** One command clears what a killed driver leaves behind.

## The designer is never told what language the book is written in ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** a book whose `source_language` is `en`, whose prose came back in English, got forty chapter titles in Italian — `La straniera in arrivo`, `Il ritorno del prodigo`. The capsule explains why: it carries the scope, the book record, the brief, the worldbuilding, the relations, the obligations and the required output, and **nothing that names the language**. The designer inferred it from a brief written in Italian, which is a reasonable guess and the wrong one: the brief is the author talking to the engine, the book is the book.

Nothing catches it either. `_title_is_beat_prefix` rejects a title copied from a beat, and no check looks at what language it is in.

**Fix:** the book design capsule carries `source_language`, and `designer.md` says every string it returns — titles, beats, plants, reveals, premise, arc — is written in that language whatever language the brief is in.

**Tasks:**
- [x] `source_language` in the book design capsule
- [x] `designer.md` states that the book's language governs, not the brief's
- [x] Test: the capsule carries the project's source language
- [x] Suite green: 299 passed, 23 subtests (era 297)
- [x] Reinstall, commit & push

**Done when:** The language of the book is something the designer is told, not something it guesses.

## The reviser must formally disposition praise ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** the reviser failed with `Revision must disposition every finding exactly once` on a 1600-word chapter. It had been handed **35 findings** — four style reviewers, a cold reader and a technical editor — and had to rewrite the whole chapter and account for every one of them in the same answer. It returned 3945 tokens and stopped normally; it simply did not comply.

Of those 35, **none was blocking, 21 were warnings, and 14 were notes** — including *"Both plants are seeded cleanly with no contradiction"*, which is praise. A note is an observation, not a request for a change, and making the reviser produce a formal `action`/`evidence`/`loss` record for a compliment is overhead that crowds out the work.

**Fix:** `_validate_revision` requires a disposition for every finding a reader must act on — blocking and warning — and accepts, without requiring, dispositions for notes. The reviser still receives the notes as context and may act on them; it is no longer failed for leaving one unremarked. `reviser.md` says which it owes.

**Tasks:**
- [x] `_validate_revision` requires dispositions for blocking and warning only
- [x] A disposition offered for a note is still validated for shape
- [x] `reviser.md` states which findings must be dispositioned
- [x] Test: a revision that dispositions every warning and no note validates
- [x] Test: a missing warning disposition still fails
- [x] Test: a malformed note disposition still fails
- [x] Suite green: 304 passed, 23 subtests (era 299)
- [x] A disposition for a finding nobody raised is refused by name
- [x] Reinstall, commit & push

**Done when:** The reviser owes an answer for what it was asked to change, not for what it was told it did well.

## Four style reviewers produce findings that all have the same identifiers ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** every style reviewer numbers its own findings from `01`, and the engine prefixes them all with `S-`. With four reviewers on one chapter, `S-01` is four different findings. Measured on chapter two: twenty-five style findings collapse onto nine identifiers — `S-01` four times, `S-02` four times, `S-03` four times, `S-04` four times, `S-05` three times.

The reviser is then asked to disposition each finding exactly once, holding four different requests that share a name. It answered 5221 tokens and covered almost none of them. Worse than the failure: had it succeeded, one disposition would have silently stood for four unrelated findings and three would have been lost without trace.

**Fix:** a finding's identifier carries the reviewer that raised it — `S-glm-5-3-flash-01` — so twenty-five findings keep twenty-five names. The reviser can answer each, and a disposition can no longer stand in for a finding nobody read.

**Tasks:**
- [x] Style finding ids namespaced by the reviewer's model slug
- [x] Test: four reviewers each numbering from 01 produce no collision
- [x] Test: the id still starts with S- so severity handling is unchanged
- [x] Suite green: 306 passed, 23 subtests (era 304)
- [x] Measured on the live book: chapter one's 24 style findings reached the reviser as 8 names, and its dispositions record 28 answers under 14 identifiers
- [x] Reinstall, commit & push

**Done when:** Twenty-five findings have twenty-five names.

## The word-count floor forbids the style pass from doing its job ✅

**Status: ✅ Done — 2026-08-27**

**Problem:** the style re-revision of a closed chapter failed with `Writer output word count 1335 is outside 1400..2800`. The chapter's contract asks for 2000 words, so the floor is 1400; the chapter already stood at 1438 after its first revision, and the style pass — which is now required to propose only replacements shorter than what they replace — cut it to 1335.

The two rules contradict each other sixty-five words apart. The floor exists to stop a writer delivering half a chapter, and it is measured against the contract because a draft has nothing else to be measured against. A style pass does: the prose it was handed. Measuring its output against the original target forbids it from removing anything once a chapter is already under target, which is exactly when it has most to remove.

**Fix:** a style-only revision is measured against the prose it received — it may not drop below 70% of that — instead of against the contract's target. A reviser that throws half the chapter away is still caught; one that cuts a fifth of the padding is not.

**Tasks:**
- [x] `_validate_revision` takes the baseline prose for a style-only pass
- [x] The draft path is unchanged and still measured against the contract
- [x] Test: a style pass cutting a fifth of a chapter already under target lands
- [x] Test: a style pass that halves the chapter is still refused
- [x] Test: a draft below the contract floor still fails
- [x] Suite green: 310 passed, 23 subtests (era 306)
- [x] Reinstall, commit & push

**Done when:** The pass that is told to cut is measured against what it cut from.

# The chapter pipeline is blind to the world it is writing about

Two chapters of a finished book were read closely and the defects sorted by origin. The largest one is in neither the design nor the prose: **every chapter contract carries `imports: ['UNI-0001#kernel']`, and the engine hardcodes that list**. In `execute_book_design` the required output contains `"imports": chapter_imports` where `chapter_imports = ["UNI-0001#kernel", *relation_imports]`, so no chapter can import a character, a place or an era.

What that means, traced through the code: the writer, the technical editor and the reviser all build their envelope from `contract["imports"]`, and the cold reader is denied context on purpose. **No role in the chapter pipeline ever sees the POV character's canon.** `technical-editor.md` is told to audit "against its contract and visible canon"; its visible canon is one block of universe invariants.

The consequences, measured on the manuscript: a German protagonist whose canon says *"when she slips into German under her breath, the town notices"* speaks two chapters without an accent, a foreign word or anyone hearing she is foreign; the town says her name although nobody asked it; the era is never stated anywhere so the writer invented the 1950s inside a brief that says contemporary; and the geography is a generic fishing harbour with a ferryman in a town of salt pans and a straight beach.

The seven fixes below are ordered: the first opens the pipe, and the rest are worth less without it.

## 1. A chapter contract imports the canon it depends on ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** the engine dictates every chapter's imports and dictates almost nothing. The designer receives the book's canon as context and is then told to write `["UNI-0001#kernel"]` into every chapter, so the canon it just read cannot reach anyone downstream.

**Fix:** the designer chooses each chapter's imports from the canon it was given, and validation requires the minimum that makes a chapter checkable: the kernel, the POV character's `summary` and `voice`, and at least one place. An import that names no known block is blocking.

**Tasks:**
- [x] `required_output` asks the designer for the imports a chapter depends on
- [x] `designer.md` states what belongs in a chapter's imports and why
- [x] `validate_book_design` requires kernel + POV summary and voice + a place
- [x] `validate_book_design` refuses an import that resolves to no block
- [x] Test: a chapter importing only the kernel is blocking
- [x] Test: a chapter naming a block that does not exist is blocking
- [x] Test: the writer envelope carries the POV character's voice
- [x] Suite green: 334 passed, 23 subtests (era 310) · reinstall, commit & push

**Done when:** The role that must judge whether the protagonist sounds like herself has her voice in front of it.

## 2. An era is a date and its consequences, not a name ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** an era row carries a name and a summary — *"The Liminal Lull — late May, the off-season pause"* — and no year, no object, no price. The brief says contemporary; the prose is a 1950s novel with a postmistress writing arrivals in a book, a guesthouse with no key and a woman walking from the station with a suitcase. Nothing in the pipeline ever stated a period, so the writer chose one.

**Fix:** an era carries `when` and `material` — three to five concrete facts a scene must obey: how people travel, how they reach each other, what money looks like, what a stranger's arrival means. An era without `when` is blocking.

**Tasks:**
- [x] `designer.md` universe scope requires `when` and `material` on every era
- [x] `validate_universe_design` blocks an era with no `when`
- [x] Test: an era without a date is blocking; one with a date and material passes
- [x] Suite green: 334 passed, 23 subtests (era 310) · reinstall, commit & push

**Done when:** No book has to guess what century it is in.

## 3. The technical editor judges the world, not the sentences ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** with canon in its envelope for the first time, the role's instruction is still generic. On a chapter where the protagonist's nationality had vanished and the town used a name nobody had given it, it returned six findings about phrasing.

**Fix:** `technical-editor.md` asks the questions the canon makes answerable: does the POV character behave and sound as her voice block says, does the place match its block, does the chapter obey the era's material facts, and — the one that catches the name — does anyone act on knowledge the text never gave them.

**Tasks:**
- [x] `technical-editor.md` rewritten around conformance to the imported canon
- [x] Test: the prompt names the checks and the role still returns its contract
- [x] Suite green: 334 passed, 23 subtests (era 310) · reinstall, commit & push

**Done when:** A chapter that contradicts the canon it imported is a blocking finding.

## 4. Dialogue rules, and a lens that reads for them ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** `writer.md` gives dialogue one line. Measured across two chapters: seventy-two lines of dialogue, six questions, and not one practical need. Nobody asks her name, how long she is staying or whether she has eaten. Every line states the book's theme — *"we are not a town of locked doors"*, *"the town has all summer to ask its questions"*, *"you'll pay me in the end"*. A fourteen-year-old reads an adult stranger twice in five minutes and introduces himself as "the ferryman's boy". In one dinner a woman the canon calls guarded answers eight consecutive questions truthfully.

**Fix:** writer.md gains the rules that forbid it, and style-review.md gains the check, or four reviewers will go on counting appositives while the landlady speaks like a chorus.

**Tasks:**
- [x] `writer.md`: no line states the theme; every scene carries one practical want; someone misunderstands or answers beside the question; nobody introduces themselves by their function; an interrogation costs the asker something
- [x] `style-review.md` reads dialogue for those five
- [x] Test: both prompts carry the rules
- [x] Suite green: 334 passed, 23 subtests (era 310) · reinstall, commit & push

**Done when:** A line that could serve as the book's epigraph is a finding.

## 5. The design may not spend a reveal before the arc places it ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** the arc says the past surfaces from chapter nine. Chapter two's third beat says to take the photograph of the drowned man out of the suitcase, and its reveals say *"Reveal to the reader what the town cannot see: Mary carries a dead man"*. The design contradicts its own arc and nothing looks.

**Fix:** the canon auditor, which already receives the whole proposal and the arc, is asked to check the reveal schedule against it, and to check that every reveal has a plant in an earlier chapter. This one stays a judgement: plants and reveals are prose, and a mechanical check would be a fake.

**Tasks:**
- [x] `canon-auditor.md` checks reveals against the arc's phases and against their plants
- [x] Test: the prompt carries the check
- [x] Suite green: 334 passed, 23 subtests (era 310) · reinstall, commit & push

**Done when:** A book cannot spend at chapter two what its own arc placed at chapter nine.

## 6. A translation has a contract, not only a glossary ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** `translations/it/style.md` is still the stub the engine generated: *"Define register, dialogue punctuation, narrative tense, and voice-preservation decisions here."* Nobody defined them, so the translator improvised: `tu` and `Lei` mixed inside sentences that also say `signora`, a masculine adjective for a female character, calques that mean nothing in Italian, English title case on a chapter heading. And `The train stopped at sixteen past five` became `alle sedici e cinque` — 5:16 turned into 16:05 — because the numeric check only looks at digits.

**Fix:** the locale style file stops being optional: a translation refuses to run while it is still the stub. The heading case check is deterministic and free. The register decision belongs in that file, and the translator is told to obey it.

**Tasks:**
- [x] `translate` refuses while the locale style file is unedited, naming the file
- [x] Heading case validated against the locale
- [x] `translator.md` obeys the locale style file's register and refuses calques
- [x] Test: the stub blocks; an edited file passes; a title-cased heading is a finding
- [x] Suite green: 334 passed, 23 subtests (era 310) · reinstall, commit & push

**Done when:** No translation starts before someone has decided how the book speaks in that language.

## 7. Repetition is caught by counting, not by asking ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** in two chapters, `counted` five times, `her own name` three, the wet stone in a pocket twice within twelve lines. Four paid style reviewers did not mention it once.

**Fix:** a deterministic pass counts repeated phrases and adds them to the findings the reviser receives, at no model cost.

**Tasks:**
- [x] `_repetition_findings` over the draft, merged into the review findings
- [x] Distinctive phrases only — stop words and dialogue tags excluded
- [x] Test: a phrase repeated three times is a finding; ordinary prose is not
- [x] Suite green: 334 passed, 23 subtests (era 310) · reinstall, commit & push

**Done when:** The cheapest defect to find is not the one that survives four reviewers.

**Measured against the manuscript that produced this plan.** Repetition, run over the two written chapters, returns `with the window open` three times, `a woman who wants` twice, `suitcase` ten times — none of which four paid style reviewers mentioned. The heading check flags `La Stanza Sopra il Portone`. The import rule makes both existing chapters blocking, which is correct: they were written with no world in front of them.

**What is deliberately not mechanical.** The reveal schedule is judged by the auditor, not by a rule: plants and reveals are prose, and a regular expression pretending to read them would be a fake check that reports success.

## The era became a fact nobody can import ⏳→✅

**Status: ✅ Done — 2026-08-28**

**Problem:** eras were given a date and material facts, and chapters were told to import "the era it happens in" — but eras live in `universe/timeline/eras.yaml` and only markdown under `universe/canon` becomes an addressable block. Measured on the live book: 238 blocks indexed, prefixes BOOK, CHR, FAC, LAW, PLC, STYLE, UNI, and **no ERA at all**. The date is required, and it can reach nobody.

**Fix:** an era is materialised as canon like a character or a place, with its `summary`, `when` and `material` as blocks, so a chapter can import `ERA-0001#when` and the writer is told what century it is in.

**Tasks:**
- [x] `_universe_design_outputs` writes `universe/canon/eras/ERA-*.md`
- [x] Test: an era becomes addressable blocks after a design
- [x] Test: a chapter can import the era and the writer envelope carries the date
- [x] Suite green, reinstall, commit & push

**Done when:** The century is a block someone can read.

## A correct spine was thrown away for its wrapper ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** the book design failed twice with `spine returned no chapter_outline`, and the answer it rejected was complete. The designer had wrapped its reply in the name of the thing it was asked for — `{"spine": {"premise": …, "arc": […], "chapter_outline": [40 rows]}}` — and the driver read `chapter_outline` at the top level, found nothing, and blocked the task. Forty outline rows and an arc were produced and paid for twice, and discarded both times.

`_merge_design_chunks` already unwraps exactly this shape for the universe design's `tail` chunk. The book's spine had no such courtesy.

**Fix:** a chunk answer that consists of a single key naming the chunk itself is unwrapped before it is read, for the spine as for the tail. The engine gets what it asked for however the model chose to label it.

**Tasks:**
- [x] A single-key `spine` wrapper is unwrapped
- [x] `chapters` wrapped the same way is unwrapped too
- [x] Test: a wrapped spine and a bare spine give the same result
- [x] Test: a genuine field called spine inside a slice capsule is untouched
- [x] Suite green, reinstall, commit & push

**Done when:** A right answer is not refused for how it was addressed.

## A twenty-minute job holds a five-minute lease ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** `_run_book_design_chunked` takes one claim and then makes six or more provider calls under it — a spine and five chapter slices. Measured on the live book, one spine call alone runs 150 to 220 seconds, and a whole design is around twenty minutes. The lease is **300 seconds** and nothing renews it.

So from the fifth minute onward a healthy, working attempt is indistinguishable from an abandoned one. Any recovery that runs in that window — `advance`'s own guard before its next stage, a `status`, an operator looking in — converts a live call into `outcome_unknown` and blocks the run, and the work it was doing is thrown away and has to be paid for again. Several of tonight's unexplained unknown outcomes were this, including one I caused myself by checking on a run while it worked.

**Fix:** the lease is renewed every time the provider answers. `mark_provider_accepted` already runs on each response and is the one moment the work is demonstrably alive, so renewal belongs there and covers every multi-call path at once — the design's slices, the pivotal variants, the translation repairs.

**Tasks:**
- [x] `mark_provider_accepted` extends the lease and the heartbeat
- [x] Test: an attempt that answers stays out of reach of recovery past its original lease
- [x] Test: an attempt that goes silent is still recovered
- [x] Suite green, reinstall, commit & push

**Done when:** Work that is answering is not mistaken for work that has died.

## OpenCode is a hard requirement that nothing declares and nothing checks ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** `run_opencode_role` is the only executor. It builds `opencode run --pure --dir … --agent <role> --format json --file <envelope>` and verifies the pin with `opencode --pure debug agent <role>` before every call, so the skill needs a CLI that exposes `run` with `--agent`, `--file`, `--format` and `--variant`, and the `debug agent` subcommand. `init` and `runtime sync` go further and write `opencode.json` and `.opencode/agents/*.md` into the project: the skill does not merely call OpenCode, it configures it.

None of that is declared. `SKILL.md` has no prerequisite, `install.sh` checks its own payload and never asks whether OpenCode exists, and `verify_runtime` — which does check the version and some run capabilities — **is called from nowhere in production**. It is reachable only from a test.

The cost was measured tonight: a CLI whose `--file` is a yargs array swallowed the prompt, and the failure surfaced as `Error: File not found: Process the attached envelope and return the requested output contract.` An hour went into reading that as an engine bug. A declared requirement would have named it in one line.

**Fix:** the capabilities the engine depends on are checked once per process before the first dispatch, cheaply and without a network call, and a missing one is reported as an unmet requirement naming the flag. `verify_runtime` gains the two capabilities that bit us, `install.sh` refuses to install without OpenCode, and `SKILL.md` states the requirement where a reader meets it.

**Tasks:**
- [x] `_verify_opencode_cli` checks `--agent`, `--file`, `--format`, `--variant` and `debug agent`, once per process
- [x] `run_opencode_role` runs it before the first dispatch
- [x] `verify_runtime` checks the same capabilities
- [x] `install.sh` fails when OpenCode is absent or too old
- [x] `SKILL.md` declares the requirement
- [x] Test: a CLI missing a flag fails naming it, and the check runs once
- [x] Suite green, reinstall, commit & push

**Done when:** A CLI that cannot do what the engine needs says so, instead of failing as a missing file.

## The designer is asked to import blocks it is never shown ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** the new import rule blocked a design for a missing `CHR-0001#voice`, and the designer had done exactly what it could: it imported the POV character, the other characters in the scene, five places and two laws. Every one of them a `#summary`, because **all 62 rows of context it receives are `#summary` blocks**. The voice blocks, the era blocks, every other detail block — it has never seen that they exist.

Validation demanded a name the designer had no way to learn. And the repair hint it would have been handed on retry talks about tier word counts, which has nothing to do with imports, so the second attempt would have failed the same way with worse advice.

**Fix:** the capsule carries the catalogue of block ids the project actually has — a few kilobytes of names, not content — so choosing imports becomes possible instead of guesswork. The repair hint learns the import case and says what is missing.

**Tasks:**
- [x] `available_blocks` in the book design capsule
- [x] `designer.md` says to choose from the catalogue
- [x] The repair hint covers import failures
- [x] Test: the capsule lists voice and era blocks, not just summaries
- [x] Suite green, reinstall, commit & push

**Done when:** Every block the validator can demand is a block the designer was shown.

## The canon audit thinks for thirty-two thousand tokens and says nothing ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** the independent audit of a finished forty-chapter design returned an empty answer. Its receipt: input 41478 tokens, **reasoning 32000, output 0**, finish `length`. It spent the whole ceiling thinking and never wrote a word, so a design that was otherwise ready could not be cleared.

The envelope is 113262 bytes and 91639 of it is the proposal. Inside the chapters, measured field by field: `beats` 34694, `plants` 17232, **`imports` 12034**, `reveals` 10924, `summary` 6072. The auditor is handed every block id every chapter imports — fourteen percent of the payload — and has no use for them: `validate_book_design` already checks imports mechanically and refuses the ones that resolve to nothing.

**Fix:** the audit receives what a continuity audit reads. `imports` goes, because another check owns it. `beats` go, because they are the staging and a contradiction between chapters lives in what each one plants, reveals and promises — the grave that changes occupant is visible in the plants, not in the blocking. That is a 56% cut, from 83010 bytes of chapters to about 36000, and an auditor that answers catches more than one that thinks until it runs out.

**Tasks:**
- [x] The book audit payload drops `imports` and `beats`
- [x] `canon-auditor.md` says what it is reading and what it is not
- [x] Test: the audit capsule keeps plants, reveals and summaries and drops the rest
- [x] Test: the universe audit is unchanged
- [x] Suite green, reinstall, commit & push

**Done when:** The audit has room to answer.

**Correction — 2026-08-28.** The cut shipped to two of the three places that build the audit capsule. The third, the resume path in `execute_book_design`, kept sending the whole proposal, and it is the path every failing attempt took: the envelope measured afterwards was 96660 bytes with all 34694 bytes of `beats` still in it. The cut now lives inside `_design_audit_record`, so no caller can forget it.

## The design counts as done before it has been audited ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** `advance --until design` ran on a book whose outline and forty contracts existed and whose `AUDIT-BOOK-0001` was still `pending`, and reported `stages none` — it did nothing at all, because `_advance_needs_design` reads the outline and the contracts on disk and asks nothing about the audit. The audit had never produced a record, so the book could never be cleared by running the stage that owns it.

The receipt beside it was worse: `design_audit: {"state": null, "blocking": 0}` and **`ready_to_write: true`**. Readiness was taught to respect a blocking audit and still treats an audit that never ran as an audit with nothing to say. A book was declared ready to write on the strength of a check that had not happened.

**Fix:** the design stage is unfinished while its audit task has not succeeded, and a book with no audit record is not ready to write. An absent verdict is not a clean one.

**Tasks:**
- [x] `_advance_needs_design` requires the audit task to have succeeded
- [x] `_advance_receipt` refuses readiness without an audit record
- [x] Test: contracts present and audit pending still runs the design stage
- [x] Test: a book with no audit record is not ready to write
- [x] Suite green, reinstall, commit & push

**Done when:** A check that never ran cannot pass.

## The canon auditor is pinned to think until the ceiling ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** the book audit returned nothing three times running. Its receipts, across two payload sizes: input 41478 then 34835 tokens, and both times **reasoning 32000, output 0, finish `length`**. Cutting the payload by half moved the input and changed nothing else, so the size was never the binding constraint.

The role's pin is: `canon-auditor` at variant **max**, with an output allowance of 3500 — maximum reasoning effort and the smallest budget but one. Asked an open question over a whole book, the model spends the entire ceiling thinking and never reaches the answer. The designer writes forty chapters at `medium`; the technical editor makes a comparable judgement at `high` and returns findings.

**Fix:** the auditor runs at `high`. A pin change does not reach a project until `runtime sync` regenerates its agents, and until then `run_opencode_role` refuses with `Resolved OpenCode agent pin differs` — a sentence that names neither what differs nor what to do. It now names both.

**Tasks:**
- [x] `canon-auditor` variant `max` → `high`
- [x] The pin mismatch error names the role, both variants and `runtime sync`
- [x] Test: the pin is high and the mismatch message is actionable
- [x] Suite green, reinstall, sync the live projects, commit & push

**Done when:** The role that must answer has room left to answer in.

**Correction — 2026-08-28.** This is wrong, and it is wrong because it reasoned from receipts of a payload that was never actually cut. Measured since on the same envelope: at `high`, reasoning 31999 and no output; at `medium`, reasoning 32000 and no output; and with the cut genuinely applied, input 18079 and still no output. The variant changes nothing. Ten chapters at 10763 tokens answer with reasoning to spare, so the binding constraint is how much book is in the question. `high` is kept because it is the right effort for the job, not because it fixed anything.

## A claim whose owner is gone waits five minutes to be noticed ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** every time a driver is stopped — killed, interrupted, taken down with its shell — its in-flight claim stays `running` until the lease expires, and nothing can be dispatched for that task until then. Four times tonight the recovery was a wait: the process was demonstrably gone, its pid absent from the process table, and the engine went on holding the task for the remainder of five minutes because the only staleness it knows is the clock.

**Fix:** an attempt records the pid that claimed it. Recovery treats a claim whose owner is no longer running as stale immediately, and then applies the same split it always did — never accepted goes back to `pending`, accepted becomes `outcome_unknown` for a person to decide. The lease stays as the fallback for the case the pid cannot answer for: another machine, a container, a process that outlived its own record.

**Tasks:**
- [x] `claim_task` records the owning pid
- [x] `recover_run` treats a dead owner as stale without waiting for the lease
- [x] The accepted / never-accepted split is unchanged
- [x] Test: a dead owner is recovered at once; a live one is left alone
- [x] Test: an attempt with no recorded pid still waits for its lease
- [x] Suite green, reinstall, commit & push

**Done when:** Work whose owner is gone is free at once.

## The audit is one question over forty chapters, and only a tenth of it fits ✅

**Status: ✅ Done — 2026-08-29**

**Problem:** the book audit has now returned an empty answer five times. Three measurements on the same design settle what is actually binding. Forty chapters with the whole proposal: input 34822, reasoning 32000, output 0. Forty chapters with `beats` and `imports` removed: input 18079, reasoning 32000, output 0. Ten chapters: input 10763, reasoning 27237, **output 917 and findings that name real defects** — it caught CH-0009 spending the book's engine ahead of the arc. The task is too large to answer in one call, and the threshold sits between eleven and eighteen thousand tokens of input.

Two entries above this one recorded conclusions this contradicts, and both need correcting rather than leaving to mislead the next reader.

*The payload cut never ran.* `_audit_proposal` is applied at two of the three places that build the audit capsule. The third is the resume path in `execute_book_design` — design succeeded, audit still pending — which passes the raw proposal, and that is the path every one of the failures took. The envelope measured on the last attempt is 96660 bytes and still carries 34694 bytes of `beats` and 12034 of `imports`.

*The variant was not the cause.* The auditor was moved from `max` to `high` on the strength of receipts that were never cut. Measured since: at `high`, reasoning 31999; at `medium`, reasoning 32000. Effort changes nothing here.

**Fix:** the audit is sliced the way the design already is. Each pass reads ten chapters in full against the spine and a one-line digest of the whole book, so a chapter can still be judged out of place. A final pass reads only what carries cross-chapter contradiction — every chapter's `plants` and `reveals`, with the spine — because a grave that changes occupant is visible there and nowhere else. A pass that comes back without JSON is halved and retried, reusing the machinery the design slices already have. Findings are namespaced per pass, since four passes numbering from `F-001` is the identifier collision the style review already hit.

**Tasks:**
- [x] The cut moves inside `_design_audit_record`, so no call site can skip it
- [x] `_run_book_audit_chunked`: windows of `BOOK_AUDIT_SLICE_SIZE = 10` over spine + digest + window
- [x] A schedule pass over every chapter's plants and reveals
- [x] Truncated pass halves and retries
- [x] Findings namespaced per pass, merged into one verdict
- [x] Test: no pass is handed `beats` or `imports`
- [x] Test: forty chapters produce five passes and one merged verdict
- [x] Test: a pass that returns no JSON is halved
- [x] Correct the two entries above that record the wrong cause
- [x] Suite green: 385 passed, 23 subtests (era 370). Reinstall, commit & push
- [x] Margherita's audit clears, and the first three chapters are written — **verified 2026-09-02**, and both halves were already true before anyone looked: `AUDIT-UNI-0001` and `AUDIT-BOOK-0001` succeeded, and `manuscript/chapters` holds three chapters. The work was done and the box was never ticked, which is the failure this plan keeps finding in itself

**Done when:** The auditor is asked a question it can finish answering.

## Every model call boots ten MCP servers, and one of them stopped the run for two hours ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** an audit pass launched at 18:42 was still running at 20:41 and had produced no provider event at all — not even `step_start`. The process tree says why. Each `opencode run` spawns the ten MCP servers declared in the operator's `~/.config/opencode/opencode.json` — airtable, gmail twice, drive, linkedin, notebooklm, trello and three local ones — and waits for them before it opens a session. One of them is installed as `uvx <package>@latest`, which resolves the package over the network on every launch. The run was blocked in that wait.

`--pure` does not cover this: it disables external plugins and leaves MCP servers alone. Every book-forge role builds its envelope with `tools=[]` and never calls a tool, so all ten are cost with no use — and, given they are started once per call, the likeliest explanation for the session failures and the `systemd-oomd` kills already seen on this machine.

The second half is that nothing bounded the wait. `run_opencode_role` calls `subprocess.run` three times — `debug agent`, `run`, `export` — and none of them passes a timeout, so a provider call that never answers holds the driver until a person notices. It held this one for two hours, and the monitor's report of "stalled 15 minutes" was the only sign.

**Fix:** book-forge runs opencode against a config derived from the operator's with the `mcp` block removed, so the roles get the model pin, the provider and the permissions and none of the servers. And every opencode subprocess gets a wall-clock timeout. On expiry the child's process group is killed rather than the child alone, and what was captured before the timeout decides how it is reported: a session id already on the wire means the provider accepted the call and the outcome is genuinely unknown, no session id means nothing was accepted and the attempt is retryable.

Measured while diagnosing: the same pass that hung for two hours answered in 250 seconds with the MCP servers gone.

**Tasks:**
- [x] `_opencode_environment` derives a config without `mcp`, from `OPENCODE_CONFIG` / `OPENCODE_CONFIG_DIR` / the default path
- [x] All three opencode subprocesses use it
- [x] A wall-clock timeout on each, killing the process group
- [x] A timeout with a session id is `ProviderOutcomeUnknown`, without one is retryable
- [x] Test: the derived config keeps the provider pin and drops the servers
- [x] Test: a call that never answers fails instead of hanging, and its whole process group goes
- [x] Test: a timeout after acceptance does not silently retry
- [x] The argv and wire tests intercept `_run_opencode_process`, not `subprocess.run` — patched at the old target they were invoking the real CLI, which is why the suite took ten minutes
- [x] Suite green: 401 passed, 23 subtests (era 385). Reinstall, commit & push

**Done when:** A model call that never answers costs minutes, not an evening.

## Ten chapters is still too much for one audit pass ✅

**Status: ✅ Done — 2026-08-28**

**Problem:** the sliced audit shipped with `BOOK_AUDIT_SLICE_SIZE = 10`, chosen from a probe where ten chapters answered at 10763 tokens of input. In production both ten-chapter windows failed the same way the whole book did — `window-1-10` returned zero bytes, `window-11-20` came back `length` with reasoning 31999 and output 0 at 9508 tokens of input — and only the five-chapter halves answered, at 7638 tokens with 16816 of reasoning. The halving recovers it, but it pays a failed call for every window before it does.

The probe that set the number was run on an envelope that still carried the beats, which made it larger, not smaller, than what production sends. So the number was not conservative; it was drawn from a different distribution.

**Fix:** the first request is the size that answers. Five chapters per window.

**Tasks:**
- [x] `BOOK_AUDIT_SLICE_SIZE` 10 → 5
- [x] Tests follow the new width
- [x] Suite green, reinstall, commit & push

**Done when:** The common case does not begin with a call that cannot succeed.

## A design that is already promoted cannot be repaired, only refused ✅

**Status: ✅ Done — 2026-08-29**

**Problem:** the audit finally ran end to end on a forty-chapter design and returned ten findings, four of them blocking — CH-0019, CH-0024 and CH-0025 each firing the arc's fifth turn between five and eleven chapters before the arc places it, and CH-0028 answering a pressure the arc has it precede. The engine then stopped: `design failed and nothing could be recovered`.

It stopped because of which path it was on. `execute_book_design` audits with `raise_on_blocked=False` and hands the findings to `_repair_blocked_design`, which rewrites exactly the chapters each finding names and audits again, twice, before giving up. The branch taken when the design is already promoted and only the audit is outstanding does none of that: it audits, raises, and returns. That is the same branch that was sending the uncut payload — the resume path is the one every long run ends up on, and it has been the poorer of the two twice now.

`_repair_blocked_design` also takes the design's `claim` for one reason: to find a directory to write its envelope and raw answer into. On the resume path there is no design claim, because that task succeeded hours ago. It already writes its telemetry under `.book-forge/repairs/<book>/round-N/`, which is where the rest of it belongs too.

**Fix:** both paths audit the same way and repair the same way. The designer capsule is built once, from disk, by a helper both call, so the repair on the resume path sees the brief, the worldbuilding, the obligations and the available blocks exactly as the first pass did. `_repair_blocked_design` writes beside its telemetry and stops needing a claim.

**Tasks:**
- [x] `_book_design_base_capsule(root, book_id)` builds the designer capsule from disk
- [x] `execute_book_design` uses it in place of the inline construction
- [x] The resume path audits with `raise_on_blocked=False`, repairs, then raises if still blocked
- [x] `_repair_blocked_design` writes under `.book-forge/repairs/` and drops the `claim` parameter
- [x] Test: a promoted design with a blocking audit is repaired, not refused
- [x] Test: the repair capsule carries the same world the first pass had
- [x] Test: a repair that still blocks after the bounded rounds still halts
- [x] A stored blocking verdict reopens the audit instead of short-circuiting every later run
- [x] Test: a blocked verdict is tried again and repaired; a clean one still costs nothing
- [x] `_advance_needs_design` keeps the stage due while the verdict is blocking, so the driver dispatches the repair instead of printing `stages none` beside the findings
- [x] Test: a succeeded-but-blocking audit does not finish the stage
- [x] Suite green: 412 passed, 23 subtests (era 401). Reinstall, commit & push
- [x] Margherita's design clears (`design_clean`, 0 blocking) and CH-0001..0003 are written, translated, exported and published

**Done when:** Reaching the audit late does not cost the book its repair.

## The repair asks for ten chapters in one answer, gets none, and says nothing ✅

**Status: ✅ Done — 2026-08-29**

**Problem:** the repair round finally ran on a real blocked design and produced an empty file. `raw-repair.txt` is 0 bytes. The call carried an envelope of 34473 tokens — the whole designer capsule, the spine, a digest of the thirty chapters not being touched, ten full chapter contracts and the findings — and asked for ten rewritten contracts back. It is the shape that has failed at every other size in this engine, and it failed here.

What the engine did with that is worse than the failure. A truncated answer is caught and discarded:

```
except BookForgeError:
    return proposal, audit
```

No log line, no retry, no second round. From the outside it is indistinguishable from a repair that looked at the findings and decided nothing needed changing, and the caller then raises the audit's blocking findings as if the repair had been given its two rounds. It was given none.

There is a second cost above it. On the resume path the engine re-audits the whole book before repairing, although a blocking verdict is already on disk. That is eleven calls to rediscover what we know — and because the auditor is not deterministic, it rediscovers a *different* list each time: one run named CH-0019, CH-0024, CH-0025, CH-0026, CH-0028; the next named CH-0009, CH-0011, CH-0016, CH-0018, CH-0028, CH-0030, CH-0031, CH-0032, CH-0035, CH-0040. A repair aimed at a target that moves between rounds cannot converge.

**Fix:** the repair is sliced like everything else in this engine. Chapters are rewritten a few at a time, each call carrying only the findings that name them, and a slice that comes back truncated is halved and asked again — the machinery `_halve_chunk` already provides. A slice that cannot be halved further fails loudly with what it was asked for, instead of returning as though it had nothing to do. And a run that already holds a blocking verdict repairs from it first and audits afterwards, so the round works against a fixed list and the eleven-call rediscovery is paid once, at the end, to check the work.

**Tasks:**
- [x] `_repair_blocked_design` rewrites in slices of `REPAIR_SLICE_SIZE` chapters
- [x] Each slice carries only the findings naming its chapters
- [x] A truncated slice is halved; one that cannot be halved raises with the slice named
- [x] The resume path repairs from the stored verdict before re-auditing
- [x] Test: ten named chapters become several calls, not one
- [x] Test: a truncated slice is retried smaller, not silently dropped
- [x] Test: a repair that produces nothing at all is an error, not a clean return
- [x] Suite green: 418 passed, 23 subtests (era 412). Reinstall, commit & push
- [x] Margherita's design clears (`design_clean`, 0 blocking) and CH-0001..0003 are written, translated, exported and published

**Done when:** A repair that could not be delivered says so.

## Rewriting one chapter costs a digest of the other thirty-nine ✅

**Status: ✅ Done — 2026-08-29**

**Problem:** the repair halved down to a single chapter and still came back empty, and the engine said so — which is the improvement working, and also the end of what halving can do. Measured on that one-chapter envelope, 75216 bytes:

| field | bytes |
|---|---|
| `written_so_far` | 34787 |
| `context` (canon imports) | 19831 |
| `role_prompt` | 5473 |
| `available_blocks` | 4802 |
| `spine` | 2627 |
| `chapters_to_rewrite` | 2530 |

Forty-six percent of the call is the digest of the thirty-nine chapters it is not touching, and the chapter it *is* touching is three percent. Slicing cannot reach that: the part that dominates is the part that does not shrink when the slice does. The digest exists for a real reason — a slice that cannot see what the other chapters promised invents a detail that contradicts one — but a repair does not need all of them. It needs the chapters its findings name, and the ones on either side of what it is rewriting.

**Fix:** the repair's `written_so_far` carries the chapters the slice actually reasons about — every chapter named in the findings handed to this slice, plus two either side of each chapter being rewritten — instead of the whole book. For a single-chapter repair that is six or seven rows rather than thirty-nine, and the envelope drops by about thirty thousand bytes without the slice losing anything it was using.

**Tasks:**
- [x] `_repair_neighbourhood(proposal, ids, findings)` selects the chapters a slice must see
- [x] `_repair_blocked_design` uses it for `written_so_far`
- [x] Test: a one-chapter repair is not handed the whole book
- [x] Test: the chapters a finding names are in the neighbourhood even when far away
- [x] Test: the neighbours either side are included, and the ends of the book do not break it
- [x] Suite green: 424 passed, 23 subtests (era 418). Reinstall, commit & push
- [x] Margherita's design clears (`design_clean`, 0 blocking) and CH-0001..0003 are written, translated, exported and published

**Done when:** The cost of a repair is set by what it rewrites.

## The repair moved a chapter, and a chapter cannot move ✅

**Status: ✅ Done — 2026-08-29**

**Problem:** told that CH-0028 "The German Face" fires the arc's third turn after the pressure it is supposed to precede, the designer did the right narrative thing and swapped the two chapters: it returned CH-0028 at order 27 and CH-0027 at order 28. The engine refused the result with `chapter.order` and the run ended.

The refusal is correct, and not only on a formality. `validate_book_design` requires each chapter's `order` to match its position in the list, and beyond that the engine assumes elsewhere that `CH-000N` *is* the Nth chapter: the previous-chapters context handed to whoever writes and cold-reads is assembled by comparing ids lexicographically. Let the orders swap while the ids stay put and a writer is given the wrong chapters as its past. Ids also appear inside the prose of plants and reveals — "payoff CH-0030" — so renumbering silently repoints those too.

So a chapter keeps its id and its place, and a repair that needs an event to happen earlier moves the *event*, exchanging what two chapters do while both stay where they are. The designer was never told this: the repair instruction says to return the chapters "complete and in order, with the contradiction resolved", which reads as permission to reorder.

**Fix:** the repair instruction states that `id` and `order` are fixed, and that moving an event means exchanging what two chapters contain. The engine checks it rather than trusting it: a slice that comes back with an order it was not given is asked once more with the rule and its own violation quoted, the way a truncated slice is asked again smaller. A second violation raises with both orders named.

**Tasks:**
- [x] `designer.md`: `id` and `order` are fixed in a repair; move the event, not the chapter
- [x] The engine rejects a slice whose returned orders differ from the ones it sent
- [x] Such a slice is re-asked once, carrying the violation, before the round fails
- [x] Test: a repair that renumbers is re-asked and the corrected answer is taken
- [x] Test: a repair that renumbers twice fails with both chapters named
- [x] Test: a repair that keeps the orders is merged untouched
- [x] Suite green: 429 passed, 23 subtests (era 424). Reinstall, commit & push
- [x] Margherita's design clears (`design_clean`, 0 blocking) and CH-0001..0003 are written, translated, exported and published

**Done when:** A repair changes what a chapter does, never which chapter it is.

## One raw newline throws away a finished chapter ✅

**Status: ✅ Done — 2026-08-29**

**Problem:** the draft of CH-0003 was written in full — 14988 characters of prose — and the engine discarded it: `Model output is not contract JSON: Invalid control character at: line 1 column 2883`. The whole output contained exactly one raw newline inside a JSON string, sitting between thousands of correctly escaped ones:

```
tasting it. \"From?\"<raw newline>\n\n\"Berlin.\"
```

Python's decoder is strict about control characters inside strings by default, and rejects the document. So one slip in fifteen thousand characters costs a chapter, its repair round, and the run — and it will happen again on every book, because it is a property of how models emit long prose, not of this one.

Reading the raw newline as the newline it plainly is loses nothing: it decodes to the same character the escaped ones decode to, and no other leniency is involved.

**Fix:** the contract decoders read model output with `strict=False`. Everything else — the object shape, the size ceilings, the required fields — is checked exactly as before.

**Tasks:**
- [x] `_parse_contract_json` and `_parse_chunked_contract` decode with `strict=False`
- [x] Test: a raw newline inside a string parses to the same value as an escaped one
- [x] Test: output that is genuinely not JSON still fails
- [x] Test: the object-shape and size checks are unchanged
- [x] Suite green: 434 passed, 23 subtests (era 429). Reinstall, commit & push

**Done when:** A chapter is not lost to a character.

## A book can withhold its premise ✅

**Status: ✅ Done — 2026-08-29**

**Problem:** landfall's premise is that the story happens on Kepler-442b four millennia after five ships landed. The author wants the reader to meet that world as a world — the weight, the metered light, the machines that must be fed — and to learn what it is only at a reveal placed late in the book, told by a character who knows. The engine has no way to hold a fact back, and three of its parts actively push the other way. The cold-reader is instructed to flag ungrounded terms and missing setup, which is precisely what a withheld premise produces on every page. The reviser repairs what the cold-reader flags, and the cheapest repair is a sentence of explanation. The designer, handed a brief whose first six words name the planet, writes it into the book's premise and from there into chapter one. None of the three is malfunctioning: each assumes everything the reader needs is meant to be on the page.

**Fix:** a book declares what it withholds, and the engine decides which role gets to see it.

The designer returns a book-level `withheld` list alongside `premise` and `arc`. Each row is `{"id":"WH-0001","fact":"the truth, stated plainly","seen_as":"what a person living in the world experiences instead","revealed_in":"CH-00NN","told_by":"CHR-000N"}`.

The engine writes that list into `design.md` and copies it into every chapter contract, cut to what that chapter's writer is allowed to know: before `revealed_in` the row carries `seen_as` and `status: withheld` and **not** `fact`; at `revealed_in` it carries the whole row and `status: revealed here`; after it, `status: known`. A writer cannot leak a fact it was never given, and before the reveal it does not need one — the clue it must drop is already written in that chapter's `plants` by the designer, who does know.

The cold-reader is the fresh reader and never receives `fact` at any point. It receives the `seen_as` rows and one instruction: a row on this list is not missing setup, and asking for it to be explained is out of scope. What it should flag instead is prose that explains one early.

The canon-auditor already refuses a reveal fired before the chapter the arc places it in — it caught four of those in margherita. It needs one addition: a withheld row revealed before its `revealed_in` is blocking, named with both chapters.

The whole field is optional. A book that declares no `withheld` list behaves exactly as it does today.

**Tasks:**
- [x] `designer.md`: the `withheld` field, its shape, and that the plants leading to a reveal are spread across the chapters before it
- [x] The spine capsule's `required_output` carries `withheld`
- [x] `_book_design_outputs` writes the `withheld` block into `design.md` and the per-chapter cut into each contract
- [x] `_book_proposal_from_artifacts` reads the block back, so a resumed or repaired design keeps it
- [x] `validate_book_design`: `revealed_in` names a real chapter and never the first one, `told_by` names a real character; blocking when either fails
- [x] `writer.md`: a withheld row is lived, not discussed — write what the people notice and do, never why the world is so
- [x] `never_write`, added while building and not in the plan above: cutting `fact` out of the contract removes the temptation, not the knowledge, because the canon every chapter imports states the fact outright — LAW-0001 puts a whole Landing in one sentence, and the kernel is imported by every chapter of every book. So a withheld row also names the words that give it away, and `validate_writer_output` — which the writer and the reviser both pass through — rejects a draft before `revealed_in` that uses one, naming the word. It is the only part of this that is checked rather than asked for
- [x] `cold-reader.md`: rows on the withheld list are not ungrounded terms; flag prose that explains one before its chapter
- [x] `canon-auditor.md`: a withheld row revealed before `revealed_in` is blocking
- [x] Tests: the cut before, at and after the reveal; `fact` never reaches a pre-reveal contract or any cold-reader capsule; validation rejects a dangling `revealed_in`; a book with no `withheld` list produces byte-identical outputs
- [x] Suite green: 457 passed, 30 subtests (era 434, 23). Reinstall, commit & push

**Done when:** A chapter written before the reveal cannot state the withheld fact, because the model that wrote it was never told.

## A forbidden word and a proper noun are not the same check ✅

**Status: ✅ Done — 2026-08-29**

**Correction to "A book can withhold its premise".** The leak check matches every `never_write` entry case-insensitively. That is right for a common noun and wrong for a proper noun, and the difference is not cosmetic: `Earth` is the fact being withheld, `earth` is the ground under a character's feet. Landfall is a book of fens, salt and gold-mud, so `the earth under her feet` is a sentence it will write, and the check as shipped rejects that draft and sends a correct chapter back to be rewritten. The same holds for `Kepler` against no ordinary word at all, which is the point: an entry the author capitalised is a name.

**Fix:** an entry containing an uppercase letter is matched as written; an all-lowercase entry keeps the case-insensitive match it has now. The author chooses which by how they write the word, and the designer prompt says so.

**Also found, in landfall's own list rather than in the engine:** two entries collide with canon that means something else. `colony` and `colonies` name the native Hwen memory-colonies, which predate the fleet and are a biological colony in the sense a coral reef is — PLC-0014 is titled "The Hwen Colony", so the entry forbids the writer from naming a place that exists. `alien` appears in CHR-0007 as `surface alien memories`, meaning unfamiliar. Both come off the list; `colonist`, `colonists`, `colonise` and `colonize` stay, because those carry the fact. `another world` and `other worlds` come off as well — a person can be in another world without having come from one.

**Tasks:**
- [x] `_withheld_leak` matches an entry with an uppercase letter case-sensitively, an all-lowercase entry case-insensitively
- [x] `designer.md` says which spelling produces which match
- [x] Test: `Earth` is caught and `the earth under her feet` is not; `ship` is still caught as `Ship`. The old case-blind test failed as written, which surfaced a hole the plan had not seen: an all-caps `EARTH` in a heading or an epigraph escaped a name matched as written, so a capitalised entry is now matched in its own spelling and in its all-caps rendering
- [x] Landfall's `never_write` drops `colony`, `colonies`, `alien`, `aliens`, `extraterrestrial`, `another world`, `other worlds`
- [x] Suite green: 459 passed, 33 subtests (era 457, 30). Reinstall, commit & push

**Done when:** A chapter is not sent back for writing the word "earth" about soil.

## The withheld list is its own call — superseded ⛔

**Status: ⛔ Superseded on 2026-08-29 by "A design call is bounded by construction, not by the book". Correct as far as it went, and too narrow: it moved the withheld list out of the spine without touching the chapter outline, which is the part whose size is the book's size.**

**Correction to "A book can withhold its premise".** Putting `withheld` in the spine's required output made the spine too big to answer. Landfall's design failed three times in a row on it, and the telemetry is unambiguous: attempt one returned 15822 bytes cut off in the middle of the `withheld` block — the last thing the model was writing — and attempts two and three returned nothing at all, at `input 42241, reasoning 31999, output 0`. That is the ceiling this project has now hit four times: reasoning plus output do not pass roughly 32000 tokens, and a request large enough to be worth thinking hard about consumes the whole budget thinking.

The spine already asks for the premise, the entry state, the arc, the exit boundary and a one-line row for every one of 27 chapters. It answered that on 2026-08-27 at 13298 bytes. Adding a list of withheld facts to the same answer is what pushed it over, and the spine is the one chunk that cannot be rescued: `_halve_chunk` splits a chunk by its range of chapters, the spine has no range, so a truncated spine goes straight to a blocked task.

**Fix:** the same medicine as the audit and the repair. `withheld` becomes its own chunk, run after the spine and before the chapter slices. It is a small answer, and it is a better-informed one: the spine's chapter outline is in its capsule, so the designer names `revealed_in` against chapters that exist and can place the telling in the final third by counting them. The rows are then part of the spine snapshot every chapter slice receives, so the slices can plant toward the reveal.

The chunk runs only when the book's brief carries a non-empty `reader_knowledge`. A book that withholds nothing pays nothing, and the author's intent is declared in one place rather than inferred.

**Tasks — never started; the entry was replaced before any of it was built, so the boxes below stay open as a record of what was proposed:**
- [ ] `reader_knowledge` joins the allowed keys of a book brief
- [ ] `_run_book_design_chunked` runs a `{"category":"withheld"}` chunk after the spine when the brief carries `reader_knowledge`, and folds the rows into the spine snapshot the chapter slices receive
- [ ] The spine's `required_output` drops `withheld`; the new chunk carries its own
- [ ] `designer.md`: the third kind of book chunk, and that it is answered against the outline it is given
- [ ] Test: a brief with `reader_knowledge` produces the extra call and the rows reach both the design and the chapter slices; a brief without it produces neither the call nor the rows
- [ ] Test: the spine is asked for no withheld list
- [ ] Suite green. Reinstall, commit & push
- [x] Re-run landfall's design

**Done when:** The spine answers at the size it answered before this feature existed.

## A design call is bounded by construction, not by the book ✅

**Status: ✅ Done — opened 2026-08-29**

**Why the previous entry was replaced.** It proposed moving `withheld` out of the spine because the spine had just failed three times. That would have worked today and failed again at a longer book, because the spine's real problem is not the withheld list: the spine's answer contains one row per chapter, so its size is the book's size. Landfall has 27 chapters and that answer came to 13298 bytes on 2026-08-27. At sixty chapters it does not fit whatever else is in it.

**The invariant this project has never written down and has now broken four times:** every model call in the design and audit path has an input and an output bounded by a constant, independent of how many chapters the book has. The engine decides the split — that lesson is already recorded in `_run_book_design_chunked` and was applied to the chapter slices, to the audit windows and to the repair. It was never applied to the five places below, which is why a longer book still breaks.

**Where size still follows the book.**

1. The spine's output carries `chapter_outline`, one row per chapter. This is what failed: a first attempt returning 15822 bytes cut off mid-sentence, then twice `input 42241, reasoning 31999, output 0`. The spine is also the one chunk with no rescue — `_halve_chunk` splits on a range of chapters and the spine carries none, so a truncated spine goes straight to a blocked task.
2. Every chapter slice receives the whole `chapter_outline` in its capsule.
3. Every chapter slice receives `written_so_far`, the digest of every chapter earlier slices wrote. By the last slice of a long book that is nearly the whole book.
4. Every audit window pass receives `book_digest`, the digest of all chapters.
5. The audit's schedule pass reads every chapter's plants and reveals in one call. It already halves its way down from forty chapters to about ten, paying two or three empty calls per audit to get there: the cost of an unbounded call discovered to be unbounded at run time.

**The shape of the fix.**

The spine returns only what is constant: premise, entry state, arc, exit boundary, and the number of chapters. The outline becomes its own sliced chunk, one call per range, halveable like every other ranged chunk because it carries the same two fields. `withheld` becomes a third chunk run once the outline exists, so the designer names `revealed_in` against chapters that are real and can place the telling in the final third by counting them.

Everything a slice reads becomes a window rather than the whole book. A chapter slice sees the outline rows and the digest for its own range plus a fixed neighbourhood on either side, which is the rule `_repair_neighbourhood` already applies to repairs. The audit's window passes read a neighbourhood digest instead of the whole-book digest.

The audit's schedule pass becomes a fold. It walks the book in fixed windows, each window handed the promises still open when the previous one ended, returning both its findings and the promises it leaves open. A plant in chapter three and its payoff in chapter forty are still checked against each other because the promise travels forward, and no single call reads more than one window. If the open set grows past a cap the engine says so rather than spending a call that will not answer.

**And the part that makes it stay true.** A test builds a synthetic book of two hundred chapters and asserts that every envelope the design and audit paths construct stays under a fixed token bound. Nothing measures this today, which is why the defect was found by a design failing three times against a paid provider rather than by the suite. Alongside it, the engine measures a chunk's envelope before spending the call: over the bound it splits further instead of asking a question that cannot be answered.

**Tasks:**
- [x] `reader_knowledge` joins the allowed keys of a book brief
- [x] Spine returns `chapter_count` and no `chapter_outline`; `required_output` follows
- [x] `{"category":"outline","first_order":N,"last_order":M}` chunk, sliced and halveable, each slice seeing the spine and the outline rows already decided within a fixed neighbourhood
- [x] `{"category":"withheld"}` chunk after the outline, run only when the brief carries `reader_knowledge`, folded into the spine snapshot the chapter slices receive
- [x] Chapter slices read an outline window and a `written_so_far` window, not the whole book
- [x] Audit window passes read a neighbourhood digest, not `book_digest`
- [x] The audit schedule pass becomes a fold over fixed windows carrying open promises forward, with a cap and a spoken failure when the open set exceeds it
- [x] The engine measures a chunk's envelope before the call and splits further rather than spending it
- [x] `designer.md` and `canon-auditor.md`: the new chunks, and that each is answered against the window it is given
- [x] Test: a 200-chapter book, every design and audit envelope under a fixed bound
- [x] Test: a 27-chapter book still produces the same chapters, so this is a change of shape and not of content
- [x] Suite green: 471 passed, 195 subtests (era 459, 33). Reinstall, commit & push
- [x] Re-run landfall's design

**Done when:** The number of chapters changes how many calls a design costs, and nothing else about it.

## Where the telling falls is the author's choice, not the engine's ✅

**Status: ✅ Done — opened 2026-08-29**

**Correction to "A design call is bounded by construction, not by the book".** `_reveal_candidates` offers the designer only the chapters from two thirds of the way in, and the constant is written into the engine. That is one book's taste compiled into every book. Landfall's designer, given that window, chose the last chapter of twenty-six: the truth and the climax in the same scene, and the reader holding the key for a handful of pages.

The author wants it earlier, and named the model: in *The Sword of Shannara* the history of the Great Wars is told early, and the rest of the book is read by that light. The revelation is the lens, not the ending.

**Fix:** a book's brief may carry `reveal_window`, two fractions between 0 and 1 naming the part of the book the telling may fall in. `_reveal_candidates` reads it and offers the outline rows inside it, still capped at twelve so the call stays bounded. Absent, the default stays the final third, which is what an author who says nothing about it most likely means.

The engine keeps only the rule it can justify: never CH-0001, because a truth told in the first chapter was never withheld from anyone. Everything else about placement is a craft decision and belongs to whoever is writing the book.

**And the truth need not arrive all at once.** The author asked for the telling around chapter seventeen of twenty-six and then for more to come out step by step in the chapters after it. The `withheld` list already carries that: it is a list, each row has its own `revealed_in`, its own `seen_as` and its own forbidden words, and the engine cuts every chapter's contract against each row separately. So a book whose truth has layers returns several rows revealed in ascending order — the first reframing what the reader has been reading, the later ones deepening it — and nothing in the engine needs to change for that. What needs to change is the designer being told it is allowed, because a prompt describing one row will produce one row.

**Tasks:**
- [x] `reveal_window` joins the allowed keys of a book brief
- [x] `_reveal_candidates` takes the window from the brief, defaulting to the final third, and stays capped at twelve rows
- [x] `designer.md`: the candidates are the author's window, the telling is placed inside it, and a truth with layers is several rows revealed in ascending order rather than one row carrying everything
- [x] Test: a brief that names an early window gets early candidates; a brief that names none gets the final third; the cap holds in both
- [x] Test: CH-0001 is never a candidate, whatever the window says
- [x] Landfall's brief carries the window the author chose
- [x] Suite green: 483 passed, 202 subtests (era 471, 195). Reinstall, commit & push
- [x] Re-run landfall's design

**Done when:** Moving the revelation is an edit to the brief, not to the engine.

## A chunk reads what it needs, and a rangeless chunk has a way down ✅

**Status: ✅ Done — opened 2026-08-29**

**What happened.** Landfall's `withheld` chunk came back empty three times and blocked the design, which the driver then restarted from the spine, re-paying nine chorus calls to arrive at the same wall. The chunk's envelope is 154473 bytes. Its task is 119729 of those, and 85102 of the task — 71% — is `worldbuilding.md`, a document this call has no use for. It is asked for a handful of rows: the truth, what a person living in the world experiences instead, which chapter tells it and who does the telling. It works from the author's `reader_knowledge`, the spine, the chapters it may choose between, and the canon summaries that let it name a teller.

**Two things are wrong, and they are different.**

The first is that every chunk is handed the same capsule whatever it was asked for. The base capsule was built for the chunk that needs the most, and the rest carry it. Cutting `worldbuilding` out of the withheld chunk takes its task from 119729 bytes to about 34600.

The second is structural, and it is the same defect that took three days to find in the spine: a chunk with no range of chapters cannot be halved, so when it comes back empty there is nothing between it and a blocked design. `_halve_chunk` is the only rescue the engine has, and it only works on chunks that carry a range. The spine, the withheld chunk and the repair all sit outside it.

**Fix.** A chunk declares what it reads, and the engine gives it that and no more. The withheld chunk does not read the worldbuilding document; the outline and the chapter slices do, because they invent what happens in the world.

And a rangeless chunk gets the rescue a ranged one has: when it exhausts its attempts, the engine retries it once with the bulk of the capsule removed — the same cut the withheld chunk now takes by default — before blocking the design. Asking for the same thing with less in front of it is what has worked every other time this ceiling has been hit.

**Tasks:**
- [x] A per-category list of what a chunk does not read, applied in `_run_design_chunk`
- [x] The withheld chunk does not read `worldbuilding`
- [x] A rangeless chunk that exhausts its length retries once on the reduced capsule before blocking
- [x] The reduction is reported on stderr with what it dropped, so a run that took it says so
- [x] Test: the withheld capsule carries the brief, the spine and the candidates and not the worldbuilding; the chapter slices still carry it
- [x] Test: a rangeless chunk that answers only on the reduced capsule completes the design instead of blocking it
- [x] Test: the reduced retry is a last resort, not the first call
- [x] Suite green: 491 passed, 206 subtests (era 483, 202). Reinstall, commit & push
- [x] Re-run landfall's design

**Done when:** A call that comes back empty is asked again with less, whatever kind of chunk it is.

## The slice width is measured, not guessed ⏳

**Status: ⏳ Not started — opened 2026-08-29, to be worked once landfall's design closes**

**What this run measured.** `BOOK_DESIGN_SLICE_SIZE = 8` was set on margherita and carried to landfall unchanged. On landfall every chapter slice needed two or three attempts: chapters 1-8 answered on the third, 9-16 on the second, and 17-24 came back empty three times and was halved into 17-20 and 21-24. Seven calls paid for three slices, and the discovery happened at run time against a paid provider. The engine already knows how to split when a chunk is too big; what it does not know is how wide a slice should have been in the first place.

**Why a wider constant is not the fix.** Eight was a guess that fitted one book. Four would be a guess that fits this one. The author's constraint is explicit: there will be longer books with denser chapters carrying more per chapter, so any single number is a guess that will be wrong later, and being wrong costs three empty calls per slice to find out.

**The shape of the fix, to be settled when the numbers are in.** The engine already records the output tokens of every chunk in `chunk_telemetry`. A design can size its own slices: take the first slice narrow, measure what one chapter contract actually cost in output tokens, and set every later slice from that measurement against the model's ceiling — with headroom, because the chapter that overruns is the one that had most to say. A book of dense chapters gets narrow slices and more calls; a book of light ones gets wide slices and fewer. Neither is a number anybody typed.

Leave the constant as the opening width only, and make it the width the engine starts from before it knows anything, not the width it uses all the way through.

**A third case, measured on the repair pass.** After landfall's design failed validation, the retry carries a repair context — the list of blocking findings and the hint — inside the capsule. Chapters 1-8, which had answered whole twice, then truncated and had to be halved. So the width that fits depends on what the capsule is carrying at that moment, not only on the book: the same slice of the same book is too wide on a repair pass and fits on a first pass. A width chosen once, however carefully measured, is wrong for half the passes the engine makes.

**And the right width is not one width.** Landfall split 17-24 into 17-20 and then 17-20 again into 17-18 and 19-20, while 1-8 and 9-16 answered whole. The chapters that would not fit are the ones carrying the revelation: CH-0017 and CH-0018 hold the first two withheld layers, so their contracts carry far heavier plants and reveals than a chapter of crossing does. A book's density is concentrated where something happens, and the engine can see that before it calls — the outline and the withheld rows already tell it which chapters do the revealing. A slice containing a reveal chapter should be narrower than one that does not, decided in advance rather than discovered by three empty calls.

**The audit's own widths, measured 2026-08-31 across two full runs of landfall.** `SCHEDULE_WINDOW_SIZE = 8` never once succeeded on this book. Every eight-chapter fold split to four, and most of those split to two, and several of those to one: 1-8, 5-8, 17-24, 17-20, 21-24, 25-26 all came back empty in both runs. `BOOK_AUDIT_SLICE_SIZE = 2` held for the windows except at 19-20 and 23-24, which are reveal chapters.

And the reason is not payload size. The fold envelopes measured 11.0k tokens at chapters 1-4, 13.9k at 9-16, 15.4k at 17-24, 12.5k at 21-22 — against a ceiling of 32k, with the open-promise ledger growing 0 → 37 rows and contributing little, since the shared capsule dominates. An eight-chapter fold fails at 13.9k while a two-chapter fold succeeds at 11.4k: 2.5k of input apart. What varies is how much the model has to reason about, which tracks the number of chapters in the slice and their density — so sizing a slice by its byte count would be measuring the wrong thing, and the telemetry to size it by is the output the slice produced, not the input it carried.

**Tasks:**
- [x] Read this run's `chunk_telemetry`: output tokens per chapter contract, and the spread between the lightest and heaviest slice
- [x] The audit's widths come from the same measurement: an eight-chapter fold has never answered on a book this dense
- [x] Decide the opening width from that measurement, with headroom stated in the comment beside it
- [x] Size later slices from what the first ones actually cost, rather than from the constant
- [x] Narrow a slice that contains a chapter the withheld rows reveal in, or that the outline marks as carrying an arc turn, before calling rather than after failing
- [x] Test: a book whose chapters answer heavily gets narrower slices without any slice failing first
- [x] Test: a book of light chapters is not split more than it needs to be
- [x] Suite green: 675 passed, 405 subtests. Reinstall, commit & push

**Measured on landfall's own `chunk_telemetry`, which is what this entry was waiting for.** Output tokens per chapter contract: 788 at chapters 1-4, 933 at 5-8, 958 at 9-12, 1003 at 13-16, 897 at 17-20, 1210 at 21-22, 1558 at 23-24, 1329 at 25-26. **A factor of two inside one book**, and the heavy end is where the reveals are.

And the same shape as everything else measured this week: the input barely moves — every slice sat around 50000 tokens — while reasoning ran 12922 to 28513 against a ceiling of 32000. A two-chapter slice reached 28513. So a slice sized by its byte count would be measuring the wrong thing, which is why the width comes from the output the finished slices produced.

**Three changes, each with its number.** The opening width drops from 8 to 4, because every four-chapter slice answered and the eight-chapter ones were halved. Every later slice is sized from the heaviest chapter measured so far rather than the average, because the chapter that overruns is the one that had most to say. And a slice holding a chapter the withheld rows reveal in is built narrow before it is called: on landfall that produces `17-18` immediately, which is where the engine arrived after three empty calls.

`SCHEDULE_WINDOW_SIZE` drops from 8 to 4 on the same evidence — across two full runs of landfall an eight-chapter fold never once answered, so eight bought three empty calls and then made the narrow calls anyway.

**Six existing tests assumed the width was eight.** They were made independent of the constant rather than re-pointed at the new number, so the next person who tunes it does not have to find them: the schedule tests derive their windows from `SCHEDULE_WINDOW_SIZE`, the cache test derives its slug from `BOOK_DESIGN_SLICE_SIZE`, and the coverage assertions check that every chapter is accounted for exactly once however the slices came out.

**Done when:** A slice is the width the book's own chapters turned out to need.

## A run resumes from the calls it already paid for ✅

**Status: ✅ Done — opened 2026-08-29**

**What happened.** Landfall's design was killed at its twenty-seventh call, and the engine had nothing to show for the other twenty-six. Nine chorus calls, the spine, three outline slices, the withheld list and fourteen chapter-contract calls — ninety-five minutes of work — were on disk as `raw-*.txt` files that nothing ever reads back. A book design writes its artifacts once, at the end, when every chunk has answered; anything that interrupts it burns the whole run.

That is not an accident of today. These runs take an hour and a half, and a kill, a reboot, a dropped connection or a design that fails its third retry all cost the same: everything.

**Fix.** Every call the engine makes is remembered under its task, keyed by the hash of the envelope that produced it. Before spending a call the engine looks for that hash; on a hit it uses the answer it already has. The key is the envelope, so a changed brief, a changed canon or a changed spine misses the cache and the call is made again — the cache cannot serve a stale answer to a question that has moved.

Only an answer that was accepted is written: never a truncation, never an empty body, and for a chorus advisor never something that did not parse. A failure must stay a failure, or the cache would freeze it in place and no retry could ever get past it.

A cached answer reports zero cost, because the run that paid for it already counted it, and carries `cached: true` so a receipt says which calls were real.

It covers the two paths that make these runs long: the chorus advisors and the design chunks — twenty-eight of landfall's thirty-eight calls. Each advisor builds its own envelope with its own role, so the hashes are distinct and one advisor cannot be served another's answer.

**The audit is deliberately not cached, and the suite is what said so.** With the audit cached, the repair loop ran to exhaustion without making a single call. The auditor is never shown a chapter's beats, so a repair that rewrites only beats leaves its question byte-identical, and the remembered verdict came straight back: the same blocking finding, forever. Beyond that loop there is a reason of kind rather than of mechanism — a design chunk is content and an audit is a judgment. Remembering a judgment makes a spurious blocking finding permanent, with no retry able to overturn it. So the ten audit calls of a killed run are lost, and that is the right trade: they are the cheap end of the run, and the repair loop depends on being able to ask again.

**Tasks:**
- [x] `_cached_call` and `_remember_call`, keyed by envelope hash under `.book-forge/call-cache/<task>/`
- [x] A cached answer reports zero cost and carries `cached: true`
- [x] Never remember a truncation, an empty body, or an advisor answer that did not parse
- [x] The design chunks read and write it; a hit is reported on stderr
- [x] The audit passes deliberately do NOT read or write it — see above; the suite caught the repair loop spinning on a frozen verdict
- [x] The chorus advisors read and write it
- [x] Test: a second design with the same inputs makes no provider calls at all
- [x] Test: a design killed halfway resumes and calls only for what is missing
- [x] Test: a changed brief misses the cache
- [x] Test: a truncated answer is not remembered, so the retry still happens
- [x] Test: two advisors never share an entry
- [x] Suite green: 506 passed, 206 subtests (era 491). Reinstall, commit & push
- [x] Resume landfall's design

**And the run that taught us this can still be recovered.** Its answers are on disk beside the envelopes that produced them, and the hash is the sha256 of exactly those envelope bytes — so the entries the cache would have written can be written now. `runtime backfill-cache` walks a run's attempts, pairs each `envelope-<slug>.json` with its accepted `raw-<slug>.txt`, and remembers the pair under the task the attempt belonged to. A hash that no longer matches simply never hits, so the command cannot serve a wrong answer: the worst it can do is nothing.

**Tasks (recovery):**
- [x] `backfill_call_cache`, walking a run's attempts and pairing envelopes with accepted answers
- [x] `runtime backfill-cache` on the CLI, reporting what it remembered and what it skipped
- [x] Never backfill a slug with no accepted answer, an empty body, or an entry that already exists
- [x] Test: a run's answers become cache hits; a truncated slug is skipped; a changed envelope does not hit

**Correction, found by using it — 2026-08-29.** The backfill walked a run's attempts in name order and kept the first accepted answer for each hash, skipping any later one as already remembered. Landfall's `RUN-0028` holds fifteen attempts accumulated over days, and two of them — ATT-0010 with four accepted answers and ATT-0011 with ten — had asked the spine the identical question and been given two different valid answers. The first one won, so the cache served ATT-0010's spine, and because every later chunk carries the spine in its capsule, ATT-0011's fourteen chapter-contract answers became unreachable: their envelopes name a spine the engine no longer produces.

The hash chain did its job — a different spine invalidates everything downstream, so nothing incoherent was assembled — but the choice of which answer to keep was made by directory order, which is no reason at all.

**The rule that has a reason:** when two attempts answered the same question, keep the answer from the attempt that got furthest. Its answer is the one the rest of that attempt was built on, so keeping it recovers a whole chain rather than stranding one. Attempts are walked in descending order of how many accepted answers they hold.

**Tasks (correction):**
- [x] Attempts are walked most-complete-first, so the answer that carries a chain wins over the answer that carries none
- [x] The report says which attempt each remembered answer came from and how complete it was
- [x] Test: two attempts answering the same question, and the one with more accepted answers is the one remembered

**Done when:** Killing a design costs the call it was making, not the run.

## An audit window is two chapters, and a pass that cannot be halved still has a way down ✅

**Status: ✅ Done — opened 2026-08-29**

**Measured on landfall, not guessed.** `BOOK_AUDIT_SLICE_SIZE = 5` was set when five chapters answered where ten did not. On landfall five almost never answers: `window-6-10` came back empty, then `6-8`, then `6-7`, and only `6-6` and `7-7` answered — in a minute each. The first audit attempt died outright when `window-11-11` came back empty, because a window of one chapter cannot be halved and the pass had nothing left to try.

**And it is not the envelope.** An audit window of five chapters is 48400 bytes and a window of one is 41803 — against the design's 150000. The input is small either way. What fails is the judgment: reading a run of chapters for contradictions is the kind of question this model spends its whole completion budget thinking about, and above a certain width it emits nothing at all. So the width that works is decided by the difficulty of the question, not by the size of the payload, which is why measuring it on one book and carrying the number to another was always going to break.

**Fix, in two parts.**

The window becomes two chapters, which is where landfall converges, with headroom deliberately on the small side: a window too narrow costs one extra call, a window too wide costs three empty ones and then the narrow calls anyway.

And an audit pass that cannot be halved gets the rescue the design chunks were given: before failing, it is asked once more with the bulk of its scope removed. Today a single-chapter window that comes back empty ends the audit, which ends the design, which burns one of three attempts.

**Tasks:**
- [x] `BOOK_AUDIT_SLICE_SIZE` is 2, with the measurement in the comment beside it
- [x] An audit pass that cannot be halved is retried once on a reduced scope before it fails
- [x] Test: a pass that answers only on the reduced scope completes the audit instead of ending it
- [x] Test: the reduced pass is a last resort, never the first call
- [x] Test: twenty-six chapters produce thirteen windows and the schedule fold is unchanged
- [x] Suite green: 508 passed, 341 subtests (era 506, 206). Reinstall, commit & push
- [x] Re-run landfall's audit

**What narrowing costs, and the direction that would not cost it.** Measured on the same envelopes: a five-chapter window is 48400 bytes and a one-chapter window is 41803, so a chapter adds about 1650 bytes and roughly 40000 — 84% — is fixed: the role prompt, the arc, the premise, and 24097 bytes of canon blocks, all carried identically whatever the width. Per chapter checked that is 41800 bytes at a width of one, 21700 at two, 9700 at five. Narrowing to one costs more than four times as much for the same work.

The heavier cost is what stops being checked. A window pass is asked two things — whether these chapters contradict each other, and whether one of them stands where the arc does not place it — and the first needs more than one chapter to mean anything. At a width of one it silently disappears: the audit reports clean having checked less, and the last-resort pass, which drops the neighbourhood digest too, checks less still. What saves this is that the check that matters most at distance — a promise planted at chapter three and paid at chapter twenty — lives in the schedule fold rather than in the window.

So the width is not really the defect. One call is being asked to do two different kinds of thinking over a large context. Splitting by question rather than by chapters would let a wide window stand: one pass asking only whether each chapter sits where the arc places it — light, mechanical, per chapter — and another asking only whether a run of chapters contradicts itself, given nothing but their plants and reveals. Two easy questions on small inputs instead of one hard question on a large one. And 24097 bytes of canon travels in every audit call unmeasured; how much of it the auditor actually needs is the thing to measure before narrowing anything further.

**Done when:** An audit that cannot answer a question asks a smaller one instead of ending the design.

## A promise is not an artifact, but the chapter that made it is ✅

**Status: ✅ Done — opened 2026-08-29**

**Correction to the schedule fold.** The fold hands each window the promises still open when the last one ended, so the auditor now has a vocabulary it did not have before: `OP-0014`, a promise. Asked for evidence, it cited one — which is the natural thing to do with an identifier it was just given — and `_bind_audit_evidence` refused it, because evidence must resolve to a stable artifact. The whole audit died on it, after seventeen passes, and burned one of three attempts.

The auditor is not wrong. The engine gave it an id and then rejected it for using it.

**Fix.** The engine carries the promise list, so it knows which chapter each promise was made in. An evidence location naming a promise — one it was handed, or one this pass is returning — is rewritten to that promise's chapter before binding. A promise it cannot place still fails closed, because unresolvable evidence is meant to fail closed.

And the prompt says what evidence is: a chapter or a canon block, never a promise id, because the promise is the claim and the chapter is where it can be checked.

**Tasks:**
- [x] `_bind_audit_evidence` resolves a promise id to the chapter that made it, from the promises carried in and the promises returned
- [x] `canon-auditor.md`: evidence is a chapter or a canon block; cite the chapter that made a promise, never the promise
- [x] Test: a finding citing a carried promise binds to that promise's chapter
- [x] Test: a finding citing a promise the pass is itself returning binds too
- [x] Test: a promise that cannot be placed still fails closed
- [x] Suite green: 513 passed, 341 subtests (era 508). Reinstall, commit & push
- [x] Re-run landfall's audit

**Done when:** The auditor is not punished for using a name the engine gave it.

## One bad citation must not destroy thirty good passes ✅

**Status: ✅ Done — opened 2026-08-29**

**Third audit failure in a row on the same seam.** `OP-0014` was a promise id the engine itself had handed out — fixed. Then `PL-0001#summary`: a canon block that does not exist, because the project's places are `PLC-` and the auditor wrote `PL-`. One mistyped prefix, in one evidence item, in one finding, killed an audit of twenty-five completed passes and burned an attempt.

**The defect is the granularity, not the check.** Failing closed on unresolvable evidence is right: a blocking finding must not be raised on a citation nobody can look up, because the repair that follows would be aimed at nothing. But it is enforced over the whole audit, so the cost of one bad citation is every call the audit has already paid for. The chorus already got this right — an advisor's unresolved evidence is marked and skipped rather than raised globally — and the audit, which is longer and more expensive, is the one that fails hardest.

**Fix.** An evidence item that cannot be resolved is dropped from its finding and recorded. A finding left with no resolvable evidence at all is set aside as unverifiable rather than kept: it never reaches the blocking verdict, so nothing is repaired against a citation that does not exist, and it is written into the audit record and printed, so nothing is silently lost either. A person can read what the auditor tried to say and decide.

The safety property is unchanged — no blocking finding stands on evidence that cannot be looked up — and the audit survives to give its verdict.

**Tasks:**
- [x] `_bind_audit_evidence` drops unresolvable evidence and returns what it set aside instead of raising
- [x] A finding with no resolvable evidence left becomes unverifiable, never blocking
- [x] `_run_book_audit_chunked` carries the unverifiable findings out, namespaced by pass like the rest
- [x] `design-audit.json` records them, and they are printed when there are any
- [x] `canon-auditor.md`: cite block ids exactly as the context spells them
- [x] Test: a finding with one good and one bad citation keeps the good one and stays blocking
- [x] Test: a finding with only bad citations is set aside, not blocking, and appears in the record
- [x] Test: an audit with one bad citation still returns a verdict for every other pass
- [x] Suite green: 515 passed, 341 subtests (era 513). Reinstall, commit & push
- [x] Re-run landfall's audit

**What the suite corrected, mid-change.** Four tests asserted that *any* unresolvable citation fails the design closed, whatever its severity — a stronger property than the one this entry set out to keep, and the right one: a citation nobody can look up means the audit is confused or the artifacts have moved, and either way a person has to look. Setting such a finding quietly aside would have let a design pass that should not have.

So the audit finishes, writes its verdict on every pass that did resolve, and then halts: the record's state is `needs_review`, and `AdvanceHalted` stops the driver rather than sending it round the retry loop, because asking the same auditor the same question returns the same citation. And only a clean verdict now counts as a finished job — a record that needs review reopens the audit on the next `advance`, on both the book and the universe path, instead of being returned as if it were done.

**Done when:** An auditor's typo costs its own finding and a person's attention, not thirty paid calls.

## The fold's answer must not grow with the book either ✅

**Status: ✅ Done — opened 2026-08-30**

**Correction to the schedule fold, and to the invariant I wrote the same day.** The fold asks each pass to return the whole set of promises still open. So the size of the answer grows with how much the book has promised: by chapter eleven the pass must restate thirty or forty promises verbatim before it reaches anything of its own. Landfall's audit died there — `schedule-11-11`, three attempts, then the reduced pass, then blocked.

The telemetry leaves no room for another reading: `input 6087, output 0, reasoning 32000, reason length`. Six thousand tokens of input. It is not the context. The attempt before it wrote 2339 bytes and stopped mid-list, enumerating `OP-0001` through `OP-0011` one at a time.

"A design call is bounded by construction" promised an input **and an output** bounded by a constant. The fold was written the same day and breaks it on the output side.

**And the reasoning that led there was wrong.** The prompt says: return the whole set every time and not the difference, because a difference makes the engine guess which promise a sentence refers to. Promises carry ids. A difference applies by exact match on an id, which is not a guess — it is the only part of this that never was one.

**Fix.** A schedule pass returns `paid` — the ids it saw answered — and `added` — the promises these chapters make. The engine reconstructs the open set: carried, minus paid, plus added. The answer is then the size of what one window changes, two or three rows, whatever the book's length. The full set still travels inward, where there is room.

A paid id that matches nothing carried is reported and ignored rather than failing the pass: the auditor mistyping an id must cost that promise's bookkeeping, not the audit — the same lesson as the citations.

**Tasks:**
- [x] The schedule pass's `required_output` is `findings`, `paid`, `added`
- [x] `_carry_open_promises` applies the difference by id and reports an id it cannot place
- [x] `canon-auditor.md`: return what was paid and what was made, never the whole ledger
- [x] Test: a pass paying two and making one leaves the set two shorter and one longer
- [x] Test: a paid id nobody carried is reported, and the pass still counts
- [x] Test: the answer of the twentieth window is no larger than the answer of the second
- [x] Suite green: 521 passed, 341 subtests (era 515). Reinstall, commit & push
- [x] Re-run landfall's audit

**Done when:** A pass in the middle of a long book answers as briefly as a pass at its start.

## The audit remembers too, and forgets when the design changes ✅

**Status: ✅ Done — opened 2026-08-30**

**Reversing a decision made yesterday, for a reason that turned out to be narrower than the rule I drew from it.** The audit was deliberately kept out of the call cache. The reason was real: the auditor is never shown a chapter's beats, so a repair that rewrites only beats leaves its question byte-identical, and a remembered verdict would come straight back — the repair loop ran to exhaustion without making a single call, and the suite caught it.

But that reason only bites **when the design has changed**. Between a hung call and its retry the proposal is identical byte for byte, and replaying the answers already paid for is not a stale verdict: it is the same verdict to the same question.

**What it has cost.** Landfall's audit has now been run five times. Each died differently — a window that could not be halved, a promise id the engine had handed out, a mistyped block prefix, a fold answer that grew with the book, and finally a call that hung for 900 seconds — and each fix let the next run get further, the last reaching twenty-eight passes and eleven folds. But every retry re-ran the whole audit from the first window, because nothing was remembered. Roughly eight hours of provider time to get one verdict that still has not landed.

**Fix.** The audit's passes read and write the call cache like the design's chunks do. And `_repair_blocked_design` clears the audit cache for that book before it re-audits a proposal it has changed, which is the one moment the old objection applies. A crash, a timeout or a kill then costs the call that was in flight; a repair costs a real re-audit.

**Tasks:**
- [x] The audit passes read and write the call cache
- [x] A repair that changes the proposal clears that book's audit cache before re-auditing
- [x] Test: an audit interrupted halfway resumes and calls only for what is missing
- [x] Test: a repair round re-asks rather than replaying the verdict it just failed on — `test_design_repair` proves it by passing at all: its fixture answers blocking then clean, so a replayed verdict would leave the design blocked
- [x] Test: the repair loop still terminates when the auditor keeps blocking
- [x] Suite green: 525 passed, 341 subtests (era 521). Reinstall, commit & push
- [x] Re-run landfall's audit

**Done when:** A hung call costs a call.

## A window in the middle of the book is not bound by its opening ✅

**Status: ✅ Done — opened 2026-08-30**

**Landfall's first completed audit blocked on four findings, and three of them are the engine's fault.** `_audit_chunk_scope` gives every pass the proposal minus its chapters — which carries `entry_state` and `exit_boundary` — and the prompt never says what those are. So a window reading chapters nine and ten was handed the book's opening state and read it as its own: *"the entry state the window opens from states that the Lost Candle is still cold in the Counting nave and that Binta does not yet know the Heart exists"*, against chapters where the company is already on the road carrying both. That is not a contradiction. That is the book proceeding.

The same reading produced the finding against chapter nineteen — *"the entry_state places Binta before her first sighting, so no trial record exists"* — and the schedule pass on chapter ten. Only the fourth finding, that chapter nineteen executes the relay severance the arc places at twenty-three, stands on its own, and even it leans part of its argument on the same mistake.

**This is a defect of the slicing, and the slicing is mine.** As one call over the whole book the entry state legitimately bound chapter one and the auditor could see that chapters two onward had moved past it. Sliced, a window at chapter ten sees an opening with no way to know it is an opening.

**Fix.** `entry_state` travels only to the pass whose range contains the first chapter, `exit_boundary` only to the pass whose range contains the last. A pass in the middle is given neither, because neither bounds it. And the prompt says what they are where they do appear: the state the book begins in, and the state it is meant to reach — not the edges of this window.

**Tasks:**
- [x] `_audit_chunk_scope` sends `entry_state` only to the pass covering chapter one and `exit_boundary` only to the pass covering the last chapter
- [x] `canon-auditor.md` says what each is, and that a window between them is bounded by neither
- [x] Test: a middle window's scope carries neither; the first carries the entry state; the last carries the exit boundary
- [x] Test: a book short enough to fit one window carries both
- [x] Test: the schedule fold follows the same rule
- [x] Suite green: 529 passed, 341 subtests (era 525). Reinstall, commit & push
- [x] Re-audit landfall and read the findings that survive

**Measured while fixing it.** The canon-auditor's role prompt is now 1951 tokens, and it rides in every audit call — thirty-odd of them per book. It has grown through today's corrections, each of which earned its line, and a budget test that had been sized with headroom now sits 51 tokens over. Nobody is measuring that growth; the same "measure, don't guess" that applies to slice widths applies to what every call is made to carry.

**Done when:** No pass is asked to reconcile a chapter with a state the book has already left.

## A verdict is stale when the question that produced it changed ✅

**Status: ✅ Done — opened 2026-08-30**

**Found immediately after fixing the window scoping.** A design whose audit already blocked skips the audit and repairs against the verdict on disk — deliberately, because rediscovering a known list costs thirty calls. But landfall's stored verdict was built by an auditor that had just been corrected: three of its four findings came from a pass reading the book's opening as its own boundary, and the fix changed both the scope and the prompt. The engine went to repair against them anyway, because a record on disk has no memory of what produced it.

The call cache already solves this shape for calls: an answer is keyed by the hash of the envelope that produced it, so a changed prompt or a changed capsule simply misses. A verdict has no such key.

**Fix.** The audit record carries the hash of the auditor prompt it was produced under. The resume path repairs against a stored verdict only when that hash still matches what the engine would ask today; otherwise the verdict is stale and the audit runs again. A prompt correction then invalidates its own conclusions instead of having them repaired against.

**Tasks:**
- [x] The audit record stores the hash of the canon-auditor prompt it was produced under
- [x] The resume path re-audits rather than repairing when that hash no longer matches
- [x] A record with no hash — every one written before this — counts as stale
- [x] Test: a stored blocking verdict is repaired against when the prompt is unchanged
- [x] Test: the same verdict is re-audited once the prompt changes
- [x] Suite green: 533 passed, 341 subtests (era 529). Reinstall, commit & push
- [x] Re-audit landfall

**Done when:** Correcting the auditor cannot leave its old conclusions standing.

## What the engine cannot use is set aside, wherever it arrives ✅

**Status: ✅ Done — opened 2026-08-30**

**The same defect, corrected three times today in three places, and it is time to correct the class.** An audit of thirty-three completed passes died on this row:

```
{"id": "F-001", "severity": "note", "issue": "A-0026 ... is not contradicted here; it is answered.", "evidence": [...]}
```

It has an id, a severity, an issue and evidence. It is missing `repair_scope`, and its text says nothing is wrong. A non-finding, announcing that the book is fine, killed the run — three times, because the driver retried it.

Earlier today the same shape arrived as evidence that would not resolve, and again as a promise id the engine itself had handed out. Each was fixed where it bit. `_validate_audit_output` still raises on a finding whose fields are incomplete, so the next unexpected shape ends the next audit.

**The principle, applied at the boundary rather than at each bite.** Anything a model returns that the engine cannot use is set aside and recorded; the run continues; a person is asked at the end. The safety property is already built and stays: a set-aside row forces `needs_review`, which halts the driver and puts the record in front of someone. Nothing passes silently; nothing costs thirty paid calls either.

**Fix.** `_validate_audit_output` returns the findings it can use and the rows it cannot, instead of raising on the first incomplete one. The unusable rows join the ones whose evidence could not be looked up, in the same `unverifiable` list, each carrying why it was set aside. A response that is not a findings list at all still raises, because that is not a bad row — it is not an answer.

**Tasks:**
- [x] `_validate_audit_output` sets aside a finding with missing or malformed fields instead of raising
- [x] Each set-aside row records why: the fields it lacked, or the citations that did not resolve
- [x] A response with no findings list at all still fails the pass
- [x] Test: a pass with one good and one incomplete finding keeps the good one and sets the other aside
- [x] Test: the audit reaches its verdict with a malformed row in the middle, and the verdict is `needs_review`
- [x] Test: a response that is not an object still fails
- [x] Suite green: 537 passed, 346 subtests (era 533, 341). Reinstall, commit & push
- [x] Re-audit landfall

**Done when:** No single row a model writes can cost more than itself.

## A repair forgets the passes it moved, not the whole audit ✅

**Status: ✅ Done — 2026-08-30**

**Too blunt, by my own hand this morning.** When a repair changes the proposal the engine forgets every remembered audit pass, so the re-audit runs all thirty from the first window: two and a half to three hours per repair round, and landfall has two rounds available.

The reason for forgetting is sound and narrow: a remembered verdict would answer a question the repair has moved. But a repair touches four chapters. A window on chapters twenty-one and twenty-two asks a question a change at chapter eight cannot reach — its scope is its own chapters and the digest of its neighbours, and neither has moved.

**What a repair actually invalidates.** A window pass whose range, widened by `AUDIT_NEIGHBOURS`, contains a repaired chapter. And every schedule fold from the earliest repaired chapter onward, because a fold carries its open promises forward: change what chapter eight promises and every fold after it is answering with a different ledger. Nothing else.

**Fix.** A remembered call records which chunk produced it. `_forget_task_calls` takes the orders that changed and forgets only the passes those orders can reach; an entry from before this, with no chunk recorded, is forgotten because it cannot be judged.

**Tasks:**
- [x] A remembered call records its chunk: the category and the range it covered
- [x] `_forget_task_calls` takes the changed orders and forgets only what they reach
- [x] A window is forgotten when its range widened by the neighbourhood contains a changed chapter
- [x] Every fold from the earliest changed chapter onward is forgotten
- [x] An entry with no chunk recorded is forgotten, since it cannot be judged
- [x] The repair passes the orders it rewrote
- [x] Test: repairing chapter eight forgets the folds after it and the windows around it, and keeps a window at chapter twenty-two
- [x] Test: forgetting with no orders given still forgets everything, as the audit-wide call does
- [x] Suite green: 542 passed, 346 subtests (era 537). Reinstall, commit & push

**Done when:** A repair round costs a re-audit of what it changed.

## A promise cannot fall due in a chapter the book does not have ✅

**Status: ✅ Done — 2026-08-31**

**The fourth of the same family tonight, and the widest.** Landfall's second audit blocked on findings like *"PROM-0043 promised that the line he will write last is in blood would land at CH-0040"* and *"PROM-0041 promised Flint's snow-death at CH-0040"*. The book has twenty-six chapters. CH-0040 does not exist.

Counted across the fold answers: **thirty-nine of fifty-nine promises — 66% of the ledger — name an `expected_in` that is not a chapter of this book**: fourteen at CH-0030, thirteen at CH-0035, eleven at CH-0040, one at CH-0033. The auditor then reasons soundly from false premises — a promise due at forty, paid at twenty-three, fires early — and blocks. Six chapters were about to be rewritten to satisfy it, on the last repair round available.

The engine accepts whatever a pass writes into `added` and carries it forward, though it knows exactly which chapters exist. Same shape as the evidence that would not resolve, the promise id nobody carried, and the finding missing a field: something arrives that the engine cannot use, and instead of setting it aside the engine reasons with it.

**Fix.** A promise whose `chapter` or `expected_in` names a chapter this book does not have is set aside, with why, and never carried. `expected_in` is allowed to be unspecified — a promise the book has not yet placed is a real thing — but it may not name a chapter that is not there. The prompt says so: the chapter ids are in the window you were given, and a promise falls due in one of them or in none.

**Tasks:**
- [x] `_carry_open_promises` takes the book's chapter ids and drops an added promise naming one that does not exist
- [x] A dropped promise is reported on stderr with its id and the chapter it named
- [x] `expected_in` may be empty or unspecified; only a named chapter is checked
- [x] `canon-auditor.md`: a promise falls due in a chapter of this book or in none
- [x] Test: a promise expecting CH-0040 in a twenty-six chapter book is dropped, one expecting CH-0020 is kept
- [x] Test: a promise with no expected_in is kept
- [x] Test: a promise whose own chapter does not exist is dropped
- [x] Suite green: 564 passed, 354 subtests (era 542, 346). Reinstall, commit & push
- [x] Re-audit landfall from the repaired design

**Done when:** No finding rests on a chapter the book does not have.

## A set-aside row is a note in the report, not a stop ✅

**Status: ✅ Done — 2026-08-31**

**The rule the user set tonight:** the pipeline decides everything itself and asks nobody. A verdict of `needs_review` does the opposite — it stops a finished audit and hands a person a row the engine already knows it cannot use.

It is also a state the driver cannot leave. `_book_design_is_incomplete` clears the design only on `design_clean`, so `needs_review` re-dispatches the design stage, which re-audits, which sets the same row aside again: the run either halts on `AdvanceHalted` or circles. The third state buys nothing that the `unverifiable` list on the same record does not already carry.

**Fix.** The verdict is `blocked` or `design_clean`, decided on the findings the engine could bind. A row it could not bind is recorded in `unverifiable`, printed with why, and the run continues. Nothing is lost — every set-aside row is on disk, with the citations that did not resolve, for anyone who wants to read them.

**Tasks:**
- [x] `_design_audit_record` drops `needs_review`: the state is `blocked` or `design_clean`
- [x] Neither `_design_audit_record` nor `run_book_design` raises `AdvanceHalted` on set-aside rows
- [x] The set-aside rows are reported on stderr as a group before the run continues
- [x] Test: an audit with one unbindable row and no blocking finding returns `design_clean` and does not raise
- [x] Test: an audit with one unbindable row and one blocking finding returns `blocked`
- [x] Test: the set-aside rows survive on the record in both cases

Found while writing the tests, and fixed here: a stored verdict was checked against the auditor that wrote it only when it was *not* clean. The check sits behind an early return that fires first, so a clean verdict written under a different auditor was handed straight back — the case where the check is the whole point. Both the book path and the universe path had it.

- [x] The early return takes a clean verdict only when it answers the question the auditor asks today, on both paths
- [x] Test: a verdict whose question has changed is audited again, and only the audit runs

**Done when:** No audit outcome waits for a person.

## A block the pipeline requires is written, not skipped ✅

**Status: ✅ Done — 2026-08-31**

**Measured on landfall.** Ten characters in canon, one `#voice` block among them — CHR-0001's. Three of the four points of view have none: Weyr, Ren, Flint. Six chapter contracts name a POV whose voice does not exist, so six chapters would be written with the character's summary and no voice at all.

The guard that should have caught it is the reason it passed. `validate` asks that a chapter import its POV's `#summary` and `#voice` — but only `if value in known_blocks`. A block that was never written is not in the index, so the requirement disappears exactly when the block is missing. The check is on the import, and the hole is in the canon.

The universe designer is asked for `voice` in the characters chunk and returned it once in ten. Nothing rejected the other nine, because tier word counts are enforced across the joined blocks and a long summary pays for a missing voice.

**Fix.** Before the design audit, the engine lists the blocks the pipeline requires and canon does not have — today, the `#voice` of every character a chapter takes as its POV — and asks the designer for exactly those, in one bounded call over the POV cast, sliced if the cast is large. The blocks are appended to the canon files, the index is rebuilt, and the chapters that lacked the import get it. Then the guard is unconditional: a POV whose `#voice` is still missing is blocking.

**Tasks:**
- [x] `_missing_pov_voices` lists, per book, the `#voice` blocks its POV characters lack
- [x] A bounded `voices` design call asks the designer for exactly those, at most `DESIGN_VOICE_SLICE_SIZE` characters per call
- [x] The returned voice is appended to the character's canon file as a `bf:block voice`
- [x] The index is rebuilt and every chapter with that POV gains the import
- [x] `validate` asks the character, not the block: a POV in canon owes `#summary` and `#voice` whether or not the block was ever written
- [x] The call is remembered in the call cache like every other design chunk
- [x] Test: a book with two POVs missing a voice gets both written, and the chapters gain the imports
- [x] Test: a book whose voices all exist makes no call
- [x] Test: `validate` blocks on a POV with no voice block in canon
- [x] Test: the cast is sliced when it exceeds the slice size
- [x] Suite green: 564 passed, 354 subtests (era 542, 346). Reinstall, commit & push
- [x] Landfall: the missing voices written, the chapters re-imported

**Done when:** No chapter is written against a character the canon does not describe.

## A call that never answers is a pass to re-ask, not a run to end ✅

**Status: ✅ Done — 2026-08-31**

**Measured on landfall's re-audit, twenty minutes in.** Six windows answered, and the seventh died on `OpenCode call for canon-auditor produced no result in 900s`. The run ended there; nothing was written; the six answers survive only in the call cache.

The message is the one that matters. `run_opencode_role` reports a timeout two ways: with a session id on the wire it is `ProviderOutcomeUnknown` — the provider accepted the call, a retry may pay twice, and that is a person's judgement. With nothing on the wire it is a plain `BookForgeError`, which means nothing was accepted and nothing was paid for. Landfall got the second, and the engine ended a seventeen-pass run over a call it could simply have asked again.

The audit already knows what to do with a pass that gives no answer: halve it, and if it cannot be halved, ask about the chapter alone. A call that timed out with nothing accepted **is** a pass that gave no answer. It should reach that rescue instead of the exit.

**Fix.** A timeout with nothing accepted raises its own type, and the loops that already rescue an unparseable answer rescue it too. A pass that produces nothing even when asked alone is set aside — recorded with the window it could not read — and the audit goes on to the next one, since the alternative is asking a person, which is what this whole line of work removes.

**Tasks:**
- [x] `ProviderProducedNothing` is raised where a timeout carried no session id
- [x] `ProviderOutcomeUnknown` is untouched: an accepted call still stops for a person
- [x] The audit loop routes it into the halve-then-ask-alone rescue it already has
- [x] A pass that produces nothing when asked alone is set aside, naming the chapters it could not read
- [x] The design chunk loop routes it into its own splitting rescue the same way
- [x] Test: a runner that times out once on a window and answers the halves reaches a verdict
- [x] Test: a runner that always times out on one window sets that window aside and audits the rest
- [x] Test: a timeout carrying a session id still raises `ProviderOutcomeUnknown`
- [x] Test: a design chunk that times out is split rather than ending the design
- [x] Suite green: 569 passed, 354 subtests (era 564). Reinstall, commit & push
- [x] Re-audit landfall

The repair loop got the same treatment: a quiet call there becomes an empty answer and the halving already in place handles it.

**Done when:** A provider that goes quiet costs the pass it was asked, not the run.

## `resume` crashed on the state its own recovery writes ✅

**Status: ✅ Done — 2026-08-31**

**Found on landfall, one command after the fix above.** The audit died mid-run with six windows answered, and `resume --resolve-unknown AUDIT-BOOK-0001:retry` — the command the halt message itself names — ended in `KeyError: 'attempt'`.

Two paths write the state and neither writes the other's field. Lease recovery walks the attempts and marks the task `outcome_unknown` from the attempt's side; `_set_attempt_failure` pops the task's `attempt` pointer. Together they leave a task in the one state that demands an explicit resolution, with nothing to resolve it against — and the only way out was editing `plan.json` by hand.

**Fix.** The resolution is about the task's most recent attempt, and it is found that way when the pointer is gone. An `outcome_unknown` task with no attempt at all still resolves: the state is what needs clearing, and the attempt is the bookkeeping.

**Tasks:**
- [x] `resume_run` falls back to the task's most recent attempt when the pointer is missing
- [x] A task with no attempt at all still resolves to `pending` on retry
- [x] Test: a task left `outcome_unknown` with no pointer resumes, and its attempt is still marked
- [x] Suite green: 570 passed, 354 subtests (era 569). Reinstall, commit & push

**Done when:** No recovery needs a hand-edited plan.

## The last question asked is the last that may end the run ✅

**Status: ✅ Done — 2026-08-31**

**Caught watching landfall's re-audit, one line before it could bite.** A pass that cannot be halved is asked once more about its chapter alone. If that last call goes quiet the window is now set aside and the audit goes on — but only when the provider timed out. An answer that comes back and will not parse, which is what this model does when it spends its whole budget reasoning, still raises and ends the run.

So the rescue covers the rarer failure and not the common one. Landfall's first audit died at `window-11-11` on exactly the common one, and the alone-call was written to fix it; the alone-call's own failure was left fatal.

**Fix.** The last resort has no next resort. Whatever comes back from it — nothing, or something unusable — the window is recorded as unread and the audit moves to the next pass. What it could not read is on the record; ending the run puts every pass that did answer on the floor and asks a person, which is the thing being removed.

**Tasks:**
- [x] The alone-call sets the window aside on any failure, not only on a silent provider
- [x] The set-aside row says which of the two happened
- [x] Test: an alone-call whose answer will not parse sets the window aside and the audit continues
- [x] Test: an alone-call that is silent still sets the window aside
- [x] Test: a pass that answers on the second ask is not set aside
- [x] Suite green: 573 passed, 354 subtests (era 570). Reinstall, commit & push

**Done when:** No single pass can end an audit.

## The writer's model is chosen from three drafts of the same chapter ✅

**Status: ✅ Done — 2026-09-01**

Landfall's design is closed and not one chapter is written, so the model that writes the prose can still be changed for nothing. Today it cannot be changed on its own: `_write_agents` writes `model: {MODEL}` into every role file in `ROLE_SPECS`, so the writer is DeepSeek v4 Flash because the canon-auditor is. `variant` is the only knob that a role owns — the writer runs at `low`, the judge at `max`.

Three things block a per-role model. `_write_agents` has no source for it. `record_execution` verifies the provider receipt against `expected_models = {MODEL, ...}` for any role in `ROLE_SPECS`, so a receipt from another model is refused as a broken pin. And the envelope does not name the model that will answer it, so the same chapter contract asked of two models hashes to one cache key and the second model would be handed the first's draft.

**Fairness of the comparison.** `qwen3.8-flash` is the one model in the catalog whose reasoning effort is not steerable: its ladder is `{"high": "high"}` and nothing else. `high` is therefore the only step the three candidates share, and the bake-off pins all of them to it — otherwise the measurement compares three efforts as much as three models. The chosen writer keeps `high` for the book, since that is the setting the drafts were read at.

**No promotion.** The route writes three drafts and stops. Which prose convinces is the user's judgement and the only decision in this pipeline that is theirs by design; the engine's job is to put the three side by side, not to pick.

**Tasks:**
- [x] One resolver reads `roles.<role>.model` and `roles.<role>.variant` from `book-forge.yaml`, falling back to `MODEL` and the `ROLE_SPECS` variant
- [x] `_write_agents` pins the overridden role's agent file to the resolved model and variant, leaving every other role where it was
- [x] `_expected_pin` and `record_execution` verify against the resolved pin, and still refuse a receipt from a model nobody asked for
- [x] A variant the target model does not offer is refused when the config is read, naming the ladder it does offer
- [x] `_opencode_config` lists the resolved writer model in the generated provider catalog even when it is not a chorus model
- [x] The envelope carries the resolved model and variant, so one capsule asked of two models is two cache entries
- [x] Test: an overridden writer writes its agent file pinned to that model, and the other eight roles are untouched
- [x] Test: a receipt from the overridden model is accepted and one from `MODEL` is refused
- [x] Test: the same contract drafted by two models leaves two cache entries, and neither is served to the other
- [x] Test: a variant outside the target's ladder is refused with that ladder in the message
- [x] `draft-bakeoff <book> <chapter> --models a,b,c` drafts one chapter under each model into `books/<book>/work/<chapter>/bakeoff/<slug>/`
- [x] Every candidate is given the same capsule, the same brief and `high` effort
- [x] Each draft passes `validate_writer_output` before it is written; a candidate that fails is recorded and the others still land
- [x] `bakeoff.json` records model, variant, word count, cost and wall time for each candidate
- [x] The route never writes `work/<chapter>/draft.md` and never closes the chapter
- [x] Test: three fake providers leave three drafts, one index and no promotion
- [x] Test: one candidate returning unusable prose is recorded while the other two land
- [x] The bake-off makes every plan write on the way back, on one thread: three threads racing on `plan.json` killed the third candidate with two already paid for
- [x] The spine bound test compares two briefs of equal length, so one character of brief no longer decides a token
- [x] Suite green: 590 passed, 354 subtests (era 573). Reinstall, commit & push
- [x] `margherita` runtime regenerated from its own config, its writer left on DeepSeek at `low`; `opencode.json` came out byte-identical
- [x] Run it on landfall CH-0001 with `deepseek-v4-flash-0731`, `glm-5.3-flash` and `qwen3.8-flash`: three drafts, three of three usable
- [x] Set `roles.writer` — model and variant both — to the model the user picks, and record the choice here

**Measured on CH-0001, 2000 words, all three at `high`.** The completion budget is reasoning and output together against a ceiling near 32000, and that is where the three separated: `deepseek-v4-flash` spent 25383 reasoning plus 3698 output, 29081 of about 32000, leaving 2900 on a chapter of median length in a book whose longest asks 2600 words. `glm-5.3-flash` spent 12035 and `qwen3.8-flash` 12817. Two designs of this same project have already died on that ceiling, so a writer that arrives within three thousand tokens of it on an average chapter is a run that ends on the long ones.

The other measurements. Words against a 2000 target: deepseek 1982, glm 1702, qwen 2036. Cost for the chapter: $0.0060, $0.0038, $0.0079, which over the book's 54600 words is $0.17, $0.12 and $0.21 — no model is chosen or refused on price here. Proper nouns invented against canon: deepseek none, glm one ship, qwen one ship and a speaking character who does not exist, which is an obligation the canon audit would open rather than a prop.

**Chosen: `glm-5.3-flash` at `high`,** written into landfall's `book-forge.yaml`. Its known cost is the word count: 1702 against 2000, and at that rate the book comes out around eight thousand words short of its design. The writer's validation band is 70-140% of target, so it cannot drift further than that, and the shortfall is visible per chapter.

**Left open, deliberately.** The reviser writes prose too and is still pinned to DeepSeek. Both roles read the same style preset, so the register is nominally shared, but a chapter written by one model and repaired by another is two hands on the same paragraph. Pinning `roles.reviser` to the writer's model is one line, and it was not taken without asking.

**Done when:** `roles.writer.model` decides who writes the book, and CH-0001 exists three times so that decision can be made by reading.

## A translation can be redone without throwing away the prose ✅

**Status: 🔄 In progress — 2026-09-01**

**Found on landfall's first Italian edition.** The locale style ruled `passato remoto` for action without excepting stative and durative verbs, and the translator was still on the default `low` effort, so three chapters came back with `Binta stette` for "Binta stood the watch" and with calques rendered word by word — `teneva i suoi polmoni dal dimenticare` for "kept her lungs from forgetting". Both causes are fixed where they live: the style now makes the imperfetto the base tense and forbids the remoto forms that stop a reader, and `roles.translator` is pinned to a model and an effort. Redoing the work is then a matter of asking again.

Nothing asks again. `translate run` translates a chapter only when its target file is absent, so a chapter whose style, glossary or model has changed is never revisited — the engine detects the staleness well enough to refuse publication, and offers no way to answer it. `reset --scope prose` does revisit it, by deleting the English manuscript with it: a hundred minutes of writing thrown away to redo five minutes of translation. What is left is deleting the locale's chapter files by hand, which is the move this project treats as the unforgivable one, because it fixes one directory and reaches no future run.

**Fix.** A `translation` reset scope that removes what a locale derived and nothing else: `translations/<locale>/chapters/*.md`, the locale state's completed chapters and boundary hashes, and that locale's editions. The manuscript, the contracts, the design and the canon are untouched. It requires `--locale`, and refuses without one rather than guessing which language was meant.

**Tasks:**
- [x] `reset --book <id> --scope translation --locale <loc>` removes the locale's chapters, its completed markers and its editions
- [x] The English manuscript, the chapter contracts and the design audit survive it
- [x] It refuses without `--locale`, naming the locales the book has, and refuses a locale the book does not have
- [x] `--yes` is required, as every other reset requires it
- [x] Test: a reset locale is re-translated by the next `translate run`, and the source chapters are byte-identical afterwards
- [x] Test: resetting one locale leaves another locale's chapters in place
- [x] Test: `--scope prose` still removes what it removed before, so the existing guard does not move
- [x] Suite green: 598 passed, 354 subtests (era 590). Reinstall, commit & push
- [x] Redo landfall's Italian with the corrected style and `glm-5.3-flash` at `high`, re-export both languages, update the four files already on Drive in place so the links keep working

**Measured.** The reset removed three chapter files and the two Italian editions, and the re-translation wrote them again from the corrected style: `Binta stette` became `Binta era di guardia`, and the four Drive files were updated at their existing ids, so every link handed out before this still resolves. The English manuscript was not touched, which is the whole point of the scope — the redo cost five minutes of translation and nothing of the hundred minutes of writing.

**Done when:** Redoing a translation costs the translation.

## A translation is read back before it is kept ✅

**Status: 🔄 Proposed — 2026-09-01**

The prose has a review stack — cold reader, technical editor, four style reviewers, reviser. A translation has one call and nobody reads it. Landfall's Italian shipped `Binta stette` for "Binta stood the watch" and `teneva i suoi polmoni dal dimenticare` for "kept her lungs from forgetting", and the pipeline reported success both times.

`_translation_validation` already refuses real defects: numbers that do not match the source, heading or scene structure that differs, a length ratio outside 0.45–2.2, source-language fragments left in, English title case in a locale that does not use it. It is deterministic, blocking, and free. What it cannot see is the target language: nothing reads the locale style or the glossary, so a decision written there reaches the translator's prompt and is never checked against the answer.

**Two halves, and the cheaper one catches more.**

The glossary is already machine-readable — `- **source** → target — note`. A source chapter containing `tide-chalk` whose translation contains no `gesso di marea` is an exact finding that costs nothing and cannot be hallucinated. The same mechanism reads a locale rules file for what prose cannot express to a machine: forbidden forms, dialogue punctuation, the body-part possessive. `stette` would have been caught here, on the first chapter, for free. The engine carries the mechanism and the project carries the rules — a skill that hardcodes Italian tense law is a skill nobody else can install.

The judgement half is a `translation-critic` role: source and translation side by side, plus the style and the glossary, returning findings that each cite a source span, a translated span and the rule broken. A finding citing nothing is set aside and recorded, the way the canon auditor already treats unverifiable evidence. This is what catches a calque, which is grammatical, breaks no listed ban, and is still wrong.

**The critic may not run on the translator's model.** A model rereading its own rendering shares its blind spots and approves them. This is refused in the resolver, not left to whoever writes the config.

**Bounded and never a stop.** One chapter per call, the same envelope class as the translation itself. Findings feed one repair call to the translator, as the reviser applies findings to prose. What the repair does not resolve is recorded beside the chapter and the run continues; nothing waits for a person.

**Tasks:**
- [x] `_glossary_compliance(source, translated, glossary)` returns a finding per term whose source appears and whose rendering does not
- [x] `translations/<locale>/checks.yaml` carries the locale's machine-checkable rules: forbidden patterns with a reason, required dialogue marks, and a body-part possessive rule
- [x] The generated `checks.yaml` is a stub, and an empty one is legal — a locale that declares no rules is checked by the glossary alone
- [x] The forbidden forms run inside `_translation_validation`, before any model is asked — exact patterns, so the gate can refuse on them
- [x] **Changed from the plan, deliberately.** Glossary compliance is advisory, not a gate. The match tolerates inflection so it can be wrong, and a heuristic inside a blocking check is how a book deadlocks: a false positive would spend the translation's one repair and then block the chapter. It runs in the review, where a false positive costs one repair call and nothing else
- [x] `translation-critic` role and prompt: cites source span, translated span, and the rule; a finding citing nothing is set aside
- [x] `_role_pin` refuses `roles.translation-critic` naming the translator's model, and says why
- [x] The critic's findings drive one repair call to the translator; unresolved findings are written beside the chapter and the run continues
- [x] Test: a translation dropping a glossary term is caught with no model call
- [x] Test: `stette` in an Italian chapter is caught by `checks.yaml` with no model call
- [x] Test: a locale with no `checks.yaml` still translates and is still glossary-checked
- [x] Test: a critic pinned to the translator's model is refused before the call
- [x] Test: a critic finding citing nothing is set aside and never becomes a repair
- [x] Test: a repair that fixes two of three findings records the third and does not stop the run
- [x] Suite green: 617 passed, 354 subtests. Reinstall, commit & push
- [x] Run it over landfall's three Italian chapters and report what it finds — 48 findings repaired across the three, including `Sua` for *Mine* reversing who belongs to whom, and `Acceava` and `soffavano`, which are not Italian words

**Reopened once, on the first real run.** The critic's answer for CH-0001 came back truncated mid-string: every finding quotes the source, the translation and the exact replacement, three strings each, and a chapter with a dozen findings does not fit the 3000-token ceiling the call was given. The engine did the right thing — set the pass aside, recorded it, carried on — and produced nothing usable.

An answer bounded by a constant is the invariant this whole engine is built on, and the critic was given a budget without being told a limit. Both halves are fixed: the ceiling rises to what a full set of quoted findings actually costs, and the prompt caps the count so the answer is bounded by construction rather than by the ceiling catching it.

- [x] The critic's output budget fits a chapter's worth of quoted findings
- [x] The prompt asks for at most twelve findings, most severe first, so the bound is in the question and not only in the cut
- [x] Test: a critic answer at the cap is parsed and drives its repair

**Reopened again, by reading the result.** The first real review repaired 48 findings across three chapters and left `lampade su la scala del porto` standing — an un-contracted preposition, the most machine-checkable defect Italian has, spotted by eye in the first paragraph. The locale's `forbidden` patterns run inside `_translation_validation`, which only executes while a chapter is being translated: `translate review` ran the glossary half and never opened `checks.yaml`. A chapter translated before a rule existed is exactly the chapter that needs the rule applied to it.

- [x] `_review_translation` runs the locale's forbidden patterns as well as the glossary, so a rule added after a translation still reaches it
- [x] Test: a forbidden form in an already-translated chapter is found by `translate review` and repaired

**Reopened a third time, and again by running it.** With the preposition rule in place, the second review of CH-0001 produced the finding and could not act on it: `Task is not ready: TRANSCRIT-BOOK-0001-CH-0001-it`. The pass reuses one task id per chapter, and that task had succeeded on the first review, so a chapter can be reviewed exactly once in its life. A review exists to be repeated — a rule written after a translation is precisely the rule that translation never met — and the engine already has `_reopen_task` for a completed task whose input changed.

- [x] The review and its repair reopen their task when it has already succeeded, because a review is a repeatable pass
- [x] Test: a chapter reviewed twice is reviewed twice, and the second pass can repair

**Done when:** A translation nobody read is not a translation the pipeline calls done.

## An attempt id is never handed out twice ✅

**Status: 🔄 In progress — 2026-09-01**

**Found on landfall, one command after the translation reset.** Re-translating died on `Execution receipt is immutable`: the claim was given `ATT-0040`, whose directory already held a receipt from the run that wrote chapter one.

`claim_task` allocates from the plan — `_next_id([row["id"] for row in plan["attempts"]], "ATT-")` — and the plan is not the record of what exists. Landfall has 207 attempt directories on disk and 69 attempts in its plan; every reset drops the attempts of the tasks it drops, and settled runs prune more. The directories stay, because they are the audit trail. So the counter walks back over ground that is already occupied, and the first claim to reach an occupied id dies on the immutability guard that exists to protect exactly that evidence.

This is not a defect of the translation scope. Any reset has always been able to do it; the translation scope is simply the first one used on a project old enough to have the gap.

**Fix.** The next attempt id is the successor of the highest id that exists anywhere — in the plan or on disk. Ids are never reused, the audit trail is never overwritten, and the guard stops firing on honest work.

**Tasks:**
- [x] Attempt ids allocate from the plan and the attempt directories together
- [x] Test: a plan pruned back to nothing still allocates past the directories on disk
- [x] Test: a reset followed by a re-run claims a fresh id and writes a fresh receipt
- [x] Test: the receipt of the earlier attempt is still there afterwards
- [x] Suite green: 617 passed, 354 subtests (era 604). Reinstall, commit & push

**Done when:** A reset cannot make the engine overwrite its own evidence.

## The glossary check is right about what it flags ✅

**Status: ✅ Done — 2026-09-01**

**Measured on landfall's three Italian chapters.** The check reported twelve terms missing. Five were real — `Contatori`, `il Conteggio`, `il Vault`, `il tenente di ronda`, and a chapter rendering `the gate` without the phrase its row fixes. Seven were the check being wrong, and it was wrong in four distinct ways, all in the matcher rather than in the translation:

The target's leading article is matched literally, and Italian contracts it: the row says `il registro di riva`, the chapter says `del registro di riva`, and the term is reported missing while sitting in the sentence. A word under five letters is matched without tolerating inflection, so `mano della palude` does not recognise `mani della palude`, which is what the chapter says. Parentheticals are stripped from the source side of a row and not from the target, so `i ripetitori a specchio (via degli specchi)` is looked for with its gloss attached. And one row is malformed — `**wind / foggia — the boatman's rig**` puts the row's own note inside the term, which makes `wind` a glossary term and flags every chapter that contains one of the commonest words in English.

Four out of ten right is usable as advice and would have been a disaster as a gate, which is the measured confirmation of a judgement made earlier by feel. But advice nobody can trust is advice nobody reads, and the repair call it drives is paid for either way.

**Tasks:**
- [x] A leading article in a target rendering is not required: the pattern starts at the first content word
- [x] A four-letter word inflects like any other when the term has more than one content word
- [x] Parentheticals are stripped from both sides of a glossary row
- [x] A row alternative carrying the note separator is not read as a term
- [x] Test: `del registro di riva` satisfies the row `il registro di riva`
- [x] Test: `mani della palude` satisfies `mano della palude`
- [x] Test: a target with a parenthetical gloss is matched without it
- [x] Test: a malformed row does not turn a common source word into a term
- [x] Test: the five real misses on landfall are still reported
- [x] The article is dropped from the rendering looked for and never from the term looked up: English tells `the Wall` from `wall` by that article, and dropping it flagged the row against six ordinary walls
- [x] A capitalised term is matched case-sensitively, for the same reason
- [x] The inflection tail is one letter and the pattern is anchored: an open tail read `watch-lieutenancy` as `watch-lieutenant` and called a correct rendering of the office a missing rendering of the person
- [x] Measured again on the same three chapters: twelve flags became one, and the one is a judgement the critic is there to make
- [x] Suite green: 628 passed, 354 subtests (era 621). Reinstall, commit & push
- [x] Fix landfall's malformed glossary row at the source
- [x] Re-review the three Italian chapters so the real misses are repaired, re-export, update Drive

**Done when:** Every term the check reports is a term the translation is missing.

## An advisory pass cannot block the run it advises ✅

**Status: 🔄 In progress — 2026-09-01**

**Found on the final review of landfall's Italian.** One chapter of three was read. CH-0002's critic answered with prose instead of the contract, and CH-0003 then died on `Run does not accept dispatch while blocked` — not because anything was wrong with CH-0003, but because the failure on the chapter before it had blocked the run.

Two defects, and both are the same sentence written twice: this pass is advisory and behaves as though it were not.

It takes a claim and, when the answer cannot be read, never settles it. The lease lapses, recovery converts the abandoned claim, and the run goes blocked — so an advisory reading that fails takes every chapter after it down with it. The engine already has the settlement for this: a failure marked `block=False` returns the task and leaves the run alone.

And it asks once. The translator gets a repair, the audit halves a window and then asks about the chapter alone, and the critic — the one role whose output is the most structured and therefore the most likely to come back malformed — gets a single attempt and is set aside. Two of three chapters went unread for want of a second ask.

**Tasks:**
- [x] Any failure of the critic settles its claim with `block=False`, so an unread chapter never blocks the run
- [x] The critic is asked twice: the second ask carries what was unreadable about the first
- [x] The repair keeps the same treatment, since it is the same kind of advisory call
- [x] Test: a critic that answers unreadably once and correctly the second time produces its findings
- [x] Test: a critic that fails twice sets the chapter aside, leaves the run running, and the next chapter is still read
- [x] Test: a failure on one chapter does not stop the chapters after it in a multi-chapter review
- [x] Suite green: 630 passed, 354 subtests (era 628). Reinstall, commit & push
- [x] Re-run the review over landfall's three chapters and report what each one got — three chapters read where one was read before, and CH-0003's later failure to answer readably no longer stops CH-0001 or CH-0002

**Done when:** No chapter goes unread because of what happened to another one.

## A refused repair is told why and asked again ✅

**Status: ✅ Done — 2026-09-02**

**Found on landfall's CH-0003, in the pass that fixed the layer above.** The critic returned thirteen findings, ten of them meaning, and the repair that carried them came back containing `volle` — a form the locale forbids. The gate held: the repair is validated exactly as the translation was, so the worse text was refused and the accepted translation kept. Then the pass stopped, and thirteen findings, ten of which are meaning changed or lost, stayed unapplied.

The refusal is right and the giving up is not. Everything else here that produces text gets told what was wrong with it and asked again — the translator does, the writer does, the critic does as of an hour ago. The repair is the one call that is judged and never answered.

**Fix.** A repair refused by validation is asked once more, carrying the reason it was refused, in the same shape the translator's own repair loop already uses. Two refusals and the accepted translation stands, recorded with what could not be applied — the run does not stop and nobody is asked.

**Tasks:**
- [x] A repair refused by validation is re-asked once with the refusal reason in its capsule
- [x] Two refusals leave the accepted translation in place and record the findings that could not be applied
- [x] The unapplied findings are written to the chapter's review file, so what the repair failed to fix is on disk rather than in a log line
- [x] Test: a repair refused once and correct the second time is applied
- [x] Test: a repair refused twice leaves the translation untouched and records the findings
- [x] Test: the second ask carries the reason the first was refused
- [x] Suite green: 632 passed, 354 subtests (era 630). Reinstall, commit & push
- [x] ~~Re-run CH-0003 and report whether its thirteen findings land~~ — **replaced, because it stopped being reproducible.** Those thirteen findings were one critic answer on one version of one chapter, and both have moved: CH-0003 has since been read and repaired, and the finding bound is now four. A verification that requires a state the project can no longer reach is not a verification, and re-running it would report on a different question while looking like it reported on this one.
- [x] Measured instead: has the refusal retry fired on real work, and did it hold — **twice, and it held both times.** `ATT-0146` on CH-0002 was refused for `forbidden form stette: passato remoto di stare su un verbo di stato`, `ATT-0148` on CH-0003 for `forbidden form dovette: forma che ferma il lettore`. Both were re-asked carrying the refusal, both came back acceptable, and both are the exact defects that started this whole line of work — `Binta stette` is the sentence that opened it.
- [x] The review's repair has never been refused in this project, so its own retry has not fired outside the tests. That is the honest state: the mechanism is one function used by both paths, the path that runs has run, and the path that has not is covered by three tests and nothing else.

**Corrected.** An earlier note in this entry called CH-0003 the chapter with the largest envelope. It is the smallest of the three at 14488 input tokens, against CH-0002's 16376. The size was inferred from the failure rather than measured, and the reason it failed was never its size.

**Done when:** The only text this pipeline refuses to improve is text it would make worse twice.

## A silent provider is waited out, not asked again at once ✅

**Status: ✅ Done — 2026-09-01**

Every retry in this engine is immediate. That is right for one of the two failures a provider has and wrong for the other, and the engine already knows which is which: `ProviderProducedNothing` is raised when nothing came back on the wire, and a parse failure is raised when something came back that could not be used.

An unusable answer is a question that was heard and answered badly, so asking again at once — carrying what was wrong with the last answer — is exactly right, and it works: the critic's second ask fixed a malformed answer an hour ago.

Silence is not that. It is a window, and tonight the windows were minutes long: two writer calls went quiet for 900 seconds each and the identical envelope then answered in 340; `deepseek-v4-pro-0813` produced no observable text twice in a row on CH-0003 and read the same chapter fine on the next command. Asking again inside the same window spends a call to be told the same nothing, and the retry that exists to make the pass autonomous is consumed before the window closes. Both times a person restarted it — that is the gap.

**Fix.** One helper, used at every point that already retries, that waits before a retry only when the last failure was silence: nothing, then a minute, then three. Feedback is what an unusable answer needs and time is what silence needs, and giving each the other's remedy is what makes both fail. Bounded at three attempts, so a dead provider costs four minutes and not a night.

**Tasks:**
- [x] `_retry_delay(attempt_number, silent)` returns zero for an unusable answer and a growing wait for silence
- [x] Every existing retry point uses it: the writer's repair, the translator's repair, the critic, the critic's repair, the audit's alone-call
- [x] The wait is reported on stderr as it happens, so a run that looks stalled says what it is waiting for
- [x] A run interrupted during a wait leaves nothing to recover: the claim is settled before the sleep, not across it
- [x] Test: a provider silent once then answering produces its result, and the clock was consulted
- [x] Test: an unusable answer is re-asked with no wait at all
- [x] Test: three silences give up, set the pass aside, and leave the run running
- [x] Suite green: 639 passed, 354 subtests (era 632). Reinstall, commit & push

**Two things came out different from the plan, both recorded rather than quietly done.**

The audit's alone-call was on the list, and it is the one point in this engine that deliberately has no next resort — the comment beside it says so, and the reason is sound: this model's common failure there is a whole budget spent on reasoning, and asking the identical question again buys the identical nothing. It now gets a second ask **only when the failure was silence**, which keeps that decision and fixes the transient case it was not about.

And the wait is skipped whenever the runner is not the real one. A substituted provider has no window to wait out — it answered exactly as the test told it to — and the first version made every existing test with a silent provider sleep for a minute, turning a two-minute suite into a timeout. That is the honest place for the condition: the engine waits for a provider, not for a stand-in.

**Done when:** A provider that goes quiet for two minutes costs two minutes, not a person.


## The checks are scored by the reader they feed ✅

**Status: 🔄 Proposed — 2026-09-01**

The deterministic checks are cheap and they are sometimes wrong. On landfall's three Italian chapters the glossary check reported twelve missing terms and was right about five; after the matcher was repaired it reports one, and that one is a polysemous word the critic correctly declined to act on. Both of those numbers were counted by hand, by reading twelve findings against three chapters and deciding one at a time. Nothing in the pipeline knows its own precision, so the next time it drifts, the person who finds out is whoever is reading the book.

A sampling audit would cost a call per sample and measure the check by asking a model the same question twice. There is something better available for nothing: **the critic is already reading the source, the translation, the style and the glossary, and it is already shown the deterministic findings.** Asking it to mark each one `holds` or `mistaken`, with a reason, costs a few tokens in an answer it is already producing, and it comes from the reader best placed to judge — the one that has both texts open.

**Fix.** The deterministic findings go to the critic labelled as such, and its contract gains a verdict on each. The engine records, per chapter, how many machine findings held and how many were mistaken, and a finding the critic calls mistaken never reaches the repair — today a false positive costs a repair call and risks a needless edit. `translate review` reports the rate, and a check whose findings are mostly mistaken says so in its own output instead of waiting to be noticed.

**Tasks:**
- [x] The critic's capsule carries the deterministic findings, labelled as machine findings rather than mixed into its own
- [x] Its contract gains `machine_findings: [{id, verdict: holds|mistaken, why}]`
- [x] A finding the critic calls mistaken is dropped before the repair and recorded with the reason
- [x] The review file records the counts: raised, held, mistaken, and the rate
- [x] `translate review` reports the rate per chapter and across the pass
- [x] A rate below half prints a line naming the check, because a check that is mostly wrong is a defect in the check
- [x] Test: a finding the critic calls mistaken never reaches the repair
- [x] Test: the counts land in the review file and in the route's report
- [x] Test: a critic that does not answer on the machine findings leaves them all standing, since silence is not a refutation
- [x] Test: the `trestle` case — a polysemous term the translation renders correctly — is marked mistaken and drops out
- [x] Suite green: 639 passed, 354 subtests (era 632). Reinstall, commit & push
- [x] Run it over landfall's three chapters and report the measured rate — one machine finding raised across the pass, held 0, mistaken 1: the polysemous `trestle`, which the critic refuted and which therefore never reached a repair. One sample is not a rate, and the counting is now the engine's rather than mine

**Done when:** The pipeline reports how often its own checks are wrong, and stops acting on the ones that are.

## A review says whether it converged ✅

**Status: 🔄 In progress — 2026-09-01**

**Found by reading the pass log rather than the book.** CH-0001 has been read back four times. The passes returned 17 findings, then 6, then 12, and the last twelve were all `meaning` — on a chapter whose overall verdict in that same answer was `faithful`. A chapter the critic calls faithful while listing twelve changes of meaning is a contradiction, and nothing looked at it.

The route has no stopping condition. `translate review` always finds something, because that is what it was asked to do, and nothing distinguishes a chapter that is finished from one that still has defects. So the decision of when to stop reading was made by a person going by feel — which is the judgement this line of work exists to remove — and there is no way to tell three passes that improved a chapter from three passes that invented work.

The signals cost nothing and are already produced. A pass with no actionable finding has converged. A finding that comes back unchanged after a repair that claimed to apply it means the repair did not land, which is worse than one that refused, because the refusal was at least recorded. A count that does not fall from one pass to the next is not progress whatever the findings say. And a verdict that contradicts the findings beside it is an answer that cannot be acted on in either direction.

**Fix.** Every pass records what it found in a form the next pass can compare: a fingerprint per finding, the hash of the text it read, and the count. The route reports `converged` with the reason, and `--until-clean` runs passes until convergence, until a pass makes no progress, or until a stated cap — and says which of the three ended it.

**Tasks:**
- [x] Each finding carries a fingerprint: its kind and the normalised span it quotes
- [x] The review file records the fingerprints, the hash of the text read, and the actionable count
- [x] A pass reports `repeated`, `new` and `gone` against the previous pass on that chapter
- [x] A finding repeated after a repair that claimed to apply it is named as such, since the repair did not land
- [x] A verdict of `faithful` beside a blocking or meaning finding is recorded as inconsistent, and the findings stand
- [x] `review_translation` returns `converged` per chapter with the reason: clean, no-progress, or more-to-do
- [x] `translate review --until-clean` runs at most `REVIEW_PASS_CAP` passes and reports which condition stopped it
- [x] Test: a chapter with no actionable findings converges in one pass and asks for no repair
- [x] Test: two passes returning the same count stop as no-progress rather than running to the cap
- [x] Test: a finding repeated after a claimed repair is reported as not landed
- [x] Test: `faithful` beside a meaning finding is recorded inconsistent and the finding is still acted on
- [x] Test: the cap ends a chapter that never converges, and the run does not stop
- [x] Suite green: 650 passed, 354 subtests (era 644). Reinstall, commit & push
- [x] Run `--until-clean` over landfall's three chapters and report how each one ended

**One condition came out of building it that was not in the plan:** `nothing-applied`. A pass whose repair changed nothing would have the next pass read the identical text and ask the identical question, so it stops there rather than spending three more calls to be told the same thing. And the two signals — a finding that did not land, a verdict that contradicts its own findings — are sticky across the passes, because reporting only the last pass hid them exactly where they mattered.

**Measured, and it says something the entry was not built to ask.** CH-0001 stopped after three passes on `no-progress` (3 findings against the previous pass's 1), CH-0002 after two on `no-progress` (5 against 2), CH-0003 after one on `unread`. The stopping condition works: no pass ran to the cap, and no person decided when to stop.

`repeated` was **0 on every chapter and every pass**. The repairs between passes are surgical — 26 words changed of 1793 on CH-0001, 33 of 2078 on CH-0002, 0 of 1666 on CH-0003 — so each pass read text that was 98.5% identical to the one before and returned a finding set disjoint from it. The hypothesis that the repair was rewriting chapters wholesale was measured and is wrong; the conclusion that replaces it is worse. **The critic's finding set is not the enumeration it is read as.** A pass with no findings does not mean a chapter with no defects, and `no-progress` reports the reading and not the chapter. This is a defect of the reading, which this entry does not fix; the cause was measured afterwards and is in [The critic's answer has room to be written].

**Done when:** The pipeline says why it stopped reading, and a person never decides that it has read enough.


## The critic's answer has room to be written ✅

**Status: ✅ Done — 2026-09-02**

**Measured over every translation-critic call this book has ever made.** Forty calls; **twenty-two returned `output: 0`** after spending **exactly 32000 tokens on reasoning**. That is $1.91 of the $3.36 the critic has cost — 57% of the spend — for zero characters. It is not one chapter's defect: CH-0001 ten empty of twenty, CH-0003 ten of thirteen, CH-0002 two of seven.

It is also not the biggest chapter that fails most, which is what was assumed before the counters were read and what they refuse: CH-0003's envelope is the **smallest** of the three at 14488 input tokens, against CH-0002's 16376. Chapter size is not the variable. The reasoning ceiling is, and every failure sits exactly on it.

**What the successful calls show is the same defect, unfinished.** When the critic does answer, it answers with what reasoning left behind: 1302, 1734, 804, 574, 402, 332 output tokens. The prompt asks for up to twelve findings, each quoting a source span, a translated span and a replacement. **Twelve quoted findings do not fit in 332 tokens.** So the finding sets that looked disjoint between passes were not a critic sampling a chapter — they were a critic cut off at a different point each time, and the convergence entry above read that as the chapter's state.

**This engine has met this failure three times and written the remedy down each time.** The designer's comment records 27045, 29441 and 31998 reasoning tokens against a ceiling near 32000, leaving 4955, 2559 and finally zero output. The audit's records `input 34822, reasoning 32000, output 0` five times, and the same design answering at ten chapters a time with reasoning to spare. `_audit_proposal` drops beats and imports for the same reason. The sentence beside the auditor is already the conclusion: *the question is not made easier by being asked again*. The translation critic is the only role that asks about a whole artifact in one call and, when that fails, asks the identical question again.

**Both of its retries are the wrong medicine, and the run pays for three of them.** The failure surfaces as `Model output contains no JSON object`, which `_is_silence` does not match, so the critic re-asks at once carrying what was wrong with the last answer — and there is no last answer to say anything about. Had it matched, the remedy would be worse: the backoff shipped this morning would wait four minutes for a provider that answered in full and billed for it. `output: 0` on a full reasoning ceiling is a third failure class. It is deterministic on the same input, it is charged at full price, and the only thing that changes it is changing the question.

**Fix, cheapest lever first.** The critic is pinned to `deepseek-v4-pro-0813` at `high`, and `high` is what buys the 32000 tokens of reasoning. Whether `medium` leaves room to write is one call to find out, and it would be built over if the structural work went first. If effort alone does not settle it, the question gets smaller the way it does everywhere else here: the chapter is read in halves, each half carrying the style, the glossary and its own machine findings, and the findings merge. What a half cannot see — a formula rendered two ways across the chapter — is what the glossary check already covers deterministically, so the split gives up something that is already covered elsewhere.

**How this Fix ended, written here rather than rewritten above.** Its cheap lever was measured and did not settle it; its structural half was measured and refused. What replaced both is a third thing the paragraph never considered — the size of the answer asked for — and it was found by varying one lever at a time instead of reasoning about which was likelier.

**Tasks:**
- [x] Measure `medium` against `high` on CH-0001 and CH-0003: reasoning, output, and whether the answer parses
- [x] Record the measurement in this entry before any code is written, since the structural half is only justified if the cheap lever fails
- [x] A critic answer with zero output tokens is its own failure, distinguished in the message and in the review file from an answer that came back malformed
- [x] It is never retried with the identical envelope: an unchanged question that exhausted the ceiling exhausts it again
- [x] `_is_silence` does not claim it, so the backoff never waits out a provider that answered
- [x] Test: a zero-output answer is not re-asked with the same envelope
- [x] Test: a zero-output answer is not treated as silence and costs no wait
- [x] The bound is a constant the engine owns, `CRITIC_MAX_FINDINGS`, carried in the capsule as `answer_bound` so the bound enforced and the bound stated are one value
- [x] The prompt carries no number of its own, and a test refuses one, since tuning the constant would otherwise leave the prompt behind
- [x] The measurement is written beside the constant, so whoever raises it knows what it buys and what it costs
- [x] Test: the capsule carries the bound the engine owns
- [x] Test: the prompt defers to `answer_bound` instead of naming a count
- [x] ~~The chapter is read in segments sized by a constant~~ — **not built.** Arm C measured it: half a chapter still reached the ceiling
- [x] ~~Findings from the segments merge, and a fingerprint stays stable whichever segment raised it~~ — **not built**, with the segmentation
- [x] ~~Test: a critic that exhausts its ceiling on a whole chapter answers on the segments~~ — **not built**; the arms are the measurement that would have justified it, and they refuse
- [x] ~~Test: findings from two segments merge without duplicating a finding that quotes across the boundary~~ — **not built**
- [x] Suite green: 661 passed, 354 subtests (era 658). Reinstall, commit & push
- [x] Re-run the three chapters and report the empty-call rate against the 22-of-40 measured here — **it did not improve, and four calls cannot say whether that means anything.** Two of four were empty against the baseline's twenty-two of forty: 50% against 55%. CH-0003, the chapter arm B answered four times out of four, answered here too at 28602 reasoning and 560 output. CH-0001 and CH-0002 each spent the ceiling. The arms' result is neither confirmed nor contradicted by a sample this size, and the production capsule differs from the arms' in carrying the machine findings, which is the next thing to vary if this is pursued.

**What did change is not a rate.** Each failure cost one call instead of three: two failures, four calls not made, $0.15 not spent. The message names the cause — `0 output token(s) after spending 32000 on reasoning` — instead of `Model output contains no JSON object`, which is what sent this investigation down the formatting path to begin with.

**`medium` measured, and it settles less than it looks like it does.** Four calls, the pin moved to `deepseek-v4-pro-0813` at `medium` and the runtime resynced:

| chapter | ask | reasoning | output | outcome |
|---|---|---|---|---|
| CH-0001 | 1 | 32000 | 0 | nothing |
| CH-0001 | 2 | 32000 | 0 | nothing |
| CH-0001 | 3 | 30410 | 1155 | 6 findings |
| CH-0003 | 1 | 26217 | 909 | 5 findings |

Both chapters were read, and CH-0003 was read for the first time in this project's history — it had gone unread through two full `--until-clean` runs. But CH-0001 still spent the ceiling twice, and four calls against a forty-call baseline cannot carry a rate. No rate is claimed here.

**What forty-four calls do establish.** Reasoning at exactly 32000 and output at 0 occur together every time, and every call that finished reasoning under the cap wrote an answer. The ceiling is hard and the outcome is binary, so the question is not why the model fails but what makes its reasoning finish sooner.

**And the premise this entry was written on is contradicted by its own numbers.** The fix above says the question is too big, meaning the input. The input is anti-correlated with failure: CH-0002 has the largest envelope at 16376 tokens and the best rate at 2 of 7, CH-0003 the smallest at 14488 and the worst at 10 of 13. Slicing the chapter on that basis would repeat the reasoning that produced "the chapter with the largest envelope" about the smallest one.

**So one lever is varied at a time before anything is built.** Three arms on CH-0003, four repetitions each, run against the provider directly — envelopes built and called with no claim, no plan write and no chapter rewritten, so the arms leave nothing behind but scratch directories. **A** is the question as it is asked today. **B** changes only the size of the answer requested, at most four findings instead of twelve. **C** changes only the size of the question, half the chapter at twelve findings. Whichever arm raises the answer rate names the lever, and if it is B the remedy is a line of the prompt and the segmentation below is not built at all.

- [x] Run the three arms and record which lever moves the answer rate

**Twelve calls on CH-0003, four repetitions of three arms, every one at `medium` on `deepseek-v4-pro-0813`.**

| arm | answered | reasoning | output | cost |
|---|---|---|---|---|
| A — the question as asked | **0 / 4** | 32000, 32000, 32000, 32000 | 0, 0, 0, 0 | $0.39 |
| B — at most four findings | **4 / 4** | 28966, 26425, 28939, 22909 | 716, 609, 724, 604 | $0.35 |
| C — half the chapter, twelve | **3 / 4** | 28520, 14837, 31999, 30307 | 1421, 583, 0, 679 | $0.32 |

A returned exactly 32000 four times out of four. That is not variance around a mean, it is a question that reaches the ceiling every time it is asked.

**What decides is the size of the answer demanded, and the arms separate it cleanly.** C failed on **half** the chapter, at 31999 — if the text were what exhausted the model, that call could not have failed. B kept the whole chapter and lowered only the bound, and answered every time, with the narrowest spread of the three arms.

**So the segmentation below is not built, and the reason is measured rather than argued.** It would have been new code, two calls per chapter instead of one, and C says it does not fix the failure it was proposed for. The premise it rested on — the question is too big, meaning the input — was contradicted twice: first by the rate across chapters, where the largest envelope failed least, and now directly by C's failure on half a text.

**The cost of the bound, stated rather than buried.** Four findings a pass instead of twelve means more passes to exhaust a chapter, and finding counts from before this change are not comparable with counts after it. That is affordable now and was not yesterday, because the pass loop only learned this morning how to tell a chapter that is finished from one that still has defects. And four findings from a call that answers beat twelve from a call that returned nothing in 22 of 40 attempts.

**What the arms found that no arm was asked.** Two calls of the same arm on the same half-chapter reasoned 28520 and 14837. The spread inside an arm is wider than the gap between the arms, so the bound does not remove the failure — it moves the whole distribution far enough below the ceiling that four repetitions did not reach it. A denser chapter will take some of that margin back, and the honest reading of `CRITIC_MAX_FINDINGS = 4` is a margin bought, not a defect closed.

**Named rather than inferred.** `ReasoningCeilingSpent` is recognised from the counters the provider returns — empty text while reasoning tokens were spent — and not from the message, which is how the case was being read as a malformed answer. An empty answer with **no** reasoning behind it is left alone: nothing on the wire is the case the existing retry was built for, and it keeps its three asks. The saving is two calls of every three on this failure, at roughly $0.12 each.

**Done when:** A critic call that is paid for produces an answer, and a finding set ends because the critic ran out of findings rather than out of room.

## A chapter that was not read is not a chapter that is clean ✅

**Status: ✅ Done — 2026-09-02**

**Found by reading the artifact instead of the route's report.** Two consecutive reviews of CH-0001 failed completely: three critic asks each, every one `Model output contains no JSON object`, nothing read. The route said so exactly — `"verdict": "unread"`, `"ended": "unread"`, `"converged": false`, `"set_aside": 1`. The convergence state written to disk beside the chapter said something else:

    "state": "clean",
    "reason": "nothing left to act on",
    "actionable": 0,
    "fingerprints": []

The route is right and the durable record is wrong. `reviews/<chapter>.state.json` is the artifact that outlives the run: it is what the next pass compares against, and it is what anyone reading the repository is told about that chapter. It says a chapter nobody could read is finished, and it gives the reason as *nothing left to act on* — which is only true in the sense that nothing was ever picked up.

The cause is that `clean` is computed from the count of actionable findings, and a reading that produced no findings is indistinguishable, at that line, from a reading that found none. They are opposite outcomes: one says the chapter is done, the other says the pass failed. Collapsing them makes the failure invisible in exactly the place built to make progress visible, and a later pass reading that state computes its `new` and `gone` against an empty set it has no reason to trust.

**Fix.** Convergence is not computed when the read was set aside. The state records `unread`, carries how many asks were spent, and leaves the previous pass's fingerprints in place rather than overwriting them with an empty set — a failed reading has no business erasing what the last successful one knew.

**Tasks:**
- [x] A pass whose critic was set aside records `state: "unread"` with the number of asks, and never `clean`
- [x] Its reason names the failure rather than the empty count
- [x] The previous pass's fingerprints survive a failed reading instead of being overwritten by an empty set
- [x] `clean` requires a reading that happened: an answer parsed, with zero actionable findings in it
- [x] Test: three failed asks leave `unread` on disk and the earlier fingerprints intact
- [x] Test: a genuine zero-finding answer still records `clean`
- [x] Test: a pass after a failed one compares against the last reading that succeeded
- [x] Suite green: 658 passed, 354 subtests (era 650). Reinstall, commit & push
- [x] Re-read landfall's three state files and confirm none of them claims a reading that did not happen — **verified on the real files.** CH-0001 and CH-0002 record `unread`, `asks: 1`, reason `the critic was not read in 1 ask(s)`, and carry 2 and 5 fingerprints from the last pass that read them. Before this change both would have recorded `clean`, reason `nothing left to act on`, with an empty fingerprint list. CH-0003 records `no-progress` from a reading that happened.

**Two came out of building it that were not in the plan.** `unread_because` is written into the state file, because the review artifact beside it is only produced by a pass that succeeded — a pass that failed outright had nowhere to record which of the two failures it was. And a pass that fails with no earlier reading behind it records `carried_from: "no earlier pass"` rather than pretending to carry something, so an empty fingerprint list is legible as never-read rather than as read-and-empty.

**Done when:** The record beside a chapter distinguishes a chapter with no defects from a chapter nobody managed to read.


## A finding has to quote the text it is about ❌

**Status: ❌ Withdrawn — 2026-09-02, refuted before any code was written**

**The case that opened this entry was not what it looked like.** CH-0003's critic quoted `La pratica era in piedi: *misread*, …` as the translation delivered, and that sentence was reported here as absent from the chapter. It was not absent. It was in the chapter the critic read, the repair changed it to `La pratica recitava: …`, and the engine committed that change as `book-forge: promote TXN-0149` before the check was made. The finding was true, the repair was correct, and the reading that called it invented was made against a working tree the engine had already updated and committed.

**The measurement the entry demanded is what refuted it, which is why it was demanded.** Every promoted critic answer was paired with the exact text its own envelope carried — the chapter as it was then, not as it is now. **140 cited findings: 4 quote something not literally present, and 3 of those 4 are one citation style.** A critic quoting two non-contiguous spans joins them with ` / ` or an internal `…`, and each part is a real quote. Understanding the joiners leaves **1 of 140, 0.7%** — `Still mud gave nothing.` where the source says `mud gave nothing.`, a quote with a word added rather than a quote of nothing.

So the check would refuse one true finding in 140 and catch nothing, because there is nothing to catch. Building it would have thrown away findings — including, on the naive version, the `«Sua» disse Cinder` finding that is the most important defect this pipeline has ever found, whose quote joins two lines with a slash.

**What is worth keeping is the method, not the entry.** The reference for what a model was given is its own envelope. A chapter file read after the run has moved, and in this project it has moved *and been committed*, because promotion commits. `git status` came back clean and `git diff` empty on three chapters that had all just been rewritten.

**Done when:** withdrawn.

## A repair that changes nothing is not a repair ❌

**Status: ❌ Withdrawn — 2026-09-02, refuted before any code was written**

**Same mistake, same run.** The staged repair for CH-0003 was compared against the chapter on disk, found byte-identical, and reported here as a repair that changed nothing. It is identical because the repair had already been promoted *and committed*: the file on disk was the repair's output, not its input. Diffed against the text the model was actually given — `previous_output` in its own envelope — the repair changed exactly the line the finding cited.

**Measured across the project:** 21 promoted repairs paired with the call that produced them. **None returned its input unchanged.** The state this entry proposed to add, `nothing-applied` for a no-op answer, would never have fired.

**And the run this came from did the opposite of what was reported.** All three chapters were rewritten and committed by it — CH-0001 and CH-0002 two lines each, CH-0003 one. The claim that no chapter changed was read off `git status` after the engine had committed, which shows a clean tree precisely when the run has done the most.

**Done when:** withdrawn.


## The reviser writes in the hand the writer chose ✅

**Status: ✅ Done — 2026-09-02**

**Left open deliberately when the bake-off was decided, and never taken.** `roles.writer` decides who writes the book — landfall chose `glm-5.3-flash` at `high` by reading three drafts of CH-0001. The reviser also writes prose: it applies the cold reader's and the technical editor's findings to a chapter, sentence by sentence. It is not pinned, so it runs on the project default, which on landfall is `deepseek-v4-flash-0731` at `low`.

So every chapter is written by one model and repaired by another, at a different effort. Both read the same style preset, which makes the register nominally shared and does not make the hand the same. The bake-off existed to decide that hand by reading, and half the prose escapes the decision.

**Fix.** A project that pins the writer and says nothing about the reviser gets the writer's pin for the reviser, because that is what choosing a writer meant. An explicit `roles.reviser` still wins, so a project that wants two hands can have them and has to say so.

**Tasks:**
- [x] `_role_pin` resolves `reviser` to the writer's pin when the project pins a writer and does not pin a reviser
- [x] An explicit `roles.reviser` overrides it, and a project pinning neither is unchanged
- [x] Test: a project pinning only the writer resolves both roles to that model and variant
- [x] Test: a project pinning both keeps them apart
- [x] Test: a project pinning neither resolves as it does today
- [x] The generated agents reflect it, so the runtime guard does not fire on a project that never edited its config
- [x] Suite green: 675 passed, 405 subtests (era 661). Reinstall, commit & push
- [x] Landfall resolves both roles to `glm-5.3-flash` at `high`, confirmed by `runtime sync`

**One test came out of building it that was not in the plan.** Pinning the writer must move the reviser and *nothing else* — a rule that quietly dragged the cold reader or the auditor onto the writer's model would be a worse defect than the one being fixed, and harder to see.

**Done when:** The model chosen by reading three drafts writes every sentence of the book, including the repaired ones.

## An edition says who wrote it ✅

**Status: ✅ Done — 2026-09-02**

**Four editions have been published from this engine and none carries an author.** `book.yaml` holds `title`, `id`, `order` and `continuity`, and the epub and PDF are built from it. An epub with no author is a file a reader's library files under nothing, and the field is part of the metadata the format already has room for.

**Fix.** An optional `author` on the book, threaded into both edition formats. Optional because a book that has not decided is a real state and should not be blocked from exporting; absent, the editions build exactly as they do today.

**Tasks:**
- [x] `author` is an allowed key of `book.yaml`, optional, and `add-book --author` accepts it
- [x] The epub carries it as its creator, and the PDF as its author
- [x] A book without one exports as it does now, with no placeholder invented for it
- [x] Test: a book with an author has it in both editions; a book without one has neither the field nor a placeholder
- [x] Suite green: 675 passed, 405 subtests. Reinstall, commit & push

**Found while building it, and it changes what this entry was for.** The project-level `author` already existed in `book-forge.yaml` and was already threaded into both formats — `dc:creator` in the epub, the author field in the PDF. Four editions shipped with none because nobody had a reason to set one for a whole universe. So the work was not adding the field but making it addressable at the level a book is actually written at: a universe can hold books by different hands, and now the book's own value wins where it has one.

**Left unset on landfall, deliberately.** An author is a name, and naming one is not a default this can pick. The mechanism is there and the value is one word away.

**Done when:** An edition names its author when the book has one.


## A malformed finding is set aside, not fatal ✅

**Status: ✅ Done — 2026-09-02**

**Found by running the book.** `advance` reached CH-0004, the first chapter written since the writer and reviser were put on one hand, and died: `chapters failed and nothing could be recovered: Review finding is missing required evidence fields`. The cold reader had answered — 707 output tokens, well formed JSON, several usable findings — and one of them lacked `fix_required`. **Corrected:** the first version of this note also blamed `evidence` for being a sentence rather than an object. The contract asks for a sentence — *exact location and brief quote* — so that half was wrong, and one missing boolean is the whole of it. `_validate_findings` raises on the first finding it cannot read, so the whole review was discarded, then the chapter, then the run. A book of twenty-six chapters stopped on one field of one finding.

This is the boundary principle, which this engine already applies everywhere else: what a model returns that the engine cannot use is set aside and recorded, the run continues, and a person is never asked. The critic does it for a finding that cites nothing. The canon auditor does it for unverifiable evidence. The two reviewers that gate every chapter do not.

**And the same call turned up the second half.** The technical editor beside it answered `output: 0` after `reasoning: 31999` — the third failure class, named this morning for the translation critic and not yet recognised anywhere else. It is worth fixing in one place rather than per role: any role whose answer is empty after a spent ceiling should be told apart from one that answered badly, because the two need opposite remedies and the wrong one is expensive.

**Fix.** A finding that does not satisfy the contract is dropped from the list, recorded beside the chapter with what was wrong with it, and the review proceeds on the findings that do. A review where **nothing** survives is a review that failed, and keeps the retry it has today. `_refuse_empty_answer` moves to every role that parses a contract, so a spent ceiling is never re-asked with the identical envelope anywhere.

**Tasks:**
- [x] `_validate_findings` returns the findings it can read and the ones it cannot, instead of raising on the first bad one
- [x] The set-aside findings are recorded beside the chapter, with the field that was missing
- [x] A review whose findings are all unusable still fails, since that is an answer nobody can act on
- [x] The count is reported on stderr, so a reviewer that is drifting is visible without reading files
- [x] `_refuse_empty_answer` guards the chapter reviews as it guards the translation critic
- [x] Test: a review with one malformed finding among good ones proceeds on the good ones and records the bad one
- [x] Test: a review with only malformed findings fails as it does today
- [x] Test: a reviewer that spends its ceiling is not re-asked with the same envelope
- [x] Suite green: 681 passed, 405 subtests (era 675). Reinstall, commit & push
- [~] `advance` gets past CH-0004

**Done when:** One field of one finding cannot stop a book.


## A pass of two roles resumes on the one that answered ✅

**Status: ✅ Done — 2026-09-03**

**Found on CH-0005, one chapter after the last one.** The chapter review asks two roles under two claims — cold reader and technical editor — inside one function. On CH-0005 the cold reader answered, validated, materialized and **promoted**; the technical editor beside it returned `output: 0` after `reasoning: 31999` and raised. The run retried the pass, and the retry died on `Only a running attempt can be marked accepted`: it re-claimed both roles, including the one whose task had already succeeded.

The resume this function has understands only total success — `if len(materialized) == 2` — so a pass that half-succeeded reads as a pass that did nothing, and the half already paid for is asked again in a state that cannot accept it. It is the same shape as the defect fixed an hour before it: **a partial result treated as no result.**

**Fix.** Reuse whichever role has already succeeded and call only the ones that have not. One role's failure then costs one call rather than the pass, and never leaves a promoted task to be re-claimed.

**Tasks:**
- [x] The materialized review of a role that succeeded is reused whether or not the other one did
- [x] Only roles without a succeeded task are claimed and called
- [x] Test: a pass where one role succeeded and the other failed calls only the failed one on the retry
- [x] Test: a pass where both succeeded calls neither
- [x] Test: a pass where neither succeeded calls both, as it does today — covered by every existing review test, which all start from an empty plan
- [x] Suite green: 690 passed, 405 subtests (era 681). Reinstall, commit & push

**Done when:** A role that answered is never asked again because the role beside it did not.

## The chapter reviewers are bounded like the critic ✅

**Status: ✅ Done — 2026-09-03**

**The technical editor has now spent its ceiling twice in two chapters** — `output: 0` after `reasoning: 31999` on CH-0004 and again on CH-0005. It is the fourth role in this engine to fail that way, after the designer, the canon auditor and the translation critic, and it is the first one that **gates a chapter**: the critic is advisory and can be set aside, this cannot.

Its contract asks for a findings list with no limit on it. The twelve-arm measurement on the translation critic says what moves this failure: **the size of the answer demanded, not the size of the text**. The question as asked answered 0 of 4; bounded to four findings it answered 4 of 4; halving the text still failed at 31999. Applying that bound here is the measured lever rather than a fresh guess, and the same holds for the cold reader, unbounded for the same reason and so far spared only by luck.

**Fix.** One constant for the chapter reviewers, carried in the capsule as `answer_bound` the way the critic's is, with both prompts deferring to it instead of naming a count of their own.

**Tasks:**
- [x] `REVIEW_MAX_FINDINGS`, carried into both reviewers' capsules as `answer_bound`
- [x] Both prompts defer to it and name no count of their own
- [x] Test: both capsules carry the bound the engine owns
- [x] Test: neither prompt names a count
- [x] Suite green: 690 passed, 405 subtests (era 681). Reinstall, commit & push
- [~] Measured on the chapters after it: how often a reviewer spends its ceiling, against twice in two

**Done when:** The role that gates a chapter is asked a question it can finish answering.


## A stage retries because the run is healthy, not because something broke ✅

**Status: ✅ Done — 2026-09-03**

**Found on the third stop in three chapters, and it corrects a generalisation made this morning.** The technical editor spent its reasoning ceiling on CH-0005 with the answer bound in the question — verified in the envelope, `Report at most 6 findings`, and in the prompt — and the run stopped. The bound is the lever the twelve arms measured on the translation critic, and **it did not transfer.**

**What the role's own history says, across all eighteen calls it has ever made on this book.** Fourteen answered with reasoning between 13398 and 30433; three came back empty at 31999 or 32000; and the decisive pair is `ATT-0260` and `ATT-0262`: **the same input of 13185 tokens, one empty and one answering with 27269 of reasoning and 1145 of output.** Input is not the driver either — `ATT-0064` and `ATT-0068` answered at 16091 and 16523, larger than every failure.

So this role sits at a mean near enough to the ceiling that variance decides, and **asking again works**: 15 of 18. That is the opposite of the translation critic, whose unbounded question came back empty 4 times out of 4 identical asks. The sentence this engine has repeated since the designer — *the question is not made easier by being asked again* — is true there and **false here**, and this morning it was applied to every role at once on the strength of one role's measurement.

**And the reason the engine did not simply ask again is its own.** `stage()` retries only when `recover_before_dispatch` reports that it recovered something. A failure that settles cleanly — the better-behaved case, and the one this engine works hard to produce — leaves nothing to recover, so `recovered` is false and the stage gives up on the first try. **Recovery is being used as the licence to retry, and it is the wrong licence.** What makes a retry safe is that the run is healthy and no person is needed, which `_halt_if_a_person_is_needed` already decides one line above.

**Fix.** A stage that fails retries while the run is healthy, whether or not recovery had anything to do, bounded by `MAX_STAGE_ATTEMPTS` as it is today. With the per-role resume shipped an hour ago, a retry re-calls only what actually failed, so a second ask costs one call and not a pass.

**Tasks:**
- [x] `stage()` retries on a clean failure, not only on a recovered one, while no person is needed
- [x] The message says which it was, so a run that is retrying a clean failure does not look like one that is recovering a broken claim
- [x] The cap stays at `MAX_STAGE_ATTEMPTS`, so a deterministic failure still ends
- [x] Test: a stage that fails cleanly once and succeeds on the second ask completes
- [x] Test: a stage that fails cleanly every time still ends at the cap
- [x] Test: a failure that needs a person still halts without retrying — already covered by `test_a_halt_always_says_what_to_do_next`, which is the case `_halt_if_a_person_is_needed` decides before any retry is considered
- [x] Suite green: 692 passed, 405 subtests (era 690). Reinstall, commit & push
- [~] `advance` gets past CH-0005

**Done when:** A run that is healthy asks again, and only a run that needs a person stops.


## A reviewer that cannot be read settles its own claim ✅

**Status: ✅ Done — 2026-09-03**

**Found by counting the times a person was needed tonight: twice, and both for the same reason.** The chapter review calls `mark_provider_accepted` and then, if the answer cannot be used, raises — with the claim left accepted and unsettled. Recovery finds an accepted claim with a session id on the wire and declares `outcome_unknown`, which is correct and deliberate: the provider took the call, a retry may pay twice, and that is a decision the engine refuses to make alone. So the run halts for `resume --resolve-unknown`.

But the engine already knows what happened. The answer came back, it was read, and it was unusable — that is a *failed* attempt, not an unknown one, and the difference is the whole point of the two classes. The translation critic settles exactly this case with `block=False`, which is why a critic that cannot be read never stops anything. The two roles that gate a chapter do not, and they are the ones that can stop a book.

**This is the fourth variation of one theme tonight** — a malformed finding treated as a failed review, a half-finished pass treated as an unstarted one, a clean failure treated as an unrecoverable one, and now a read failure treated as an unknown outcome. Each time the engine had more information than the path it took used.

**Fix.** A review whose answer is unusable settles its own claim as failed before it raises. The stage retry then does its work without a person, and a genuine unknown — the provider accepted and *nothing* came back — still halts, because that one really is a decision about paying twice.

**Tasks:**
- [x] A chapter review that cannot use its answer settles the claim as failed before raising
- [x] `block=False`, since the stage above already decides whether to retry and one chapter must not block the run
- [x] A call that was never accepted is untouched, so a real unknown still reaches a person
- [x] Test: a reviewer whose answer cannot be parsed leaves its task failed rather than outcome_unknown
- [x] Test: a reviewer that spends its ceiling leaves its task failed, and the retry re-asks it
- [x] Test: an attempt accepted with nothing back is still an unknown outcome — untouched, and covered by `test_an_unknown_outcome_is_never_recovered_because_a_retry_may_pay_twice`
- [x] Suite green: 699 passed, 405 subtests (era 692). Reinstall, commit & push

**The first version of this fix settled the wrong claim, and the test written for it was too weak to say so.** It settled only the role that raised, and asserted that the task was not `outcome_unknown` — which was true of a claim still sitting at `running`, so it passed without proving anything. Reading the real state showed what mattered: the loop raises on the first role, so the **sibling's** claim — accepted, never looked at — is the one left holding, and the one that would have become the unknown. The pass now tracks every claim it holds, drops each as it promotes, and settles whatever is left before the exception leaves. The assertion is `pending` or `failed`, which is what settled means.

**Done when:** A person is asked only about paying twice, never about an answer the engine has already read.


## The reviser is asked for a list it can finish ✅

**Status: ✅ Done — 2026-09-03**

**Measured on CH-0008, the first stage this run could not retry its way out of.** Three attempts, all refused by the same gate: `Revision must disposition every blocking and warning finding exactly once; missing S-glm-5-3-flash-02, -06, -07`. The reviser was handed **45 findings** and answered with 6155 output tokens, missing three of the ones it had to cover.

The composition is the finding:

| | |
|---|---|
| findings handed to the reviser | 45 |
| of which from the four style advisors | 30 |
| must be dispositioned (blocking + warning) | **21** |
| of those, from the style advisors | **15** |

So three quarters of the reviser's *mandatory* work comes from a pass that is advisory by design. The two roles that gate the chapter contribute six between them; the chorus contributes fifteen, because each of four advisors returns as many findings as it likes.

And the gate is right to be strict — a disposition silently skipped is a finding nobody acted on and nobody recorded. The demand is what is wrong, not the check.

**This is the same lever, for the third time.** The translation critic answered 0 of 4 unbounded and 4 of 4 bounded; the chapter reviewers were bounded on that evidence; the style advisors are the last unbounded producer of findings in the chapter pipeline, and they are the ones now overflowing the role downstream of them.

**Fix.** The style advisors carry `answer_bound` like every other role that returns findings. Four advisors at a small bound still outnumber the two gates, which is the point of a chorus — but the reviser's list stops being a function of how talkative four models happen to feel.

**Tasks:**
- [x] `STYLE_MAX_FINDINGS`, carried into the style capsule as `answer_bound`
- [x] The style prompt defers to it and names no count of its own
- [x] Test: the style capsule carries the bound
- [x] Test: the prompt names no count
- [ ] Measured on the chapters after it: how many findings reach the reviser, against 45 and 21 mandatory
- [x] Suite green: 701 passed, 405 subtests (era 699). Reinstall, commit & push
- [~] CH-0008 closes

**A prediction made here and disproved within the hour.** This entry said the reviser could not finish a list of that size. CH-0008 was restarted carrying the same forty-five findings — its style tasks had already succeeded, so the new bound did not reach it — and the reviser finished it on the next attempt, with no retry at all. So the failure was variance, the same signature as the technical editor's, and "cannot finish" was too strong: it finishes, not always. What survives is the measurement that motivated the bound — fifteen of the twenty-one mandatory findings coming from a pass that is advisory by design — which is an imbalance worth removing whether or not the reviser sometimes copes with it.

**One condition written into the test rather than left to judgement.** Four advisors at this bound must stay *more* numerous than one gating role and *fewer* than the twenty-one that broke the reviser. A chorus that says less than a single gate is not a chorus, and that is as easy to get wrong from this direction as the overflow was from the other.

**Done when:** The reviser's list is the size the engine chose, not the size four advisors happened to produce.


## A lease outlives the call it protects 🔄

**Status: 🔄 In progress — 2026-09-03**

**`Only a running attempt can be marked accepted` appeared three times tonight and was twice left undiagnosed for want of data.** The data is now in: **the lease is shorter than the calls it covers.** `LEASE_SECONDS = 300.0`, and `OPENCODE_CALL_TIMEOUT = 900.0` — so a call may legitimately run three times longer than the claim protecting it, and when it does, the claim lapses while the work is still healthy. The engine then takes its own answer and finds the attempt no longer running.

**Measured over 294 calls this project has made:**

| role | calls | median | max | over the 300s lease |
|---|---|---|---|---|
| translation-critic | 51 | 433s | 674s | **46** |
| reviser | 52 | 229s | 609s | 14 |
| writer | 18 | 309s | 900s | 9 |
| technical-editor | 28 | 251s | 308s | 4 |
| canon-auditor | 24 | 176s | 900s | 5 |
| translator | 32 | 109s | 447s | 5 |

The critic exceeds its lease on **46 calls out of 51**. Half this engine's roles routinely run with a lapsed claim, and whether that becomes a failure is decided by whether anything happens to call recovery inside the window — which is why it surfaced as an intermittent error on one role rather than as the systematic condition it is.

**The lease is not a timeout and was being used as one.** It exists so a claim abandoned by a dead process can be reclaimed, and for that it has to be longer than the longest a live call can legitimately take. That length is not a matter of opinion: it is `OPENCODE_CALL_TIMEOUT`, the point at which the engine itself gives up. A lease shorter than that declares healthy work abandoned by arithmetic.

**Fix.** The lease is derived from the call timeout with headroom rather than typed as an independent number, so the two cannot drift apart again. The cost is stated plainly: a genuinely dead process holds its claim for longer before it can be reclaimed. That is the right side to err on — reclaiming early breaks work that is running, and tonight it did, three times.

**Tasks:**
- [x] `LEASE_SECONDS` is derived from `OPENCODE_CALL_TIMEOUT`, with the headroom stated beside it
- [x] Test: the lease is longer than the call timeout, so a call that runs to its own limit never outlives its claim
- [x] Test: an abandoned claim is still reclaimable once the lease has passed — unchanged and still covered by the recovery tests, which set their own lease rather than reading the constant
- [x] The measurement above is recorded beside the constant, so the next person who shortens it knows what it costs
- [x] Suite green: 703 passed, 405 subtests (era 701). Reinstall, commit & push
- [~] `advance` runs a chapter without the error appearing

**Done when:** A claim outlives the work it covers, and only a dead process loses it.


## The chapter reviewer's input does not grow with the book ⏸️

**Status: ⏸️ Proposed — 2026-09-03, measured and not started**

**Measured inside one run, on the role that gates every chapter.** The technical editor's capsule, in characters:

| chapter | context | prose | contract | consequences |
|---|---|---|---|---|
| CH-0004 | 19429 | 9788 | 5331 | 2440 |
| CH-0006 | 33923 | 10270 | 6068 | 2444 |
| CH-0009 | **35126** | 8821 | 6750 | 3011 |

**The context nearly doubles across six chapters while the prose stays flat.** What grows is the imported canon: a chapter deeper into the book imports more of it, so the input of the role that must approve every chapter is a function of how far the book has got. At CH-0009 the context is about half the whole envelope.

And the failures track it. On CH-0009 the technical editor answered twice and came back empty twice on the identical input, and the run has now stopped on this chapter more than once. Earlier chapters, at 13185 and 15254 tokens, failed occasionally; this one fails about half the time.

**This engine designs against exactly this shape and says so out loud.** The designer slices so no call's size follows the book's length; the audit windows its passes; `_audit_proposal` drops the fields the auditor does not need. The chapter reviewers have none of it, and they are the ones that can stop a book.

**The engine already measures this and treats it as advice.** Every failing call printed `envelope 22372 tokens is over the advisory budget 20000` and proceeded. The budget is right, the number it names is right, and nothing acts on it.

**Why this is proposed rather than done.** The fix is not a constant — it is deciding what the technical editor can be asked to check without reading all the canon a chapter imports, and that is a judgement about what the role is for, not an arithmetic one. `_audit_proposal`'s precedent is to drop what another check already owns, and the equivalent here has to be chosen by reading what the technical editor's findings actually cite. Picking it at four in the morning, on the strength of a correlation, is how the last three guesses tonight got disproved.

**The cheap lever was tried and it does not work here.** The technical editor was pinned to `medium` on this project — the same operating point that let the translation critic read CH-0003 for the first time — and CH-0009 came back `reasoning 31998, output 0` at the first ask. One call, so it settles nothing about the role in general; it does settle that this is not the way past this chapter. The pin was reverted, because a change with no evidence behind it should not sit in a project's config.

**So the input is what is left**, and the correlation now has nothing else standing beside it: not the answer bound, which is in place; not the effort, which was just tried; not the text, which is flat while the context doubles.

**That measurement was made, and it rules out the obvious fix.** Across the 34 technical-editor findings this book has produced: **19 of them — 55% — cite no canon block at all**, and the 15 that do cite **17 distinct blocks**, none more than twice. The cited set is not small and stable, it is as wide and thin as the canon itself, so "send the blocks that get cited" cannot work: there is no predicting which one the next finding needs.

**What it does support is splitting the question rather than trimming the input,** which is the move this engine already makes everywhere else. More than half of what this role finds needs no canon at all — contract, state and consequence checks against the prose in front of it. Those could be asked without the context that is doubling, and the canon-dependent half asked separately with it. Two calls whose sizes do not follow the book's length, in place of one that does.

**And the closure is not where the growth is either.** Measured: CH-0004 declares 13 imports worth 16649 characters, CH-0009 declares 14 worth 32199. The transitive closure adds about 550 characters on top in both cases — under 2%. Same number of blocks, twice the text, because **the canon blocks themselves grow as chapters close and write back into them**. So neither trimming the closure nor capping the import count touches it.

**Still not built, and deliberately.** That is a change to what a gating role is asked, it doubles its calls, and it needs its own measurement of whether the split halves find what the whole one found. It is a session's work with a clear head, not a patch at four in the morning — and the measurement above is what makes it designable rather than a guess.

**A larger sample does not support the correlation this entry was written on, and it is the fifth prediction of that session the data refused.** Across 32 technical-editor calls on twelve chapters:

| chapter | calls | empty | context |
|---|---|---|---|
| CH-0006 | 1 | 0 | 33923 |
| CH-0009 | 8 | **5** | 35126 |
| CH-0010 | 2 | 1 | **48037** |
| CH-0011 | 2 | 0 | 39625 |
| CH-0012 | 2 | 0 | 33440 |

**CH-0010 carries the largest context of the book — 48037 characters — and answered in two calls**, while CH-0009 at 35126 came back empty five times in eight. The overall rate is 13 empty of 32, about 40%, and it is flat across chapter depth rather than climbing. So CH-0009 was an unlucky cluster on a role that fails four times in ten wherever it is asked, and the context growth, which is real, is not what decides.

**What that leaves.** The growth is still worth removing on its own terms — an input that follows the book's length is the shape this engine slices everywhere else, and it will matter at forty chapters even if it does not at twenty-six. But it is no longer a fix for the failure rate, and building it expecting one would be building the wrong thing. The failure looks like what the arms found for the translation critic: a role sitting near enough to its ceiling that variance decides, where the remedy that works is the bounded re-ask already shipped.

**Done when:** The role that gates every chapter is asked a question whose size does not depend on how far the book has got — undertaken as the design cleanup it is, and not as a cure for a rate it does not explain.


## A role that answers on the second ask is given a second ask 🔄

**Status: 🔄 In progress — 2026-09-03**

**The blocker on CH-0009, addressed where the evidence actually points.** The technical editor spends its reasoning ceiling about half the time on that chapter, and the three levers that could change the question have each been ruled out by measurement: the answer bound is in place, `medium` effort was tried and returned `reasoning 31998, output 0` at the first ask, and trimming the imports saves under 2% because the growth is inside the canon blocks rather than in how many are pulled.

What *is* established, from 18 calls of this role across the book, is that **re-asking works: 15 of 18 answer, and ATT-0260 and ATT-0262 answered differently on the identical envelope.** This is the role for which "the question is not made easier by being asked again" was already found to be false — that finding is a fortnight-old entry above, and it is what the stage retry was built on.

The stage gives the whole pass three attempts, and each of them costs a fresh call of *every* unfinished role. A role whose failure is variance should get its own bounded re-asks first, where a retry costs one call rather than a pass.

**Fix.** On a spent ceiling — and only on that, since a malformed answer already has its own remedy — the chapter review re-asks the failing role a bounded number of times before letting the failure reach the stage. The translation critic keeps its single ask, because for the critic re-asking was measured useless: 0 of 4 on four identical questions.

**Tasks:**
- [x] A chapter reviewer that spends its ceiling is re-asked within the pass, bounded by a constant
- [x] The bound is written beside the measurement that justifies it, and the roles it does not apply to say why
- [x] The re-asks are reported, so a role that needs three every time is visible rather than silently expensive
- [x] Test: a reviewer empty once and answering next produces its findings in one pass
- [x] Test: a reviewer empty every time still fails, and the stage still sees it
- [x] Test: the translation critic is unchanged, since re-asking was measured useless there
- [x] Suite green: 711 passed, 405 subtests (era 703). Reinstall, commit & push
- [~] CH-0009 closes and the run goes on

**Writing it put back a defect fixed three hours earlier, and the test caught it in one run.** The re-ask raises from inside the executor, which is *before* the block that settles the claims — so a reviewer empty on every ask left both claims at `running`, exactly the state that becomes `outcome_unknown` and stops the run for a person. The claims are now held from the moment they are taken rather than from the moment the answers come back. The lesson is not about this defect: a fix that moves where an exception is raised moves what is left unsettled behind it, and the two have to be looked at together.

**Done when:** A failure that a second ask fixes costs a second ask, not a pass.


## The reviser's budget counts the dispositions as well as the prose 🔄

**Status: 🔄 In progress — 2026-09-03**

**Measured on CH-0013, which stopped the run three times with `Expecting ',' delimiter: line 1 column 17602`.** The reviser's output budget is `min(8000, max(1000, target_words * 2))`, so a 2000-word chapter is given 4000 tokens. Its three answers came back at 5251, 5771 and 6069 output tokens, cut mid-string every time.

The formula sizes the answer as if it were the rewritten prose. It is not: it is the prose **plus one disposition per finding** — each carrying the finding id, the action, the evidence, what was lost and what it supersedes. On this chapter that is around twenty dispositions beside a 2000-word chapter, and the measured answers land where prose and dispositions together land: about 2700 tokens of chapter and roughly 3000 of bookkeeping.

So the budget is right about the half it counts and blind to the half it does not, and the failure it produces is a truncation the gate then refuses — three paid calls that could not have fitted.

**Fix.** Size it from both: the chapter as it does today, plus an allowance per finding it is being asked to disposition, still capped by the role's declared ceiling. The cap stays because a budget that grows without limit is how a role stops answering at all, which this engine has now measured four times.

**Tasks:**
- [x] The reviser's `max_output_tokens` counts the findings it must disposition, not only the chapter's target words
- [x] Both call sites, since the style-only pass has the same shape and the same blind spot
- [x] The allowance per finding is written beside the number that justifies it
- [x] Still capped by `ROLE_BUDGETS["reviser"]`, so it cannot grow without limit
- [x] Test: a chapter with many findings is given more room than the same chapter with few
- [x] Test: the budget never exceeds the role's declared ceiling
- [x] Suite green: 715 passed, 405 subtests (era 711). Reinstall, commit & push
- [~] CH-0013 closes

**Done when:** The reviser is given room for the answer it was asked for, not for half of it.


## What the engine calls an output budget never reaches the provider ⏸️

**Status: ⏸️ Proposed — 2026-09-03, measured**

**Found while diagnosing a credit wall, and it reframes most of what this session chased.** Every attempt after CH-0015 came back `HTTP 402: You requested up to 32000 tokens, but can only afford 25352`. The decisive row is `ATT-0390`: the **cold reader**, at `variant=low`, whose envelope declares `max_output_tokens: 2500` — and the request still asks the provider for **32000**.

So `max_output_tokens` is a number the engine writes into the payload and validates against `ROLE_BUDGETS`. It is read by the model as an instruction. **It is not a limit sent to the provider.** `run_opencode_role` invokes `opencode --pure debug agent <role>` and hands the envelope over stdin; what `max_tokens` reaches OpenRouter is OpenCode's business, and it is 32000 for every role at every effort.

**That is very likely the ceiling this session spent the night on.** The translation critic, the technical editor, the designer and the canon auditor all failed the same way — `output: 0` after exactly 32000 reasoning tokens — and lowering `reasoningEffort` never helped, on any of them. If the model is handed 32000 tokens to spend and no instruction it must obey, spending them on reasoning and having none left to write is not a mystery. Every remedy this session built works *around* that: bounding the answer asked for, re-asking when the dice fall badly, sizing the reviser's own budget. None of them could take the 32000 away, because the engine never had it to give.

**Probed once, and the obvious option is not the one.** `maxTokens: 3000` added to a model's `options` in the generated `opencode.json` changed nothing: the next attempts still requested 32000. The probe was free — a 402 names the amount requested — and the generated file was restored from the generator afterwards. Guessing further option names costs one probe each and is exactly the habit that produced five disproved predictions this session.

**What to establish before building anything:** whether OpenCode accepts a per-model or per-agent cap on the completion at all, and under what key. That is a question for its configuration surface, not for another guess. If it does, `sync_runtime` should write each role's declared budget there, and `max_output_tokens` stops being advice the model may ignore. If it does not, the entry closes with that recorded, and the remedies already shipped are the whole of what is available.

**Done when:** A role's declared output budget is the budget the provider enforces, or the plan records that it cannot be.


## A chapter that will not translate does not stop the sixteen behind it 🔄

**Status: 🔄 In progress — 2026-09-03**

**Found translating seventeen chapters.** CH-0005 came back twice carrying `i suoi occhi`, which the locale forbids — the possessive on a body part, one of the defects the Italian rules exist to catch. The gate refused it both times, correctly, and then the whole `translate run` stopped: `Translation blocked after one repair`. Thirteen chapters behind it were never attempted.

**The rule is right and the check is right.** Measured against the accepted chapters, the pattern matches only a possessive followed by a body part from a fixed list, and the one occurrence it finds in already-shipped prose — `i suoi occhi` — is a real defect that slipped in before the rule existed. This is not the over-broad matcher the preposition rule nearly became; it is a good check doing its job.

**What is wrong is the blast radius, and it is the same shape as five other defects this session.** One chapter that cannot pass takes the run with it. The engine's own principle says the opposite: what cannot be used is set aside and recorded, the run continues, and nobody is asked. The translation is the one pass still doing it the other way.

**And the translator gets one repair where every other producing role now gets more.** The review's repair is re-asked when validation refuses it, and that second ask has landed twice in production on exactly these locale rules — `stette` and `dovette`. The translator, which faces the same gate, is given one attempt and then blocks.

**Fix.** The translator gets the same second repair its sibling has, carrying the refusal. A chapter that still cannot pass is recorded beside the locale with what it violated, and the run moves to the next chapter. The locale is then incomplete, which publication already refuses — so the outcome is a named list of chapters needing attention rather than a stopped run or a silent gap.

**Tasks:**
- [x] The translator is re-asked twice on a refused translation, not once, carrying the reason each time
- [x] A chapter that still fails is recorded and skipped, and `translate run` continues with the next
- [x] The route reports which chapters were skipped and what they violated
- [x] Publication still refuses an incomplete locale, so a skipped chapter cannot ship silently
- [x] Test: one chapter that cannot pass does not stop the chapters after it
- [x] Test: a translation refused once and correct the second time is kept — already covered, and the existing test that asserted *one* repair now asserts the count the engine declares
- [x] Test: the skipped chapters are named in the route's output
- [x] Suite green: 716 passed, 405 subtests (era 715). Reinstall, commit & push
- [~] The seventeen chapters translate, or the ones that cannot are named

**One thing came out of building it that the plan did not say.** The last refused attempt was settled with `block=True`, which stops the run — so setting the chapter aside was not enough on its own: the chapter behind it still could not dispatch. It settles with `block=False` now. The lesson is the one from three hours earlier in another form: deciding to carry on is not the same as leaving the run in a state that can.

**Done when:** A locale rule stops a chapter, never a book.


## The catalogue can hold a batch model, and the critic uses one ❌

**Status: ❌ Withdrawn — 2026-09-04, the model cannot be reached from here**

**Priced against the critic's own measured profile, not against a list price.** The translation critic is 53 calls and **$4.50 of this project's $7.94** — 57% of the spend for 13% of the volume. What makes it expensive is the shape of its work: 14686 tokens of input, **27510 of reasoning** and 518 of output per call, and reasoning bills at the completion rate. So for this role the completion price is nearly the whole cost.

| model | per call | over 17 chapters |
|---|---|---|
| deepseek-v4-flash | $0.006 | $0.10 |
| gemini-3.1-flash-lite | $0.046 | $0.78 |
| **gemini-3.8-flash:batch** | **$0.058** | **$0.99** |
| deepseek-v4-pro *(current)* | $0.110 | $1.87 |
| gemini-3.8-flash | $0.116 | $1.97 |
| gemini-3.5-flash | $0.274 | $4.66 |

The batch variant is the same model at half price, and this role already takes seven minutes a call — batch latency is not a cost it can notice. Chosen over the flash models beneath it because the critic is the one role whose job is adversarial reading, and a cheaper reader that misses the calque costs more than it saves.

**What is honest to say about quality: nothing measured.** Prices and token counts here are measured; which model *catches* more as a critic is not, and a model's reputation is not a measurement. The experiment that would settle it is the one the three arms used — the same chapters read by two candidates, counting the real findings one finds and the other misses.

**The catalogue is the gate.** `_role_pin` refuses a model it does not configure, deliberately, so this is not a config line but a catalogue entry: provider pin, effort ladder, and whatever the model actually accepts.

**Tasks:**
- [ ] `google/gemini-3.8-flash:batch` joins the catalogue with its provider pin and effort ladder
- [ ] Its ladder matches what the model reports it supports, rather than being copied from a sibling
- [ ] Test: the new model resolves as a critic pin and is refused as the translator's own model like any other
- [x] Suite green: 720 passed, 405 subtests (era 716). Reinstall, commit & push
- [ ] Pinned on landfall once the running translation finishes, so the change does not land mid-chapter
- [ ] Measured after a few chapters: cost per critic call against the $0.110 it is replacing

**Done when:** The critic reads at half the price of the model it replaced, and the catalogue can hold a batch variant.

**Withdrawn, and the reason is a date.** The pin was applied and every call died on `Model not found: openrouter/google/gemini-3.8-flash` — with and without the `:batch` suffix, so the suffix was never the problem. The installed OpenCode binary was compiled **2026-08-25** and `google/gemini-3.8-flash` was released **2026-09-02**: the model postdates the build. `~/.cache/opencode/models.json` refreshes on its own and does carry the model, but the binary validates against a list of its own, and writing the model into the project's `opencode.json` does not change that.

**Three diagnoses were given and two were wrong** before the dates were compared: that the `:batch` suffix collided with OpenCode's model addressing, and that OpenCode's catalogue did not have the model at all. What settles it is `stat` on the binary against `release_date` in the catalogue — two facts that cost nothing and were reached last.

**What it cost.** Three chapters — CH-0010, CH-0011, CH-0012 — were translated while the critic answered nothing, so they are on disk without ever being read back. `translate review` is the route that reaches them.

**Both entries are removed from the catalogue rather than left unused.** A model the engine offers and OpenCode cannot resolve is a trap for whoever picks it next, and the engine's catalogue is a promise that a pin will work.

**What would make it available:** `opencode upgrade`. Not done here — another harness runs `opencode serve` on this machine and the binary is not this project's to replace.


## A draft is published in the book's order, not in the order it was translated ✅

**Status: ✅ Done — 2026-09-04**

**Found publishing seventeen translated chapters.** `Draft publication refused: completed chapters out of order`. The locale's `completed_chapters` reads `… CH-0006, CH-0008, CH-0009, CH-0011, CH-0007, CH-0010, CH-0012 …` — the order in which chapters *finished*, not the order they are read in. CH-0007 and CH-0010 finished late because they were refused once and retried, which is exactly what the set-aside-and-carry-on fix shipped yesterday is for.

So the gate refuses a state its sibling feature now produces routinely. The list is a completion log; the gate reads it as a running order.

**What the gate is actually for is still worth having.** A draft must not publish a chapter the book does not have, and must not silently reorder the reader's experience. Both are answered by the set of chapters and the outline, not by the sequence of a log: **what matters is that every completed chapter is a real one, and that the export walks them in the outline's order.**

**Fix.** Keep refusing a chapter the book does not have. Drop the ordering test on the log, and sort the export by the outline instead — which is where a chapter's order actually lives.

**Tasks:**
- [x] The unknown-chapter check stays exactly as it is
- [x] The order test on `completed_chapters` is removed, since the log records when a chapter finished and not where it sits
- [x] The export walks the chapters in the outline's order regardless of how the log is arranged
- [x] Test: a locale whose log is out of order publishes, and its chapters come out in the book's order
- [x] Test: a completed chapter the book does not have is still refused
- [x] Suite green: 720 passed, 405 subtests (era 716). Reinstall, commit & push
- [x] Landfall's Italian publishes with all seventeen chapters in order — verified in the epub's spine, `chapter-0001` through `chapter-0017`, and the four files are on Drive at their existing ids

**Done when:** A chapter that was retried reads in its own place, and the publication gate stops rejecting the retry it asked for.


## A translation is read by someone who cannot see the source 🔄

**Status: 🔄 In progress — 2026-09-04**

**Found by giving landfall's first Italian chapter to readers who knew nothing about it.** Nine broken constructions in two pages, every one a word-for-word calque: `go count your chalk` → «vai a contare il tuo gesso», an English idiom rendered literally and meaning nothing; `stood the last dark` → «era di guardia all'ultimo buio»; `the rolls carried the watch, and the watch carried no Binta` → «i registri riportavano la guardia, e la guardia non riportava nessuna Binta», where the English pun on *carry* holds and the Italian verb cannot; `She stood it the way the wall stood it` → «La montava come la montava il muro», a wall mounting a watch, which is not a sentence in Italian; `a faint blue smolder` → «un ardore azzurro fioco», where *ardore* means passion.

**The rules to catch these already exist and were read.** The locale style has a section headed *Contro il calco* saying an English idiom is rendered with its Italian equivalent and never word by word, and even *«a sentence that would not be said in Italian is rewritten, even when every single word is correct»*. The critic was given that style and approved the chapter anyway.

**The reason is structural, and it is the whole point of this entry.** The critic reads the source and the translation side by side. With the English in front of it, «vai a contare il tuo gesso» *parses* — you can see where it came from. **The defect exists only for a reader who does not have the original**, and no role in this pipeline is that reader.

**Fix.** A `locale-reader` role that is given the translated chapter and the locale style **and nothing else** — no source, no glossary, no contract. It answers as a reader: what it did not understand, which sentences it had to read twice, which words are not words in this language. Its findings join the critic's and go to the same repair.

**What it must not be given, and why that is the design.** The source, because seeing it makes a calque legible. The glossary, because a term that is unreadable in the target language must be reported as unreadable, not excused as agreed. This role is the only one in the engine whose value comes from what it is denied.

**Tasks:**
- [ ] `locale-reader` role, prompt and budget: it receives the translated chapter and the locale style, and refuses to be given the source
- [x] Its capsule is asserted to carry no `source_markdown` and no glossary, so the denial cannot erode
- [x] It answers with what stopped it, quoting the sentence, and never proposes a rendering — it is a reader, not a translator
- [x] Its findings merge with the critic's for the repair, marked by origin so a rate can be measured per source
- [x] It runs inside `translate` and in `translate review`, so chapters already translated can be reached
- [x] Test: a chapter carrying a literal calque that the bilingual critic passes is caught by the monolingual reader
- [x] Test: the role's capsule is refused if it contains the source
- [~] Measured on landfall's CH-0001 against the nine constructions the human readers found
- [x] Suite green: 726 passed, 405 subtests (era 720). Reinstall, commit & push

**Done when:** A sentence that is not a sentence in the target language is found by someone who could not see where it came from.

## The prose is not built out of closing lines 🔄

**Status: 🔄 In progress — 2026-09-04**

**Measured by a reader who had never seen the book.** *«Almost every paragraph ends on a closing line with a twist in it… Coming at a rate of four or five a page, I started hearing the rhythm before the sentence arrived, and by the middle of the chapter I was noticing the author rather than the harbour.»* The Italian reader, independently: *«frasi mozzate a effetto, una parola sola per riga. All'inizio dà atmosfera, dopo venti volte è un tic.»*

Both named the same two moments where the writing improves, and both are the moments it stops doing this: the pen writing everything except her name, and a thumb finding a scar without looking.

**The style preset has ten rules and none of them forbids it.** Rule 10 — *End a scene with the situation changed* — arguably invites it. So the writer produces closing lines because nothing has ever told it not to, the four style advisors do not flag them because they carry the same preset, and the reviser has no rule to apply.

**Two more things the same reader caught that no role is asked to look for.** Eight invented terms in the first three pages before the reader is given a reason to care — *«I was still doing vocabulary maintenance when the barge started dying»*. And register breaks: `four-meter` and `sodium-dim` in a chapter of fathoms, tallow and oilcloth — *«hang on, what century is this»*.

**Fix.** Three rules added to `plain-concrete`, which every writing and judging role already reads, so one edit reaches the writer, the reviser and the four advisors at once.

**Tasks:**
- [x] A rule against the sentence built for effect: the test is to delete it, and if nothing is lost it was ornament
- [x] A rule on coinage: a new term earns its place when the scene needs it, and an opening spends its reader's patience before it has bought any
- [x] A rule on register: the vocabulary of measurement and material belongs to one world, and a modern term inside an old one stops the reader dead
- [x] ~~The same three reach `neutral` where they apply~~ — **wrong, and a test said so.** `neutral` exists to add nothing at all; that is its contract and `test_the_neutral_preset_adds_nothing` holds it. A craft rule is still an imposition, and a project that asked for no style must get none
- [x] Test: the presets carry the rules, and the role prompts that compose them still build
- [x] Suite green: 726 passed, 405 subtests (era 720). Reinstall, commit & push
- [~] CH-0001 rewritten in English against the new preset, and read again by a reader who has not seen it

**Done when:** A reader notices the harbour and not the author.
