# Compare writing models on one chapter

Use this route only for `bakeoff`.

`bakeoff <book> <chapter> --models a,b,c` drafts the same chapter once per model and promotes none of them. Every candidate is handed the identical capsule — the same contract, the same imports, the same book state — and is pinned to `high`, the one effort step every catalogue model offers. What varies is the model and nothing else.

- Name models in full (`openrouter/z-ai/glm-5.3-flash`) or by their short id (`glm-5.3-flash`). A model the catalogue does not configure is refused, with the known models listed.
- At least two models, or it is not a comparison.
- A model outside the project's chorus is added to the generated runtime before the call, so it resolves instead of dying at the agent probe.

Drafts land in `books/<book>/work/<chapter>/bakeoff/<slug>/draft.md`, beside the beat map and the consequences each candidate disclosed. `books/<book>/work/<chapter>/bakeoff/bakeoff.json` records, per candidate: model, variant, word count against the target, cost, wall time, and state.

The route never writes `work/<chapter>/draft.md`, never runs the review stack, and never closes the chapter. A candidate whose answer fails writer validation is recorded as `unusable` with the reason; the other drafts still land.

### Keeping the winner

Reading the drafts and choosing is a person's job. Applying the choice is one edit to `book-forge.yaml`:

```yaml
roles:
  writer:
    model: openrouter/z-ai/glm-5.3-flash
    variant: high
```

Then `runtime sync`. Name the variant as well as the model: an override moves only what it names, so a writer pinned to a new model without an effort keeps the effort it had, which is not the one the bake-off drafts were read at. A variant the target model does not offer is refused, with that model's ladder in the message.

Every other role stays where it was. The design, the canon audit and the reviser keep the project's pinned model unless they are named too.
