# Plain Writing: a complete topic-brain example

Start with [the brain card](workspace/plain-writing/brain.md), then [the wiki index](workspace/plain-writing/wiki/index.md). The library holds the source text; source pages explain one chapter or section; concept pages combine the authors; debates preserve their differences.

This self-contained workspace uses only three public-domain books: the complete 1918 text of William Strunk Jr.’s *The Elements of Style*, four lectures from Arthur Quiller-Couch’s *On the Art of Writing* (1916), and selected sections of Chapter I, Vocabulary, of H. W. Fowler and F. G. Fowler’s *The King’s English* (1906). The Fowlers are one co-authored voice. Exact retrieval URLs, edition details and capture notes are in each library publisher’s `sources.yaml`, raw frontmatter and crawl log. The text is public domain in the United States; no paid course or private material is included.

Useful entry points:

- [Audit jargon](workspace/plain-writing/wiki/methods/jargon-audit.md)
- [Economy without compression](workspace/plain-writing/wiki/principles/economy-without-compression.md)
- [Technical coinage debate](workspace/plain-writing/wiki/debates/debate-technical-coinages.md)
- [The generated skill](skills/plain-writing/SKILL.md)
- [Eight evaluation questions](workspace/plain-writing/evals.md)
- [Build notes and documentation friction](BUILD-NOTES.md)

Run the framework tools from the repository root, using your configured Python environment:

```powershell
python -X utf8 -I tools/check_wiki.py --brain examples/workspace/plain-writing
python -X utf8 -I tools/rule_status.py --brain examples/workspace/plain-writing --write
python -X utf8 -I tools/lint_wiki.py --brain examples/workspace/plain-writing --fix-slug-map
python -X utf8 -I tools/build_wiki_index.py --brain examples/workspace/plain-writing
```

Raw captures are immutable. Paragraph locators point into the HTML captures; `p. N` locators point to original Quiller-Couch scan PDF pages (printed page N minus 16). The capture retained page positions while excluding unselected lectures. Early twentieth-century spellings, dialect preferences and social judgments are attributed historical material, not current universal standards.

The bundled skill is a portable demonstration whose paths resolve from the framework repository root. For everyday installation, regenerate it with `generate_persona.py --brain <your-brain> --out <your-skills-parent>` so it points at your own workspace. A fresh-agent eval run is still to be performed; this example includes the questions and answer criteria, without claiming an unrun test passed.
