# Final VLM versus VSS comparison: plan v1 (frozen before any run)

Status: frozen 2026-11-05 by commit, before the VSS arm has made any call. Separate from the C3 freeze `eb316f37…`, which is unchanged. This is **not** an original pre-registered C3 experiment. It is a new comparison, specified before its own data exist, on clips that have been exposed in earlier work. The owner authorised it on 2026-11-05 within the existing budget.

## Question

On matched clips, what does the current VSS orchestration change compared with sending the same P1 request directly to the same model?

## Arms

| | Direct VLM | VSS final (Nano) |
|---|---|---|
| Model | `nvidia/cosmos-3-nano-reasoner` | Same, in every model slot (P1, captions, grounding, zoom, object detector) |
| Prompt, contract | `p1-v4-base` `409ed9b3…`, contract v4 | Same |
| Settings | temperature 0, `max_tokens` 16,384, `num_frames` 64 | Same |
| Clips | 55 `split-v2` test clips, 2 repeats | Same clips, 2 repeats |
| Source | Stored Track A `nano-direct` (original C3 runs, 3–4 Nov), no new calls | New run, agent at `origin/main` `9f39b5706`, local experiment path, no Supabase or R2 writes |
| Stages | P1 only | Captions (clips over 30 s, inline), P1, grounding, object tracking (NanoTrack), zoom |

The stored direct requests equal the agent's P1 body in all 110 cases except the agent's explicit `"stream": false`, which is the API default.

## Differences from production, none hidden

1. Person tracking is off: the experiment path refuses it, this host has no GPU or Docker, and `kwanz-ws` is unreachable.
2. Grounding, zoom and the object detector run Nano. Production uses Super there. Super is unavailable.
3. Experiment caps: 40 grounding, 80 zoom, 30 caption calls.
4. Captions are sent inline, not through R2 scratch; evidence is in memory.
5. OpenCV 4.13 here, 5.0 recorded on the VM.
6. The arms ran at different times on a shared endpoint.

So the result is reported as "VSS final (Nano-only, no person tracking)". It must never be called production VSS.

## Scoring

`evalv2-score-stage-v3`, `ground-truth-v1.0`, τ 0.40, same judge (`openrouter-gpt-oss-20b-c3-v1`, provisional) for description. VSS uses the `final` stage. Pairs are (clip, repeat): repeat 1 with repeat 1, repeat 2 with repeat 2.

## Primary family (3 tests, Holm, α 0.05, two-sided)

All are VSS minus direct.

| Metric | Population | Failure handling |
|---|---|---|
| Type accuracy | All 110 planned pairs, end to end | Rejected, invalid or missing output counts as incorrect, in either arm |
| Object score (mean of entity F1 and pooled instrument+asset F1) | All 110 planned pairs, end to end | A failed run is an empty report: no predictions, every reference item a miss |
| Severity MAE | Pairs valid in both arms | MAE is undefined without a prediction; the count of pairs is reported |

An open infrastructure failure in the VSS arm is retried under `retry-v2` and by resuming the run. Any item still without output at analysis counts as a failure in the primary view. Nothing is excluded.

## Secondary, descriptive

Holm across the family below; never a basis for a claim on its own: both-valid type and object score; start and end MAE; description pass; entity, instrument and asset F1; contract-valid rate. Evidence metrics are reported for VSS only, since the direct arm produces no evidence.

## Test

Clip-cluster paired bootstrap, 10,000 resamples, seed 20261027, percentile 95% CI, two-sided p = 2 × min(share ≤ 0, share ≥ 0). Both repeats of a clip are resampled together. Script: `scripts/v2_final_comparison_analysis.py`, committed with this plan.

## Efficiency

Per planned video: tokens by stage, input and output where the provider reports them; end-to-end latency p50 and p95, over answered and over all attempts; attempts; failures and timeouts; contract rejections. Cost: Switchyard records none, so measured USD is reported as unavailable, plus judge spend.

## Claim rule

A significant result needs: Holm-adjusted p < 0.05 in the primary family, and a 95% CI that excludes 0 in the favourable direction. It may then be stated as a post-hoc-labelled, separately frozen result for this configuration only, and the owner is notified at once. Attribution to a single stage is not allowed. Nothing else counts as evidence that VSS outperforms direct inference.

## Stop rules and limits

- Never concurrent with an original C3 Super run: if the gate recovers, this run stops, C3 goes first, then this run resumes.
- 10 consecutive identical failures stop the run.
- Spend stays under the USD 2.00 cap. The judge is the only paid step, expected about $0.04.
- If the run cannot complete, the shortfall is reported as incomplete under the same rules.
- No configuration, scoring or test changes after results are seen.
