# Ground-truth adjudication prompt gt-adjudication-v1.0

You adjudicate one Pending ground-truth entry at a time. Each entry is a finding from the PR 3 audit, plus an earlier AI proposal (`gt-correction-v1.0`). This is the AI-assisted adjudication the project owner authorised in `.docs/mvp2/resolve-ground-truth-proposals.md`. Your decisions are applied to a **new AI-adjudicated candidate**, marked **"AI-assisted, not human-reviewed"**. The owner approves that candidate before anything is frozen.

**Rules:** [`annotation-guidelines-v1.0`](../annotation-guidelines-v1.0.md), including §7 and **pronoun policy P1**: a gendered pronoun may follow a visually supported, qualified identification ("appears to be a man"); a person described neutrally takes neutral pronouns. **`Filename` is never changed.**

## Procedure for each entry: look first, then compare

1. **Read** the entry in the review packet (`eval_data/gt_review_packets/<Id>.json`): the original annotation, the finding's rule, field and guideline reference.
2. **Inspect the video yourself before reading the earlier AI proposal.**
   - Start with the contact sheets in `eval_data/gt_frames/<Id>/`.
   - Then make close-up frames of the moments that matter with the frame tool:
     `uv run --no-project --python 3.12 --script scripts/gt_frame_detail.py --clip <local clip> --start S --end E --fps F --scale 2 --columns 3 --out eval_data/gt_adjudication/<Id>/<name>.jpg`
     The local clip path is in the packet (`clip.local_path`). Use a higher frame rate (4–10 fps) for short events and the moment of contact, ignition or a gender cue.
   - Write a one-sentence **blind assessment** of what the frames show for this finding.
3. **Then** read the earlier AI proposal (`ai-proposals-v0.2.jsonl`, same `change_id`) and decide:

| Decision | Meaning | `final_value` |
|---|---|---|
| `ACCEPT` | The AI proposal is right, and you verified it. A `keep_original` proposal accepted means the original stays | the AI's `proposed_value` (`null` for keep) |
| `REJECT` | Keep the original: it is correct, clear enough or more informative. Not allowed when the AI proposal is already `keep_original` | `null` |
| `MODIFY` | A better value that follows the guidelines | your value, in full |
| `UNRESOLVED` | The video is genuinely ambiguous, inaccessible or contradictory after close inspection. Do not guess | `null` (the original stays, marked unresolved) |

**Do not reproduce the AI proposal by default.** Reassess it. **Do not use the AI confidence as evidence.**

## Standards

- **Gender and pronouns** (R25):
  - change only the age or gender words the frames do not support;
  - keep visually supported information, using "appears to be …" with moderate cues and "person" plus clothing without them;
  - make the record's pronouns consistent under P1;
  - make **minimal** edits; never rewrite an accurate sentence.
- **Factual changes** (type, taxonomy, severity, threat, timestamps, item identity or count, instrument versus asset, event sequence):
  - accuracy over fluency, verified on the frames;
  - keep meaningful details;
  - no inferred motive, injury or invented event.
- **Style:** reject a change that only rephrases an accurate annotation. Do not tune wording for any model or judge.
- **Consistency:**
  - the same standard across categories;
  - the two halves of a reclassification (R10) get the same decision;
  - person descriptions in the incident and entity records of one clip must agree.

## Impact (record it for every entry)

| Impact | What changes |
|---|---|
| low | pronouns, grammar, minor wording that keeps the meaning |
| medium | entity or object descriptions, event wording that could affect semantic similarity |
| high | incident type or taxonomy, severity or threat, timestamps, entity count or identity, instrument or asset identification, the event sequence |

**Every entry here needs actual video inspection** (`video_verified: true`, with at least one cited frame you looked at). High-impact entries need a close-up (`gt_frame_detail.py`) as well as the contact sheet.

## Integrity

Read only:
- the packet;
- the guidelines and this prompt;
- the contact sheets, the clip, and close-ups you make;
- the earlier AI proposal, after your blind assessment;
- the local overrides file `review-overrides-v0.2.json` (suggested P1 pronoun fixes).

**Never read** model predictions, Stage 0 or pilot outputs, scores or results: nothing under `eval_data/results/`, `eval_data/pilot-*`, `contracts/experiments/` or `eval/experiments/`. **Never tune a label** to favour the direct VLM or VSS.

## Output: one JSON object per entry, one per line

```json
{"change_id": "CL-0001", "incident_id": "...", "record_id": "...", "field": "...", "rule": "R25",
 "decision": "ACCEPT|REJECT|MODIFY|UNRESOLVED", "final_value": null, "impact": "low|medium|high",
 "blind_assessment": "...", "justification": "...",
 "evidence": [{"file": "eval_data/gt_adjudication/<Id>/<name>.jpg", "t": 12.5, "observation": "..."}],
 "video_verified": true, "uncertain": false, "agrees_with_ai": true,
 "adjudicator": {"kind": "ai", "model": "claude-opus-5-5", "method": "contact sheets + close-up frames"},
 "adjudication_prompt": "gt-adjudication-v1.0", "adjudication_prompt_sha256": "<sha256 of this file>",
 "guidelines": "annotation-guidelines-v1.0", "provenance": "AI-assisted, not human-reviewed"}
```

`evidence[].file` is a contact sheet (`eval_data/gt_frames/<Id>/…`) or a close-up you made. `t` is a tile time shown in that image.
