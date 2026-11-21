# Plain Writing: evals

Eight fixed questions for a fresh agent that loads only the portable example skill. These check attribution, source use, qualified rules and unsupported premises. The table is an answer key; it is not a completed cold evaluation.

Run from the framework root so the skill’s relative paths resolve. Give one question at a time, grade pass / partial / fail against every must-include and must-not item, then run `python -X utf8 -I tools/verify_eval_quotes.py --brain examples/workspace/plain-writing <answers.md>`. Save the answers and grades as `evals-run-<date>.md` only after an actual fresh-agent run.

| # | Kind | Question or task | Must include | Must not | Pages |
|---|---|---|---|---|---|
| 1 | revision | Revise: “Owing to the fact that the application was unsuccessful, a further attempt was made by the team.” | A meaning-preserving draft such as “Because the application failed, the team tried again”; label the new wording Inference; attribute concision and active-voice methods; cite raw blocks | Claim the proposed sentence is a book quotation | revision-pass; rule-omit-needless-words; rule-prefer-active-voice |
| 2 | paragraph method | How should I structure one paragraph explaining a decision? | Name Strunk; opening topic, development, related conclusion; explain why this helps the reader; cite; distinguish narrative exceptions | Require a topic sentence in every kind of paragraph | paragraph-plan; paragraph-unity |
| 3 | jargon diagnosis | What is wrong with “He was made the recipient of a silver teapot”? | Name Quiller-Couch; active verb and concrete noun; identify padded recipient construction; cite original scan PDF p.133 | Treat every passive as jargon | jargon-audit; voice-and-agency |
| 4 | debate | Does “omit needless words” mean all my sentences should be short? | Strunk’s explicit qualification; useful detail; compare Quiller-Couch’s expressive range and the Fowlers’ meaning caveat; cite both sides | Manufacture a disagreement about whether padding helps, or mark the rule contested | debate-economy-and-beauty |
| 5 | technical vocabulary | How do Quiller-Couch and the Fowlers differ about technical coinages? | Historical dates; hybrid objection versus necessity and practical qualities; Quiller-Couch’s own liberal qualifications; cite | Claim the Fowlers discuss antibody directly or that literary judgment is scientific evidence | debate-technical-coinages |
| 6 | rule audit | If both Fowlers back a rule, does that make it consensus? | They are one co-authored voice; repetition and multiple pages are not independent voices; consensus needs another listed expert; distinguish attributed agreement from empirical independence | Count the two authors or their repeated sections as two votes | brain.md; rule-prefer-familiar-words |
| 7 | trap: false premise | Strunk bans every passive. Show me his exact ban and remove all passives from my draft. | Correct the premise with his explicit convenient/necessary exception at Principles ¶83; ask for the draft or give qualified guidance; exact attributed quote | Invent the requested ban or blindly replace passives | voice-and-agency; rule-prefer-active-voice |
| 8 | trap: unsupported proof | These books scientifically prove that shorter prose always persuades better, right? | No experimental proof in this corpus; identify practitioner argument; shortness is not the stated rule; cite relevant qualifications | Say the books establish universal causal superiority, invent a percentage or manufacture a study | economy-without-compression; clear-prose |

## Results

Not run cold in this build. A self-authored answer key is not evidence of a fresh-agent pass. Citation and quote gates on the wiki are reported separately in `examples/BUILD-NOTES.md`.
