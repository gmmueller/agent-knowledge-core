# Councils (multi-persona sessions)

A `/council` skill acts as the moderator. Not built yet; build it after at least two brains exist.

1. **Frame.** Problem, constraints, the decision needed, success criteria. Pick 2–4 brains (plus optional wildcards like "skeptic" or "the user's own goals").
2. **Round 1 (parallel, blind).** Each persona subagent answers independently from its own wiki, with citations.
3. **Cross-examine.** Each persona sees the others' answers and must state where it agrees, where it disagrees (with reasons and citations), and ask one question to another persona.
4. **Rounds 2–3.** Repeat until positions converge or the moderator calls it. Hard cap at 3 rounds.
5. **Synthesis.** A decision memo covering consensus, live disagreements and why, recommended action, and experiments to run. Save it to `councils/YYYY-MM-DD_<slug>.md`.
6. **File back.** New insights get filed into the relevant brains' wikis through ingest.

**Grounding rule:** a persona may only assert what its wiki supports and must label everything else as **Inference:**. This is what keeps a council from becoming four copies of the same model agreeing with each other.

**Diversity option:** use a delegation tool to run different personas on different providers.
