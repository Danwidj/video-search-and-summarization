# Annex slide: Does the 0.50 description threshold drive our conclusions?

**Exploratory, post hoc. 0.50 remains the primary metric.**

- Lowering 0.50 to 0.40 moves 14 descriptions: +3 to +6 points per model.
- The four complete models keep the same order at every threshold from 0.30 to 0.70. Gemma ranks first in 90–96% of resamples.
- Near-cutoff descriptions are mixed: of the 14, an AI reading found 9 plausibly acceptable and 3 likely wrong.
- The judge itself is noisy: 4 of 31 repeat pairs flip at 0.50.

| Model (valid) | At 0.50 | At 0.40 |
|---|---|---|
| Gemma 4 31B (65) | 0.646 | 0.692 |
| Nemotron 3 Nano Omni (63) | 0.508 | 0.571 |
| Qwen3.5-9B (64) | 0.406 | 0.469 |
| Cosmos 3 Nano (95) | 0.295 | 0.326 |
| Cosmos 3 Super (26, incomplete) | 0.423 | 0.423 |

**Chart:** `plots/pass_rate_vs_threshold.png`.

**Takeaway:** conclusions do not depend on the cutoff. Better calibration needs human labels, not a new number.
