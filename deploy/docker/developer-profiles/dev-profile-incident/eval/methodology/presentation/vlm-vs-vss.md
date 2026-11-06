# Direct VLM versus VSS

Every number comes from `data/` or the raw V1 report. Sources are listed under each table. Super-dependent rows must be re-read if `README.md` says the Super gate reopened.

## Slide A: baseline VLM versus baseline VSS

**Title:** With the same request, the baseline VSS path matched direct calls.

**Setup.** V1 Stage 3 on the 55 test clips (held out from prompt selection, previously exposed). One repeat. Model Cosmos 3 Super. Frozen prompt `p1-v4-base`. Contract v4.

**What "VSS" means here.** A transport wrapper: agent hop, `stream: false` and a bounds check. Captions and zoom did not exist in that code. Crops were off. The agent's RP1 was off, although the shared harness still generated an RP1 report after scoring in both arms, so extraction scores are unaffected.

| Metric | C1 direct VLM | C2 baseline VSS | C2 − C1 paired, 95% CI | Status |
|---|---|---|---|---|
| Valid outputs (recovery-adjusted) | 55/55 | 53/55 | not tested | final, historical |
| D9 primary ΔI | n/a | n/a | −0.0066 [−0.0364, +0.0241] | final, historical; primary |
| Type accuracy, valid | 0.836 [0.727, 0.927] (n=55) | 0.815 [0.704, 0.907] (n=54) | −0.0185 [−0.0566, 0.0000] | final, historical |
| Severity MAE (v1.3) | 0.9273 (n=55) | 0.8679 (n=53) | −0.0189 [−0.1132, +0.0755] | final, historical |
| Start ±5 s | 0.691 | 0.722 | +0.0185 [0.0000, +0.0566] | final, historical |
| End ±5 s | 0.582 | 0.593 | 0.0000 [−0.0556, +0.0556] | final, historical |
| Entity F1 (pooled; paired is per clip) | 0.482 | 0.490 | +0.0043 [−0.0661, +0.0809] | final, historical |
| Instrument F1 | 0.065 | 0.167 | +0.0513 [0.0000, +0.1667] (13 pairs) | final, historical; too few items |
| Asset F1 | 0.285 | 0.219 | −0.0205 [−0.0495, +0.0065] | final, historical |
| Model time p50 | 22.67 s | 21.62 s | not tested | final, historical |
| VSS overhead p50 / p95 | n/a | 0.01 / 0.05 s | n/a | final, historical |

Same contrast with the V1 prompt (C3 − C4): ΔI +0.0231 [−0.0031, +0.0500]. No ΔI excludes zero.

**Interpretation.** No difference was detected, which is what a wrapper around an identical request should show. Equivalence is not established: no margin was set, and effects under about 0.03–0.04 are undetectable.

**Caveat.** This did not test captions, grounding or zoom.

**Sources:** `eval_data/results/reports/stage3/recovery-adjusted-v1/stage3-report.json` (`configs.*`, `comparisons["C2-C1"]`), `docs/experiments/final-report.md` §6–7, `evidence/vlm-vs-vss-evidence.md` §3 (raw-verified by re-running `compare`).

## Slide B: final VLM versus final VSS

**Title:** The latest VSS matched direct Nano on accuracy, at about 3× the tokens and 9× the latency.

**What this is.** A new matched experiment, frozen before its first call (`../v2-final-comparison-plan-v1.md`, plan hash `2f59d49c…`). It is not an original C3 run and it is not production. Clips were previously exposed. VSS arm: agent `9f39b5706` (origin/main), Nano in every model slot, captions, grounding, object tracking (NanoTrack) and zoom on, person tracking off. Direct arm: stored C3 Nano. Same 55 clips, 2 repeats, prompt `p1-v4-base`, contract v4, scorer and judge.

