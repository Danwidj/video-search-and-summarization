# C3-E pre-registration: Evidence Crop Evaluation (DRAFT v0.1, 2026-11-04)

**Status:** SUPERSEDED by [v0.2](c3e-preregistration-v0.2.md) (owner, 2026-11-04: no mandatory human review; never frozen). DRAFT. The owner approved the approach on 2026-11-04 (sampling with clarifications, human verification,
Claude annotation passes; proposal A deferred). The draft is frozen, with its own manifest, before any held-out
(test-half) evidence is scored. C3's pre-registration, freeze manifest (`eb316f37…`), configs and amendments A1–A4
are unchanged; C3-E results are reported separately from them and together with them in the six-dimension report.

Background and estimates: [`c3e-evidence-crops-proposal.md`](c3e-evidence-crops-proposal.md).

## 1. Subjects and data

| Item | Rule |
|---|---|
| Subjects | `nano-pipeline`, `super-pipeline` on the **historical C1b profile** (agent `acbf892ba`; captions, P1, grounding, zoom; person and object tracking off). Never reported as production (tracking-on) performance |
| Development split | 25 dev clips (`split-v2`), predictions from C1b |
| Evaluation split | 55 previously exposed test clips, predictions from C3 Track B historical plus its recovery run |
| Splits | Reported separately; never pooled |

## 2. Sampling (`c3e-sampler-v1`, `evalv2/references/c3e.py`)

- **Frame limits.** Every planned time is clamped to the clip's last decodable frame (`frame-limits-v1.json`).
- **Visibility grid.** Generator: every even second of every clip, all GT items of the clip, 3x3 contact sheets.
  Blind validator: every odd second. The grid only proposes intervals; people set the final boundaries (§4).
- **Box anchors.** Per clip and **predicted kind**, every whole second used as the evidence second of a located box
  (`box_seconds`, else `timestamp_seconds`; `located` true and a stored `bounding_box`), pooled over both subjects
  and all repeats of that split's runs. Only the kind and the second are read: never the item matching, the
  predicted box or any score. Each anchor is annotated for **every GT item of that kind** in the clip.
- **Decoys (blinding only).**
  - Count: per clip and kind with `A ≥ 1` anchor seconds, `D = max(1, ceil(A / 4))`.
  - Candidates: whole seconds `s` with a frame at `s` and at `s + 0.5`, excluding every anchor second of the clip
    (any kind).
  - Distribution: each decoy, drawn without replacement, comes with probability 0.5 from the candidates within 3 s
    of an anchor of that kind (when there are any) and otherwise uniformly from all candidates.
  - Seed: `random.Random` seeded from SHA-256 of `"c3e-decoy-v1|20261104|<clip>|<kind>"`.
  - Anchors and decoys are merged into one sorted list per item. Packets, images and the review page do not say
    which seconds are anchors; that is recorded only in `sampling.json`, which annotators and reviewers never see.
  - **Decoys are never scored as evidence.** Scoring iterates the predicted evidence entries only; decoy references
    serve blinding and reference-quality statistics (agreement, "none fits" rate).
- **Box packets.** RA1's generator packet (`gen-box-select-v1`) on the item's seconds and its blind validator
  packet (`gen-box-validate-v1`) on the frames 0.5 s later, with RA1's cached OWLv2 proposals for the item's query
  and RA1's `assert_blind`. Agreement between the passes: IoU ≥ 0.5.
- **Held-out sampling** runs once, after C3 Track B completes, with this code and seed unchanged.

## 3. Matching (fixed)

- A predicted evidence entry belongs to a predicted item. It reaches a GT item only through the **final-stage
  one-to-one item matching** of `incident_objects` v1 (the J5 wiring, `evalv2/tasks/pipeline/crops.py`).
- With several GT objects of one kind, the entry is compared **only** with the reference of the GT item its
  predicted item was matched to. No box-based re-matching (choosing the best-overlapping same-kind reference) is
  used for any primary or secondary metric.
- An entry of an unmatched predicted item is reported as **unmatched item**, outside the correct-evidence
  denominator, with its count.
- Diagnostic only, labelled as such: IoU against the best-overlapping same-kind verified reference at that second.

## 4. References and human verification

