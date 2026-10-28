# Stage 2 prompt engineering: plan (revised, not executed)

> **Status (2026-10-28, revision 2):** this revision follows the owner's review of Stage 1, which approved S2-A (b), the recovery protocol work and the V1–V8 adjustments. The preparation is implemented: methodology v1.2 (proposed), `retry-v2`, `recovery-v1`, keep-awake and the draft prompts. **Nothing has run.** Recovery, Stage 2 and Stage 3 wait for the owner's approval of the final methodology and the budgets (§6).

## 1. Fixed rules

| Rule | Source |
|---|---|
| **Data:** dev split only (25 clips × 2 repeats), frozen `ground-truth-v1.0` (unchanged). Test clips are never run, and their earlier outputs are never read (D15 quarantine) | plan §F.2, §F.5 |
| **Arm:** VSS only, local experiment agent, crops off, RP1 skipped, no Supabase or R2 writes. C1 (direct) is not rerun | plan §F.2, D14 |
| **Selection:** D9 v2 unchanged (components, equal weights, `+0.02`, G1–G3, tie-breakers, ≤ 8 versions), via `select_d9`. The only implementation change: G3 also requires the same methodology version (item-matching τ) and the same protocol on both sides | decisions.md 2026-10-27 |
| **Scoring:** evaluation-methodology **v1.2** once approved, otherwise v1.1. One version for every Stage 2 record | [v1.2](../../methodology/evaluation-methodology-v1.2.md) |
| **Prompt changes:** one component per version, wording from `annotation-guidelines-v1.0`, never from ground-truth answers or judge behaviour. **No few-shot examples** in this iteration | owner, 2026-10-28 |
| **Retries and recovery:** `retry-v2` in every Stage 2 config, then one `recovery-v1` pass applied to all configs of a stage | [recovery protocol](infrastructure-and-recovery.md) |

## 2. Versions (drafts in [`experiments/stage2-drafts/`](../../experiments/stage2-drafts/), not registered)

Each draft is `p1-v4-base` plus one inserted block. Diffs: `<id>.diff`. Proposed registry entries: [`registry-proposal.json`](../../experiments/stage2-drafts/registry-proposal.json).

| # | Id (SHA-256) | What changes (guideline source) | Stage 1 dev evidence | Hypothesis / target |
|---|---|---|---|---|
| V1 | `p1-v4-e01-severity` (`004746ea7d19`) | How to apply the **existing** rubric from observed evidence (§2.3): observed harm and demonstrated danger; each level needs its own visible indicators; a clearly visible indicator is never downgraded; property alone; the guideline tie-break **only when two levels fit equally** (not a default to the lower level); the decisive evidence named in `SEVERITY_REASON` (+205 words) | Exact 0.15–0.25; ground-truth 3 predicted as 4 or 5 in 24 of 38 | Severity exact, within one, signed error |
| V2 | `p1-v4-e02-entities` (`19ce9a01c9a6`) | The guidelines' role test for participants, victims and responders (include) and bystanders and background (exclude) (§3) (+116) | Entities over-listed; v1.2 provisional entity P 0.44–0.58 | Entity precision at equal recall |
| V3 | `p1-v4-e03-instruments` (`fe6adc566ad1`) | The **existing** instrument definition applied to each entity's hands, non-weapon examples, the exclusions, threat by capacity to harm (§4, §6) (+103) | Instrument recall 0.20–0.33 (v1.2 provisional) | Instrument recall |
| V4 | `p1-v4-e04-assets` (`58f8840431c7`) | Only **relevant** assets: a visible role is required, and prominent background objects are excluded (§5) (+72) | Asset precision 0.29–0.30 (v1.2 provisional) | Asset precision |
| V5 | `p1-v4-e05-descriptions` (`fac6f74aaa1d`) | General description principles: event, who, key action, outcome; observable verbs (§2.4, §7). No example sentence and no ground-truth wording (+37) | Description pass 0.27–0.47, unstable between repeats | Description |
| V6 | `p1-v4-e06-boundaries` (`4b498b0d75e4`) | Start and end identification: start 0 when already under way; locate the end at the last second of the harmful action or its active consequence; rounding (§2.2) (+71) | End 0.47–0.50, duration 0.32–0.38 | End, duration (start not lower) |
| V7 | `p1-v4-e07-checklist` (`1f2734d82f2e`) | A new final section: seven explicit consistency checks (ids and holders, instrument versus asset, roles, timeline within bounds, rubrics, text against fields, uncertainty) (+121) | 2 `contract_invalid` (C2) | Valid-output rate, consistency |
| V8 | `p1-v4-e08-combined` (built after Stage 2a) | The blocks of every V1–V7 version whose D9 comparison against the concurrent baseline has **`ΔI` > 0 and no G2 problem**. With fewer than two such versions, V8 is not run (it would equal one of them) | – | `ΔI` |

- **V8:** the rule is fixed here, before any Stage 2 output. V8 is built from dev results and scored on the same dev clips; this is disclosed, and Stage 3 is the held-out check.
- **Selection:** all versions that ran go into `select_d9`. If none reaches `ΔI ≥ +0.02` with no guardrail problem, `p1-v4-base` stays selected, and that result is reported.

## 3. Schedule

