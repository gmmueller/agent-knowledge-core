# Tech choices (researched 2026-10-11)

| Option | Verdict | Why |
|---|---|---|
| **Karpathy LLM Wiki** | **Core** | The only option that *synthesizes* principles, rules and methods, which is the persona layer. Plain markdown, git and Obsidian, with no infrastructure. |
| **qmd** (tobi/qmd) | **Add at scale** | Local hybrid search (BM25 + vectors + LLM rerank) with a CLI and an MCP server. Fixes the wiki's weak spot past ~100 sources and lets personas quote raw transcripts with timestamps. |
| Obsidian | **Viewer** | Graph view, backlinks, Dataview. Opens the folder in place. |
| Plain vector RAG | Covered by qmd | Retrieval with no accumulated synthesis. |
| GraphRAG / LightRAG / Cognee | Skip | Graph DB plus LLM extraction at index time. Built for big corpora. Benchmarks are mostly vendor-run; GraphRAG is weaker than vanilla RAG on simple factual questions. |
| Graphiti / Zep | Skip | Temporal facts; course knowledge is mostly static. |
| Letta (MemGPT) | Skip | A separate agent server outside Claude Code skills and subagents. |
| Basic Memory MCP | Skip | Linked markdown through MCP, which plain file edits already cover. |
| NotebookLM | Side tool | Cited Q&A over one notebook; no persona rules, councils or automation. |
| Delphi.ai | Skip | Hosted creator self-clones; wrong fit for private brains. |

Revisit graph tooling (a Neo4j index built deterministically from wiki links) only past roughly a thousand pages per brain.
