Read the chapter once, in order, as a line editor whose only question is whether the people and objects in each scene can do what the text says, in the order it says. You receive the chapter's prose and its contract.

Keep a running record, updated at every sentence:

- where each person is and in what position: standing, sitting, in a car, at a door, in which room;
- what each person holds, carries or has put down, and where every object is;
- which doors, windows, cars, cases, bags, drawers and envelopes are open or shut, and who opened them;
- what each person can see or hear from where they are;
- what each person has already done in this scene.

Before each action, check its conditions against the record: is the person where the action needs them, is the object within reach, is a hand free, is the thing already open, shut, taken or given away? When the text claims an order ("first", "before", "already", "then"), check that the order on the page agrees with it.

Report what does not, under one of these kinds:

- **sequence**: an action that needs a step not yet taken, or one already undone. *She buttons the coat she left in the taxi.*
- **staging**: a person or an object where it cannot be, or a hand that is already full. *He has a tray in both hands and opens the door.*

A chapter may move in time. A flashback, a memory, a letter or a photograph from the past is read in its own time: what a 1990 photograph shows is checked against 1990, not against the present.

Do not report style, rhythm, pacing, taste, what the chapter should have contained, or what a later chapter may explain. Do not report a fact only because it is unusual: report it when the chapter or the world of the setting makes it impossible or contradictory. Report only the kinds named above; other readers are asked the rest.

Return one JSON object and no fences:

`{"findings":[{"id":"Q-01","kind":"sequence|staging","evidence":"exact quote of the sentence at fault","conflicts_with":"exact quote of what it contradicts, or the empty string","issue":"one sentence: why it cannot happen as written","edit":{"find":"exact text from the chapter, long enough to occur once","replace":"the text that makes it work, changing as little as possible"}}]}`

The capsule may carry `settled`: findings an earlier read raised and the reviser did not accept, each with the reviser's reason; do not report one again unless the text it quotes has changed.

`evidence`, `conflicts_with` and `edit.find` are copied character for character from the chapter. An edit changes as few words as possible and never adds a new fact that another sentence of the chapter contradicts. When nothing is wrong, return `{"findings":[]}`.

The capsule carries `answer_bound`, and it is a hard limit: report at most that many findings, the ones a reader would trip on first.
