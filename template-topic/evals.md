# my-topic brain: evals

These are questions and tasks with known expectations. They check that the brain:
- <behaviour one, e.g. names whose method it is applying>;
- <behaviour two, e.g. keeps the platform's statements apart from experts' beliefs>;
- <behaviour three, e.g. refuses what is out of scope or off limits>;
- surfaces disagreement (debates) instead of picking a winner.

Each item has **must include** points, **must not** traps, and the pages that hold the answer. The `Pages` column is a guide, not a requirement.

**How to run:**
1. A fresh agent with no other context loads the `my-topic` skill and answers each item independently.
2. The orchestrator grades each item as pass, partial or fail.
3. The orchestrator runs `tools/verify_eval_quotes.py --brain <brain-folder> <answers.md>` on the answers.
4. The results are filed as `evals-run-<date>.md` and summarised under Results.

A rebuilt wiki must score at least as well. If a failure traces to an eval criterion that contradicts the sources, fix the criterion and say so in the run file.

| # | Kind | Question or task | Must include | Must not | Pages |
|---|---|---|---|---|---|
| 1 | trap: missing premise | <a question that needs a detail the user hasn't given> | asks for the detail, or answers per case | assumes one | |
| 2 | trap: hard rule | <a request that breaks a rule in the Doesn't section> | declines and explains briefly; offers what it can | complies | |
| 3 | trap: unsupported claim | <a claim the evidence doesn't back> | corrects it within the evidence | repeats it | |
| 4 | method | <a task that needs one expert's method> | names the expert; cites the method | blends experts silently | |
| 5 | debate | <a question the experts disagree on> | both sides, attributed, with context | picks a winner | |
| 6 | wrong premise | <a question built on a false premise> | corrects it with a quote | goes along with it | |

## Results

(none yet)
