# Dev selection: object-matching threshold

> **Decision: retain tau = 0.40.** One common threshold; no per-model or per-kind value.
> Written 2026-11-05 from dev evidence only, before any evaluation-half sweep of this study. Rule: [`selection-rule.md`](selection-rule.md), SHA-256 `9d7cb97d67bb6bf3d8aa1e7c9de76f4bfe69c01c3e57ec0a375014fe51588ecf`, fixed before the dev sweep. Sealed in `selection-ledger.json`.

**Not a blind choice.** The author had read the calibration table and earlier audit figures for the evaluation half (Nano and Gemma entity F1 at 0.30 to 0.50). The replay check at 0.40 also ran on the evaluation half first, at 0.40 only. What is sealed is that this study's evaluation-half sweep did not feed the decision.

**Dev data:** 25 clips, 5 models, 2 repeats: 250 rows, 249 with model output. Gemma's and Qwen's dev rows are in `c1e-openrouter-gemma4-31b` and `c1f-openrouter-qwen35-9b`, not `c1a`, so those two runs were added.

**Labels:** 140 sampled dev pairs (seed 20261105), labelled by one AI reader from stored texts, blind to similarity, band, model and clip. **Not human.** Text alone leaves many pairs undecidable (62 of 140 `cannot_tell`).

## Gates on the pairs newly accepted in [tau', 0.40)

| tau' | Precision [95%] | Decided-only | Entities / assets / instruments | Lowest model | L4: object gain in all 4 models | Calibration F1 (0.40: 0.814) | Gates passed |
|---|---|---|---|---|---|---|---|
| 0.35 | 0.412 [0.153, 0.618] | 0.909 | 0.461 / 0.400 / 0.222 (n=7) | 0.263 | No: Omni +0.013, Gemma interval touches 0 | 0.787 | None |
| 0.30 | 0.356 [0.155, 0.521] | 0.671 | 0.422 / 0.200 / 0.154 | 0.200 | Yes | 0.812 | L4, L6 |
| 0.25 | 0.302 [0.158, 0.443] | 0.573 | 0.362 / 0.154 / 0.125 | 0.175 | Yes | 0.788 | L4 |
| 0.20 | 0.272 [0.149, 0.408] | 0.504 | 0.360 / 0.083 / 0.111 | 0.140 | Yes | 0.788 | L4 |

- **Required:** L1 precision >= 0.75 with lower bound >= 0.60. Every candidate fails L1, L2, L3 and L5.
- **0.45:** precision of [0.40, 0.45) is 0.535 [0.308, 0.785]. Raising needs <= 0.50 with upper bound <= 0.65, so it fails.
- **Sensitivity (cannot-tell left out):** 0.35 would pass L1 on precision (0.909), but it still fails L4 and L6, so the decision does not depend on how those pairs are counted.

**Result:** no candidate passes, so the rule retains 0.40.