| Metric | Direct VLM | VSS final | Difference, VSS − direct | 95% CI / significance | Family |
|---|---|---|---|---|---|
| Type accuracy, end to end (110 pairs) | 0.673 | 0.709 | +0.036 | [−0.036, +0.118]; Holm p 0.861 | Primary |
| Object score, end to end (110 pairs) | 0.427 | 0.437 | +0.010 | [−0.044, +0.065]; Holm p 0.861 | Primary |
| Severity MAE, both valid (91 pairs) | 0.813 | 0.714 | −0.099 | [−0.233, +0.022]; Holm p 0.412 | Primary |
| Type accuracy, both valid | 0.780 | 0.813 | +0.033 | [−0.022, +0.106]; Holm p 1.0 | Secondary |
| Object score, both valid | 0.456 | 0.476 | +0.020 | [−0.040, +0.078]; Holm p 1.0 | Secondary |
| Entity F1, end to end | 0.431 | 0.498 | +0.067 | [−0.023, +0.159]; Holm p 1.0 | Secondary |
| Asset F1, end to end | 0.448 | 0.393 | −0.055 | [−0.126, +0.019]; Holm p 1.0 | Secondary |
| Instrument F1, end to end | 0.286 | 0.245 | −0.041 | [−0.209, +0.224]; Holm p 1.0 | Secondary |
| Start error, s (both valid) | 5.25 | 5.65 | +0.40 | [−2.30, +3.34]; Holm p 1.0 | Secondary |
| End error, s (both valid) | 11.04 | 7.26 | −3.78 | [−12.05, +1.15]; Holm p 1.0 | Secondary |
| Description pass (both valid, provisional) | 0.297 | 0.330 | +0.033 | [−0.065, +0.133]; Holm p 1.0 | Secondary |

**Efficiency and reliability, per video**

| Metric | Direct Nano | VSS final | Ratio |
|---|---|---|---|
| Tokens, median (answered) | 9,922 | 28,500 | 2.9× |
| Input / output tokens, median | 9,225 / 616 | 26,144 / 2,457 | 2.8× / 4.0× |
| Latency p50 / p95, answered | 7.85 / 104.2 s | 69.13 / 153.44 s | 8.8× / 1.5× |
| Latency p95, all attempts | 125.26 s | 188.68 s | 1.5× |
| Attempts | 185 for 110 replies | 110 for 110 replies | not like for like |
| Timeouts / rate limits | 41 / 18 | 0 / 0 | different days; not a VSS effect |
| Valid outputs | 95/110 | 101/110 | +6 |
| USD | not recorded | not recorded; judge about $0.016 | n/a |

**Interpretation.** The direction favours VSS on type, severity, entities and end time, and is against it on assets and instruments, but no test is significant. No improvement is shown. Equivalence is not shown either. VSS also returns evidence, which the direct arm does not produce (see Evidence Crops).

**Do not say:** "production VSS" or "VSS improves accuracy". Person tracking and Super grounding were not in this run. The arms ran on different days.

**Baseline and final:** do not compute an improvement between Slides A and B. Model, repeats and pipeline differ.

**Exploratory subgroups** (`data/final_subgroups.csv`): no subgroup survives Holm correction. The largest is clips where captions reached P1, type +0.115 [+0.016, +0.246], unadjusted p 0.048, Holm p 0.816; it conditions on VSS having answered, so it favours VSS by construction. Long clips: type 0.583 against 0.389, +0.194 [0.00, +0.389], Holm p 0.864.

**Earlier evidence:** the Nano-only contingency (A5-B) and dev rows are kept in `evidence/` and `data/vlm_vs_vss_paired.csv`.

## What each label means

| Label | What it is | Can it stand for production? |
|---|---|---|
| Historical VSS (V1 C2/C3) | Super, wrapper only, no crops, no captions, no zoom | No |
| Dev Track B (C1b) | Historical agent, captions, Super grounding and zoom, tracking off, 25 dev clips | No |
| Original C3 Track B | Same profile, 55 test clips, Super-dependent; **2 scored runs only** | No, incomplete |
| Nano-only contingency (A5-B) | Same agent, all stages Nano, tracking off | No |
| VSS final, Nano-only (plan v1) | origin/main agent, all stages Nano, object tracking on, person tracking off | No: closest available, not production |
| Tracking-off versus production | Every evaluated VSS arm had tracking off; the VM has tracking on | Tracking has no accuracy evaluation |
| Frozen V4 prompt versus later prompts | Every arm used `p1-v4-base`, except V1's C3/C4 prompt, which was not adopted | Later grounding, zoom and chat prompt changes are not covered |
| Original C3 versus V1 | V1 Super is a re-scored historical observation; it is not a C3 run | Sensitivity only |
