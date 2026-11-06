# C3-E development results v1: evidence crops on C1b (2026-11-04)

**DEVELOPMENT SPLIT, AI-REFERENCED.** 25 dev clips; C1b Track B runs, historical profile (agent `acbf892ba`,
person and object tracking off: not production). References are C3-E v0.2 AI-consensus and AI-adjudicated
annotations by one model family (Claude). They are **not human-verified ground truth**. IoU measures agreement with
AI reference boxes, not physical accuracy. These are not held-out (C3) results. Reference annotations, thresholds,
matching and scoring were fixed before scoring and were not changed after it. Raw output:
`v2/references/c3e-v1/results/c3e-dev-c1b-v1.json` (private). Script: `scripts/v2_c3e_dev_report.py`.

## 1. Reference coverage at the pipelines' evidence seconds (corrected)

Unit: ground-truth object × evidence second of a located box of that object's kind (anchor), 596 in all.

| Kind | Object-seconds | Box reference (consensus + adjudicated) | "Not visible" reference | Timing-scorable | Visibility unresolved | Box unresolved (timing scorable) | GT identity flag |
|---|---|---|---|---|---|---|---|
| Entities | 479 | 230 (187 + 43) | 40 | 290 | 189 | 20 | 0 |
| Assets | 102 | 53 (32 + 21) | 12 | 76 | 20 | 11 | 6 |
| Instruments | 15 | 6 (0 + 6) | 3 | 9 | 6 | 0 | 0 |
| **All** | **596** | **289 (219 + 70)** | **55** | **375** | **215** | **31** | **6** |

**Reporting correction:** an earlier one-off table (702 object-seconds; instruments 35) counted each object at the
anchors of every kind sharing a second. This table counts each object only at anchors of its own kind
(`tiers/dev/anchor-coverage-v1.json`). The tier records themselves are unchanged.

## 2. Evidence-generation reliability (all entries, no reference needed)

| | Runs | Evidence entries | Located | Not located | No verdict (crop-call cap) | Other image gaps |
|---|---|---|---|---|---|---|
| Nano pipeline | 25 | 346 | 229 | 6 | 111 | 6 |
| Super pipeline | 24 | 150 | 150 | 0 | 0 | 0 |

## 3. Results at IoU ≥ 0.5 (combined consensus + adjudicated references)

Population: 496 entries. Nano: 346 entries, of which 287 belong to predicted items matched to no ground-truth
object (scored by the object metrics, not here). Super: 150 entries, 96 unmatched. 0 matched objects lacked
evidence.

| Model | Kind | Entries of matched items | Scorable (correct-evidence denominator) | Correct-evidence (conditional) [95% CI] | Correct over all matched entries | Box-scorable | Median IoU | IoU ≥ 0.5 | Temporal alignment |
|---|---|---|---|---|---|---|---|---|---|
| Nano | all | 59 | 36 (61%) | **20/36 = 0.56** [0.37, 0.74] | 20/59 = 0.34 | 29 | 0.74 | 20/29 | 34/41 = 0.83 |
| Nano | entities | 34 | 22 | 12/22 = 0.55 [0.30, 0.80] | 12/34 | 19 | 0.73 | 12/19 | 21/24 |
| Nano | assets | 21 | 13 | counts only: 8/13 | 8/21 | 10 | 0.83 | 8/10 | 13/16 |
| Nano | instruments | 4 | 1 | counts only: 0/1 | 0/4 | 0 | — | — | 0/1 |
| Super | all | 54 | 35 (65%) | **20/35 = 0.57** [0.38, 0.76] | 20/54 = 0.37 | 30 | 0.81 | 20/30 | 35/40 = 0.88 |
| Super | entities | 31 | 20 | 15/20 = 0.75 [0.56, 0.91] | 15/31 | 18 | 0.93 | 15/18 | 22/24 |
| Super | assets | 22 | 15 | counts only: 5/15 | 5/22 | 12 | 0.48 | 5/12 | 13/16 |
| Super | instruments | 1 | 0 | counts only: — | 0/1 | 0 | — | — | 0/0 |

Cells with fewer than 20 scorable entries are counts only (pre-registered).

**By reference tier (all kinds):**

| Model | Consensus-only | Adjudicated-only | Combined |
|---|---|---|---|
| Nano | 9/21 = 0.43 [0.22, 0.65] | 11/15 = 0.73 [0.50, 0.94] | 20/36 = 0.56 |
| Super | 12/22 = 0.55 [0.33, 0.77] | 8/13 = 0.62 [0.33, 0.86] | 20/35 = 0.57 |

