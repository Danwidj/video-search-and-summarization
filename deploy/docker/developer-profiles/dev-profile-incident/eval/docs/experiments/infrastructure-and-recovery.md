# Gateway failures, host availability and the recovery protocol

> **Status, 2026-10-29:** **`retry-v2` and `recovery-v1` are approved by the owner** (B1) as the standard protocol for future experiments. They are applied identically to every arm.
> - **Stage 2a recovery ran (2026-10-29):** 7 of 7 infrastructure failures were recovered with 11 attempts ([results §2](stage2a-results.md#2-failures-and-recovery-recovery-v1)).
>   - Two new classes were added first (owner-approved): a DNS or connection failure is `transport_error`, and R2's 403 on an expired signed URL is `expired_url`.
> - **Stage 2b recovery ran (2026-10-29):** 1 of 1 infrastructure failure (an HTTP 524 timeout) recovered with 1 attempt ([results §2](stage2b-results.md#2-failures-and-recovery-recovery-v1)). The baseline's one invalid output was not retried.
> - **Stage 1 recovery:** still deferred by the owner.
> - **Stage 2:** the final execution plan and its reconciled budget are in [stage2-plan.md](stage2-plan.md) (§3–§4).
> - **The original Stage 1 results are unchanged.**

## 1. What failed in Stage 1 (investigation)

| Cause | Evidence | Video-runs lost |
|---|---|---|
| **Host suspend.** The laptop lid was closed, putting Windows into Modern Standby | Windows System log: *"The system is entering Modern Standby. Reason: Lid"* at 12:51:27 SGT (04:51 UTC). It exited on *"Austerity Battery Drain Budget Exceeded"* at 13:24 and resumed at 16:46. Sleep after idle is 1 h on battery and 5 h on AC (`powercfg`) | 1 in flight (`timeout`) |
| **After the resume** | All 12 calls between 08:51 and 09:10 UTC failed: 8 timeouts and 4 rate limits | 12 |
| **Shared gateway capacity (429)** | LiteLLM *"Model capacity reached for nvidia/nvidia/cosmos3-super-reasoner. Priority: dev, Rate limit type: tokens, Model TPM: 500000, Model RPM: 240, Remaining: 0"*. This harness used about 10k tokens a minute. The 500k-TPM model budget is shared with other users of the sponsor's proxy, so its capacity was consumed elsewhere | 21 in total (C1 10, C2 11, including the post-resume 4) |
| **Gateway timeouts (Cloudflare 524, about 100 s)** | Clips of 7–13 s timed out as well as the 196 s clip, so the cause is upstream load, not clip length | 13 in total (C1 6, C2 7, including the post-resume 8 and the in-flight call) |

**Why nothing was retried:**
- The Stage 1 caps were set to exactly one attempt per video-run (50 per config), so `retry-v1`'s 429 retries had no spare attempts.
- `retry-v1` never retries timeouts.

**What was not changed:** the production gateway, its key limits and the sponsor's proxy settings. They are not ours, and the instruction was to leave them alone.

## 2. Host availability

- **`experiments/keep-awake.sh -- <command>`** (WSL):
  - It holds a Windows `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` request for the command's lifetime, then releases it.
  - It changes no power setting.
  - It prevents **idle** sleep, but **cannot override a lid close**. Operating rule for authorised runs: **lid open, on AC power**, with the wrapper.
  - Tested 2026-10-28: the request was held, then released on exit.
- **Suspend detection (every attempt):**
  - Each attempt compares wall-clock and monotonic time. A suspend stops the monotonic clock.
  - A gap of 30 s or more marks the attempt `host_suspended_s`.
  - A failed attempt across a suspend becomes **`host_suspended`**: an infrastructure failure, no model output, retried under `retry-v2`.
  - A valid output from such an attempt is kept and flagged.

## 3. Fixed retry policy `retry-v2` (proposed; applied identically to every arm)

| | `retry-v1` (Stages 0–1) | `retry-v2` (proposed) |
|---|---|---|
| Pacing | ≥ 20 s between attempts | Same |
| Retried | HTTP 429 only | 429, timeout (504/522/524 or client timeout), transport error, `host_suspended` |
| Never retried | Everything else | Any model output (valid or `contract_invalid`), any other HTTP error (a possible defect, reported), judge failures (methodology v1.1 rules) |
| Retries per video-run | ≤ 2 | ≤ 2 (at most 3 attempts) |
| Wait before retry 1 / 2 | 60 s / 60 s (≥ Retry-After) | 60 s / 180 s (≥ Retry-After on a 429) |
| Caps | Every attempt counts toward `max_p1_calls`. A retry only uses spare attempts. Unmetered non-429 attempts count at 35,000 tokens | Same |

- **Selection:** a config chooses the policy with `pipeline.retry_policy`. A config without it ran under `retry-v1`.
- **Implementation:** `eval_vlm_client.P1_RETRY_POLICIES`. Each result records the policy in `p1_raw.rate_limit.policy`.

## 4. Recovery protocol `recovery-v1`

1. **What is recoverable:** only video-runs with **no model output** because of infrastructure (`experiment_recovery.failure_class`):
   - `rate_limited`, `timeout`, `host_suspended`, `transport_error`;
   - an `http_error` whose stored agent error wraps an upstream 429 or 504/522/524;
   - an `http_error` whose stored error is a DNS or connection failure (`transport_error`; since 2026-10-29 the runner also records a new one as `transport_error`, which retry-v2 retries);
   - an `http_error` whose stored error is R2's `403 Forbidden` on the signed video URL (`expired_url`). This happened when a URL expired during a host suspend and a retry reused it.
   - **Fresh URLs:** every recovered video-run signs a fresh URL just before its first attempt. The 1-hour lifetime is longer than the worst-case retry-v2 span, which a test pins.
   - A valid or invalid model output, a low score, or an unexplained HTTP error is **never** re-run.
2. **The original is preserved.** Recovery writes a separate immutable result, `<experiment>-recovery/<ts>/results.json` (`protocol: recovery-v1`, `recovers` = the original's path and SHA-256).
   - Every recovered video-run carries `recovers: {position, run_id, outcome, class}`, the original attempt it replaces.
3. **How it runs:**
   - under `retry-v2`;
   - arms interleaved in the D10 order (same gateway conditions for each arm);
   - its own hard caps, worst case: 3 attempts per listed run, 35,000 tokens per attempt, and the judge cap derived for the listed runs;
   - the 25% rate-limit stop rule unchanged.
4. **Merging:** `merged-original+recovery-v1.json` replaces each recovered video-run and records `recovered_from`.
   - It keeps the original run's reliability as `reliability_original` and reports the merged reliability separately.
5. **Labelling:**
   - every record carries its `protocol` (`original`, `recovery-v1`, `original+recovery-v1`);
   - D9 G3 refuses a comparison between different protocols or methodology versions;
   - reports show original-run reliability next to recovered-run accuracy, never mixed.
6. **Symmetry:** a recovery is applied to **all** arms of a stage or to none.
7. **Hard limit:** at most 15 recovered video-runs per config (`experiment_recovery.MAX_RECOVERED_RUNS`, `--max-runs`). More than that after `retry-v2` means a persistent outage: the recovery is refused, and the outage is reported.
   - The deferred Stage 1 recovery (16 and 18 runs, from a run with no in-run retries) would need `--max-runs 18`, set deliberately.

**Commands** (from `eval/`):
- `eval_experiment.py recover <results.json>…` is a dry run: it lists what would be recovered and the caps.
- Adding `--confirm-paid` runs it. **Not run.**

## 5. Additional inference budget (revision 2; superseded by [stage2-plan.md §3](stage2-plan.md#3-reconciled-budget))

| Item | Video-runs | Hard cap: P1 attempts / P1-token bound / judge calls | Expected attempts |
|---|---|---|---|
| Stage 1 recovery (C1 16, C2 18; dry run) | 34 | 102 / 3.57 M / 1,205 | about 45–55 |
| Stage 2a: concurrent VSS baseline + V1–V7, retry-v2 | 8 × 50 = 400 | 8 × (120 / 2.1 M / 1,710) = 960 / 16.8 M / 13,680 | about 520–560 |
| Stage 2a recovery pass (all 8 configs) | about 80–130 (actual, 2026-10-29: **7**) | 3 × the failed runs (actual: 21) | about 120–180 (actual: **11**) |
| Stage 2b: V8 + baseline drift check | 2 × 50 = 100 | 2 × (120 / 2.1 M / 1,710) | about 130–140 |
| **Total** | **about 615–665** | **≈ 1,600 attempts** | **about 815–935** |

- **Judge caps** are derived from the ground truth and are worst cases. Stage 1 used 31–41 judge calls per config; v1.2's lower τ matches more pairs, so expect perhaps 150–300 per config.
- **Time:** at Stage 1's pace (about 1.2 min per attempt), about 16–19 h of active run time. That is several sessions, each under `keep-awake.sh` with the lid open on AC.
