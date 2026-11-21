# Log

## [2026-11-20] ingest | Public-domain source waves

Captured eight library items from three publishers and wrote 16 chapter/section source pages plus three staging files. Initial check: `ok: 19 files`. Triage selected all eight captured items A; the archived metadata inputs were regenerated after temporarily moving the scored TSVs aside because `triage_inputs.py` correctly skips scored rows.

## [2026-11-20] merge | Shared concepts and debates

Ran `merge_topic.py survey` and `bundles`; wrote 22 concepts and two debates. A follow-up source-context pass added worked cases, full section ranges, stronger parallelism excerpts and two explicit conflict/emphasis records. Rebuilt bundles and concepts. The Fowlers count once; documented literary borrowing remains visible.

## [2026-11-20] lint | Citation, rule and link gates

`check_wiki.py`: `ok: 43 files` (40 wiki pages plus three staging files). `rule_status.py --write`: three consensus, three bench. `lint_wiki.py --fix-slug-map`: zero broken targets, zero orphan concepts. Rebuilt `wiki/index.md`. Privacy and portability checks are recorded in `examples/BUILD-NOTES.md`.

## [2026-11-20] skill | Portable generated loader and eval key

Generated the skill in scratch, copied it to `examples/skills/plain-writing`, replaced the workspace absolute prefix with a repository-relative path and documented this adaptation. Added eight eval questions, including two traps. Cold evaluation has not been run; no self-grade is reported as independent evaluation.

## [2026-11-20] recapture | Fowler scope and privacy audit

Recaptured the selected Fowler sections to omit an uncited section containing a historical-name false positive in the private scrub. Retained original words, verified the paragraph shift, re-anchored every affected citation and staging entry, and removed the superseded capture unchanged with scratch. The final word count and source hashes are recorded in `ingest/source-manifest.yaml`.
