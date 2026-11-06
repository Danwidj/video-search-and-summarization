# Evaluation V2: proposed runs (prepared 2026-11-03)

**Status (updated 2026-11-06). Historical planning record, not approved methodology.** The text below is unchanged from 2026-11-03, when none of these runs had been approved.

| Run | Status |
|---|---|
| A. Box-reference AI review | Not run as proposed |
| B. Chat judging | Approved by the owner and run: 221 calls, $0.0117 ([results](v2-chat-judged-results.md)) |
| C. Adjudicator experiments | Not run. The 10 AI-review disputes stay **unresolved** ([results](v2-ai-review-results.md)) |

**Scope and rules for every run:**
- Development split only. No held-out clip, frame or ground-truth text is sent.
- Every run is paced one call at a time, with hard caps on calls, tokens and USD; the worst case is checked before each call.
- Raw responses and provenance are kept.
- No record becomes human-verified.

**Spend so far:** OpenRouter balance used $0.886 (key limit $10). Switchyard is not charged to the project.

| Run | Calls (expected) | Hard cap: calls | Hard cap: tokens | Expected USD | Hard cap: USD |
|---|---|---|---|---|---|
| A. Box-reference AI review (after RA1) | ≤ 200 + adjudication | 310 | 3,810,000 | ≈ 0.39 | **1.25** |
| B. Chat semantic and unsupported-claim judging | **221** | 245 | 1,250,000 | ≈ 0.017 | **0.08** |
| C. Adjudicator experiments (existing 10 disputes) | **30** | 34 | 230,000 | ≈ 0.02 | **0.07** |
| Total if all approved | | 589 | 5,290,000 | ≈ 0.43 | **1.40** |

## A. Development-only AI review of evidence-box references (after RA1 finishes)

**Records:**
- The box references of the **25 dev clips** only: at most 98 ground-truth items (50 entities, 18 instruments, 30 assets).
- The real count is the number of items that end with a validated reference after RA1's selection and blind validation.
- Frames of the 55 test clips are never sent.

**Packet:**
- Per item, up to 3 **actual frames**: the first, middle and last second that have a reference box, with the box drawn and numbered.
- Frames are scaled to at most 1,024 px on the long side.
- Text: the item's dev ground-truth name and description.
- Prompt: `air-box-v1`, finalised from the draft and hash-pinned before approval.
- No reviewer sees the other, the generator or the validator.

**Reviewers:**

| Role | Model | Provider | Price in / out per M tokens |
|---|---|---|---|
| A | DeepSeek V4.1 Flash | Nebius (fp8) | $0.30 / $1.20 |
| B | GLM-5.3 Flash | Reka | $0.12 / $0.30 |

- Neither endpoint charges separately for images.
- Settings: temperature 0, seed 20261103, strict JSON schema, `data_collection: deny`, no fallback, `max_tokens` 4,000.

**Adjudication (debiased):**
- Each AI-disputed record is adjudicated **twice, with the opinion order swapped**.
- A verdict counts only if both orders agree; otherwise the record stays unresolved.
- The adjudicator model is the one run C qualifies; if none qualifies, there is no adjudication.

**Probe first:** 4 calls (A and B on 2 items). Stop if any of these happens:
- any reply is invalid;
- a provider reports more than 2,500 tokens per image;
- the provider does not accept images.

**Calls:**
- 4 probe calls, 196 review calls (98 × 2) and up to 80 adjudication calls (at most 40 disputed × 2 orders).
- A 10% retry margin gives the **cap of 310 calls**.

**Tokens:**
- Worst case per call: 3 images × 2,500, plus 800 text, plus 4,000 output = 12,300, so the **cap is 3.81 M**.
- Expected per call: about 3,800 input and 1,200 output.

**USD:**
- Expected: A ≈ $0.25, B ≈ $0.08, adjudication ≈ $0.06, total **≈ $0.39**.
- Worst case at every cap: ≈ $1.22. **Cap: $1.25.**

## B. Chatbot semantic correctness and unsupported-claim judging (existing C1c chat answers)

**Records:**
- The 140 answers of `v2-c1c-chat-pilot` (70 dev questions × oracle and system corpora). No held-out clip is involved; this was checked against `split-v2`.
- The judged checks are the ones the chat scorer leaves pending.
- **Exact workload:** an offline replay of the scorer with a recording judge, deduplicated as the judge cache dedupes. It needs **221 calls**:

| Check | Calls |
|---|---|
| Unsupported claim | 79 |
| Contradiction with ground truth | 93 |
| Fact stated (facts and holder questions) | 49 |

**Judge:**
- `openrouter-gpt-oss-20b-v1`: OpenAI gpt-oss-20b via OpenRouter → DeepInfra or DekaLLM, no fallback, no data retention.
- Temperature 0, `max_tokens` 1,500.
- Prompts: `judge-fact-v1`, `judge-unsupported-v1`, `judge-contradiction-v1` (unchanged).
- Its family is neither the subject's (NVIDIA) nor the generator's (Anthropic).

**Tokens:**
- Prompt bytes: 754,632.
- Sum of per-call upper bounds: **1,142,708**.
- Expected: about 216k input and 77k output.

**USD:** at $0.03 in / $0.13 out per M, expected **≈ $0.017**, worst ≈ $0.066. **Caps: 245 calls, 1.25 M tokens, $0.08.**

**Needs its own cap:** the primary judge's registry cap (999 calls) has about 193 calls left, so this run needs its own cap.

**Caveats:**
- The judge is more lenient than the AI-consensus (κ 0.63; it passes 10 pairs both AI reviewers fail).
- No sensitivity judge is planned, because further Mistral calls are paused.
- The results stay PROVISIONAL.

## C. Adjudicator experiments on the 10 existing disputes (8 judge-calibration, 2 chat; all dev)

**C1. MiniMax M3.1 Flash (InferenceNet), order-swap replay.**
- The same packets and prompt (`air-adjudicate-v1`), with the opposite opinion order: **10 calls**.
- It directly tests the position bias seen (first-shown opinion in 9 of 10).
- Measured input of the original 10: 31,087 tokens.

**C2. Xiaomi MiMo-v2.6-flash (Io Net, fp8) as an alternative adjudicator, both orders: 20 calls.**
- MiMo is a family outside the subjects, judges, generator and both reviewers, on an unused provider.
- Price: $0.10 in / $0.28 out per M tokens.

**Pre-registered rule:**
- An adjudicator is usable only if its verdict is **order-invariant on at least 9 of the 10** disputes.
- Otherwise the disputes stay unresolved permanently, and run A uses no adjudicator.
- Agreement of the adjudicator with either reviewer is never treated as correctness.

**Cost:**
- **30 calls**, with a 34-call cap including retries.
- About 93k input tokens. Worst case 30 × (input + 4,000) ≈ 213k, so the cap is 230k.
- Expected ≈ $0.02. **Cap $0.07.**

## Not proposed (needs a separate decision)

- **The 41 held-out chat references:** deferred until after C3.
- **More severity words:** major, extreme and catastrophic are one-band under the rule, but were not requested.
- **A Mistral retry with reasoning effort "low":** paused.
