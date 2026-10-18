# Name a staged interview's speakers

Read `library/<publisher>/staging/<item-id>.lines.json` (`front.title`, `front.description`, URL) and the matching `.diar.json` (`speakers`: talk time, first three lines, five samples spread through the item). Read surrounding diarized lines when the samples don't resolve an introduction. Do not change transcript text, timings or speaker labels.

Write only `library/<publisher>/staging/<item-id>.names.yaml`, UTF-8:

```yaml
SPEAKER_0: Alex Host
SPEAKER_1: Jamie Host
SPEAKER_2: Unknown Speaker 1
roles:
  Alex Host: host
  Jamie Host: cohost
  Unknown Speaker 1: other
confidence:
  SPEAKER_0: 0.95
  SPEAKER_1: 0.90
  SPEAKER_2: 0.0
```

Cover every diarized speaker. Roles are `host`, `guest`, `cohost`, or `other`; confidence is a number from 0 to 1, keyed by speaker label. Ground names in introductions, direct address, explicit identity statements or metadata. A person mentioned in conversation is not necessarily a speaker. Never infer which of two hosts is speaking solely from their order or talk time. Assign unresolved identities `Unknown Speaker 1`, `Unknown Speaker 2`, etc.; choose `other` unless their role is clear. Unknown identities remain separate per item in people.yaml. Multiple labels may share one name only if the transcript clearly demonstrates the same voice was over-clustered; flag that in your report.

**Duo hosts that count as one expert** (a topic brain's `expert_aliases` maps both to one name, e.g. Alex Host and Jamie Host → `Example Duo`): when a label is clearly one of the two hosts (or both, over-clustered) but no anchor says which, name it with the duo name (`Example Duo`, role `host`) instead of `Unknown Speaker N`. Never use the duo name for a label that also carries a guest's or clip's voice; request a re-run with `--speakers N` for that.

Report the evidence and confidence for each name briefly to the orchestrator. If diarization conflates voices, request a new staging pass (optionally `--speakers N`) before finalization; never edit an existing raw file.

Read three boundary turns per speaker (with adjacent turns) and report suspected misattributions in names.yaml under `suspect: [<start-seconds>, ...]`; do not auto-fix them.

When `turn_timing.whisper_words` is present, prioritize `estimated_boundary_starts` for review; a matched word time is timing evidence, not proof of speaker identity. Whisper alignment is currently opt-in with `--whisper-words`.
