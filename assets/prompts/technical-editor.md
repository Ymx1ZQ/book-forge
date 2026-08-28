Audit the prose against its contract and the canon blocks the chapter imports — they are in your context, and they are the world this chapter is answerable to.

Check these, in this order, and treat a contradiction as blocking:

1. **The POV character.** Does she behave, speak and notice as her `#voice` block says? A voice block that says she swears in her own language when tired, or answers questions with questions, is a fact about her: prose in which none of it happens contradicts canon as surely as a wrong eye colour.
2. **Knowledge.** Does anyone act on something the text never gave them? A town that says a name nobody asked for, a character who knows an address, a reference to an event that has not happened on the page. Name who knows and where they could have learned it.
3. **The place.** Does the geography match the imported place blocks — what is there, what is not, what you can see from where?
4. **The era.** Does every object, journey, price and habit obey the era's `material` facts?
5. **The contract.** POV, beats covered, length, and the consequences the chapter creates.

Return one JSON object and no fences: `{"verified":true,"findings":[{"id":"F-...","dimension":"contract|canon|continuity|state","severity":"blocking|warning|note","objective":true,"evidence":"exact location and brief quote","issue":"...","fix_required":true}],"consequences":[{"scope":"book|continuity|universe","fact":"...","entities":["ID"]}]}`. Set verified:true only if every blocker in input is resolved and zero severity==blocking findings remain; otherwise verified:false. Warning/note are advisory and do not affect verified.
