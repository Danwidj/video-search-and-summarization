# Prompt experiments (PR 6A runner)

`experiment_runner.py` and `scripts/eval_experiment.py` run one **configuration** per config file in `configs/`. A configuration is an arm (`direct-vlm` or `vss`), a registry prompt, a model, a split half (`dev` or `test` of `split-v2`), the frozen ground truth, repeats and a P1 call budget. Plan: [`.docs/mvp2/ground-truth-and-prompt-experiments-plan.md`](../../.docs/mvp2/ground-truth-and-prompt-experiments-plan.md) §F.

```bash
uv run python scripts/eval_experiment.py plan configs/…json            # the plan and every guard; no calls
uv run python scripts/eval_experiment.py run  configs/…json --confirm-paid   # only after the stage budget is approved
uv run python scripts/eval_experiment.py rescore <results.json> --confirm-paid  # judge calls only, no P1
uv run python scripts/eval_experiment.py compare C1=… C2=… C3=… C4=…    # the four paired comparisons, offline
```

## Fairness

- **Same request:** both arms send the same P1 request, with the same prompt text, `inference.json` settings and signed URL.
- **Same policy and scoring:** both run under the same rate-limit policy. Both are re-validated by `contract.evaluate_policy` and scored by the same scorer against the same frozen ground truth.
- **The VSS arm** calls the agent's `/analyze` with `skip_rp1: true`, `skip_crops: true` and, for a non-baseline prompt, `experiment_prompt_id`.
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

`direct-vlm-baseline` (C1 on dev, frozen after its first run) and `vss-baseline` (C2 on dev, local agent per D14 (b)). Their `repeats: 2` and `max_p1_calls: 50` follow plan D10/D11 and are **placeholders until those decisions and the Stage 1 budget are approved**.
