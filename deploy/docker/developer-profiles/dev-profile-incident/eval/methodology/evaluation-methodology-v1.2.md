# Evaluation Methodology v1.2 (proposed)

> **Status: PROPOSED, not in force.** Version id `evaluation-methodology-v1.2`. The owner approved its preparation on 2026-10-28 (Stage 1 review, option S2-A (b)). It takes effect only after the owner approves the calibrated rule below. Until then `methodology.METHODOLOGY_VERSION` stays `evaluation-methodology-v1.1`, and every v1.1 result is kept unchanged. Results of different versions are never pooled.

## The one change: the item-matching threshold

| Instrument | v1.1 | v1.2 |
|---|---|---|
| Item-matching acceptance threshold (entities, instruments, assets) | cosine ≥ 0.75 (`config.MIN_MATCH_SIMILARITY`), set a priori | cosine ≥ **τ**, calibrated on a labelled dev pair set by the rule below (`methodology.MATCH_THRESHOLDS["evaluation-methodology-v1.2"]`) |

**Unchanged:**
- **Matching:** the embedder (MiniLM-L6-v2), the embedded texts (`type description` for entities, `name description` for instruments and assets), and one-to-one Hungarian assignment within one clip and one kind.
- **Counts:** TP, FP and FN, pooled P/R/F1.
- **Matched-pair attribute scoring:** entity type, threat, holder and the judged descriptions.
- **Everything else:** the incident fields, the judge and its limits, failures, aggregation and intervals, as in v1.1.
- **D9 v2:** weights, components, guardrails and the `+0.02` minimum are unchanged. Its implementation only gains a G3 check that both records use the same methodology version and protocol.

## Why

Stage 1 found that at 0.75 almost no pair matches, even clear same-item pairs (cosine about 0.6–0.7). Entity, instrument and asset F1 are therefore about 0–0.06 in both arms ([Stage 1](../docs/experiments/stage1-baselines.md#entities-instruments-and-assets-pooled-prf1)). 0.75 was never calibrated for these description styles. A threshold that rejects true matches turns two of D9's three components into noise.

## Calibration procedure (fixed before any label or similarity was looked at)

1. **Data: dev only.** The Stage 1 baseline results, both arms, on the 25 dev clips. No test clip, test prediction or Stage 2 output is ever used (`matching_calibration.eligible_blocks` refuses a non-dev record).
2. **Unit: a block.** One video-run's predicted items and ground-truth items of one kind. Every pair in the block is labelled, so the matcher can be evaluated exactly as it runs: assignment inside a block.
3. **Sampling** (`matching_calibration.sample`, seed 20261028):
   - **Eligibility:** blocks with items on both sides and at most 9 pairs.
   - **Selection:** shuffled per kind, at most one block per clip and kind, until the pair quotas are met (entities 25, instruments 12, assets 25).
   - **Never by similarity.**
   - **Result:** 22 blocks and 70 pairs (entities 30, instruments 15, assets 25) over all five categories.
   - **Difficult pairs** come naturally: same-clip, same-kind items that are different (hard negatives) and loosely described true matches.
4. **Labels, blind to similarity:**
   - Each pair is `same` (the same person, animal or object in the clip), `different` or `ambiguous`.
   - The label sheet shows only the texts and ids: no score, model or arm.
   - **First labeller:** an AI labeller that has not seen any similarity value, working from the texts and the clip's frames. Its labels are **provisional**.
   - **Human audit:** before v1.2 is put in force, a person audits at least 20 pairs (all `ambiguous` ones, every pair whose label disagrees with the matcher at the selected τ, and a random rest). The agreement is reported. A person's label overrides the AI label, and τ is re-derived by the same rule.
5. **Candidates:** τ from 0.30 to 0.80 in steps of 0.05.
6. **Scoring a candidate** (`matching_calibration.score_threshold`):
   - Run the unchanged matcher on every block at τ.
   - **TP:** an accepted pair labelled `same`. **FP:** an accepted pair labelled `different`. **FN:** a `same` pair not accepted.
   - `ambiguous` pairs are left out (primary). As a sensitivity check they are counted as `same`, then as `different`.
   - Reported: P/R/F1 pooled and per kind, a 95% block-bootstrap interval for the pooled F1, and the false-match examples.
7. **Selection rule** (`matching_calibration.select_threshold`): the τ with the highest pooled F1. Every τ within 0.01 of the best goes to the **higher** τ (favouring precision). One τ for all kinds.
   - A per-kind τ is adopted only if a kind's own best F1 beats the pooled τ's F1 for that kind by more than its bootstrap interval. That decision is recorded.
   - **Stage 1 model scores are never an input.**

## Limitations

- **Small:** 70 pairs from 25 clips. The interval on F1 is reported, and τ is a point estimate.
- **Distribution:** the pairs come from the baseline prompt's outputs. A Stage 2 prompt that writes very differently could match differently at the same τ. All Stage 2 versions are scored with the same τ, so there is no differential bias between versions.
- **Labels:** AI-labelled pairs are provisional until the human audit. The ground truth is itself AI-assisted and approved at the dataset level ([freeze README](../ground_truth/freeze/README.md#ground-truth-v10-as-frozen-limitation)).
- **Dev reuse:** calibration and Stage 2 selection both use the dev split. The calibration set fixes τ once, before any Stage 2 output exists. Selection then compares versions under that fixed τ.

## Calibration result

**Provisional (2026-10-28), from AI labels:**
- **The rule selects τ = 0.30.** Pooled F1 0.857, 95% interval [0.69, 0.98]; precision 0.857, recall 0.857. The v1.1 value 0.75 gives F1 0.091 on the same pairs.
- **Caveats:** 0.30 is the lowest value on the grid, and the sample excludes blocks of more than 9 pairs (half of the dev pairs).
- **Still needed:** the human audit and the owner decisions listed in [`calibration/matching-v1.2-calibration.md`](calibration/matching-v1.2-calibration.md). `methodology.MATCH_THRESHOLDS` holds the provisional value, and `MATCH_THRESHOLD_PROVISIONAL` marks it.
