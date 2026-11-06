# Evaluation V2: C3 amendments (owner-approved 2026-11-03)

**Status:** approved by the owner on 2026-11-03, after C3 was paused. No scoring rule, metric, threshold or primary analysis changes. Results affected by an amendment are reported as such, and unaffected results are not changed. Hashes are in [`v2-c3-amendments.json`](v2-c3-amendments.json); the freeze manifest (`eb316f37…`) is unchanged.

## What happened (before any C3 result was inspected)

1. **Harness crash.** Track A on Switchyard stopped after 129 of 330 items: a Nemotron 3 Nano Omni reply (Explosion004, repeat 1) ran away to the output cap (`finish_reason: length`) and contained a 13,698-digit integer. Python's JSON parser refuses that with a plain `ValueError`, not the `JSONDecodeError` the V1 policy catches, so the exception escaped and stopped the run.
2. **Switchyard overload.** Of 266 Track A attempts, 111 were rate-limited (HTTP 429) and 74 timed out. 65 of the 129 finished items held no model output. A timed-out attempt keeps its worst-case token reservation, so the Nano and Omni token caps were nearly exhausted (1.72 of 1.74 M; 2.92 of 2.95 M). Track B hit the same overload: after 9 items, 3 HTTP errors and 4 budget refusals. Its caption cap was spent by the worst-case holds of failed runs. C3 was paused, and every checkpoint is preserved.

## Amendments

| Id | Change | Effect on results |
|---|---|---|
| **A1** | `evalv2.tasks.incident_objects.v1.evaluate_policy` wraps V1's policy. A reply the parser refuses with a plain `ValueError` is classified exactly as unparseable content already is (`INVALID_JSON`), which is an invalid output. Test: `tests/v2/test_v2_policy_huge_integer.py` | None for any parseable reply. The crashed item is **scored from its stored reply, never re-sent**: `parse_failure` (`INVALID_JSON`, `finish_reason: length`), recorded in the run's `amendment-a1-records.jsonl` |
| **A2** | The remaining items run as **recovery runs**, the pre-registered recovery policy. They re-send only items without a model output (infrastructure failures and never-attempted items), one at a time (`--parallel 1`, paced) | Track A: 265 items (Nano 96, Super 87, Omni 82); the 64 items with a model output and the crashed item are kept. Track B: 108 items; the 2 answered items are kept. Pilot and recovery outcomes combine per work item, one outcome each |
| **A3** | The Switchyard attempt and token caps of the recovery runs are ×2.5 the frozen caps. Switchyard is not charged | No cost change; the **$2.00 USD cap is unchanged** ($0.375 spent) |
| **A4** | The C3 chat run's system corpus (Track B historical, Super, final stage) is read from the sealed Track B recovery run **plus** the 2 Super items the original Track B run had already answered (Burglary041, RoadAccidents037). Those 2 are read from its checkpoint (`corpus.load_checkpointed_predictions`); an item without a prediction, or one already in the main run, is refused. Test: `tests/v2/test_v2_chat_checkpointed_corpus.py` | Only the corpus source changes; the questions, scorers and caps are as frozen |

## Reporting rules

- Every C3 table states the number of items from recovery runs.
- The crashed item counts as an invalid output (a model failure), exactly as any unparseable reply.
- If a recovery run still leaves items without output, they count as failures in the end-to-end view and are listed.
- Track B results remain labelled **historical pipeline (C1b profile, agent `acbf892ba`)**.
