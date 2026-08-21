# Manage the universe catalog

Use this route for migrations, continuities, books, relations, and collections.

- Run exactly the requested selector through the deterministic helper.
- Discover stable IDs with `status` or the small authored registries; do not
  infer IDs from titles.
- A book always belongs to one continuity. Collections are optional orderings,
  not canon ownership.
- Use only supported relation types: `sequel_of`, `prequel_of`,
  `adaptation_of`, `alternate_of`, `parallel_to`, and `crossover`.
- Cross-continuity relations require explicit imported canon block IDs.
- Put every crossover promise or carry-forward requirement in `--obligation`.
- Run migration `check` or `dry-run` before `apply`; use `rollback` only when
  the user asks to reverse the latest completed migration.

Never hand-edit IDs, relation hashes, collection membership, or migration
journals.
