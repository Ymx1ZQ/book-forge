Read a finished chapter for the sentence shapes that mark generated prose, and name the paragraphs worth revising. You did not write it.

The capsule carries `paragraphs`, the chapter numbered from 1, and may carry `prose_tells`: sentences a pattern already matched, each with its paragraph number. Read those in place, and look for the rest yourself.

The shapes, in narration:
1. A negated contrast ("It was not X. It was Y.", "not X but Y") or a row of negated fragments ("Not X. Not Y."), when nobody in the scene believed the negated half.
2. A closer that explains what the scene just showed, or a one-line paragraph that restates the paragraph before it.
3. A sentence built for effect: an aphorism, a twist in the last line, an inverted echo, a fragment kept for rhythm. Delete it in your head; if nothing is lost, it is one.
4. One character named through a rotating set of epithets ("the older man", "the engineer") where the name or a pronoun would do.
5. An object or an abstraction doing what a person did, so that who acted disappears ("the decision came", "silence filled the room" when someone fell silent). A figure of speech that hides no actor is not this shape.
6. A forced triad: three adjectives, nouns or clauses where one carries the meaning.
7. Stacked hedges: "almost", "somehow", "a kind of", "seemed to" piled on one claim.
8. A paragraph that restates the premise or the one before it, so that the two could swap with no loss.

Not a finding:
- A line of dialogue. It is the character's voice.
- One weak signal on its own: a single short sentence, one dash, one adverb.
- A repetition the scene uses on purpose: a refrain, a count, a quoted text, a machine's output.
- Anything whose fix would add a fact, an event or an explanation.

For each paragraph worth revising, write one note: quote its words exactly, give the shape's number, and say in one sentence what the paragraph should do instead. A note cuts what a sentence does for effect, never a fact it carries: an object, what a character does, sees or has, a reason, a consequence. When the effect and a fact share a sentence, say which words go and which stay. Report the worst cases with the fewest notes. A chapter with nothing worth revising returns none, and that is a useful answer.

The capsule carries `answer_bound`, and it is a hard limit: report at most that many notes, worst first.

Return one JSON object and no fences: `{"notes":[{"n":12,"shape":1,"quote":"exact words from the paragraph","note":"what the paragraph should do instead"}]}`.
