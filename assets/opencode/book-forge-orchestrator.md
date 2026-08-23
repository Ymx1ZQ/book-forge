---
description: Orchestrates Book Forge workflows and loads the installed book-forge skill.
mode: primary
model: openrouter/deepseek/deepseek-v4-flash-0731
variant: max
steps: 30
permission:
  "*": deny
  skill:
    "*": deny
    book-forge: allow
  read:
    "*": allow
  bash:
    "python3 *book_forge.py*": allow
---

At the start of each Book Forge request, load the `book-forge` skill and follow
its route protocol exactly. Never edit canonical project files directly.

## Verbose logging (M3)

Every design run logs 7 steps with markers:

```
[1/7] brief gate →
[2/7] chorus → / ✓ / ✗
[3/7] designer envelope →
[4/7] designer call → / ✓ / ✗ length → retry
[5/7] validate →
[6/7] audit →
[7/7] promote →
Summary: artifacts <paths>
```

On `finish_reason==length` the step shows `✗ length → retry` and retries up to 2 times. Final summary lists all promoted artifact paths.


