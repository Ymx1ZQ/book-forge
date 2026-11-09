# Check continuity across closed chapters

Use this route for `continuity ledger`, `continuity flags` and `continuity resolve`.

Slips between chapters survive a chapter-by-chapter review: an interval of a month and a half in one chapter and two months in a later one, the same night in a blouse and in a dress, the same heaps called cones and then pyramids, gossip at four in the morning under a dawn sky. They are cheap to fix before the book is translated and costly after.

## `continuity ledger <book>`

Reads every closed chapter of the book and writes the contradictions it finds as open flags.

1. A `continuity-extractor` call per closed chapter lists its checkable facts: elapsed-time statements and intervals, clock times and time of day, clothing, the names used for recurring objects and places, and who knows what. Each fact carries a verbatim quote. A fact whose quote is not in the chapter is dropped. The list is stored in `books/<BOOK>/work/continuity/facts/<CHAPTER>.json` with the source hash of the chapter, and a chapter whose hash has not changed is not read again.
2. A `continuity-checker` call per chapter compares its facts with those of every earlier chapter. A contradiction becomes a flag only when both quotes are found in the chapters it names. A chapter is compared again only when its own facts or an earlier chapter's facts changed.

Flags are stored in `books/<BOOK>/work/continuity/flags.json`. A flag has an id (`CF-<BOOK>-0001`), the later chapter, the earlier chapter, both quotes, a category and a one-sentence reason. Both roles run at a low cost: the extractor at `low`, the checker at `medium`, through the pins in `roles.<role>` like any other role. A chapter that cannot be read or compared is listed under `unread` and the rest go on.

Run it after chapters close and again after any source fix. Flags that no longer hold when the chapter is read again are dropped; flags closed by hand stay closed.

## `continuity flags [<book>] [--all]`

Lists the open flags, or every flag with `--all`. `status` also shows the open flags of the book under `continuity_flags_open`.

## `continuity resolve <flag-id> --reason TEXT`

Closes a flag. The reason is required and stored: the slip was fixed in the manuscript, or it is not a slip (time passes between the chapters, a character is said to wear different clothes). Fix the manuscript first when it is a slip, then run `adopt` and the ledger again.

## The translation gate

`translate next` and `translate run` refuse a chapter while the book has an open flag on that chapter or on an earlier one. The refusal names the flags and the command that closes them and nothing is translated or paid for. `--accept-flags` translates anyway and prints the flags it let through.
