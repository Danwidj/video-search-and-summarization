# Stage 2 prompt engineering: execution plan (final, not executed)

> **Status (2026-10-28, revision 3): ready to run, waiting only for the owner's go-ahead.** No Stage 2 inference has run.
>
> **Approved so far by the owner:**
> - the structure (concurrent baseline under the same retry policy and gateway conditions);
> - `retry-v2` and `recovery-v1` (B1);
> - V1–V7 provisionally (C1). They are now registered.
>
> **Implemented:** methodology v1.2 (τ = 0.40, AI-calibrated, not human-validated) is in force in code. Revision 2's decision table is resolved below (§7).

## 1. Fixed design

| Item | Value |
|---|---|
| Clips and repeats | The 25 dev clips (`split-v2`), 2 repeats per configuration |
| Model | `nvidia/cosmos-3-super-reasoner`, P1 settings from `contracts/inference.json` |
| Ground truth | Frozen `ground-truth-v1.0` (unchanged) |
| Scoring | evaluation-methodology-v1.2: τ = 0.40; the judge, the 1,500-token limit and the incident rules as in v1.1 |
| Arm | VSS only, through the isolated local experiment agent (`experiments/agent/start-experiment-agent.sh`: no Supabase, database or R2 variable; `persisted: false`). Crops off, RP1 skipped |
| Retries | `retry-v2` in every config: at most 2 retries for 429, timeout, transport error or `host_suspended`, waiting 60 s then 180 s. A model output is never retried. Every attempt, error and token count is kept in `p1_raw.rate_limit.attempts`, and the attempts count toward the caps |
| Recovery | `recovery-v1` after each stage, applied to all of that stage's configs, at most 15 video-runs per config (more means an outage: stop and report) |
| Selection | D9 v2 unchanged (`select_d9`), baseline `s2-vss-baseline`. Every record is `original+recovery-v1` under v1.2 (G3 enforces it) |
| Prompts | V1–V7 registered ([record](stage2-prompts.md)). V8 by the fixed combination rule. No few-shot examples. No version is assumed to help |

## 2. Configurations (`experiments/configs/s2-*.json`)

| Stage | Config | Prompt (SHA-256) |
|---|---|---|
| 2a | `s2-vss-baseline` | `p1-v4-base` (`409ed9b3187a`) |
| 2a | `s2-e01-severity` | `p1-v4-e01-severity` (`004746ea7d19`) |
| 2a | `s2-e02-entities` | `p1-v4-e02-entities` (`19ce9a01c9a6`) |
| 2a | `s2-e03-instruments` | `p1-v4-e03-instruments` (`fe6adc566ad1`) |
| 2a | `s2-e04-assets` | `p1-v4-e04-assets` (`58f8840431c7`) |
| 2a | `s2-e05-descriptions` | `p1-v4-e05-descriptions` (`416b6790b230`) |
| 2a | `s2-e06-boundaries` | `p1-v4-e06-boundaries` (`4b498b0d75e4`) |
| 2a | `s2-e07-checklist` | `p1-v4-e07-checklist` (`1f2734d82f2e`) |
| 2b | `s2-e08-combined` + `s2-vss-baseline-b` (drift check) | Created after 2a by the V8 rule. Not run if fewer than two versions qualify |

**Caps per config:**
- **150 P1 attempts:** 50 video-runs × 3, so retries can never run out.
- **5,250,000 P1-token reservation:** 150 attempts × the 35,000-token ceiling, so even three unmetered attempts on every run never stop the run.
- **1,710 judge calls:** derived from the ground truth; `caps` checks it.
- A hermetic test runs all 8 configs at that worst case and confirms the stage completes.

## 3. Reconciled budget

| Item | Video-runs | Hard cap: P1 attempts / P1-token reservation / judge calls | Expected P1 attempts | Expected judge calls |
|---|---|---|---|---|
| 2a | 400 | 1,200 / 42.0 M / 13,680 | ≈ 580 | ≈ 1,650 |
| 2a recovery (≤ 15 per config) | ≤ 120 | 360 / 12.6 M / ≤ 1,425 per config (derived from the listed runs) | ≈ 25 | ≈ 70 |
| 2b (if V8 runs) | 100 | 300 / 10.5 M / 3,420 | ≈ 146 | ≈ 410 |
| 2b recovery | ≤ 30 | 90 / 3.15 M / derived | ≈ 6 | ≈ 15 |
| **Total** | **500 + recovered** | **1,950 attempts / 68.25 M tokens reserved** | **≈ 760 (up to about 900 with clustered outages)** | **≈ 2,150** |

**How the expectations are derived:**
- **Attempts:** from Stage 1's per-attempt failure rate (34%). With independent failures that gives 1.46 attempts per run and about 4% of runs still failing after 3 attempts. Failures cluster in outages, so the upper figure allows for that.
- **Judge calls:** about 4.1 per scored run (the description, plus the matched pairs at τ = 0.40 in the v1.2 Stage 1 re-match).
- **Tokens:**
  - P1 about 9.5k per successful call, roughly 4.8 M metered P1 tokens;
  - judge about 500 per call, roughly 1.1 M.
  - The reservations are ceilings, not spend.
- **Cost:** the gateway is configured at $0 per token; the infrastructure cost is unknown and borne by the sponsor.

## 4. Runtime and schedule

**Pace:**
- Stage 1 ran at about 70 s per attempt: the 20 s minimum pacing plus the call.
- `retry-v2`'s waits block the stage. About 136 first retries × 60 s plus about 46 second retries × 180 s add about 4.6 h to 2a.
- **2a ≈ 16 h, 2b ≈ 4 h, recoveries ≈ 0.5 h. About 20 h of active run time in total.**

