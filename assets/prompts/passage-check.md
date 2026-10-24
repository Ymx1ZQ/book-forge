You check a revision of a finished chapter. Some paragraphs were rewritten to meet notes; every other paragraph is unchanged and is not shown.

The capsule carries the chapter's `contract`, the `notes`, and `changes`: for each rewritten paragraph its number `n`, `before`, `after`, and the paragraphs on either side for context.

Rule each change on its own. It passes when all of these hold:
1. It does what its note asked, or moves the paragraph in that direction.
2. Every fact, name, object, action, perception, reason and consequence in `before` is still in `after`, unless the note names that exact fact for removal. A note that asks to cut a closer, an aphorism or a simile does not license dropping a fact that shared its sentence; list the missing fact in `why`.
3. It adds no event, no fact about the world, and nothing a character could not know at that point.
4. Point of view, tense and voice match the paragraphs around it.
5. No beat of the contract that the paragraph carried is lost.

Wording you would not have chosen is not a failure.

Return one JSON object and no fences: `{"verdicts":[{"n":12,"ok":true,"why":"one sentence"}]}`. One verdict per change; when `ok` is false, `why` names what failed.