| Step | Configs (interleaved, D10 order) | Video-runs |
|---|---|---|
| 0 (optional, for the Stage 1 report) | `recover` of C1 and C2 Stage 1 | 34 |
| 2a | `vss-baseline-s2` (`p1-v4-base`, retry-v2) + V1–V7 | 400 |
| 2a-r | `recovery-v1` of every 2a config | about 80–130 |
| 2b | V8 + `vss-baseline-s2b` (drift check) | 100 |
| 2b-r | `recovery-v1` of both | about 15–30 |
| Selection | `select_d9`. Baseline = `vss-baseline-s2` merged (`original+recovery-v1`); candidates = V1–V8 merged; the selection record goes in `decisions.md` | – |

- **Why a concurrent baseline** (instead of comparing against Stage 1's `vss-baseline`):
  - the Stage 1 baseline ran under `retry-v1` and, if recovered, under a different protocol, so G3 would refuse the comparison;
  - the shared gateway's behaviour drifts over time;
  - running the baseline interleaved with the versions gives every comparison the same conditions and the same protocol.
- **V8 and drift:** V8 is compared against the 2a baseline. The 2b baseline is reported only as a drift check (2b baseline − 2a baseline), never in selection.

## 4. Budget

See [infrastructure-and-recovery.md §5](infrastructure-and-recovery.md#5-additional-inference-budget-for-approval-gateway-0-per-token-infrastructure-cost-unknown).

| Item | Value |
|---|---|
| Video-runs | About 615–665 in total |
| Hard caps | About 1,600 P1 attempts |
| Expected attempts | About 815–935 |
| Gateway cost | $0 per token; infrastructure cost unknown |
| Active run time | About 16–19 h, run under `keep-awake.sh` with the lid open on AC |

## 5. Methodological limitations

1. **Ground truth:** AI-assisted adjudication, approved by the owner at the dataset level; not individually human-verified. Every accuracy figure is against that reference ([freeze README](../../ground_truth/freeze/README.md#ground-truth-v10-as-frozen-limitation)).
2. **Item matching (v1.2):**
   - τ was calibrated on 70 AI-labelled dev pairs, which are provisional until a human audit;
   - the selected τ = 0.30 is the lowest value on the grid;
   - the sample excludes the large blocks that hold half the dev pairs, so precision may be optimistic for over-listing outputs ([calibration](../../methodology/calibration/matching-v1.2-calibration.md));
   - calibration and selection both use dev. τ is fixed once, before any Stage 2 output, and every version is scored under it.
3. **Small dev set:** 25 clips. Intervals are wide, and instruments are thin.
4. **Infrastructure:**
   - a shared, rate-limited gateway, so losses are expected even under `retry-v2`;
   - recovery restores samples but changes the protocol; it is labelled and kept apart from original-run reliability;
   - upstream non-determinism at temperature 0 (Stage 1: description pass agreement between repeats 5/10 in C2).
5. **Dev reuse:**
   - V8 and the selected prompt are chosen on dev;
   - dev clips were few-shot examples in the retired P1-v1 prompt (D15). With exposure in prompts, absolute dev accuracy is not a generalisation figure.
6. **Held-out exposure (Stage 3):** the 55 test clips are not unseen (plan §F.5, D15).
   - They were in the 2026-10-02 benchmark.
   - Three (Animal003, Assault018, Burglary005) shaped the v3 timeline wording through an earlier pilot.
   - Other pilots' clips are unrecorded.
   - Any bias favours the baseline prompt, so prompt gains are conservative. Absolute test accuracy may be optimistic, and is not comparable with 2026-10-02.
   - The 52-clip unexposed-pilot subset is descriptive only and is never called unseen.
7. **Prompt-only scope:** today's VSS adds nothing before extraction, so the VSS–direct difference at equal prompt is a pipeline or reliability effect, never an architectural one (plan §F.1).

## 6. Decisions that still need the owner

| # | Decision | Recommendation |
|---|---|---|
| A1 | Human audit of ≥ 20 calibration pairs (list in the calibration report), then re-derive τ by the same rule | Yes, before v1.2 is in force |
| A2 | Calibration coverage: accept the ≤ 9-pair sample, or approve the pre-declared extension (4 random large blocks, about 150 pairs) | Approve the extension. It tests precision where over-listing happens |
| A3 | τ: adopt the rule's output (currently 0.30), or record a deliberate deviation (for example 0.40, F1 −0.015, precision 0.94) | Decide after A1 and A2. Do not choose on Stage 1 model scores |
| A4 | Put v1.2 in force (`METHODOLOGY_VERSION`) for Stage 2 | After A1–A3 |
| B1 | Approve `retry-v2` and `recovery-v1` as the fixed protocol for future experiments | Yes |
| B2 | Run the Stage 1 recovery (34 video-runs, ≤ 102 attempts) | Optional: it improves the Stage 1 parity sample only |
| C1 | Approve drafts V1–V7 (wording), then register them (`prompt_registry.add`) | Review the diffs |
| C2 | Approve the schedule (concurrent baseline, 2a/2b, V8 rule) and the budget (§4) | Yes |
| C3 | Judge re-score of the Stage 1 v1.2 records (new matched pairs' judged attributes; about 100–200 judge calls at $0) | Optional; the item F1 values need no judge |
