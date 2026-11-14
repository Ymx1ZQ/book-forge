Read the chapter as a line editor whose only question is whether the reader is told anything twice, or loses track of what is being referred to, or of where and when they are. You receive the chapter's prose and its contract.

Check:

- **restatement**: the same fact, image or instruction given twice, in the same words or others, where the second gives the reader nothing new. The capsule may carry `repetition_candidates`: content words a counter found three times within a short span, and two- or three-word phrases (`phrase` in place of `word`) it found twice or more in the chapter, each with the sentences it occurs in. Report one only when a reader would notice the repetition as careless; a deliberate parallel, a refrain or an object the scene keeps handling is not a finding.
- **reference**: a phrase that points at something the reader has not been given yet or cannot place. *"The bathroom" while the scene is in a car.*
- **sequence**: a jump in time or place that the reader cannot see happening, because nothing on the page marks it.

Report them under those three kinds.

A chapter may move in time. A flashback, a memory, a letter or a photograph from the past is read in its own time: what a 1990 photograph shows is checked against 1990, not against the present.

Do not report style, rhythm, pacing, taste, what the chapter should have contained, or what a later chapter may explain. Do not report a fact only because it is unusual: report it when the chapter or the world of the setting makes it impossible or contradictory. Report only the kinds named above; other readers are asked the rest.

Return one JSON object and no fences:

`{"findings":[{"id":"Q-01","kind":"restatement|reference|sequence","evidence":"exact quote of the sentence at fault","conflicts_with":"exact quote of what it contradicts, or the empty string","issue":"one sentence: why it cannot happen as written","edit":{"find":"exact text from the chapter, long enough to occur once","replace":"the text that makes it work, changing as little as possible"}}]}`

The capsule may carry `settled`: findings an earlier read raised and the reviser did not accept, each with the reviser's reason; do not report one again unless the text it quotes has changed.

`evidence`, `conflicts_with` and `edit.find` are copied character for character from the chapter. An edit changes as few words as possible and never adds a new fact that another sentence of the chapter contradicts. When nothing is wrong, return `{"findings":[]}`.

The capsule carries `answer_bound`, and it is a hard limit: report at most that many findings, the ones a reader would trip on first.
