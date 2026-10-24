Translate the paragraphs of a chapter whose source changed. The rest of the chapter is already translated and stays as it is.

The capsule carries `paragraphs`: for each, its number `n`, the new `source`, and the `previous_translation` it had before the source changed. `context` carries the translated paragraphs around them, which you do not change. Follow `locale_style` and the fixed terms of the `glossary`.

1. Translate the new source. Where a sentence of the source did not change, keep the previous translation's wording for it, so that what did not change reads as it did.
2. Match the voice, tense and terms of the surrounding translation. A reader must not find the seam.
3. One answer is one paragraph: no blank line inside it.
4. When `repair` is present, it names what a reviewer found wrong in your last rendering of a paragraph. Fix that.

Return one JSON object and no fences: `{"paragraphs":[{"n":3,"text":"the whole translated paragraph"}]}`. Every paragraph in `paragraphs` gets an answer.
