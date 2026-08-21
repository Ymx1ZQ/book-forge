# Export EPUB and PDF editions

Use this route only for `export`.

Run `export BOOK --lang TAG --format epub|pdf|all`. Export makes no model calls.
It accepts only a complete, current, single-language source or requested locale
workspace and refuses missing chapters, stale prose, pending boundary audits,
mixed locale metadata, or stale source artifacts.

EPUB is assembled with deterministic member order, timestamps, identifiers,
navigation, metadata, and validation. PDF uses the pinned WeasyPrint lock and
hash-verified Noto Serif fonts, then validates A5 geometry, text order, and
embedded Unicode fonts. Both formats write an input/toolchain manifest and
register edition dependencies in the artifact DAG.

Report output paths and SHA-256 values. If a font or renderer pin drifts, stop
and report the prerequisite; never fall back to host fonts or an unpinned tool.
