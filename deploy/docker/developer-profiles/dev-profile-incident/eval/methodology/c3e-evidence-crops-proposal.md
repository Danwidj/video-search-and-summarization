# C3-E: Evidence Crop Evaluation (PROPOSED, 2026-11-04; not frozen, not approved)

**Status:** approved in principle by the owner on 2026-11-04; the binding rules are in [`c3e-preregistration.md`](c3e-preregistration.md). This page keeps the background and estimates. It extends Evaluation V2 with dimension 3 (evidence crops) as a separately
versioned study. It does not change C3: the C3 pre-registration, the C2 freeze manifest (`eb316f37…`), the C3 configs
and amendments A1–A4 stay as they are. C3-E gets its own pre-registration and its own freeze manifest, written and
frozen before any held-out (test-half) evidence is scored.

## 1. Scope

| Item | C3-E |
|---|---|
| Question | Does the pipeline's evidence image show the right object, at a moment it is visible, in the right place? |
| Subjects | Track B pipelines `nano-pipeline` and `super-pipeline` on the **historical C1b profile** (agent `acbf892ba`, captions, P1, grounding, zoom; person and object tracking **off**) |
| Predictions | Development: C1b (25 dev clips, 49 runs, 496 evidence entries). Held-out: C3 Track B historical, including its recovery run (55 test clips, 1 repeat) |
| Not covered | The current production configuration (tracking on). No result is reported as production performance |
| Unchanged rules | Methodology v2.0 §4C: same-second IoU, correct evidence = located + temporal hit + IoU ≥ 0.5; capped or never-judged entries are unscorable, never misses; primary metrics on `human_verified` references only |

## 2. Reference dataset: `box-references-v2`

One record per ground-truth item (entity, instrument, asset) of all 80 clips. GT v1.0 has no boxes and no per-object
visibility times (only incident start and end), so every reference is new.

| Field | Content |
|---|---|
| `clip`, `kind`, `item_id` | GT v1.0 video ID, object type and ID |
| `visible_spans` | Verified visible intervals in whole seconds (an object may leave and return) |
| `boxes` | `{second: [x1, y1, x2, y2]}` on the 0–1000 grid at the sampled reference seconds |
| `source` | `ai_proposed` (generator), `ai_validated` (generator and blind validator agree), `human_verified` |
| `review` | Reviewer, decision (accept, correct, reject), corrected values, adjudication when two reviewers differ |
| Provenance | Detector identity, prompts and SHA-256s, packet hashes, frame-limits file, sampling seed |

AI-made records are never labelled `human_verified`. Results are reported in three groups: verified,
provisional AI-assisted, and unscorable.

## 3. Sampling (pre-specified; fixed before any held-out evidence is scored)

The full 1 s grid needs about 22,800 item-seconds per pass (about 45,000 judgements). C3-E samples instead:

1. **Visibility grid (GT-anchored, prediction-free).** Every 2 s of each clip (even seconds of the existing grid),
   all items of the clip. It proposes each item's visible intervals; the human sets the final boundaries in a video
   scrub (§4), so the grid only pre-fills them.
2. **Box anchors (prediction-anchored, blind).** For each clip, every whole second any Track B subject used as an
   evidence second (`box_seconds`, else `timestamp_seconds`; always whole seconds in the stored runs), annotated
   for **every GT item of the same kind** in that clip. The rule uses only the predicted kind and second, never
   the item matching or the predicted box, so choosing the anchors reveals no result. Anchors are mixed with one
   control second per clip, drawn with seed 20261104 inside the incident window, so annotators cannot tell anchors from controls.
3. **Frame limits.** Every planned time is clamped to the clip's last decodable frame (`frame-limits-v1.json`;
   §6). The 8 dropped frames are listed.

All anchor seconds are on the existing 1 s grid, and the validator's frames on the existing +0.5 s grid, so the
cached OWLv2 proposals already cover them. No extra detector run is needed.

Estimated volume per pass:

| Part | Development | Held-out (estimate from dev rates) |
|---|---|---|
| Distinct anchor clip-seconds | 194 | about 430 |
| Anchor item-seconds (same kind) | 602 | about 1,300 |
| Visibility grid frames (2 s) | about 800 | about 1,700 |

## 4. Passes and human verification

- **Generator (Claude, `gen-box-select-v1`):** one frame per anchor clip-second with numbered detector marks; per
  item it picks a mark or "none fits". Visibility: 12-frame contact sheets, visible / not visible per item.
