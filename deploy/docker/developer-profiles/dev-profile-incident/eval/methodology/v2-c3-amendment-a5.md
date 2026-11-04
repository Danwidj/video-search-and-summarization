# C3 amendment A5: Super outage contingency (owner-approved 2026-11-04)

Approved by the owner on 2026-11-04 ("Implement A5-a and A5-b", Super deadline 2026-11-06 09:00 SGT, a separately
versioned Track B contingency). Proposal and audit: `v2-c3-contingency-a5-proposal.md` (C3-E branch). The C2 freeze
manifest, the pre-registration and A1–A4 are unchanged; nothing below relabels an earlier observation as a C3 run.

| Part | Config | What it does | Reported as |
|---|---|---|---|
| A5-a | `amendments/c3-track-a-switchyard-recovery-a5a.json` | The 170 open Nano and Omni items of the A2 recovery (open = the executor's `OPEN_OUTCOMES` on the last checkpoint row, or never attempted), gated on Nano and Omni health only | Original C3 Track A (same prompts, models, settings, retry policy, A3 caps, stop rules) |
| A5-s | `amendments/c3-track-a-switchyard-recovery-a5s.json` | The 84 open Super items, sent only after two consecutive healthy Super rounds and before the deadline; after it they stay open and Super is reported **incomplete** with its denominators | Original C3 Track A |
| A5-b | offline (C3-E branch script) | V1 Stage 3 `s3-c1-direct-base` raw replies re-scored with C3's frozen scorer | **V1 historical Super observation (re-scored)**, never C3 |
| A5-B | `amendments/c3-track-b-contingency-nano-grounding.json` | The historical C1b agent (`acbf892ba`, same flags, pinned identity) with grounding and zoom on **Nano** (`VLM_NAME`), Nano pipeline only, 55 clips, 1 repeat, caps ×2.5 (A3 precedent) | **Track B contingency profile**, never pooled with `c3-track-b-historical` |
| A5-c1 | `amendments/c3-chat-a5-oracle.json` | The oracle corpus of c3-chat (A4) now | Original C3 chat, oracle corpus |
| A5-c2 | to follow | System corpus: from `c3-track-b-historical-recovery` (Super) if it completes before the deadline, else from the A5-B contingency, labelled | Original C3 (if Super) or **contingency** |

**Correction to the outage log.** The 9 recovery-run items that timed out during the outage are *open* under the
executor's rules (`timeout` is an infrastructure outcome), so the approved procedure (resuming the recovery run)
would have re-tried them; the earlier note that they were "made final and not re-run" was wrong. A5-a/A5-s include
them. `c3-track-a-switchyard-recovery` itself is not resumed again, so no item is sent twice.

**Analysis order of runs** for combined rows: original, A2 recovery, A5-a, A5-s; a model output from any run wins.
