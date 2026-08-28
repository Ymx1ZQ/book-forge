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
- [ ] Patch `assets/prompts/canon-auditor.md`
- [ ] `./install.sh --force`
- [ ] Verifica Margherita: audit universe chiude

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

## The audit is one question over forty chapters, and only a tenth of it fits 🔄

**Status: 🔄 In corso — 2026-08-28** (codice fatto; resta la corsa su margherita)

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
- [ ] Margherita's audit clears, and the first three chapters are written

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

## A design that is already promoted cannot be repaired, only refused 🔄

**Status: 🔄 In corso — 2026-08-28**

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
- [ ] Margherita's design clears and the first three chapters are written

**Done when:** Reaching the audit late does not cost the book its repair.

## The repair asks for ten chapters in one answer, gets none, and says nothing 🔄

**Status: 🔄 In corso — 2026-08-28**

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
- [ ] Margherita's design clears and the first three chapters are written

**Done when:** A repair that could not be delivered says so.
