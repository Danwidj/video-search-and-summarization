# Prompt experiments: readiness and budget statement

> **Superseded for decisions by [`experiment-decision-record.md`](../../../.docs/mvp2/experiment-decision-record.md)** (D9 v2 proposed; D10 and D15 approved; D11 caps enforced, with dollar limits provisional; Stage 0 prepared, with 10 calls and no crop pilot). Status 2026-10-27. The Stage 0 pilot has run ([results](stage0-pilot.md)); no later stage has. This page states what is ready, the call volume of each stage, and the approvals each stage needs (plan §F.2, D9–D11, D15). Tokens and cost are unknown until the Stage 0 paid pilot measures them.

## Ready

| Piece | State | Where |
|---|---|---|
| Prompt registry | `p1-v4-base` (= production prompt), append-only | [`contracts/experiments/`](../../../contracts/experiments/README.md) |
| Runner, both arms | Same P1 request, policy, validator and scorer. Guards: test split, frozen baseline, budget, `--confirm-paid`, frozen ground truth, crops and RP1 off, VSS prompt echo | [`experiments/README.md`](../../experiments/README.md) |
| Agent hooks | `experiment_prompt_id`, `skip_crops`, P1 timing and usage, behind `INCIDENT_EXPERIMENTS_ENABLED=1`, never persisted | [`vm-api-contracts.md`](../../../.docs/vm-api-contracts.md#experimental-settings-prompt-experiments-pr-6b) |
| Reports | Configurations, fields with CIs, severity, items, reliability, inference vs end-to-end latency, the four paired comparisons, limits and exposure disclosure. A NOT REPORTABLE banner on candidate ground truth | `experiment_report.render`, `eval_experiment.py report` |
| Reproducibility | `results.sha256`, prompt bytes vs registry, config hash, ground-truth digest, split and call count | `eval_experiment.py verify` |
| Selection guard | Dev records only, frozen ground truth only, and the rule must be a pre-registered decisions.md heading | `experiment_report.select` |
| Stage 0 step 1 (offline plumbing) | **Done.** C1–C4 on the 25 dev clips with a scripted model, a fake judge and a fake embedder: 100/100 scored, `verify` clean, no configuration problems, report marked NOT REPORTABLE | `scripts/eval_experiment_plumbing.py` |

The plumbing run checks the machinery, not a prompt. Its scripted baseline over-rates severity on one dev clip in three. The comparisons find this as +0.32 in C3−C2 and C4−C1 (95% CI [0.16, 0.52]), with 0.00 pipeline effect (C2−C1, C3−C4), as intended.

## Call volume per stage

P1 counts follow from the configs and the split. Judge calls are estimated at about 5 per scored video-run (plan D11) until the pilot counts them. Accuracy runs make no crop calls.

| Stage | Configs | P1 calls | Judge calls (est.) | Crop (box) calls | Approval needed before it runs |
|---|---|---|---|---|---|
| 0 pilot | `pilot-direct-vlm` (5), `pilot-vss` (5), `pilot-vss-crops` (2) | 12 | ≈ 60 | ≈ 10–40 (2 clips, crops on) | **Pilot budget**, plus a local experiment agent with `INCIDENT_EXPERIMENTS_ENABLED=1` and no Supabase or R2 settings |
| 1 baselines | `direct-vlm-baseline` (25 × 2), `vss-baseline` (25 × 2) | 100 | ≈ 500 | 0 | Stage 1 budget (from the pilot's measured figures), D10 (repeats) |
| 2 prompt engineering | about 8 VSS-arm versions × 25 × 2 | ≈ 400 | ≈ 2,000 | 0 | Stage 2 budget, **D9 selection rule pre-registered** before the first dev run |
| 3 held-out | C1–C4 × 55 × 2 | 440 | ≈ 2,200 | 0 | Stage 3 budget, a decisions.md selection record (the runner's test guard), D15 |
| End-to-end profile | C2, C3 × 15 test clips | 30 `/analyze` | – | ≈ 150–600 | With Stage 3 |
| Optional transfer | 2 models × C1, C4 × 55 | +220 | ≈ +1,100 | 0 | Separate approval |

After the pilot, `uv run python scripts/eval_experiment.py budget experiments/configs/*.json --pilot <measured.json>` prices each config. The `measured.json` file holds `tokens_per_p1_call`, `cost_per_p1_call` and `cost_per_judge_call`.

## What blocks Stage 1

1. **Frozen ground truth.** `ground-truth-v1.0` is a candidate: 98 entries are Pending human review, and there is no approval record ([readiness](../../ground_truth/freeze/ground-truth-v1.0-readiness.md)). The runner refuses unfrozen ground truth for real runs.
2. **Stage 0 pilot budget approval**, then the pilot itself and its measured tokens and cost.
3. **Decisions D9, D10, D11, D15** (plan §H). Their recommendations are not adopted by this code.
