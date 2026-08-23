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

### Input budget

The canon-auditor envelope is bounded by `audit.input_budget` in `book-forge.yaml` (default `32000`). The helper enforces this as a hard-fail: when the estimated input exceeds the budget it raises `ContextOverflowError` with message `estimated_input X > budget Y` (e.g. `estimated_input 19800 > budget 16000` or `estimated_input 33000 > budget 32000`). Raise the knob or reduce context and retry. Example:

```yaml
audit:
  input_budget: 32000
```

Validation is strict: a non-integer `audit.input_budget` fails closed with `audit.input_budget must be an integer`. `max_output_tokens` budgets are unchanged by this knob.

