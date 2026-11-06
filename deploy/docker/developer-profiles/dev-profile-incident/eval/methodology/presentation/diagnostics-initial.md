# Initial diagnostic findings (2026-11-05)

Aggregates only; GT text stays in `/home/hengz/evalv2-data/v2/diagnostics/` (private). No code bug found in description scoring or contract validity. Official scores unchanged.

| Issue | Metric | Root cause | Evidence | Class | Confidence | Action |
|---|---|---|---|---|---|---|
| Mixed denominators | Description, start/end ±5 | V1 continuity view: invalid outputs are misses, no-output runs excluded | Nano 28/110 vs Super 11/26 | C, reporting | High | Report valid-only and of-planned together |
| Judge instability | Description | Non-deterministic at temperature 0; one cache per run | 138 pairs re-judged: 74 differ, 15 flip pass/fail, max gap 0.8 | C | High | Caveat; same-pair repeat test |
| Strict on brief correct text | Description | Prompt has no anchors; omission penalised | 25-case review by the assistant: 4 of 10 in the 0.1-0.4 band look like false negatives | C | Medium | Blind stratified review, separately versioned |
| Wrong-event descriptions | Description | Genuine | 10 of 10 sampled zero scores defensible | D | High | Report as is |
| Token limit | Yield | 16,384 cap with reasoning | finish_reason length: Nano 15, Omni 23, Qwen 40 | C and D | High | Explain cause |
| Out-of-clip timestamps | Yield, timing | Omni: likely genuine. Gemma: windows do not track the clip and prompt tokens take 3 values, so provider video handling is a likely cause, unproven | Omni 16, Gemma 41 rejected | Omni D, Gemma F (likely E) | Medium | Report as unresolved for Gemma |
| HTTP 400 video download | Gemma, Qwen yield | Provider download failure; final, no recovery run | Gemma 3, Qwen 5 | E | High | Report as infrastructure |

Metrics: completed / planned: Nano 110, Omni 110, Gemma 107, Qwen 105, Super 26 of 110. Valid / completed: 0.864, 0.573, 0.607, 0.619, 1.000. Valid / planned: 0.864, 0.573, 0.591, 0.591, 0.236.
