Read the chapter once, in order, as a first-time reader who remembers everything already said and stops where they would hesitate, reread or ask a question the text never answers. You receive the chapter's prose and its contract. A stop need not be impossible. Report each unresolved stop with its sentence.

Kinds of stop:

- **an action on something whose state an earlier sentence changed**: opened, taken, put down. *She tips dough from the bowl she scraped clean a minute ago.* (sequence)
- **a sense that notices too early or late**. *The ward hears the night nurse's footsteps only after she reaches the bed.* (timeline)
- **two claims of "first", "opened with", "only" or "last" about one thing**. *The first net comes up empty, and the first net is hauled again at dusk.* (contradiction)
- **where someone lives, sleeps or is headed, and since when**, unclear or pulling two ways. *The warden has lived in the refuge since spring, then walks up from where he sleeps in the valley.* (contradiction)
- **spans of time that do not fit together**. *The depot opens at five, the first driver clocks in at nine, yet buses are already out.* (timeline)
- **the same fact or image given twice in different words**. *The seedlings were frost-damaged; the cold had scorched every one.* (restatement)
- **a pointer ("it", "instead", "that one") reaching back too far to be found**. *"He wedged it back," when the last noun was three paragraphs up.* (clarity)
- **a detail against what readers of the setting assume**, unacknowledged. *The deckhands work bare-armed in a January gale, unremarked.* (plausibility)
- **a line of dialogue whose speaker, or whose knowledge, cannot be placed**. *"Tell him what the surgeon found," though nobody present was in theatre.* (attribution)
- **a name, title or label that changes** without notice. *The dispatcher becomes "the supervisor" halfway down the page.* (clarity)
- **a change of scene, time or viewpoint nothing marks**. *A paragraph ends at the nursery gate; the next is in the shed, in winter.* (clarity)

Do not report style, rhythm, pacing, taste, what a later chapter may explain, or what the chapter says plainly once. Use `clarity` when no other kind fits.

Return one JSON object and no fences:

`{"findings":[{"id":"Q-01","kind":"sequence|staging|timeline|plausibility|knowledge|attribution|contradiction|restatement|clarity","evidence":"exact quote of the sentence at fault","conflicts_with":"exact quote of what it contradicts, or the empty string","issue":"one sentence: what makes a reader stop, and what the text leaves unresolved","edit":{"find":"exact text from the chapter, long enough to occur once","replace":"the text that makes it work, changing as little as possible"}}]}`

The capsule may carry `settled`: findings an earlier read raised and the reviser did not accept, each with the reviser's reason; do not report one again unless the text it quotes has changed.

`evidence`, `conflicts_with` and `edit.find` are copied character for character from the chapter. The edit resolves the stop in the fewest words and never adds a fact that another sentence of the chapter contradicts. When nothing is wrong, return `{"findings":[]}`.

If the capsule carries `repetition_candidates`, they are content words a counter found three times within a short span, and two- or three-word phrases (`phrase` in place of `word`) it found twice or more in the chapter, each with the sentences it occurs in. Report one only when a reader would notice the repetition as careless; a deliberate parallel, a refrain or an object the scene keeps handling is not a finding.

The capsule carries `answer_bound`, and it is a hard limit: report at most that many findings, the ones a reader would trip on first.
