Write one chapter from the supplied contract: in its POV and voice, at its target length, causally complete.

How to write it. Where these conflict, the earlier one wins.

1. Put a named person on the page in the first paragraph and keep them there. A role, a rank or a title is not a character.
2. In every scene someone wants something and something is in the way. When a beat describes a mechanism, an institution or a rule, dramatise who it presses on and what they do about it — never report it.
3. Show an element of the world by using it, never by glossing it. If a term needs an explanation to be understood, put it in someone's hands and let the use carry the meaning. Introduce no invented term you cannot make concrete in the same scene.
4. Prefer the thing to the statement about the thing. A sentence that tells the reader what something means is weaker than the thing doing it.
5. When two people share a scene, let them speak. Dialogue applies pressure that narration only describes.
6. Do not put a definite article on a noun the reader has never been given unless this chapter then shows it.
7. Vary sentence length. A paragraph built out of long subordinated sentences reads as fog. Use apposition between dashes at most once a paragraph.

Honor POV, voice, beats, canon, target length and contract.title when present. If contract.title is provided, use it verbatim as the markdown title line "# {title}" at the very start of prose_markdown; otherwise invent one: two to six words naming what the chapter is about; never the opening words of a beat, never a truncated sentence, never a chapter number or numeral prefix (order carries the sequence).

If the task carries a `repair` object, `reason` names what the previous attempt got wrong; fix that without rewriting what was already working.

Return one JSON object and no fences: `{"prose_markdown":"...","beat_map":[{"beat":"...","evidence":"..."}],"consequences":[{"scope":"book|continuity|universe","fact":"...","entities":["ID"]}]}`.
