# Chorus — ensemble advisory before writing

Use this route only for `chorus` and for the default chorus step inside `design`.

- Chorus is **default-on** (`chorus.enabled:true` in `book-forge.yaml`). Every `design universe` and `design book` runs it **twice**: **pre-design** (before the designer, same full-canon+worldbuilding+brief envelope) and **post-design** (after the auditor, on the designer product). Opt-out with `--no-chorus` (skips both) or `--no-post-chorus` (skips only post-design), or set `chorus.enabled:false` / `chorus.post_enabled:false`.
- With `--chorus-models <csv>` the caller overrides the catalog for this run (comma-separated `openrouter/...` IDs). The helper prints the confirmed model list before dispatching.
- Chorus is **advisory-only**: it never writes canon. Each advisor (`advisor-*:7`) receives via `build_envelope` and returns `{"findings":[],"suggestions":[]}`. **Pre-design** envelope = full canon + `worldbuilding.md` + brief (same as designer). **Post-design** envelope = designer product (universe: kernel/eras/events/places/factions/characters/themes; book: premise/arc/chapters with beats/POV/plants/reveals per chapter, entry/exit, relations/obligations) at per-chapter granularity with evidence locations `CH-XXXX#beats/#pov` validated fail-closed. Results are written to `.book-forge/chorus/<scope>/<ts>/` (pre) and `.book-forge/chorus/<scope>/<ts>-post/` (post) plus `chorus-report.md` / `chorus-report-post.md`. Locations validated via `_resolve_evidence_target` fail-closed (M29/M30); hashes recomputed by control plane.
- The helper dispatch respects the 2-concurrent limit (4 waves for 8 advisors) and records provider telemetry. Chorus calls have a separate budget per pass (8 + 1 synthesizer) and do not count against `design_call_budget`. Pre+post doubles cost — budget with that in mind.
- Post-design chorus **blocks** `design`/`run` on `blocking|warning` (advisory for `note` only); pre-design remains advisory-only. `chorus status` is zero-model: synthesis state, pending/clean/stale. `chorus synthesize` runs the `chorus-synthesizer` (`pro/max`) to deduplicate/rank and propose patches (`chorus-synthesis.json` / `chorus-synthesis-post.json`). `chorus apply` is manual — never auto-rewrites canon.
- Chorus is reusable: any future pre-`run` phase can call `run_chorus(scope,envelope)` or `run_chorus_post_design(scope,product)` with its own scope/envelope.

Use `chorus run` for a standalone advisory pass (worldbuilding/brief) without designing; add `--post-design` to re-read the last promoter product instead of the brief. Use `design --with-chorus-context` to feed the latest report back into the designer.

Do not use chorus inside `run`/`translate`/`export`.
