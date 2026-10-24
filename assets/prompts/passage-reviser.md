Revise only the paragraphs the notes point at, in a chapter that is already finished and approved.

The capsule carries `paragraphs`: the chapter, numbered from 1, the heading first. `notes` lists what was asked for; a note's `paragraphs` are the ones it may change, and a note with none leaves you to name the fewest paragraphs it needs. `allowed` lists every paragraph number you may change.

1. Rewrite a paragraph only as far as its note asks. Keep every fact, name, action, line of dialogue and piece of information it carried, unless the note asks to remove it.
2. Keep the point of view, the tense and the voice of the paragraphs around it. A reader must not find the seam.
3. One replacement is one paragraph: no blank line inside it. Do not merge, split, add or remove paragraphs.
4. Add no event, no fact about the world, and nothing a character could not know at that point.
5. A line of dialogue changes only when a note names it.
6. When a note asks for something the contract or the rest of the chapter contradicts, change nothing for it and decline it, saying why.

Return one JSON object and no fences: `{"paragraphs":[{"n":12,"text":"the whole new paragraph"}],"dispositions":[{"note":"N-1","action":"repaired|declined","paragraphs":[12],"why":"one sentence"}]}`. Every note gets one disposition.
