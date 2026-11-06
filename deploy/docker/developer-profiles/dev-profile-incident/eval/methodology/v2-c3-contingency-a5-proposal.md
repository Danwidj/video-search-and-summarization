# C3 amendment A5 (PROPOSED, not approved, not implemented): Cosmos 3 Super outage contingency (2026-11-04)

**Status:** proposal for the owner. Nothing here has run. The C2 freeze manifest (`eb316f37…`), the C3
pre-registration, amendments A1–A4 and every existing output stay as they are. Any option adopted is a new,
separately versioned amendment, applied only after approval.

## 1. Situation (verified from checkpoints and health records)

- Switchyard health rounds r1–r13 (2026-11-03 22:35 → 2026-11-04 14:55) all failed. Since r5, Nano and Omni answer
  (HTTP 200 in 4–13 s); **Super returns HTTP 524 at about 125 s** in every round. The resume rule needs all three.
- Track A (direct): 85 of 330 Nano/Super/Omni items final; 245 open in the recovery run. Gemma and Qwen
  (OpenRouter) 220/220 final.
- Track B (historical pipeline): 9 of 110 final; 108 open in the recovery run.
- Chat (A4) not started. Dashboard: inference and scoring complete.

## 2. What depends on Super

| Work | Needs Super? | Why |
|---|---|---|
| Track A Super items (59 open) | Yes | The subject itself |
| Track A Nano and Omni items (61 + 60 open) | No | Direct calls to their own models; both healthy |
| Track B **Nano** pipeline | **Yes** | The historical agent's grounding and zoom calls use `VLM_NAME` = `cosmos-3-super-reasoner` (launcher `start-experiment-agent.sh`; `crop_evidence.py` default). Only P1 and captions use Nano |
| Track B Super pipeline | Yes | Every stage |
| Chat, oracle corpus | No | `nemotron-3-ultra` on Switchyard (not part of the health check) |
| Chat, system corpus | Indirectly | Built from Track B recovery reports |
| C3-E evaluation half | Indirectly | Its anchors and scored boxes come from Track B evidence |
| Dashboard | No | Done |

## 3. Can earlier Super outputs stand in? (audit)

There is **no V2 or C2 Super output on the 55 evaluation clips**: C2 was a freeze, and every V2 pilot (C1a, C1b)
ran on the 25 development clips only. The only earlier Super outputs on these clips are V1's.

| Element | C3 Track A `super-direct` | V1 Stage 3 `s3-c1-direct-base` (2026-10-29/30) | Match |
|---|---|---|---|
| Model id | `nvidia/cosmos-3-super-reasoner`, Switchyard | same | Yes (no weight pin is exposed on either date) |
| Prompt | production P1, sha `409ed9b3187a…` | `p1-v4-base`, sha `409ed9b3187a…` | Yes |
| Contract and schema | `incident-contract-v4`, schema `a1306278…`, strict | same | Yes |
| Settings | temperature 0, max_tokens 16,384, 64 frames | same | Yes |
| Video | R2 full clip (`anomaly/<category>/<clip>_x264.mp4`) | same keys | Yes |
| Clips | split-v2 test half, 55 | same 55 | Yes |
| Repeats | **2** | **1** | **No** |
| Harness and retries | evalv2 executor, C3 retry and stop rules, A3 caps | V1 harness `820591008`, `retry-v2`; 53 scored + 2 recovered | **No** (different retry path) |
| Raw replies | stored | stored (`p1_raw`, 55/55) | Re-scorable offline |
| Exposure | held out from V2 choices | **published and analysed in V1** (final report §6) | **No** |
| Date | 2026-11-03 onward | 5 days earlier | Drift unknown |

**Finding:** V1's C1 Super outputs match C3's Super condition on model, prompt, contract, settings, video and
clips, so they can be re-scored with C3's frozen scorer. They are **not C3 runs**: one repeat instead of two, a
different harness and retry path, an earlier date, and results already seen in V1. They may only enter the report
as a separately labelled **"V1 historical Super observation (re-scored)"**, never as C3 Super.

## 4. Options (for the owner's choice)

| Option | What it does | Keeps C3 intact? | Cost | Main limitation |
|---|---|---|---|---|
| **A5-a. Split the Track A recovery** (recommended, now) | New recovery config with only the 121 open **Nano and Omni** items; Super's 59 stay open and untouched. Health gate for this run: Nano and Omni only | Yes (same items, prompts, caps and stop rules; only the subject set and the gate change) | Switchyard calls, free; within the $2.00 cap | None for Nano and Omni; Super still pending |
| **A5-b. V1 Super re-score as a labelled observation** | Offline re-score of `s3-c1-direct-base` (+ recovery) with the C3 scorer; reported beside C3 with its own label; Nano − Super(V1) shown only as a sensitivity comparison, repeat 1 of C3 Nano paired to V1 Super | Yes (nothing relabelled) | $0 (offline; the description judge only if approved) | Not the pre-registered comparison; exposure; drift |
| **A5-c. Deadline** | If Super is still failing at a set time (for example 2026-11-06 09:00), close Super's open items as unavailable, report Super as incomplete with its denominators, and keep A5-b as the only Super reference | Yes, under a pre-stated rule | $0 | Primary Nano − Super test loses power or becomes unavailable |
| A5-d. Alternative Super endpoint | — | — | — | **None found.** Cosmos 3 Super is not on the public NVIDIA catalog (RB1, 2026-11-01); `cosmos-3-auto` routes to an unpinned model; OpenRouter does not list it. Self-hosting needs a GPU NIM deployment outside this plan |
| A5-e. Track B with Nano grounding | Swap the grounding and zoom model to Nano | **No**: changes the historical C1b profile | — | Not recommended |

**Track B has no Super-free option** that keeps the historical profile. Its recovery stays gated on Super. If A5-c
fires, Track B is reported from the 9 final runs plus the development C1b results, clearly labelled, and Track B
categories remain incomplete.

**Chat:** an amendment could run the **oracle corpus now** (Ultra only) and the system corpus after Track B. It
changes only the order, not prompts or scoring.

## 5. Recommendation

Approve **A5-a** now. Approve **A5-b** as an offline, labelled observation. Set the **A5-c** deadline. Optionally
approve the **oracle-first chat** split. Keep Track B and C3-E's evaluation half waiting for Super. None of these
changes the frozen C3 methodology or relabels earlier observations as C3 runs.