**Sensitivity (combined):**

| | Nano | Super |
|---|---|---|
| IoU ≥ 0.3 | 22/36 | 23/35 |
| IoU ≥ 0.5 | 20/36 | 20/35 |
| IoU ≥ 0.7 | 18/36 | 20/35 |
| Bounds, unresolved as miss / hit (over matched entries) | 0.34 – 0.73 | 0.37 – 0.72 |
| Excluding all 9 GT-noted items | 20/35 | 18/33 |

**Paired Nano − Super** (pooled correct-evidence rate; clips with scorable entries for both; clip bootstrap, seed
20261027):

| References | Clips | Entries (Nano, Super) | Difference | 95% CI | p |
|---|---|---|---|---|---|
| Combined, IoU 0.5 | 18 | 32, 32 | +0.06 | [−0.11, +0.25] | 0.50 |
| Combined, IoU 0.3 | 18 | 32, 32 | +0.03 | [−0.08, +0.15] | 0.62 |
| Combined, IoU 0.7 | 18 | 32, 32 | +0.03 | [−0.16, +0.22] | 0.78 |
| Consensus-only | 13 | 17, 20 | +0.03 | [−0.19, +0.24] | 0.80 |
| Adjudicated-only | 7 | 10, 8 | +0.18 | [0.00, +0.43] | 0.23 |

**How the paired estimate differs from the aggregates.** The paired estimate uses only the 18 clips where both
models have scorable entries (32 entries each). On those clips Nano is 19/32 = 0.594 and Super 17/32 = 0.531, so
Nano − Super = +0.06. Over all their clips (20 each) the conditional rates are 20/36 = 0.556 and 20/35 = 0.571, a
difference of −0.02. Both are inside the noise; neither direction is a finding.

**Two different questions.** *Conditional correct-evidence* (0.56, 0.57) asks: when an evidence entry belongs to a
matched object and a scorable AI reference exists, is it correct? *Pipeline reliability* asks how often the pipeline
produces usable evidence at all: Nano left 111 of 346 entries without a locate verdict (crop-call cap) and 287 of
its entries belong to unmatched predicted items; Super located all 150 entries, 96 of them for unmatched items.
Correct evidence over all matched entries (0.34, 0.37) mixes both.

## 4. What the development results support

- **Supported:** on matched objects with a scorable AI reference, both historical pipelines put the evidence box on
  the AI-referenced object at a visible second about half the time (0.56 and 0.57). When the second is visible and
  a reference box exists, the box agrees with it at IoU ≥ 0.5 about two-thirds of the time (median IoU 0.74–0.81).
  Evidence timing falls in a visible second in 83–88% of timing-scorable entries.
- **Supported:** reliability differs. Nano produced more than twice as many evidence entries as Super, most for
  items matched to no ground-truth object. A third of Nano's entries got no locate verdict because the crop-call cap
  (40) was reached; Super located every entry.
- **Not supported:** any difference in evidence correctness between Nano and Super. The paired difference is
  small, its CI spans zero, and only 32 paired entries on 18 clips exist.
- **Not supported:** per-kind conclusions for assets and instruments (under 20 scorable entries); the entity gap
  (Super 0.75, Nano 0.55) rests on about 20 entries each and is indicative only.
- **Not supported:** any claim about held-out performance, production (tracking on), human-verified accuracy, or
  the 40% of matched entries without a scorable reference (bounds 0.34–0.73).
- The adjudicated-only subset scores higher than consensus-only for Nano (0.73 vs 0.43). On 15 and 21 entries this
  may be chance or a selection effect (adjudication resolves easier identities). It is not a finding.

## 5. Ground-truth discrepancy audit (notes v1; GT v1.0 unchanged)

**Public archive note:** the per-item table is omitted here because it quotes private ground-truth content. It is kept in the private evaluation data (`ground_truth/ground-truth-v1.0-c3e-notes-v1.json`). Scores, denominators and rules are unaffected.

One blind AI check per noted item, against the clip's frames. Outcomes are AI judgements, not verified corrections. Items whose identity wording was contradicted were treated as unresolved in C3-E, and GT v1.0 was not changed. Excluding all 9 noted items changes the combined results by at most 2 entries (sensitivity row above).