- **Blind validator (`gen-box-validate-v1`):** the +0.5 s frame, renumbered marks; `assert_blind` guarantees it
  sees no generator answer. Agreement stays IoU ≥ 0.5 between the two passes.
- **Human verification (the primary tier):** a local, offline review page (no shared service) per clip:
  - intervals: the clip player with proposed start and end per item; accept or set new times;
  - boxes: each anchor frame with the proposed box; accept, redraw or reject (not visible / not identifiable);
  - every generator–validator disagreement and every "none fits" is shown first;
  - a second reviewer re-does a 10% stratified sample for Cohen's κ (intervals: boundary within 1 s; boxes:
    IoU ≥ 0.5).
- **Held-out frames go only to the Claude generator and validator and to the team's reviewers, never to an
  external review model.** Proposal A's AI review (OpenRouter) is limited to development records and is optional.

## 5. Metrics (per subject, per split; 95% CIs by clip-cluster bootstrap, seed 20261027, 10,000 resamples)

**Primary (human-verified references):**
- Correct-evidence rate: located, temporal hit and IoU ≥ 0.5, over scorable evidence entries of matched items.
- Temporal alignment rate: evidence second inside a verified visible interval (reported apart from IoU).
- IoU at the same second: median, share ≥ 0.5, the full distribution.

**Error taxonomy (each entry in exactly one class):** missing evidence (matched item, no entry or no image);
not located; temporal miss; spatial miss (IoU < 0.5); correct; unscorable (crop-call cap, setup or infrastructure
gap, no verified reference box at that second, reference rejected as not identifiable).

**Reliability (no references):** evidence success rate, image gaps, grounding failures, crop-cap truncation and
refused calls (C1b Nano: 111 refused), unscorable entries by reason.

**By kind:** entities, instruments and assets separately when a cell has at least 20 scorable entries; otherwise
counts only (held-out GT has 14 instruments, so instruments are expected to be descriptive).

**Comparison:** one paired Nano − Super difference in correct-evidence rate on the held-out split (clip-cluster
bootstrap, two-sided), its own family. Missing or unscorable references never count as correct.

## 6. RA1 repair (done offline on 2026-11-04, branch `eval/v2-c3e-evidence`, not pushed)

- **Cause:** the plan used the manifest's durations, rounded up to the half second. 8 test clips got a final
  planned frame past their last decodable frame (Assault018 12.5 s, Burglary005 258.0 s, Burglary041 60.5 s,
  Explosion004 63.5 s, Explosion019 12.0 s, RoadAccidents030 43.0 s, RoadAccidents037 73.0 s, RoadAccidents060 28.0 s).
- **Fix:** `scripts/v2_frame_limits.py` measures each clip's last video packet (presentation time + duration) with
  the pinned ffprobe; `references ra1 --frame-limits` keeps a time only when `t < end_s` and lists every dropped
  time. On the 80 clips the rule matches the extraction exactly (10,026 of 10,026 planned frames).
- **Preserved:** the 37 clips with cached proposals keep byte-identical plans, so their caches are reused; the
  original plan is kept as `extraction-plan.2026-11-02.json`. The detector (same OWLv2 identity, CPU) resumed on
  the 43 remaining clips.

## 7. Workload, runtime and cost (estimates)

| Step | Runtime | Paid API cost |
|---|---|---|
| Detector, 43 remaining clips (CPU, no GPU) | about 4–4.5 h | $0 |
| Claude generator and validator passes (in Claude Code, as RA1 planned) | about 1,700 image reads, about 3–4 M tokens, several sessions | $0 project API spend (Claude Code session usage) |
| Human verification: intervals for 298 items (pre-filled) | about 2.5–5 h | — |
| Human verification: about 1,900 anchor boxes + disagreements | about 3–4 h | — |
| Second-reviewer κ sample (10%) | about 1 h | — |
| Optional proposal A AI review, development only | — | ≤ $1.25 (approved cap) |
| Scoring (offline) | minutes | $0 |

## 8. Order and dependencies

| Step | Can run during the Switchyard pause? |
|---|---|
| Detector completion | Yes; stopped automatically before C3's Track B agent starts (one memory-heavy job), resumes from cache |
| C3-E code: sampler, `box-references-v2` record builder, review page, J5 config | Yes (offline, hermetic tests) |
| Visibility grid passes and interval review, all 80 clips | Yes (prediction-free) |
| Development anchors (C1b) passes and review | Yes |
| Freeze C3-E pre-registration and manifest | Before held-out anchors are drawn |
| Held-out anchors | After C3 Track B (historical recovery) completes |
| Held-out scoring | After the held-out references are verified and frozen |
