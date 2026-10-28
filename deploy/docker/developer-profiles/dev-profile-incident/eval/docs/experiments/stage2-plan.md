# Stage 2 prompt engineering: proposed plan (not executed)

> **Status (2026-10-28): proposal for the owner's review.** Nothing here has run. No prompt file or registry entry is created until it is approved. Stage 3 stays closed until the Stage 2 selection record exists.

## Fixed rules (unchanged, from the plan and the decision log)

| Rule | Source |
|---|---|
| **Data:** dev split only (25 clips × 2 repeats), frozen `ground-truth-v1.0`, evaluation-methodology-v1.1. Test clips are never run, and their earlier outputs are never read (quarantine, D15) | plan §F.2, §F.5 |
| **Arm:** VSS only, local experiment agent, crops off, RP1 skipped, no Supabase or R2 writes. The direct-VLM baseline (C1) is not rerun | plan §F.2, D14 |
| **Comparison:** each version is paired against `vss-baseline` (Stage 1 C2). C1 is context only | D9 v2 |
| **Selection:** D9 v2 as pre-registered. Primary `ΔI` (incident, entity F1, object F1, equal weights), `ΔI8` secondary, `+0.02` minimum, guardrails G1–G3, the tie-breakers. Implemented by `select_d9`, which refuses test, pilot, incomplete or unfrozen records | decisions.md 2026-10-27 |
| **Versions:** at most 8, all reported, regressions included | D9 v2 |
| **Prompt changes:** one component per version, wording derived from `annotation-guidelines-v1.0`, never from ground-truth descriptions or judge behaviour. Registry entries are append-only, with parent `p1-v4-base` and a written hypothesis | plan §F.3 |
| **Caps per version:** 50 P1 attempts, 1,050,000 P1 tokens, judge cap derived from the ground truth (1,710). The runner refuses a run whose cap is below the requirement | D11 |
| **No changes to the ground truth or the methodology from Stage 2 results** | owner instruction 2026-10-28 |

## Decisions needed before any Stage 2 call

### S2-A: item matching is at the floor

