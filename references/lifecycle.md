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

## Restarting a book

`reset` is zero-model and destructive. It returns a book to its pre-writing state without leaving the plan claiming work whose output is gone: a hand-deleted manuscript leaves every `DRAFT-` task reporting `succeeded`, so the writer is never re-run and the restart silently does nothing.

- `--scope prose` removes the manuscript chapters, the translated chapters, the reviews, the pivotal-variant work, the cold-read state and the editions; drops every chapter-scoped task; reseeds the book state and each translation workspace; drops the artifact rows whose files are gone and rebuilds the derived views.
- `--scope design` does all of that and additionally reseeds the outline, the chapter contracts, `design.md`, `reader-state.md` and the design audit, and drops the book's `DESIGN-` and `AUDIT-` tasks. Use it when the beats are what needs rewriting, not just the prose.
- Neither scope touches the universe canon, `book.yaml`, `book-brief.json`, `continuity.yaml` or the locale aids — glossary, style guide and metadata. Those are input, not output.
- `--yes` is required. Without it the command refuses and changes nothing.
- The receipt names every removed path, dropped task and dropped artifact. Report it rather than summarizing it.

## When the driver was killed

A driver killed mid-call — by the OOM killer, by a closed terminal, by `kill` — leaves the run marked `running`, its task `running`, and its attempt holding a lease that then expires. If the provider had already accepted that call, its outcome is unknown: it may have completed and been paid for.

`resume --resolve-unknown TASK:retry|abandon` is the whole recovery. It settles the stale claim first, so it works whether or not anything has converted the attempt yet; there is no pause step to find. `retry` accepts that the accepted call may be paid for twice, `abandon` gives the task up and blocks whatever depended on it. That decision is the only part a person owns.

`pause --emergency` is for stopping a *live* run immediately and is not part of this. A run that is genuinely running, with a lease that has not expired, still refuses to resume — there is nothing waiting on a decision.

