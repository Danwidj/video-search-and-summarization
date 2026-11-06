# C3-E pre-registration v0.2: AI-referenced evidence-crop evaluation (PROPOSED, 2026-11-04)

**Status:** proposal for the owner's approval. It replaces v0.1's human-verified primary metric with an
**AI-referenced** one; human review becomes optional. v0.1 ([`c3e-preregistration.md`](c3e-preregistration.md)) was
never frozen and is kept as history. C3's pre-registration, freeze manifest (`eb316f37…`), configs and amendments
A1–A4 are unchanged. Everything in v0.1 §1–§3 (subjects, splits, sampling, decoys, matching) and §6 (exposure and
process record) still applies unless changed below.

**What C3-E can claim:** agreement between the pipelines' evidence and **AI-generated reference annotations**. It
does not establish physical bounding-box accuracy. No reference is human-verified.

## 1. Inputs kept as they are

- RA1 OWLv2 proposals (37 + the clips still running), frame limits, the sampler (`c3e-sampler-v1`, seed 20261104).
- Visibility passes for all 80 clips, generator on even seconds and blind validator on odd seconds (160 answers).
- Dev box passes (89 items, 782 frames, generator and blind validator).
- Every answer, packet hash and disagreement stays on disk. Later passes write new files and never overwrite.

## 2. Added automated steps

1. **Extra candidate boxes (local, no API).** Seconds where the generator found no mark covering the item get a
   second OWLv2 run with **descriptive queries**: the ground-truth name plus description nouns, for example
   "wooden stick held in a hand" instead of "stick". It uses the same pinned weights, threshold 0.05 and top-k 5
   per query, and caches to `proposals-c3e-extra/`; RA1's cache is never touched. These seconds are the generator's
   "none fits" and validator-only seconds; the validator-only ones are the second variant noted in §5. An optional
   second localiser (Grounding DINO, Apache-2.0) needs a separate approval for its weights. Candidates never come
   from the evaluated VSS pipeline.
2. **Re-pass on augmented frames.** Frames that gained candidates go through new blind generator and validator
   packets (`c3e2-…`, same prompts) with the union of RA1 and extra proposals, renumbered.
3. **Box adjudication (`gen-box-adjudicate-v1`, new prompt).** A fresh, blind Claude context gets:
   - the frame at the second, with up to three numbered candidates: the generator's choice; the validator's choice
     mapped to the same second (the detector proposal at that second with the highest IoU to it, used only when
     that IoU is at least 0.3); and the best extra candidate;
   - the frames one second before and after, unmarked, for identity;
   - the ground-truth words.

   It answers with a number, "not visible", or "cannot identify". Each question is asked **twice with the
   candidate order and numbers swapped**. A box is adjudicated only when both answers name the same box with
   confidence ≥ 0.6. This counters the position bias the earlier AI review adjudicator showed. Neither VSS
   predictions nor which pass chose which box are shown.
4. **Visibility adjudication (`gen-visibility-adjudicate-v1`, new prompt).** Items without consensus get 2x2
   sheets at higher resolution (768 px tiles) of their unclear and conflicting seconds, at most 12 seconds per
   item, in time order. Each sheet is asked twice with tile order shuffled, and must be consistent.
   Seconds are chosen by a fixed rule: every non-consensus box-sampled second first (anchors and decoys, not told
   apart), then evenly spaced non-consensus seconds, up to 12 in all; seconds with a consensus box are visible and
   are not asked. The evaluation split's sampled seconds exist only after C3 Track B, so its first adjudication
   covers the evenly spaced seconds, and a **supplementary adjudication** (same prompt, rule and thresholds) covers
   its non-consensus sampled seconds once they are drawn. The two orders go to different annotator contexts.
5. **Ground-truth discrepancy check.** The 9 flagged items get one adjudication-style pass that reads the
   ground-truth words against frames. Outcomes ("confirmed discrepancy", "not confirmed", "cannot tell") go into
   `ground-truth-v1.0-c3e-notes-v1.json`, a separate versioned record. GT v1.0 is never edited. An item with a
   confirmed identity discrepancy is unresolved in C3-E.

