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
