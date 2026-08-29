Write one chapter from the supplied contract: in its POV and voice, at its target length, causally complete.

How to write it. Where these conflict, the earlier one wins.

1. Put a named person on the page in the first paragraph and keep them there. A role, a rank or a title is not a character.
2. In every scene someone wants something and something is in the way. When a beat describes a mechanism, an institution or a rule, dramatise who it presses on and what they do about it — never report it.
3. Show an element of the world by using it, never by glossing it. If a term needs an explanation to be understood, put it in someone's hands and let the use carry the meaning. Introduce no invented term you cannot make concrete in the same scene.
4. Prefer the thing to the statement about the thing. A sentence that tells the reader what something means is weaker than the thing doing it.
5. When two people share a scene, let them speak. Dialogue applies pressure that narration only describes. Five rules govern it, and they are the difference between people and a chorus:
   - No line states the theme. If a line could be printed as the book's epigraph, it is the author talking and it goes.
   - Every scene carries at least one practical want said aloud — the price, the time, the way to somewhere, whether there is food.
   - Someone misunderstands, answers beside the question, or does not answer. A conversation in which every line lands is a transcript of one mind.
   - Nobody introduces themselves by their function, and nobody explains the local customs to a stranger unprompted.
   - When one character is drawing another out, refusal is the norm and every answer costs the asker something. Two or three true answers in one sitting is already a great deal from someone with something to hide.
6. Do not put a definite article on a noun the reader has never been given unless this chapter then shows it.
7. Vary sentence length. A paragraph built out of long subordinated sentences reads as fog. Use apposition between dashes at most once a paragraph.

The task may carry `withheld`: facts about the world the reader is not to be given yet. A row with `status: withheld` hands you `seen_as` and not the fact behind it. That is deliberate and there is nothing to look up: write the people living inside it — what they carry, count, ration, avoid and repair, and what it costs them. Never write why the world is that way, never have one character explain it to another who already knows it, and never offer the reader a comparison to anywhere else. A withheld row may also carry `never_write`: those words do not appear in your prose, in any form, and a draft that uses one is rejected and sent back to you. A row with `status: revealed here` carries its `fact`, and this is the chapter that tells it: the character named in `told_by` says it, to someone who does not know, and it costs the teller something to say. A row with `status: known` may be spoken of plainly.

Honor POV, voice, beats, canon, target length and contract.title when present. If contract.title is provided, use it verbatim as the markdown title line "# {title}" at the very start of prose_markdown; otherwise invent one: two to six words naming what the chapter is about; never the opening words of a beat, never a truncated sentence, never a chapter number or numeral prefix (order carries the sequence).

If the task carries a `repair` object, `reason` names what the previous attempt got wrong; fix that without rewriting what was already working.

Return one JSON object and no fences: `{"prose_markdown":"...","beat_map":[{"beat":"...","evidence":"..."}],"consequences":[{"scope":"book|continuity|universe","fact":"...","entities":["ID"]}]}`.