**Sessions:**
- Run 2a in about four sessions of about 4 h each, then its recovery, then 2b and its recovery.
- **Pauses (approved by the owner, 2026-10-28):** `--session-hours 4` ends a session cleanly between video-runs. 4 consecutive video-runs with no model output, or a session rate-limit share above 25%, pause the stage instead of spending more attempts. A pause keeps the checkpoint; resume later.
- **Checkpoint and resume:** `run_stage` writes `checkpoint.json` after every video-run. Stop a session with Ctrl-C and continue with `eval_experiment.py run <same configs> --confirm-paid --resume <stage dir>`.
- The D10 order and run ids are kept, finished video-runs are never repeated, and the result is written once when the stage completes. Tested hermetically.

**Gateway load:**
- One request in flight at a time, at least 20 s apart: under 1 request and about 10k tokens a minute, about 2% of the shared 500k-TPM model budget.
- The 25% rate-limit stop rule stays in force. If it fires, end the session and resume later.
- Watch the 429 share over a session's first 20 attempts.

**Host:**
- Every paid session runs under `experiments/keep-awake.sh --` with the **lid open and on AC power**. Windows sleeps after 1 h idle on battery and on a lid close; the wake request prevents only idle sleep.
- On WSL the runner refuses a paid run without the wake request (`KEEP_AWAKE_ACTIVE`, override `--allow-sleep`).
- Any suspend that still happens is recorded as `host_suspended`.

## 5. Order of work for the go-ahead

1. **Start the services:** the embedding server (`:8811`) and the local experiment agent on the real endpoint.
2. **Health checks:** `/health`, and the agent's environment (7 variables, no storage settings).
3. **Dry runs:** `eval_experiment.py caps experiments/configs/s2-*.json` (8 × 1,710 OK) and `run … ` without `--confirm-paid`.
4. **Stage 2a:** `experiments/keep-awake.sh -- .venv/bin/python scripts/eval_experiment.py run experiments/configs/s2-*.json --confirm-paid`, then `--resume` per session.
5. **Recovery:** `recover <the 8 results.json>` as a dry run, then `--confirm-paid`. `verify` every directory.
6. **V8 and 2b:** compare V1–V7 against `s2-vss-baseline` (merged). Build V8 by the rule and register it. Create the `s2-e08-combined` and `s2-vss-baseline-b` configs, then run 2b and its recovery.
7. **Selection and report:** `select_d9` over every version that ran, the selection record in `decisions.md`, and the report `stage2-prompt-engineering.md` with every version, including the ones that did not help.

## 6. Methodological limitations

1. **Ground truth:** AI-assisted adjudication, approved at the dataset level; not individually human-verified.
2. **Item matching:**
   - τ = 0.40 comes from 132 AI-labelled, AI-audited dev pairs. They are **not human-validated**, and 8 pairs await human review.
   - F1 at τ has the interval [0.65, 0.94]. The data separate 0.30–0.40 from 0.75 firmly, but 0.40 from 0.30 only weakly.
   - Large blocks (heavy over-listing) score lower (F1 0.71). No large instrument block was available.
3. **Same split for calibration and selection:** calibration and selection both use the dev split. τ was fixed before any Stage 2 output, from baseline outputs only.
4. **Small dev set:** 25 clips, so intervals are wide and instruments are thin.
5. **Shared gateway:**
   - non-determinism at temperature 0 (Stage 1: C2 description agreement between repeats 5/10; C2 − C1 entity F1 −0.12 at the same request);
   - recovery changes the protocol, so it is labelled and reported apart from original-run reliability.
6. **V8 and selection on dev:** they are chosen on dev; Stage 3 is the held-out check. The dev clips were also few-shot examples in the retired P1-v1 prompt.
7. **Held-out exposure (Stage 3):** the 55 test clips are not unseen.
   - They were in the 2026-10-02 benchmark.
   - Three (Animal003, Assault018, Burglary005) shaped the v3 timeline wording through an earlier pilot, and other pilots' clips are unrecorded.
   - Any bias favours the baseline prompt, so gains are conservative. Absolute test accuracy may be optimistic.
   - The 52-clip subset is descriptive and never called unseen.
8. **Today's VSS adds nothing before extraction:** VSS and direct differences at the same prompt are pipeline or reliability effects only.

## 7. Decision status

| # | Item | Status |
|---|---|---|
| A1–A4 | Calibration audit, large blocks, τ, v1.2 | **Done (AI-assisted):** τ = 0.40 by the pre-registered rule; v1.2 in code. **Open:** human review of 8 pairs (`eval_data/matching_calibration/human-review-package-v2.md`). If a person changes labels, τ is re-derived by the same rule before Stage 2 |
| B1 | `retry-v2`, `recovery-v1` | **Approved** (2026-10-28) |
| B2 | Stage 1 recovery (34 runs) | **Deferred** by the owner. It needs `--max-runs 18`, because Stage 1 ran without in-run retries |
| C1 | V1–V7 | **Registered.** V5 received a completeness-and-consistency clause, as the owner's description asked ([record](stage2-prompts.md)) |
| C2 | Schedule and budget (§3, §4) | Structure approved; **needs the owner's go-ahead** for the budget and the start |
| C3 | Stage 1 judge re-score | Existing judge outputs cover only 5 matched pairs. **193 judged fields** (names and descriptions of newly matched pairs) would need new judge calls: about 193–210 calls, at most 965 with retries, about 100k tokens, at $0. Not needed for D9 or Stage 2. **Not run; awaits approval** (it would need a pending-fields-only re-score command) |
