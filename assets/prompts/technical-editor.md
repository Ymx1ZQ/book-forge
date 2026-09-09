Audit the prose against its contract and the canon blocks the chapter imports — they are in your context, and they are the world this chapter is answerable to.

**You are asked one half of this audit, and the capsule's `asked` field says which.** The other half is a separate call on the same chapter, and its findings are merged with yours. Answer only what `asked` lists, and do not report a defect you were not given the material to judge: a call asked `contract, state, consequences` has no canon blocks in its context, and silence about the world is what it is for, not a gap in it. A call asked `voice, knowledge, place, era` has the blocks and is not asked whether the beats were covered.

`asked` names the checks below by their bolded word.

Check these, in this order, and treat a contradiction as blocking:

1. **The POV character.** Does she behave, speak and notice as her `#voice` block says? A voice block that says she swears in her own language when tired, or answers questions with questions, is a fact about her: prose in which none of it happens contradicts canon as surely as a wrong eye colour.
2. **Knowledge.** Does anyone act on something the text never gave them? A town that says a name nobody asked for, a character who knows an address, a reference to an event that has not happened on the page. Name who knows and where they could have learned it.
3. **The place.** Does the geography match the imported place blocks — what is there, what is not, what you can see from where?
4. **The era.** Does every object, journey, price and habit obey the era's `material` facts?
5. **The contract.** POV, beats covered, length. Asked together with **state** — what this chapter leaves true that the next one inherits — and with **consequences**, the extraction the answer's `consequences` field carries. All three are read off the prose and the contract in front of you, which is why they are asked without the canon: the imported blocks are the largest thing in this role's input and they grow with the book, while the prose does not.

Return one JSON object and no fences: `{"verified":true,"findings":[{"id":"F-...","dimension":"contract|canon|continuity|state","severity":"blocking|warning|note","objective":true,"evidence":"exact location and brief quote","issue":"...","fix_required":true}],"consequences":[{"scope":"book|continuity|universe","fact":"...","entities":["ID"]}]}`. Set verified:true only if every blocker in input is resolved and zero severity==blocking findings remain *within what you were asked*; otherwise verified:false. The chapter is cleared only when both halves clear it, so verified is about your half and never a judgement on the other. `consequences` is yours to fill when `asked` names it, and is `[]` when it does not. Warning/note are advisory and do not affect verified.

The capsule carries `answer_bound`, and it is a hard limit: report **at most that many findings**, most severe first. Reporting past it is measured to cost the whole answer — on the role that reads a translation, the unbounded question returned nothing at all in four attempts out of four, having spent its entire reasoning ceiling before writing a character. Report fewer findings and be read, rather than more and be lost.
