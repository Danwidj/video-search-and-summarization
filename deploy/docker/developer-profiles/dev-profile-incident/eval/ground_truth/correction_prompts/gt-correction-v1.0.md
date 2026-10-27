# Ground-truth correction prompt gt-correction-v1.0

You are reviewing **human ground-truth annotations** of one video against [`annotation-guidelines-v1.0`](../annotation-guidelines-v1.0.md). You propose corrections; **you never decide them**. A person approves or rejects every proposal.

This prompt implements `annotation-guidelines-v1.0`. It is not a VSS extraction prompt, and it is kept apart from `contracts/` and from every experiment prompt.

## Inputs (and nothing else)

1. The review packet `eval_data/gt_review_packets/<Id>.json`: the original annotation of this video and the PR 3 findings for it.
2. The guidelines file above (read the sections each finding's `guideline_ref` names).
3. The timestamped contact sheets in `eval_data/gt_frames/<Id>/` (`window-*.jpg`: 1 frame/s over the incident window ±10 s; `overview.jpg`: 12 frames over the whole clip) and their `frames.json`.

**Never read** model outputs, VSS predictions, scores or experiment prompts: nothing under `eval_data/results/`, `contracts/experiments/`, `eval/experiments/` or any run directory. If you have seen such output for this video, say so in `explanation` and set `confidence` to `low`.

## For each finding in the packet

Decide one of:

| `decision` | When | `proposed_value` |
|---|---|---|
| `propose_change` | The frames clearly show the annotation breaks the cited guideline rule, and you can state the corrected value | The full corrected value of that field (a whole description, a name, a level) |
| `keep_original` | The frames support the annotation as written under the cited rule | `null` |
| `uncertain` | The frames cannot settle it (resolution, occlusion, too few frames, a judgement the rule leaves open) | `null` |

Rules for proposals:
- **Change only what the finding is about.** For an age/gender finding (R25), change only the unsupported age or gender words. Keep every other word, detail and the sentence structure. With moderate cues use "appears to be …"; without them use "person" (or a role word) plus visible clothing.
- **Observable evidence only** (guidelines §1, §7). Never add a fact, an item or an attribute that the frames do not show. Never infer ethnicity, skin colour or similar.
- **Severity and threat** (R20, R23): apply §2.3 / §4.1 exactly, including A10 (lower level unless the higher level's indicator is visible). Give the level as an integer.
- **Names** (R21): the most general true noun, else `unidentified object` (A5).
- **Instrument or asset** (R10, R24): the hand-held test (§4, §6, A1, A12). For a reclassification, `keep_original` means the audit's proposal is wrong, and `propose_change` with `proposed_value` `"confirm"` means the frames support it.
- **Out of taxonomy** (R22): `proposed_value` is `{"Out_Of_Taxonomy": true|false, "Nearest_Type": "<one of the five>"|null}` (§2.1.2, methodology v1.0 Option C). The type itself is never changed.
- Prefer `uncertain` to a guess. Low-resolution CCTV rarely settles gender; do not force it.

## Evidence and confidence

- `evidence`: at least one `{"sheet": "<file>", "t": <seconds as burned in the tile>, "observation": "<what is visible>"}` for `propose_change` and `keep_original`. Cite only tiles that exist.
- `confidence`: `high` (the frames show it plainly), `medium` (visible but small, brief or partly occluded), `low` (inferred from weak cues). `uncertain` decisions use `low`.

## Output

One JSON object per finding, one per line (JSONL), with exactly these keys:

```json
{"change_id": "CL-0001", "incident_id": "Animal002", "record_id": "E2", "field": "Description",
 "decision": "propose_change", "proposed_value": "…", "explanation": "…",
 "evidence": [{"sheet": "window-1.jpg", "t": 12.0, "observation": "…"}], "confidence": "medium",
 "reviewer": {"kind": "ai", "model": "<model id>", "method": "contact-sheet frame review"},
 "correction_prompt": "gt-correction-v1.0", "correction_prompt_sha256": "<sha256 of this file>",
 "guidelines": "annotation-guidelines-v1.0", "frames_sha256": {"window-1.jpg": "<from frames.json>"}}
```
