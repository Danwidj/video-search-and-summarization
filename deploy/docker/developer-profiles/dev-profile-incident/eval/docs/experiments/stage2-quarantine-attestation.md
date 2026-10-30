# Stage 2 quarantine: retrospective attestation (O3)

> **Status (2026-10-30): partial.** The plan (§F.5) asked Stage 2 prompt authors not to open per-video test results and to record that they complied. No attestation was recorded at the time. This page records, retrospectively, **only what can be verified**, and states what cannot.
> - **AI author (the Claude Code sessions that drafted V1–V8): verified from the session transcripts, with the limits in §3.**
> - **Human author (the owner, who reviewed and adjusted V1–V7 before registration): not obtained.** It cannot be produced on the owner's behalf; §4 records what is known.

## 1. Who wrote the Stage 2 prompts

| Prompt | Drafted | Adjusted / approved | Registered |
|---|---|---|---|
| V1–V7 | Claude Code session `13e6139f…`, 2026-10-28, committed in #240 (`065974d3a`, 2026-10-28 09:42 UTC) | The owner reviewed them ("V1–V7 as adjusted", decisions.md 2026-10-28) | 2026-10-28 14:25 UTC (`21c4266d5`); V5 with one added bullet |
| V8 | Built 2026-10-29 by the fixed combination rule (V1–V7 blocks unchanged) | Owner approved Stage 2b | 2026-10-29 (`03533816d`) |

V8 adds no new text, so the drafting window that matters is from the start of the workstream (2026-10-27 02:21 UTC) to the V1–V7 registration (2026-10-28 14:25 UTC).

## 2. What the transcripts show (AI author)

**Method:**
- **Scope:** all 24 transcripts of this project directory under `~/.claude/projects/` (the main session and every subagent), read only.
- **Tool calls:** every tool call before the registration time whose input names the 2026-10-02 benchmark files (`eval_data/results/*.json`, `results/runs/`, `results/benchmark/`, `eval_benchmark_export`); their outputs were then read.
- **Messages:** every user-turn message in the window, checked for test-clip ids.
- **Why those files:** before Stage 3 the only stored per-video results for test clips were that benchmark (contract v2, pre-correction ground truth, 3 models × 55 clips). Stages 0 and 1 ran on dev clips only.

**Findings:**
1. **No per-video test result was read while the prompts were drafted.**
   - No tool call on 2026-10-28 before registration touched the benchmark files or any other test-clip result.
   - The calls that day read the guidelines, the ground truth, and the Stage 0 and Stage 1 results, which are dev only.
2. **Before drafting (2026-10-27, the plan's current-state audit), the AI author saw aggregate benchmark figures:**
   - validity, outcome, finish-reason and token counts per model and category;
   - latency medians;
   - the summary "severity exact accuracy 22–27% for all three models; type 44–92%", which is in the plan's §A.1.

   These are aggregates over the 55 test clips. Their only bearing on V1 is the general observation that severity was hard for every model.
3. **One per-video record was printed, inside a planning subagent:**
   - **What:** test clip Assault012, Cosmos 3 Nano, contract v2: ground truth, prediction scores and validation (2026-10-27 04:20 UTC).
   - **Reach:** that subagent's report to the drafting session used "Assault012" only as an example of an incident id, with none of its results.
4. **The AI author knew test-clip ground-truth labels.** The AI-assisted correction and adjudication (PR 4, 2026-10-27 and 2026-10-28) covered all 80 clips, including test clips, before the prompts were drafted. For example, it changed test severities such as Animal004 from 1 to 2. That work never saw a VSS or direct-model prediction or score (its independence guard), but it means the prompt author was not blind to test labels.
5. **The prompts carry no clip-specific content:**
   - no registered V1–V8 prompt contains a clip id;
   - none of the text they add to the base prompt shares any 8-word phrase with any of the 364 long ground-truth strings in `ground-truth-v1.0`;
   - they are built only from `annotation-guidelines-v1.0` blocks (registry rule: no few-shot, no video-specific or ground-truth wording).

## 3. Limits of the AI-author check

- Transcripts record tool calls and messages, not what the model weighed. Context from 2026-10-27, including the aggregates in finding 2 and the labels in finding 4, was available to the drafting session, sometimes as compaction summaries.
- The check covers this machine's transcripts only. A session elsewhere would not appear, though none is known.
- Pattern matching finds the benchmark by path. A copy under another name would not be found.

## 4. Human author (owner)

**Not obtained.** The owner reviewed and adjusted V1–V7, so the plan's attestation applies to them too. This page does not attest on the owner's behalf.

What is verifiable:
- the 2026-10-02 benchmark, including its per-video export, was produced in a session the owner started, for the midterm slides, so it was available to the owner before Stage 2;
- the owner's adjustments recorded on 2026-10-28 concern rubric emphasis (V1) and the existing instrument definition (V3), not any clip.

If the owner wants the attestation completed, it is their own statement of whether they consulted per-video test results while adjusting V1–V7. It would be added here verbatim, with its date.

## 5. Consequence for the results

- **Unchanged:** the leakage assessment of D15 / final report §11. The test clips were held out from selection but are not unseen.
- **What this adds:**
  - the AI author had aggregate test-set benchmark figures and test ground-truth labels in context, but read no per-video test result while drafting;
  - no prompt contains clip-specific text.
- **Direction of any bias:** it is the same as before. Any exposure-driven tuning would favour V1 on test, yet V1 did not show a clear test gain (Stage 3), so no inflated claim rests on it.
