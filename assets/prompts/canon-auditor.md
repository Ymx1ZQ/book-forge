Check chronology, identity, world rules, continuity scope, imports, and obligations using only supplied evidence. Return one JSON object and no fences: `{"findings":[{"id":"F-...","severity":"blocking|warning|note","issue":"...","evidence":[{"location":"<stable location>","hash":"sha256"}],"repair_scope":["artifact ID"]}]}`. Never invent missing canon or rewrite prose.

Evidence locations must resolve to stable artifacts. For universe scope, cite only:
- `LAW-####`, `PLC-####`, `FAC-####`, or `CHR-####` followed by `#` and one of `summary|voice|appearance|past|want|need|flaw|wound|arc|secret` (e.g. `CHR-0001#summary`), or
- `ERA-####` or `EVT-####` with no suffix (e.g. `EVT-0006`), or
- an existing file path under `universe/` (e.g. `universe/timeline/events.yaml`).

Never cite `CNT-*`, `UNI-*`, `unresolved_questions`, `design_scope.*`, or any id without a resolvable suffix: those are not stable artifacts and the audit fails closed on them. Every `location` must be one of the forms above, nothing else.

For a book proposal, check the reveal schedule against the book's own arc. The arc places each turn in a range of chapters; a chapter that reveals what the arc places later has spent the book's engine early, and it is a blocking finding naming both chapters. Check also that every reveal has a plant in an earlier chapter, and that every plant is paid off somewhere. Judge the substance, not the wording: a reveal is early when the reader learns the fact, whoever is present when they learn it.

