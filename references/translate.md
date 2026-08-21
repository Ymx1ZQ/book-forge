# Translate a book by locale

Use this route only when the user explicitly requests a target locale.

1. `translate add BOOK TAG` creates the isolated locale workspace and makes no
   model call. Never create it implicitly.
2. `translate next BOOK TAG` translates one next chapter; `translate run` walks
   the current source chapters serially.
3. `translate status` is zero-model and reports completion/currentness.

Each chapter receives source prose, its contract, explicit canon, prior
translated boundary, locale style, glossary, and localized metadata. The normal
path is one low-reasoning translator call; validation permits at most one repair.
Source prose remains authoritative. If source, canon, glossary, style, metadata,
or a prior boundary changes, preserve existing translated prose and report the
minimal stale suffix instead of silently regenerating it.
