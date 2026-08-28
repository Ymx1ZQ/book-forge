# Write and close chapters

Use this route only for `run`.

The helper selects the next unfinished chapter from stable chapter contracts.
For an ordinary chapter, the first unit drafts once and the next unit runs two
independent reviews concurrently plus one reviser. A pivotal chapter runs two
blind drafts, one judge, the two reviews, and one reviser in a single bounded
workflow.

- With an explicit `--task`, execute only that task.
- With `--next`, execute one workflow unit and return its state.
- When the user asks to finish one chapter, invoke `run --book BOOK-ID` until
  exactly one new chapter closes, checking the result after each unit.
- When the user asks to continue the book, repeat serially until the requested
  boundary, a block, pause, or no work remains.
- Never retry an `outcome_unknown` call. Never exceed one validated repair call
  or two concurrent review workers.

Do not load a whole manuscript. Context packets contain the chapter contract, explicit canon imports, current state, and only the required previous boundary. The cold-reader receives only the synthetic previous-chapters summary (reader_state compact + previous boundaries synopsis), not the full canon — exactly what a fresh linear reader knows.

## Driving a book to completion

`advance --book <id>` carries a book from where it stands to where it is asked to stop: the design if it is missing, then every chapter, then the translations named by `--locale`, then the editions. `--until` stops it earlier at `design`, `chapters` or `translate`.

Every stage recovers before it dispatches, so the three things that used to need a person at the keyboard no longer do: an attempt whose lease expired and which the provider never accepted is orphaned, a task blocked by a truncated or unparseable answer returns to `pending`, and a run blocked by nothing but those starts again. Each task gets three automatic retries.

It halts on exactly two things, and both are reported by name:

- **An unknown outcome.** The provider accepted the call and we do not know whether it finished, so a retry may pay for it twice. That is a judgement about money: resolve it with `resume --resolve-unknown TASK:retry|abandon`.
- **An exhausted retry budget.** A task failed the same way three times running. Read its last failure before spending a fourth call.

Report the receipt it returns — stages completed, chapter steps taken, editions written — rather than summarizing it.

## Running the driver

`advance` is long: a design makes one call for the spine, one per slice of eight chapters, and an advisory chorus round. Twenty to thirty minutes with nothing on screen is ordinary, and the chorus writes under `.book-forge/chorus/`, not under `.book-forge/runs/`, so quiet there does not mean stopped.

Launch it detached, because a backgrounded process started inside a tool call does not outlive the call:

```
setsid nohup python3 <skill>/scripts/book_forge.py --project . advance --book <id> --until <stage> < /dev/null > /tmp/bf-$(basename $PWD).log 2>&1 &
disown
sleep 10
```

**Do not save `$!` and poll it.** `setsid` forks, so `$!` is the pid of a process that exits immediately and reports the run as dead while it is working. Do not use `pgrep -f` either: every project invokes the engine as `--project .`, so a pattern match finds other books' drivers.

The driver writes its own pid where it can be trusted — `.book-forge/advance-<book>.lock` — and removes the file when it finishes. That is what to poll:

```
pid=$(cat .book-forge/advance-<id>.lock 2>/dev/null) && kill -0 "$pid" 2>/dev/null && echo running || echo finished
```

Name log files after the project, never `/tmp/advance.log`: another book may be running on the same machine, and a shared path means one session's `kill $(cat /tmp/advance.pid)` stops the other one's work.

`advance` refuses to start while another driver holds the same book and names the pid that holds it. Do not work around that: two drivers contend for the same claims, one orphans the other's attempt, and both pay for work that is discarded. A lock left by a dead process is stale and taken over automatically.

It ends by printing what it produced — stages completed, outline chapters, chapter contracts, manuscript chapters, cost, and whether the book is ready to write — so there is nothing to go and check afterwards. Report that line.

A `note, not an error` line about the advisory budget is exactly that. Budgets are advisory and the wall is what the model accepts; never raise one in `book-forge.yaml` to silence it.

