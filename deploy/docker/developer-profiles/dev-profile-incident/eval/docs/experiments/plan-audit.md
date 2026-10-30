# Evaluation plan audit and deviation record

> **Status (2026-10-30, updated after the end-to-end profile and the owner's acceptance of O1, O2 and O4).** This page audits the [original plan](../../../.docs/mvp2/ground-truth-and-prompt-experiments-plan.md) (PRs 0-7, decisions D1-D15) against what was built and run. It records every requirement that was replaced, omitted or deferred, and the two offline checks added on 2026-10-30.
> - **Explicit acknowledgement:** the ground truth (`ground-truth-v1.0`) and the item-matching calibration (τ = 0.40) are **AI-assisted, not human-validated**. The plan's human review and agreement steps were not carried out. Every reported accuracy is accuracy against an AI-assisted reference that the owner approved at the dataset level.
> - **Read-only:** nothing on this page changed the frozen ground truth, split, methodology, D9 v2, prompts or any Stage 0-3 result. The offline checks sent no model, embedding, judge or cropping request.

## 1. Checklist

Status: **Done** (built and, where it is an experiment, executed), **Done (replaced)** (met by an approved alternative), **Prepared** (built, not executed), **Partial**, **Not done**, **Optional**. All of it is merged into `main` unless marked otherwise.

| # | Plan requirement | Status | Evidence |
|---|---|---|---|
| A | Current-state audit; A.2 gaps 1-3, 5-7, 10 | Done | Plan doc; PR 0 #214, #218, #221 |
| A | A.2 gap 4 (holder rate), gap 8 (ground-truth defects) | Done | Holder rate in the [secondary metrics](#3-offline-checks-added-2026-10-30); PRs 3-4 |
| A | A.2 gap 9 (5 broken finals `videos.filepath`) | Not done (out of scope by the plan) | Supabase; separate decision |
| PR 0 | Stash recovery, offline scoring, no finals table creation | Done | #214 |
| PR 1A | Annotation guidelines v1.0 | Done (owner-approved 2026-10-27). Annotator review omitted (O4, accepted); owner approval is **not** an annotator review | #216 |
| PR 1B | Methodology v1.0: pinned judge, failure classes, bootstrap, metadata, fixtures | Done | #218, then v1.1 #227, v1.2 #240/#256, v1.3 #258 |
| PR 1B | Severity within ±1, bias, confusion | Done | v1.3 (#258), reporting only |
| PR 1B | τ = 0.75 kept (D4) | **Done (replaced)**: τ = 0.40 | §2 R2 |
| PR 1B | Threshold sensitivity at 0.65 and 0.85 | Done (2026-10-30, offline, lower bounds) | §3.2 |
| PR 1B | Macro (category-mean) accuracy; per-video-mean item F1 | Done (2026-10-30, offline) | §3.2 |
| PR 1B | Holder accuracy with counts; threat level on matched instruments | Done (2026-10-30, offline) | §3.2 |
| PR 1B | MiniLM description cosine as a judge-drift check | **Omitted (O1, accepted by the owner)** | §2 O1 |
| PR 2 | 80 clips fetched and verified; manifest; `_demo`; split keys; `*.xlsx` ignored | Done | #215 |
| §E | Perceptual-hash near-duplicate check across splits | Done (2026-10-30, offline) | §3.1 |
| PR 3 | Workbook audit and review workbook | Done | #217 |
| PR 4 | AI correction proposals from video, independence guard, change log | Done | #219, #230, #231 |
| PR 4 | Human review: 100% high-impact, ≥ 30% descriptions, ≥ 20% blind unchanged, second reviewer ≥ 20% with κ | **Done (replaced)**: AI-assisted adjudication | §2 R1 |
| PR 5 | Freeze `ground-truth-v1.0` with manifest, checksum loader and approval record; `split-v2` | Done | #220, #238 |
| D7 | Workbook copy in R2 | **Not done (deferred)** | §2 D2 |
| PR 6A | Registry, two-arm runner, guards, metadata | Done | #221 and later |
| PR 6B | Agent experiment hooks, parity and crops-on/off identity tests | Done | #222, #226 |
| – | Per-request crop-call cap and crop budget (not in the plan) | Done | #359 |
| Stage 0 | Plumbing on mocks, paid P1 pilot, budget statement | Done | #223, #228 |
| Stage 0 | 2-video crop pilot | **Done (replaced)** by the capped end-to-end profile | §2 R6 |
| Stage 1 | Direct and VSS baselines on dev, N = 2 | Done (executed) | #238; [results](stage1-baselines.md) |
| Stage 1 | Recovery of its 34 failed runs | **Not done (deferred by the owner)** | §2 D1 |
| Stage 2 | E1-E7 on dev through VSS, combined candidate, pre-registered selection | Done (executed) | #240-#275; [2a](stage2a-results.md), [2b](stage2b-results.md) |
| Stage 2 | E6 few-shot examples | **Done (replaced)** by V6 incident boundaries | §2 R4 |
| Stage 2 | D9 (c) selection rule | **Done (replaced)** by D9 v2 | §2 R3 |
| Stage 2 | Quarantine attestation by the prompt authors | **Partial**: AI author verified retrospectively; owner attestation not obtained | §2 O3; [attestation](stage2-quarantine-attestation.md) |
| Stage 3 | C1-C4 on 55 test clips, run once, four comparisons plus C3−C1 | Done (executed) | #276, #339; [results](stage3-results.md) |
| Stage 3 | N = 2 on test (D10) | **Done (replaced)**: N = 1 | §2 R5 |
| Stage 3 | D15 sensitivity on the 52 clips | Done | Stage 3 §3 |
| Stage 3 | Optional transfer models (Nano, Omni on C1, C4) | Optional, not run (owner: not to run) | – |
| Profile | End-to-end profile: C2, C3 crops on, 15 test clips | **Done (executed 2026-10-30)**: 30 video-runs, 26 with output, within every cap | #359; [plan](e2e-profile-plan.md), [results](e2e-profile-results.md) |
| Recovery | recovery-v1 for infrastructure failures | Done for Stages 2a, 2b, 3 (7/7, 1/1, 4/6) | [failures and recovery](infrastructure-and-recovery.md) |
| D11 | Per-stage budget approval before each stage | Done | decisions.md, Stages 0-3 |
| D11 | Dollar limits from confirmed pricing | Partial: $0 per token recorded, provisional; infrastructure cost unknown | `experiments/pricing.json` |
| Report | Per-stage reports | Done | stage docs |
| Report | Final report (14 sections) | Done, including §7 end-to-end latency | [final-report.md](final-report.md) |
| Repro | Results immutable, `verify`, test run once with guard log | Done | `results.sha256`, run-once guard, Stage 3 audit |
| Repro | Scoring reproducible from saved results | Done for Stage 3 (full audit); Stages 0-2 by `verify` and hashes | `audit-20261030T071810Z.json` |
| Optional | Judge calibration set (about 20 human-scored pairs); threat ±1 as a metric; RP1 cost | Optional. Threat ±1 done offline (§3.2); the others not done | – |

## 2. Deviations: decision record

### Replaced by an approved alternative

| Id | Original requirement | What was done instead | Decided by | Why | Effect on results |
|---|---|---|---|---|---|
| **R1** | Human review of the ground-truth corrections (100% high-impact, ≥ 30% description edits, ≥ 20% blind review of unchanged incidents, a second reviewer on ≥ 20% with Cohen's κ) | AI-assisted adjudication of all 98 pending entries, each video-verified by AI; freeze on the owner's **dataset-level** approval | Owner, 2026-10-28 ([decision](../../../.docs/decisions.md#2026-10-28-the-98-pending-entries-are-resolved-by-ai-assisted-adjudication-into-a-separate-owner-approved-candidate), [freeze](../../../.docs/decisions.md#2026-10-28-ground-truth-v10-is-frozen-on-the-owners-dataset-level-approval-of-the-ai-assisted-adjudication-stage-1-ran)) | The owner could not review the 98 entries by hand; the look-first procedure, mandatory video evidence and a separate approval record keep it traceable | **The ground truth is not human-validated** and no inter-rater agreement exists. Accuracy is against an AI-assisted reference. A later human review could only produce `ground-truth-v1.1` and a re-score of every arm |
| **R2** | Keep τ = 0.75 (D4: "do not recalibrate") | τ = 0.40 from calibration v2: 132 dev pairs, **AI-labelled and AI-audited**; the selection rule was fixed before labelling | Owner, 2026-10-28 (decisions.md: "Methodology v1.2 adopted with τ = 0.40") | At 0.75 item F1 was about 0.01 in Stage 1: MiniLM rarely reaches 0.75 for equivalent descriptions, so the item metrics measured nothing | **τ is not human-validated**: 8 calibration pairs await human review. Item metrics depend on τ (§3.2 shows how strongly). Calibrated on dev, never on VSS predictions selected for |
| **R3** | D9 (c): equal-weight index of 8 field scores with guardrails | D9 v2: ΔI = mean of the incident, entity-F1 and object-F1 component differences, with G1-G3; ΔI8 reported as secondary | Owner, pre-registered 2026-10-27, before any Stage 2 output | Fixed before any Stage 2 result; equal weights stop the five incident fields from dominating the item scores | None on the integrity of selection (pre-registered). ΔI8 is reported beside ΔI |
| **R4** | E6 few-shot examples (dev clips); E7 self-consistency checklist | V6 incident boundaries (no few-shot); V7 a structured self-check | Owner, 2026-10-28 (V1-V7 registered "with no few-shot examples") | Few-shot clips leaked the label in the retired P1-v1 prompt, and the dev clips were those examples | Few-shot prompting is untested |
| **R5** | N = 2 repeats on test (D10) | N = 1 (220 video-runs) | Owner, 2026-10-29 | One repeat keeps the test run single and within one or two sessions | Run-to-run variation cannot be separated from pipeline effects in Stage 3; intervals reflect clip-to-clip variation only |
| **R6** | Stage 0 crop pilot (2 videos, about 10-40 box calls) | Not authorised; replaced by the end-to-end profile with a per-request crop-call cap and its own budget | Owner, 2026-10-27 (crop pilot not authorised); profile prepared 2026-10-30 | Box calls could not be bounded before the response arrived | End-to-end latency with cropping is still unmeasured |
| **R7** | Each Stage 2 variant compared with the initial (Stage 1) VSS baseline, and with the saved direct-VLM baseline as secondary context | Each variant compared with a concurrent, interleaved VSS baseline run in the same stage (Stage 2a; a fresh baseline-b in 2b). The secondary comparison with the direct baseline is not in the Stage 2 reports | D9 v2 and the Stage 2 plan (owner-approved 2026-10-28) | Paired comparison under the same gateway conditions; the Stage 1 baselines had lost a third of their runs | No effect on selection. The direct arm re-entered at Stage 3 (C1, C4) |

### Omitted or deferred

| Id | Original requirement | Status | Why | Remaining |
|---|---|---|---|---|
| **D1** | Recovery of Stage 1's 34 failed runs | Deferred by the owner | Stage 1 informed setup only; no selection uses it | None needed to complete Stages 2-3. Stage 1 tables include the failures |
| **D2** | Copy of the ground-truth workbooks in R2 (D7 c) | Deferred (an R2 write; never approved) | Ask-first shared-storage write | Durability is one machine. Owner decision |
| **O1** | MiniLM description cosine as a secondary judge-drift check | Not done | Not implemented in methodology v1.0-v1.3. Computing it now needs new embedding calls on the descriptions | **Accepted by the owner (2026-10-30).** The judge is pinned (model, prompt version, temperature 0, output cap) and its tokens and calls are logged, which limits drift but does not measure it |
| **O2** | Matching sensitivity at thresholds *below* the frozen τ | Not done | The saved results keep similarities only for matched pairs, so a looser threshold needs new embedding calls | **Accepted by the owner (2026-10-30).** Stricter thresholds are covered offline (§3.2) |
| **O3** | Written quarantine attestation by the Stage 2 prompt authors | **Partial** (2026-10-30, retrospective) | None was recorded at the time; the owner asked for a retrospective one, recording only what can be verified | **AI author:** verified from the session transcripts that no per-video test result was read while V1-V7 were drafted. They had aggregate test benchmark figures and test ground-truth labels in context, and no prompt contains clip-specific text. **Owner (who adjusted V1-V7):** not obtained; it cannot be given on the owner's behalf ([attestation](stage2-quarantine-attestation.md)) |
| **O4** | Annotators' review of the guidelines (PR 1A acceptance) | Omitted | The owner approved them (D1, D2) | **Accepted by the owner (2026-10-30)**, with the disclosure that the owner's approval is **not equivalent to an annotator review** |
| **O5** | D11 dollar limits from confirmed pricing | Partial | The gateway reports $0 per token; the sponsor's infrastructure cost is not visible to the project | Recorded; every report states it |
| **O6** | Optional: judge calibration set, RP1 cost, transfer models | Optional, not done | Optional in the plan; transfer models excluded by the owner | None for completion |

## 3. Offline checks added 2026-10-30

### 3.1 Perceptual-hash near-duplicate check (plan §E)

- **Command:** `~/.cache/vss-agent-venv/bin/python -I scripts/eval_near_duplicates.py --out eval_data/audit/near-duplicates-20261030.json`. It uses the agent venv's OpenCV; the eval venv gains no dependency. It is read-only.
- **Method:**
  - every local clip is verified against its manifest SHA-256 first;
  - 1 frame per second, at most 120 per clip; near-uniform frames (grey-level std < 8) are skipped;
  - a 64-bit DCT pHash per frame;
  - a frame match is a Hamming distance of 10 bits or less;
  - a pair is a candidate when 30% or more of the shorter clip's frames match.
- **Scope:** all 80 clips (25 dev, 55 test); 4,095 frames hashed, 12 skipped. The manifest and split hashes are unchanged before and after.
- **Result: no near-duplicate found.**
  - There are no exact duplicates, and 5 pairs share any matching frame.
  - One pair reached the flag: Explosion004 and RoadAccidents030, both test, overlap 0.42. The next was Assault013 and Explosion051, both test, overlap 0.13. No dev-test pair exceeded 0.05.
  - **Visual check of the closest frames** (Hamming 8 and 10): different scenes, cameras, places and dates. Explosion004 is a fire-rescue doorway, RoadAccidents030 a street corner; Assault013 a café interior, Explosion051 a snowy yard fire.
  - The matches come from the wide black letterbox borders, which dominate the low-frequency hash. **No clip overlaps another, within or across the split halves.**
- **Limit:** pHash on letterboxed CCTV is coarse. A clip re-encoded with a different crop or overlay could escape it, but a shared source clip would still produce many more matching frames than the 1-18 seen here.

### 3.2 Secondary metrics from saved Stage 3 results (reporting only)

- **Command:** `scripts/eval_secondary_metrics.py` (module `secondary_metrics.py`) on the four recovery-adjusted Stage 3 records. It makes no call. The report is in `eval_data/results/reports/stage3-secondary/recovery-adjusted-v1/`.
- **Check:** the pooled F1 values equal the primary Stage 3 tables (C1 entities 0.482, C4 entities 0.416).
- **Scope:** D9 v2, the primary metrics and every conclusion are unchanged. These tables are descriptive, with no intervals and no selection.

| | C1 | C2 | C3 | C4 |
|---|---|---|---|---|
| Type, micro / macro | 0.836 / 0.823 | 0.815 / 0.808 | 0.836 / 0.823 | 0.852 / 0.843 |
| Severity exact, micro / macro | 0.255 / 0.248 | 0.278 / 0.268 | 0.273 / 0.260 | 0.315 / 0.310 |
| End ±5 s, micro / macro | 0.582 / 0.592 | 0.593 / 0.598 | 0.655 / 0.658 | 0.630 / 0.637 |
| Description, micro / macro | 0.364 / 0.368 | 0.333 / 0.344 | 0.327 / 0.328 | 0.222 / 0.227 |
| Entity F1: pooled / per-video mean / macro | 0.482 / 0.549 / 0.473 | 0.490 / 0.563 / 0.491 | 0.456 / 0.544 / 0.460 | 0.416 / 0.517 / 0.416 |
| Asset F1: pooled / per-video mean / macro | 0.285 / 0.345 / 0.282 | 0.219 / 0.332 / 0.260 | 0.294 / 0.364 / 0.287 | 0.283 / 0.355 / 0.278 |
| Matched instruments (threat exact; ±1) | 1 (0.00; 1.00) | 2 (0.00; 0.50) | 3 (0.00; 0.67) | 4 (0.25; 0.75) |
| Holder correct / incorrect / unresolved | 1 / 0 / 0 | 1 / 0 / 1 | 1 / 1 / 1 | 0 / 2 / 2 |

- **Macro vs micro:** the incident fields differ by at most 0.02, and no field's ordering of C1-C4 changes. The instrument macro F1 differs more, but it rests on 1-4 matches.
- **Per-video mean F1:** higher than pooled, because clips with few items score well and the false positives concentrate in a few over-listed clips. The entity ordering is the same as pooled; for assets C1 and C4 swap places (0.345 vs 0.355), within noise.
- **Instruments:** 1-4 matched instruments per configuration. Threat level is rarely exact, and holder accuracy rests on 1-2 decided cases: descriptive only.
- **Stricter thresholds** (pooled F1 lower bounds; frozen τ = 0.40):

  | τ' | Entities C1 / C2 / C3 / C4 | Assets C1 / C2 / C3 / C4 |
  |---|---|---|
  | 0.50 | 0.289 / 0.294 / 0.248 / 0.222 | 0.170 / 0.127 / 0.167 / 0.182 |
  | 0.65 | 0.084 / 0.098 / 0.072 / 0.040 | 0.034 / 0.031 / 0.054 / 0.061 |
  | 0.75 | 0.000 / 0.007 / 0.007 / 0.000 | 0.007 / 0.000 / 0.013 / 0.000 |
  | 0.85 | 0 for every kind and configuration | |

  Item scores depend steeply on τ. At the plan's original 0.75 they collapse to the floor, as in Stage 1. This is why τ was recalibrated (R2), and why item results are reported as conditional on the AI-calibrated τ = 0.40. Even at 0.50 the entity ordering (C2 ≈ C1 > C3 > C4) is the same as at 0.40.

## 4. What remains to complete the original plan

1. ~~Run the end-to-end profile~~: **done 2026-10-30** ([results](e2e-profile-results.md)).
2. ~~Owner acceptance of O1, O2 and O4~~: **accepted 2026-10-30**.
3. **O3, the owner's part of the quarantine attestation:** open. The AI author's part is verified ([attestation](stage2-quarantine-attestation.md)); the owner's own statement can be added verbatim if they choose to give one.

Apart from item 3, nothing in the plan is outstanding as mandatory work. The human validation that R1 and R2 replaced stays a disclosed limitation unless the owner commissions a human review, which would start a new ground-truth or calibration version and a re-score.
