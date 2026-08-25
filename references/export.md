# Export EPUB and PDF editions

Use this route only for `export`.

Run `export BOOK --lang TAG --format epub|pdf|all` for a final edition, or add `--draft` for a partial review export. Export makes no model calls.

- Final (`--draft` not set): accepts only a complete, current, single-language source or requested locale workspace and refuses missing chapters, stale prose, pending boundary audits, mixed locale metadata, or stale source artifacts. Writes `dist/<book>/<lang>/<book>.epub` and `<book>.pdf`, validates, writes manifest, and registers the edition in the artifact DAG.
- Draft (`--draft`): exports whatever chapters are currently closed/completed for review, even if the book is incomplete. Requires at least one closed/completed chapter and matching markdown files on disk, but does not require all chapters, currentness, or boundary audit. Writes `dist/<book>/<lang>/<book>.draft.epub` and `<book>.draft.pdf` with `manifest.draft=true`, does not register as a final edition artifact. Use for manual feedback, proofreading, or sharing work-in-progress.

EPUB is assembled with deterministic member order, timestamps, identifiers, navigation, metadata, and validation. PDF uses the pinned WeasyPrint lock and hash-verified Noto Serif fonts, then validates A5 geometry, text order, and embedded Unicode fonts. Both formats write an input/toolchain manifest and register edition dependencies in the artifact DAG (draft exports skip DAG registration).

Report output paths and SHA-256 values. If a font or renderer pin drifts, stop and report the prerequisite; never fall back to host fonts or an unpinned tool.
