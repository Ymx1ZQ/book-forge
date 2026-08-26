# Inspect, pause, and resume work

Use this route for `status`, `pause`, and `resume`.

- `status` is zero-model. Summarize task/run state, transaction recovery,
  accepted calls, tokens, cost, retries, ambiguity, stale causes, and budget
  violations from immutable receipts.
- Use ordinary `pause` to drain accepted work safely. Use `--emergency` only
  when the user requests an immediate stop; accepted unfinished calls become
  `outcome_unknown`.
- Resume only with an explicit decision for every unknown task:
  `--resolve-unknown TASK:retry` or `TASK:abandon`.
- A task blocked by a failed contract validation requires an explicit
  `--resolve-blocked TASK:retry` before the run resumes; `abandon` is not
  offered for these tasks.
- A retry acknowledges possible duplicate provider cost. Abandon blocks
  dependent tasks. Explain that tradeoff before executing the resolution.
- Use `status --repair-view` only to rebuild the human plan from verified
  machine state, never to bless an edited canonical plan.
- `artifacts backfill` is zero-model. It registers artifact rows for work that
  was promoted before the registry tracked it, and completes rows an earlier
  call site recorded without their dependencies. Run it when a translation or
  publication fails on a dangling dependency, or after upgrading a project whose
  chapters predate the registry. It is idempotent and reports what it changed;
  it never rewrites a hash, which is `reconcile`'s job.

Every command first reconciles incomplete promotion journals. Session memory is
never completion evidence.