- **Finding** ([Stage 1](stage1-baselines.md#entities-instruments-and-assets-pooled-prf1)):
  - At the pre-registered 0.75 MiniLM threshold, entities, instruments and assets score F1 ≈ 0–0.06 in both arms. Even clear same-person pairs score cosine 0.6–0.7.
  - Two of `ΔI`'s three components therefore carry almost no signal. A version would have to gain about +0.06 on the incident component alone to clear `+0.02`.
  - Item-focused versions (V2–V4 below) would be unmeasurable.

| Option | What | Consequence |
|---|---|---|
| (a) Keep v1.1 and D9 v2 unchanged | Run as pre-registered | Honest and needs no change. Item results stay uninformative, and the item hypotheses cannot be tested |
| **(b) Methodology v1.2 before Stage 2 (recommended)** | Fix the item-matching rule (for example a lower threshold, or matching on type plus a short identifying phrase, or judge-based pairing). The new threshold is calibrated on a small labelled set of same / not-same pairs, labelled by the owner or a teammate (about 60 pairs, about 30 min), drawn from the ground truth and the Stage 1 **baseline** outputs only. Then re-score Stage 1 offline (`rescore`: judge calls only, no P1 call) and record a D9 v2 input amendment in `decisions.md` before the first Stage 2 call | Item scores become meaningful. Calibrating on baseline output only, before any variant exists, applies one scorer to every version, so there is no differential bias. It needs owner time and a methodology bump |
| (c) Selection on incident fields only | Amend D9 v2 so `ΔI` is the incident component; items are reported descriptively | Simple. It changes a pre-registered rule, so it needs a new pre-registration entry before any Stage 2 result |

### S2-B: a third of the video-runs were lost to the gateway

- **Finding:** Stage 1 lost 34 of 100 video-runs to 429s and 524 timeouts. All 12 calls after the host resumed from suspend failed. Only 19 clips are paired across the arms, and G1 and G3 compare valid runs and video sets.

| Option | What |
|---|---|
| (a) As Stage 1 | Same retry policy. Expect about 30% loss per version and wide intervals |
| **(b) Recommended** | Keep the host awake (no WSL or laptop suspend), run during quieter hours, and pre-declare one **top-up pass**: after a version's main pass, only its infrastructure-failed video-runs (429, timeout) are attempted once more, within the same caps. Outcomes are still recorded and failures still counted. The same top-up is applied once to `vss-baseline`'s 18 failed video-runs, so baseline and variants have the same chance. This changes §3's "fixed retry policy", so it needs the owner's approval and a methodology note |

### S2-C: E6 (few-shot) would leak labels inside the dev split

- **Problem:** a dev clip used as a worked example would also be scored on dev, and G3 forbids dropping it from the comparison.
- **Recommendation:** drop E6. Use its slot for an end-timestamp rule, because end accuracy (0.47–0.50) and duration (0.32–0.38) are weak. Alternative: synthetic, text-only examples written from the guidelines and drawn from none of the 80 clips.

## Proposed versions (V1–V8)

Every version is `p1-v4-base` with one section changed (V8 combines). Each target is taken from the Stage 1 dev error analysis.

| # | Registry id | Component changed | Stage 1 evidence (dev) | Hypothesis | Target scores |
|---|---|---|---|---|---|
| V1 | `p1-v4-e01-severity` | Severity rubric: guideline decision rules. Observed harm before potential danger. Level 4 or 5 needs observed serious injury or damage, or a clearly present weapon threat; tie-break to the lower adjacent level | Exact 0.15–0.25; ground-truth 3 predicted as 4 or 5 in 24 of 38 outputs; mean signed error +0.18 / +0.53 | Fewer over-ratings | severity exact, within one, signed error |
| V2 | `p1-v4-e02-entities` | Entity significance: list participants, victims and responders or interveners. Exclude bystanders and background people, even when visible | 85–102 predicted against 55–72 ground-truth entities | Higher entity precision at equal recall | entity P/F1 (needs S2-A) |
| V3 | `p1-v4-e03-instruments` | Instrument rule: the hand-held test, "report every hand-held object used in the act", instrument vs asset, threat from potential harm | 9 predicted against 18–25 ground-truth instruments (recall ≤ 0.04) | Higher instrument recall | instrument R/F1, threat (needs S2-A) |
| V4 | `p1-v4-e04-assets` | Asset relevance: only objects damaged, stolen, targeted or directly involved. Scenery, furniture and parked vehicles are excluded unless involved | About 105 predicted against 41 ground-truth assets | Higher asset precision | asset P/F1 (needs S2-A) |
| V5 | `p1-v4-e05-descriptions` | Incident description template from the guidelines §B.1: what happened, who, the key action, the observable outcome, in 1–3 sentences | Description 0.27–0.47; unstable between repeats (C2 agrees on 5 of 10) | Higher and more stable description pass | description |
| V6 | `p1-v4-e06-boundaries` (replaces few-shot, S2-C) | Start and end: the end is the last second the incident action or its immediate consequence is visible, not the clip end, unless it continues | End 0.47–0.50, duration 0.32–0.38, start 0.65–0.69 | Better end and duration | end, duration |
| V7 | `p1-v4-e07-checklist` | A short self-check before answering (ids and holders consistent, timeline inside the incident window, severity re-checked against the rubric, uncertainty stated rather than guessed) | 2 `contract_invalid` in C2; holder and threat errors | Fewer invalid outputs, consistency | valid-output rate, severity |
| V8 | `p1-v4-e08-combined` | V1–V7 components that, **by a rule fixed now**, have a positive `ΔI` point estimate and no G2 violation | – | The gains add up | `ΔI` |

- **Selection:** all 8 go through `select_d9`. If none reaches `ΔI ≥ +0.02`, `p1-v4-base` stays selected, and that result is reported.
- **V8 disclosure:** V8 is built from dev results and scored on the same dev clips. This is disclosed. The held-out check is Stage 3.

## Order, volume and budget

- **Order:** two stages of four versions each (V1–V4, then V5–V8, because V8 needs V1–V7's results). Each stage is interleaved by the D10 order, so versions share gateway conditions.
- **Volume:** 8 × 25 × 2 = **400 P1 attempts**, plus the top-up passes if S2-B (b) is approved (about +30%, within each version's 50-attempt cap only if the main pass leaves room). Otherwise the caps rise to about 65 attempts per version, which needs approval.
- **Judge cap:** derived per version (about 1,710). Stage 1 actually used 31–41 judge calls per config; more will be used if S2-A (b) yields more matches.
- **Cost:** gateway $0 per token (configured). The infrastructure cost is unknown and borne by the sponsor.
- **Time:** about 2 h of active time per 100 calls in Stage 1, so about 8–10 h in total, run as four sessions.
- **Stop rules:** unchanged (25% rate-limit share, caps, judge failures stop the run). A persistent gateway outage stops a session, and it is reported.

## Outputs (after approval and execution)

- `contracts/experiments/p1/<id>.txt` and their registry entries.
- `eval/experiments/configs/<id>.json`.
- Results under `eval_data/results/experiments/<id>/`.
- `eval/docs/experiments/stage2-prompt-engineering.md`: every version's hypothesis, its diff from the parent, paired results against C2 (and against C1 for context), regressions and the `select_d9` output.
- The selection record in `decisions.md`.
