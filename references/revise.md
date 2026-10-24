# Revise passages of a promoted chapter

Two commands change a chapter that is already promoted without redrafting it.
Both change whole paragraphs, and every paragraph they do not name stays
byte-identical, in the source and in every translation.

```text
book-forge revise --book <id> --chapter <ch> --note "<what to change>" [--anchor "<words of the passage>"]
book-forge humanize --book <id> [--chapter <ch>]
```

## revise

The author's note goes to the reviser with the chapter numbered by paragraph.
With `--anchor`, only the paragraphs containing those words may change;
without it, the reviser names the fewest paragraphs the note needs. The
technical editor rules each rewritten paragraph: the note is met, and no fact,
beat, point of view or tense moved. A paragraph it does not pass reverts.

An anchor the chapter does not contain is refused before any call. The heading
cannot change. A note that would change a beat of the chapter's contract is
declined: contracts are not versioned yet.

## humanize

A reader that did not write the chapter reads it for the shapes of generated
prose: negated contrasts, closers that explain the scene, sentences built for
effect, rotating epithets, objects acting for people, forced triads, stacked
hedges, paragraphs that restate the one before. It is given the scanner's hits
and looks for the rest. Dialogue is the character's voice and is left alone.
Each note names one paragraph and goes through `revise`. A chapter with no
notes costs one call and is not touched.

## Translations

When the source changed, each translation of the chapter translates again
only the changed paragraphs, with the paragraphs around them as context. The
translation critic checks each new paragraph against the new source; one it
finds wrong is translated once more with its note. The chapter is then current
against the revised source. A translation whose paragraph count differs from
the source is skipped and reported, since paragraphs pair by position.

Run `translate review <book> <locale> --chapter <ch>` afterwards for the full
read-back of the chapter in its language.

## Records

- `books/<book>/reviews/<ch>/passages.json`: every revision, with notes,
  before and after of each paragraph, verdicts, refused answers, dispositions.
- `books/<book>/feedback/<ch>.json`: each note with its status and the
  paragraphs it changed.

Report to the user which paragraphs changed, which reverted and why, and the
state of each translation.
