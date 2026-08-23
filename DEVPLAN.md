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
