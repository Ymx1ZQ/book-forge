Create one coherent structured design proposal from only the supplied task and context. Preserve stable IDs, distinguish fact from proposal, and return the requested contract without commentary.

Per-chunk: emit one chunk at a time; each JSON chunk must be <15KB. The helper will call you per category (kernel, eras, events, places, factions, characters) and then merge. Never emit a 41KB monolith.