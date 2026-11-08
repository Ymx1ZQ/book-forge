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
- `--scope translation --locale <loc>` removes only what that locale derived: its translated chapters, its completed-chapter markers and boundary hashes, and its editions. The manuscript it was translated from, the contracts, the design and every other locale survive. Use it when the locale style, the glossary or `roles.translator` has changed and the existing translation was made under the old decision — `translate run` only translates a chapter whose file is absent, so without this the change never reaches the prose. It requires `--locale` and refuses without one, naming the locales the book has.
- No scope touches the universe canon, `book.yaml`, `book-brief.json`, `continuity.yaml` or the locale aids — glossary, style guide and metadata. Those are input, not output.
- `--yes` is required. Without it the command refuses and changes nothing.
- The receipt names every removed path, dropped task and dropped artifact. Report it rather than summarizing it.

## When the driver was killed

A driver killed mid-call — by the OOM killer, by a closed terminal, by `kill` — leaves the run marked `running`, its task `running`, and its attempt holding a lease that then expires. If the provider had already accepted that call, its outcome is unknown: it may have completed and been paid for.

`resume --resolve-unknown TASK:retry|abandon` is the whole recovery. It settles the stale claim first, so it works whether or not anything has converted the attempt yet; there is no pause step to find. `retry` accepts that the accepted call may be paid for twice, `abandon` gives the task up and blocks whatever depended on it. That decision is the only part a person owns.

`pause --emergency` is for stopping a *live* run immediately and is not part of this. A run that is genuinely running, with a lease that has not expired, still refuses to resume — there is nothing waiting on a decision.


## When a source chapter was fixed by hand

The artifact registry keeps the hash of each source chapter as the pipeline last promoted it. A chapter corrected outside the pipeline makes every later `translate run` stop with `Derived artifact was edited directly: <id>`.

`adopt <artifact-id> --reason TEXT` accepts the file as it now is: it re-registers the current hash, appends the old hash, the new hash and the reason to `.book-forge/adopted.jsonl`, and prints the artifacts that now read as stale. The translations of that chapter are among them: confirm each as still valid or translate it again. `adopt <artifact-id> --keep-translations --reason TEXT` is for a wording-only fix: the dependents stay current and their names are written to the journal row as `kept_dependents`. Use it only when the translations are still correct for the new text. Only a `source-chapter` or a `translation-chapter` can be adopted; any other derived file edited by hand is still refused.

`translate next` and `translate run` hold the same per-book lock as `advance`. A second process on the same book exits at once and names the pid already driving it; a lock left by a dead process is taken over.
