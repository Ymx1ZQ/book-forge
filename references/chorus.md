# Chorus — ensemble advisory before writing

Use this route only for `chorus` and for the default chorus step inside `design`.

- Chorus is **default-on** (`chorus.enabled:true` in `book-forge.yaml`). Every `design universe` and `design book` runs it before the designer unless the user passes `--no-chorus` or the project sets `chorus.enabled:false`.
- With `--chorus-models <csv>` the caller overrides the catalog for this run (comma-separated `openrouter/...` IDs). The helper prints the confirmed model list before dispatching.
- Chorus is **advisory-only**: it never writes canon. Each advisor (`advisor-*:7`) receives the same envelope as the designer (full canon + `worldbuilding.md` + brief) via `build_envelope` and returns `{"findings":[],"suggestions":[]}`. Results are written to `.book-forge/chorus/<scope>/<ts>/` and a human `chorus-report.md`. Locations are validated via `_resolve_evidence_target` fail-closed (M29/M30); hashes are recomputed by the control plane.
- The helper dispatch respects the 2-concurrent limit (3-4 waves for 7 advisors) and records provider telemetry. Chorus calls have a separate budget (7 + 1 synthesizer) and do not count against `design_call_budget`.
- `chorus status` is zero-model: synthesis state, pending/clean/stale. `chorus synthesize` runs the `chorus-synthesizer` (`pro/max`) to deduplicate/rank and propose patches (`chorus-synthesis.json`). `chorus apply` is manual — never auto-rewrites canon.
- Chorus is reusable: any future pre-`run` phase can call `run_chorus(scope,envelope)` with its own scope/envelope.

Do not use chorus inside `run`/`translate`/`export`.
