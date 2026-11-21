# Plain Writing: a complete topic-brain example

Start with [the brain card](workspace/plain-writing/brain.md), then [the wiki index](workspace/plain-writing/wiki/index.md). The library holds the source text; source pages explain one chapter or section; concept pages combine the authors; debates preserve their differences.

This self-contained workspace uses only three public-domain books: the complete 1918 text of William Strunk Jr.’s *The Elements of Style*, four lectures from Arthur Quiller-Couch’s *On the Art of Writing* (1916), and selected sections of Chapter I, Vocabulary, of H. W. Fowler and F. G. Fowler’s *The King’s English* (1906). The Fowlers are one co-authored voice. Exact retrieval URLs, edition details and capture notes are in each library publisher’s `sources.yaml`, raw frontmatter and crawl log. The text is public domain in the United States; no paid course or private material is included.

Useful entry points:

- [Audit jargon](workspace/plain-writing/wiki/methods/jargon-audit.md)
- [Economy without compression](workspace/plain-writing/wiki/principles/economy-without-compression.md)
- [Technical coinage debate](workspace/plain-writing/wiki/debates/debate-technical-coinages.md)
- [The generated skill](skills/plain-writing/SKILL.md)
- [Eight evaluation questions and cold-run grades](workspace/plain-writing/evals.md) (8 / 8 pass, both traps caught)
- [Build notes and documentation friction](BUILD-NOTES.md)

Run the framework checks from the repository root after activating the virtual environment (Windows PowerShell: `.\.venv\Scripts\Activate.ps1`; macOS/Linux bash: `source .venv/bin/activate`):

```sh
python -X utf8 -I tools/check_wiki.py --brain examples/workspace/plain-writing
python -X utf8 -I tools/rule_status.py --brain examples/workspace/plain-writing --write
python -X utf8 -I tools/lint_wiki.py --brain examples/workspace/plain-writing --fix-slug-map
python -X utf8 -I tools/build_wiki_index.py --brain examples/workspace/plain-writing
```

Without activating the venv, replace `python` with `.\.venv\Scripts\python.exe` (Windows) or `.venv/bin/python` (macOS/Linux).

Raw captures are immutable. Paragraph locators point into the HTML captures; `p. N` locators point to original Quiller-Couch scan PDF pages (printed page N minus 16). Since this example was built, `book_to_raw.py --pages` and `web_to_raw.py fetch --from-heading` / `--to-heading` support pre-capture page and heading selection directly, and `book_to_raw.py` updates `catalogue.tsv` and `crawl-log.md`. Early twentieth-century spellings, dialect preferences and social judgments are attributed historical material, not current universal standards.

The bundled skill under [`skills/plain-writing/`](skills/plain-writing/SKILL.md) is generated directly with:

```sh
python -X utf8 -I tools/generate_persona.py --brain examples/workspace/plain-writing --out examples/skills --relative-to .
```

`--relative-to .` writes portable paths relative to the repository root, and topic-brain skills omit annotated-example and platform notes when a brain has none. For local installation, run `generate_persona.py --brain <your-brain> --out <your-skills-parent>` without `--relative-to` so paths are absolute. A fresh agent from a different model provider than the builder, given only this skill, answered the eight eval questions on 2026-11-20 and passed all eight. Its answers and the grades are linked from `evals.md`.