## 3. Reference-quality tiers (per item and second; fixed before any held-out scoring)

**Visibility at second *s*:**

| Tier | Rule |
|---|---|
| AI consensus | The pass that sampled *s* voted clearly (yes or no), and at least one neighbouring second of the other pass agrees. Or both box passes chose agreeing boxes at *s*, which counts as visible |
| AI adjudicated | Not consensus, but the visibility adjudicator gave the same clear answer in both orders |
| Unresolved | Otherwise. Temporal alignment at *s* is unscorable |

**Box at an anchor second *s* (only where *s* is visible at consensus or adjudicated tier):**

| Tier | Rule |
|---|---|
| AI consensus | Both passes chose a box and the IoU between them is ≥ 0.5 (validator at *s* + 0.5). The reference is the generator's box at *s* |
| AI adjudicated | Not consensus, and the box adjudicator chose the same box in both orders with confidence ≥ 0.6 |
| Unresolved | Otherwise, with its reason recorded: no candidate, cannot identify, adjudicator inconsistent, or not visible. IoU at *s* is unscorable |

**Identity:** a reference exists only when the item was identified at that tier. "Cannot identify" is never turned
into a box. Records keep their schema tier (`ai_proposed` or `ai_validated`, never `human_verified`); the C3-E tier
is stored per second in the payload (`visibility_tiers`, `box_tiers`) with the evidence behind it.

## 4. Metrics and reporting (v0.1 §5, with these changes)

- **Primary: correct-evidence rate on combined scorable references** (consensus plus adjudicated). Correct means
  the matched object is located, the second is visible, and IoU ≥ 0.5. Missing predicted evidence for a scorable
  reference is a pipeline failure; an unresolved reference is unscorable, never correct.
- **Reported side by side:** consensus-only, adjudicated-only and combined. Every metric shows its numerator,
  denominator and coverage (scorable ÷ all evidence entries).
- **Also reported:** temporal alignment separately; same-second IoU (median, share ≥ 0.5, distribution);
  reliability (evidence success, missing images, grounding failures, crop-cap truncation, unscorable reasons);
  results by kind when a cell has ≥ 20 scorable entries; and one paired Nano − Super difference on the held-out
  split when both have ≥ 20 paired scorable entries.
- **Sensitivity:**
  - IoU thresholds 0.3, 0.5 and 0.7;
  - tier subsets;
  - bounds with every unresolved entry taken as a miss and as a hit (labelled bounds, not estimates);
  - excluding the GT-discrepancy items.
- **Reference quality:**
  - visibility κ between passes at adjacent seconds;
  - the distribution of pass-to-pass IoU;
  - adjudication consistency (the swap-agreement rate);
  - "none fits" and unresolved rates by kind;
  - tier counts.
- Uncertainty: clip-cluster bootstrap (seed 20261027, 10,000 resamples).

**Required statements in the report:**
- References are AI-generated and not human-verified.
- IoU measures agreement with AI reference boxes, not verified physical ground truth.
- Adjudication does not establish correctness.
- Annotators and adjudicator are one model family (Claude), so their errors may be correlated.
- Results are biased toward objects automated methods can find (instruments especially).
- Historical C1b profile, tracking off: not production.

## 5. Independence safeguards

- No annotator or adjudicator sees VSS predicted boxes, scores or matches. Anchors are mixed with decoys, and which
  seconds are anchors stays in `sampling.json`.
- Thresholds, prompts and tier rules are frozen (C3-E manifest) before held-out anchors are drawn. They are
  calibrated only on **dev reference agreement**, never on prediction accuracy.
- Box choice never depends on evaluation scores. Every disagreement and both adjudication answers are kept.
- If a category cannot get reliable references (expected for instruments), it is reported as a limitation with
  counts, never forced into a score.
- Held-out frames go only to Claude in Claude Code and to local models, never to an external review model.

## 6. Freeze

Before held-out scoring: this file (v1.0), prompts, sampler, extra-localiser identity, tier code, scorer, frame
limits, the dev and test `sampling.json`, the reference records and the run directories are hashed into
`c3e-freeze-manifest.json`, and the owner approves the freeze.
