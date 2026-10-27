# Prompt experiments (PR 6A runner)

`experiment_runner.py` and `scripts/eval_experiment.py` run one **configuration** per config file in `configs/`. A configuration is an arm (`direct-vlm` or `vss`), a registry prompt, a model, a split half (`dev` or `test` of `split-v2`), the frozen ground truth, repeats and a P1 call budget. Plan: [`.docs/mvp2/ground-truth-and-prompt-experiments-plan.md`](../../.docs/mvp2/ground-truth-and-prompt-experiments-plan.md) §F.

```bash
uv run python scripts/eval_experiment.py plan configs/…json            # the plan and every guard; no calls
uv run python scripts/eval_experiment.py run  configs/…json --confirm-paid   # only after the stage budget is approved
uv run python scripts/eval_experiment.py rescore <results.json> --confirm-paid  # judge calls only, no P1
uv run python scripts/eval_experiment.py compare C1=… C2=… C3=… C4=…    # the four paired comparisons, offline
uv run python scripts/eval_experiment.py report --title "…" C1=… C2=…   # Markdown report from saved results
uv run python scripts/eval_experiment.py verify <results dir>           # reproducibility check of one run
uv run python scripts/eval_experiment.py budget configs/*.json [--pilot measured.json]   # call volume (and cost once measured)
uv run python scripts/eval_experiment_plumbing.py                       # Stage 0 step 1: offline C1–C4, scripted model
```

Readiness, the budget statement and the approval gates: [`docs/experiments/readiness.md`](../docs/experiments/readiness.md).

## Fairness

- **Same request:** both arms send the same P1 request, with the same prompt text, `inference.json` settings and signed URL.
- **Same policy and scoring:** both run under the same rate-limit policy. Both are re-validated by `contract.evaluate_policy` and scored by the same scorer against the same frozen ground truth.
- **The VSS arm** calls the agent's `/analyze` (experimental settings documented in [`vm-api-contracts.md`](../../.docs/vm-api-contracts.md#experimental-settings-prompt-experiments-pr-6b); the agent must run with `INCIDENT_EXPERIMENTS_ENABLED=1` and without Supabase or R2 settings) with `skip_rp1: true`, `skip_crops: true` and, for a non-baseline prompt, `experiment_prompt_id`.
  - A 200 response, or a 422 with a `raw_output`, is a model output. Anything else is a request failure (eval.md §4).
  - A non-baseline prompt counts only when the agent echoes the prompt id and SHA-256 it used. Otherwise the attempt fails, so a VSS run can never silently use the production prompt.

## Guards

Every guard runs before any call:

| Guard | Rule |
|---|---|
| Test split | Only for `final: true` with a `selection_record` that is an existing `### ` heading in `.docs/decisions.md` |
| Frozen baseline | A `frozen_baseline` config with a completed run is never rerun. Re-score its saved outputs instead |
| Budget | Videos × repeats must not exceed `budget.max_p1_calls` |
| Paid calls | `run` and `rescore` send nothing without `--confirm-paid` |
| Ground truth | Must be frozen. A candidate needs `ground_truth.allow_candidate` (plumbing only), and every result is then marked `reportable: false` |
| Accuracy runs | `skip_rp1` and `skip_crops` must be true. Cropping belongs only to the separate end-to-end profile |

Results are written to `eval_data/results/experiments/<id>/<UTC time>/` as `results.json` (every §F.4 field) and `prompt.txt`. They are immutable and gitignored.

## The committed configs

| Config | Stage | What |
|---|---|---|
| `pilot-direct-vlm`, `pilot-vss` | 0 (paid pilot) | `p1-v4-base`, 1 dev clip per category (`videos`), repeats 1 |
| `pilot-vss-crops` | 0 (paid pilot) | 2 dev clips with cropping on (`profile: end-to-end`): crop cost and end-to-end latency only |
| `direct-vlm-baseline` | 1 | C1 on dev, frozen after its first complete run |
| `vss-baseline` | 1 | C2 on dev, local agent per D14 (b) |

`videos` (optional) narrows a config to a subset of its split half and refuses clips outside it. `repeats` and budgets follow plan D10/D11 and are **placeholders until those decisions and each stage's budget are approved**. C3/C4 configs are written only after the Stage 2 selection is recorded in decisions.md.

## Reports and selection

- **`render`:** a report over any result on candidate ground truth carries a NOT REPORTABLE banner. Inference latency and end-to-end latency are separate tables.
- **Paired comparisons:** the C3−C1 comparison is shown as the sum (C3−C4) + (C4−C1), with the plan's interpretation limits and held-out exposure disclosure.
- **`select`:** applies a selection rule only to dev, reportable records, and only when the rule is an existing decisions.md heading. Plan D9 (the rule itself) is not decided by this code, and test results can never feed selection.
