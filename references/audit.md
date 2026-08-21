# Audit continuity

Use this route only for `audit`.

Choose one optional scope: book, relation, or continuity. The helper derives
bounded jobs from explicit relations, consecutive appearances, overlapping
events, boundaries, obligations, and disclosed consequences; it never performs
all-pairs manuscript comparison.

- Keep `--max-jobs` between 1 and 8.
- More than 20 candidates requires the user's explicit override, which is
  recorded in machine state.
- Each job uses one canon-auditor call and at most one contract-repair call.
- Findings require a stable evidence location and SHA-256. The helper schedules
  repair tasks but never rewrites prose automatically.

Report blocking and warning findings first, then notes and scheduled repairs.
