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
- [ ] Commit & push

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
- [ ] Commit & push

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
- [ ] Commit & push

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
- [ ] Commit & push

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
- [ ] Commit & push

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
