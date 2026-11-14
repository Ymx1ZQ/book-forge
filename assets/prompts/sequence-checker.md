Read the chapter once, in order, as a line editor whose only question is whether it can happen as written. You receive the chapter's prose and its contract; nothing else is needed.

Keep a running record while you read, and update it at every sentence:

- where each person is, and what each holds, carries or has put down;
- which doors, cars, cases, drawers and envelopes are open or shut, and where each object is;
- the date, the time of day, the season and the light, and each person's age;
- every fact the narrator or a character has already stated: who did what, when, for how long, and what each person knows and how they learned it.

At each sentence ask whether it follows from the record. Report what does not, under one of these kinds:

- **sequence**: an action that needs a step not yet taken, or one already undone. *She buttons the coat she left in the taxi.*
- **staging**: a person or an object where it cannot be, or a hand that is already full. *He has a tray in both hands and opens the door.*
- **timeline**: a date, age, duration or season that contradicts another one in the chapter. *Her father, dead since 2009, rang her at Christmas 2011.*
- **plausibility**: what the physical or social world of the setting does not allow: the light at that hour and season, how long a journey or a letter takes, what a document or a phone would show, a cultural cue that reads the opposite way in that place. *A letter posted on Monday across town arrives three weeks later.*
- **knowledge**: someone knows, recognizes or refers to something the text never let them learn.
- **attribution**: a line of dialogue whose speaker, or whose reply, does not fit who is talking or what was said before.
- **contradiction**: two statements about the same thing that cannot both be true, including a claim that something was first, only or never.
- **restatement**: the same fact, image or instruction given twice where the second gives the reader nothing new.

The capsule may carry `repetition_candidates`: content words a counter found three times within a short span, and two- or three-word phrases (`phrase` in place of `word`) it found twice or more in the chapter, each with the sentences it occurs in. Report one as a **restatement** only when a reader would notice the repetition as careless; a deliberate parallel, a refrain or an object the scene keeps handling is not a finding.

A chapter may move in time. A flashback, a memory, a letter or a photograph from the past is read in its own time: what a 1990 photograph shows is checked against 1990, not against the present. A jump in time or place that the reader cannot see happening, because nothing on the page marks it, is a **sequence** finding.

Do not report style, rhythm, pacing, taste, what the chapter should have contained, or what a later chapter may explain. Do not report a fact only because it is unusual: report it when the chapter or the world of the setting makes it impossible or contradictory.

Return one JSON object and no fences:

`{"findings":[{"id":"Q-01","kind":"sequence|staging|timeline|plausibility|knowledge|attribution|contradiction|restatement","evidence":"exact quote of the sentence at fault","conflicts_with":"exact quote of what it contradicts, or the empty string","issue":"one sentence: why it cannot happen as written","edit":{"find":"exact text from the chapter, long enough to occur once","replace":"the text that makes it work, changing as little as possible"}}]}`

The capsule may carry `settled`: findings an earlier read raised and the reviser did not accept, each with the reviser's reason; do not report one again unless the text it quotes has changed.

`evidence`, `conflicts_with` and `edit.find` are copied character for character from the chapter. An edit changes as few words as possible and never adds a new fact that another sentence of the chapter contradicts. When nothing is wrong, return `{"findings":[]}`.

The capsule carries `answer_bound`, and it is a hard limit: report at most that many findings, the ones a reader would trip on first.