- **Record `box-references-c3e-v1`** per GT item: clip, kind, item id; `visible_spans`; `boxes` at its sampled
  seconds (0–1000, `[ymin, xmin, ymax, xmax]`, the agent's convention); provenance (detector identity, prompt ids
  and hashes, packet hashes, frame limits, sampler version); tier; review block.
- **Tiers:** `ai_proposed`, `ai_validated` (both passes agree), `human_verified` (a team member reviewed the item's
  intervals and every sampled box). Nothing is `human_verified` before a person has reviewed it.
- **Review (local page, no shared service).** Per clip:
  - interval check with the clip player: accept or set new start and end per item (several spans allowed);
  - per sampled box: accept, redraw, or reject (`not_visible`, `not_identifiable`);
  - order: generator–validator disagreements, "none fits", unclear and flicker flags first.
- **Reviewers** are project team members, configured in `review-config.json` (ids only, no names in code).
- **Second review.** An independent reviewer redoes a 10% sample of items, stratified by split × kind × category,
  seed 20261104, without seeing the first review.
- **Agreement reported:** interval boundaries within 1 s and Cohen's κ on per-second visibility; κ on the
  categorical box decision (accept or redraw versus reject); IoU between the two reviewers' final boxes (median,
  share ≥ 0.5); adjudication outcomes for every disagreement (a third team member or the two reviewers jointly,
  recorded).

## 5. Metrics (per subject, per split)

Uncertainty: 95% CIs by clip-cluster bootstrap, seed 20261027, 10,000 resamples.

- **Primary (human-verified references only).**
  - Correct-evidence rate = located, evidence second inside a verified visible span, and IoU ≥ 0.5 against the
    matched item's verified box at that second; over scorable entries of matched items.
  - Temporal alignment rate (evidence second inside a verified span), reported apart from IoU.
  - Same-second IoU: median, share ≥ 0.5, full distribution.
- **Taxonomy (each entry in one class):** missing evidence (matched item, no entry or no image); not located;
  temporal miss; spatial miss (IoU < 0.5); correct; unscorable (crop-call cap, setup or infrastructure gap, no
  verified box at that second, reference rejected as not identifiable); unmatched item.
- **Reliability (no reference):** evidence success rate, missing images, grounding failures, crop-cap truncation and
  refused calls, unscorable entries by reason.
- **By kind:** entities, instruments, assets separately when a cell has ≥ 20 scorable entries; otherwise counts only.
- **Comparison:** one paired Nano − Super difference in correct-evidence rate on the evaluation split
  (clip-cluster bootstrap, two-sided), its own family.
- **Provisional results** on `ai_validated` references are reported in a separate, labelled table. Missing or
  unscorable references never count as correct.

## 6. Exposure and process record

- **Limited exposure (2026-11-04).** While sizing C3-E, the evaluator counted the evidence entries of the 2 C3
  Track B test items completed before the Switchyard pause: 10 entries, all located. No box, timestamp, IoU, match
  or accuracy value was looked at. Sampling, matching and metrics above were chosen without any other held-out
  prediction result.
- **C3 recovery monitoring (2026-11-04).** The host suspended overnight after health round r4 (00:14), so no round
  ran until 10:00 and the 3-hour notification point passed during the suspension; the owner was notified and asked
  for the checks to continue. `health_loop_v2.sh` continues from r5 with the same check, 30-minute cadence and
  two-consecutive-OK rule, without the 3-hour exit. No other recovery or stop condition changed.
- **Resource rule.** C3's resume script stops the RA1 detector (it resumes from its per-clip cache) before the
  Track B agent starts: one memory-heavy job at a time.
- **Annotation fix before use (2026-11-04).** The first rendering of the dev box frames drew marks with x and y
  swapped (`[ymin, xmin, ymax, xmax]` read as `[x1, y1, x2, y2]`); it was caught on inspection before any packet
  was answered, fixed with a test, and every image was redrawn.

## 7. Freeze

Before held-out scoring: this file (v1.0), the sampler, record builder, review import and scorer code, the
frame-limits file, the prompts, the dev and test `sampling.json`, the verified reference records and the run
directories are hashed into `c3e-freeze-manifest.json`; the owner approves the freeze.
