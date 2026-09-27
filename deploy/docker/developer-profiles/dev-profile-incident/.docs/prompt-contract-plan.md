# Unified Prompt & Structured-Output Contract Plan

> **IN PROGRESS.** Phase 0 is done (results in §5a; the probe script has been removed). Phase 1 (eval) is on `main`, waiting for a live benchmark run. Phases 2 (console), 3 (agent) and 5 (docs) are implemented on branch `claude/sweet-clarke-g3etx6`, not yet merged or deployed. Phase 4 (database) has not started.
> **Date:** 2026-09-27
> **Scope:** `eval/`, `incident-console-v2/`, `services/agent/` (incident path), `supabase/migrations/`

---

## 1. Problem

Incident extraction runs through three paths that do not share a prompt, schema, request shape or parser. So the eval benchmark does not measure what the console and agent actually do.

| Aspect | eval P1 | console gateway mode | agent mode |
|---|---|---|---|
| Prompt | `P1-v1` (`eval/prompts.py`) | `incident-v2-snake` (`lib/analysis/prompt.ts`) | VLM markdown report (`video_report_gen`), then an LLM extraction prompt (`incident_report_gen.py`) |
| Pipeline | 1 VLM call (P1) → 1 text call (RP1 prose report) | 1 VLM call + JSON-repair retry | VLM → markdown → LLM `with_structured_output` |
| Video | Local MP4 as base64 data URI | Signed R2 URL | Fetched from VST |
| Content order | Video, then text | Text, then video | n/a |
| Shape | Nested `incident` + `entities`, no timeline | Flat snake_case, `persons`, timeline | Flat snake_case, `persons`, timeline |
| Taxonomy | road accident, burglary, explosion, **assault**, **animal attack** | road accident, burglary, explosion, **fighting**, **animal** | same as console |
| Confidence | `null` (no self-report) | Self-reported 0-1 | Self-reported 0-1 |
| Few-shot | 5 examples **from the true category** | none | none |
| Output control | Prompted JSON template; best-effort brace/fence extraction (`extract_json`) | Prompted template; tolerant Zod, alias normalisation, duration fallback, repair retry | `with_structured_output` (Pydantic) |

**Known defect in eval:** `build_few_shot_block` feeds each held-out video 5 worked examples from its own true category. That leaks the label, so type accuracy is inflated. The console cannot reproduce it either, because the category is exactly what is unknown at analysis time.

## 2. Decisions (captain, 2026-09-27)

| # | Decision | Notes |
|---|---|---|
| D1 | The eval P1 prompt is the base. Console-only fields are added to it, not dropped. | See §3 for the added fields. |
| D2 | Nested snake_case shape with a structured `timeline`. | |
| D3 | The output shape is enforced by the API (`response_format: json_schema`), not by a JSON template in the prompt. | The prompt describes field meaning only. |
| D4 | One request pattern everywhere: P1 (video → JSON), then RP1 (JSON → prose). | "Multiple calls" in eval means this two-step chain. It has no retries. |
| D5 | Strict parsing. A schema mismatch fails with HTTP 422. | No repair retry, alias normalisation, fallback defaults or brace extraction. |
| D6 | **No few-shot** anywhere. | Removes the label leak. Past benchmark numbers are no longer comparable. |
| D7 | Agent mode is in scope. `incident_report_gen` uses the same prompt, schema and call. | Reverses the flat-contract direction from #101. |
| D8 | Taxonomy is **eval's 5 labels**: road accident, burglary, explosion, assault, animal attack. | Matches the ground truth. A 7-label superset was rejected because `fighting`/`assault` and `animal`/`animal attack` overlap, and the ground truth cannot score `fighting` or `animal`. |
| D9 | The video reaches the model as a **signed R2 URL** (1 h) in every path. | eval stops downloading and base64-encoding clips. |
| D10 | `confidence_score` is `null` unless the API gives a native score. | The UI must render "no confidence" and sort nulls last. |
| D11 | Timeline events must fall within `[start_timestamp, end_timestamp]`. Lead-up events are a contract violation (422). | Chosen over relaxing to `[0, end]`. |
| D12 | Derived fields are computed by code: `incident.duration = end_timestamp - start_timestamp`. The model is never asked for them. | Removes a class of arithmetic failures. Eval scoring gets the same value. |

## 3. Target contract

**Single source of truth:** `dev-profile-incident/contracts/`

| File | Content |
|---|---|
| `incident_report.schema.json` | JSON Schema (draft 2020-12), strict-mode compatible (see below) |
| `incident_extraction_prompt.md` | P1 text: sections 1-6 kept, few-shot removed, section 7 "OUTPUT FORMAT" removed, and rules added for the extra fields |
| `report_generation_prompt.md` | RP1 text (`RP1-v1`, unchanged apart from the input shape) |
| `VERSION` | One contract version (now `incident-contract-v2`), stored as `prompt_version` on every model run |

**Strict-mode rules:**
- `additionalProperties: false` on every object.
- Every property is `required`. An optional value is expressed as a nullable type (`["string", "null"]`).

**Shape** (added to P1 in *italics*):

```text
incident
  type                enum: road accident | burglary | explosion | assault | animal attack
  title               string                        (*added*)
  start_timestamp     integer (s)
  end_timestamp       integer (s)
  description         string
  severity_level      integer 1-5
  severity_reason     string                        (*added*)
  confidence_score    number | null                 (D10)
  location            string | null                 (*added*)
entities[]            entity_id "E<n>", type: human | animal | unknown, description
instruments[]         instrument_id "I<n>", entity_id string | null, name, description, threat_level 1-5
assets[]              asset_id "A<n>", name, description
timeline[]            start_seconds integer, end_seconds integer | null, description    (*added*, D2)
uncertainties[]       string                                                             (*added*)
```

- Console `persons[{description, actions}]` becomes `entities`. Actions go into `description`, as the P1 rules already require.
- `incident_start_confirmed` is dropped. The P1 rules already say to base `start_timestamp` on observable evidence only.
- Cross-field rules that JSON Schema cannot express are checked after parsing, and a failure also returns 422:
    - every `instruments[].entity_id` exists in `entities`
  - `timeline` falls within `[start, end]`

**One validator per language, both reading the same file:**

| Language | Consumer | Request | Validation |
|---|---|---|---|
| Python | `eval/` | `response_format={"type": "json_schema", "json_schema": {"name": "incident_report", "schema": <file>, "strict": True}}` | `jsonschema.validate` + cross-field checks |
| Python | `services/agent` | same, over `httpx` (not `with_structured_output` over markdown) | Strict Pydantic `ContractReport` (`strict=True`, `extra="forbid"`, no defaults) in `vss_agents/incident_contract/`, with a test that its fields, enums and bounds mirror the schema file. `jsonschema` is not used because the agent lock cannot be regenerated here (see `decisions.md`). |
| TypeScript | `incident-console-v2` | same `response_format` via `lib/gateway/client.ts` | Ajv (draft 2020-12) compiled from the file at runtime, server only (`lib/analysis/contract.ts`). Types are hand-written in `lib/analysis/contract-types.ts` and checked against the file by `tests/contract.test.mjs`, rather than generated (no extra dev dependency). The Zod contract, `normalizeIncidentAliases` and the repair retry are removed. |

The agent keeps a vendored copy of `contracts/`, because it is deployed from `services/agent`. A test fails when the copy differs from the profile copy.

## 4. Unified request pattern (D4, D9)

```text
P1   POST {gateway}/v1/chat/completions
     model            configured VLM
     messages         [ user: [ {video_url: <signed R2 URL>}, {text: incident_extraction_prompt} ] ]
     response_format  json_schema (strict)
     p1_request.json: temperature 0, max_tokens 16384, media_io_kwargs {video: {num_frames: 64}}
     → parse JSON → schema + cross-field validation → 422 on failure

RP1  POST {gateway}/v1/chat/completions
     rp1_request.json: nvidia/nemotron-3-nano-30b-a3b, temperature 0, max_tokens 4096, thinking off
     messages         [ user: report_generation_prompt with the P1 JSON ]
     → prose report (text)
```

- **Agent mode:** the console sends the signed URL in the `POST /api/v1/incidents/{id}/analyze` body. The VM then needs no R2 credentials and does not fetch from VST for analysis.
- **Persistence:** P1 JSON plus RP1 prose go into `model_runs.notes` under the contract version. Relational rows are written from the P1 JSON as today. The single-writer question stays with Option B ([`restructure-plan.md`](restructure-plan.md)).

## 5. Implementation order

| Phase | Work | Gate |
|---|---|---|
| **0. Pre-flight check (done; probe script removed after the runs)** | Add `contracts/`. Add `eval/scripts/probe_structured_output.py`, which runs P1 with `json_schema` and a signed URL against every model in use: the 3 eval models, the console default `cosmos-3-nano-reasoner`, and the agent's `cosmos-3-super-reasoner`. It reports two things per model: whether the schema is enforced, and whether the model fetched the URL. | **Stop and review.** A model that fails either check is dropped; no lenient fallback is added. Only structured output on `nemotron-3-ultra` (a text LLM) is verified today. |
| 1. eval, **implemented** | Few-shot removed (`eval_few_shot.py`, `prompts.py` deleted). Signed URL replaces base64 (`resolve_and_sign`). Strict `contract.parse_report` replaces `extract_json`; contract failures are scored as misses, listed as `contract_failures`, and RP1 is skipped for them. Fixed P1 config: `max_tokens 16384`, `num_frames 64`. The ground truth already uses the 5 labels. `vlm_benchmark_results.md` is marked superseded. **Outstanding:** a smoke run, then the full benchmark. | `uv run pytest tests/` passes (93) |
| 2. console, **implemented (branch)** | `lib/analysis/contract.ts` (Ajv) + `contract-types.ts`. `app/api/analysis/route.ts` runs P1 → RP1 in gateway mode; a violation is 422 and nothing is persisted. Agent mode sends `{model_run_id, video_url}` and re-validates the returned report. Report editor, dashboard, library and comparison views use the contract shape; `confidence` is nullable. The edit route validates edits against the contract (400). Read-only `legacyToContract` adapter for old notes. Migration `20260927120000_contract_report_summaries.sql` (library titles, null confidence) is written but **not applied**. `vlm-gateway` upstream timeout 60 s → 300 s. | `npm run typecheck && npm test && npm run build` pass (63 tests) |
| 3. agent, **implemented (branch)** | `incident_report_gen` makes the direct P1 then RP1 calls over `httpx`; the VLM-markdown → LLM-extract steps and `data_models/incident_report.py` are removed. `/analyze` takes `{video_url, model_run_id?}` and returns 422 on a contract violation. The agent no longer writes `videos`. Vendored contract + parity tests. **Not redeployed on the VM.** | `ruff`, `ruff format`, `mypy` and `pytest` pass (57 tests, run against stubbed `nat`/`supabase` because `pypi.nvidia.com` is blocked in the cloud session) |
| 4. database | Migration mapping `incidents.type` fighting → assault and animal → animal attack; `entities.type` person → human. Dry run first, then apply only after approval. | [`incident-manage-database`](../skills/incident-manage-database/SKILL.md) rules |
| 5. docs, **done (branch)** | `analysis-schema.md` rewritten; `architecture.md`, `data.md`, `status.md`, `decisions.md`, `incident-profile-operations.md`, component READMEs and the `incident-analyze-video`, `incident-manage-database` and `incident-operate-vm` skills updated. | Standing docs rule |

## 5a. Phase 0 results

**Run 1, 2026-09-27T03:18:56Z** (`anomaly/explosion/Explosion019_x264.mp4`, max_tokens 4096)

| Model | schema_enforced | url_fetch | url_negative_control | p1_contract | P1 answer |
|---|---|---|---|---|---|
| `cosmos-3-nano-reasoner` | PASS | PASS | PASS (500 quoting R2's `404 Not Found`, so the fetch is proven) | PASS | `assault`, severity 1: **wrong type** |
| `cosmos-3-super-reasoner` | PASS | PASS | PASS (200 with `null` body, weaker evidence) | PASS | `assault`, severity 1: **wrong type**. Its one-line description invents a "forklift collides with a worker". |
| `nemotron-3-nano-omni-30b-a3b-reasoning` | PASS | PASS (describes a fire, consistent with the clip) | PASS (200 with `null` body) | **FAIL**: empty content | none |

**Findings**
- Server-side `json_schema` enforcement is real on all three models, so D3 is feasible.
- A signed-URL fetch is proven for Cosmos Nano and plausible for the other two.
- A strict pass says nothing about correctness. Both Cosmos models misclassified an explosion clip.
- Nemotron's empty P1 content is unexplained; the likely cause is the reasoning budget running out before the JSON.

**Research after run 1** (sources in the linked notes below):
- **The gateway stack is LiteLLM in front of a vLLM-based server.** The nano negative-control error text is LiteLLM wrapping the server's own `404` from R2, so the server downloads the URL itself.
- **Frame sampling defaults depend on the server type.** A Cosmos 3 NIM defaults to 4 fps, matching the training data. Plain vLLM defaults to 32 frames spread evenly across the video. `Explosion019_x264` is a long UCF-Crime clip, so both defaults are poor for it: 32 frames means about one frame every few seconds, and 4 fps spreads the pixel budget across hundreds of low-resolution frames.
- **Frame sampling is set with the top-level field `media_io_kwargs`** (`{"video": {"fps": F}}` or `{"video": {"num_frames": N}}`). Using both at once, or an fps above the video's own, returns HTTP 400 on a NIM. Whether LiteLLM forwards the field is unknown.
- **Reasoning and structured output:**
  - On the vLLM server, the grammar applies only after `</think>` when a reasoning parser is enabled, so Nemotron can reason and then emit JSON.
  - Nemotron Omni's documented reasoning budget is 16,384 tokens, against our `max_tokens` of 4096. That is the likely cause of the empty P1 content.
  - Cosmos reasoning is prompt-activated (`<think>`) and has no parser, so under strict JSON it cannot reason first. An `analysis` field placed first in the schema is the candidate fix.
- **NVIDIA sampling guidance for Cosmos:** media before text (already done). Temperature 0.6-0.7 with `seed=0`, rather than greedy decoding, for reproducibility.

**Sampling test, 2026-09-27T03:31:02Z** (`--sampling-tests`, same clip). The prompt-token counts below are decisive; the answer text is not, because answers vary between runs even at temperature 0.

| Model | Tokens per frame | Default frames (no `media_io_kwargs`) | `num_frames` takes effect |
|---|---|---|---|
| `cosmos-3-nano-reasoner` | about 44 ((2840 - 372) / 56) | about 24 | yes |
| `cosmos-3-super-reasoner` | n/a | about 24 (a flat 1080 tokens) | **no** (1080 tokens at 8 and at 64 frames) |
| `nemotron-3-nano-omni-30b-a3b-reasoning` | about 141 | about 24 | yes |

- **The gateway forwards `media_io_kwargs`, but invalid combinations are accepted, not rejected.** That is vLLM-style capping rather than NIM validation.
- **The effective default is about 24 frames per video, whatever its length.** Long UCF-Crime clips are therefore sampled roughly every 5-10 s, which is the likely cause of the misclassifications.
- **Cosmos Nano sees frames at thumbnail resolution** (about 44 tokens each).
- **Cosmos Super cannot be tuned through this gateway.**
- **Nemotron P1 ended with `finish_reason=length` after 14,805 reasoning characters,** which confirms that the 4096 budget is too small.

**Run 2, road-accident clip** (`--compare-base64 --p1-max-tokens 16384 --num-frames 64`):

| Model | P1 (URL) | P1 (base64) | Notes |
|---|---|---|---|
| `cosmos-3-nano-reasoner` | valid: `road accident`, severity 3 | identical to URL | URL input does not change the result |
| `cosmos-3-super-reasoner` | **rejected by a cross-field rule**: timeline events at 0 s and 2 s fall outside the incident window [3, 7] | same | Valid JSON. The model included lead-up events, which the prompt asks it to exclude. |
| `nemotron-3-nano-omni-30b-a3b-reasoning` | valid: `road accident`, severity 3 | identical to URL | 16k budget fixes P1. `url_fetch` failed only because the override did not reach that call (`finish_reason=length`); now fixed, as `--max-tokens` applies to every call. |

- There is no general `assault` bias. The explosion miss is clip-specific, most likely due to sparse sampling of a long clip.
- **Decided (captain, 2026-09-27):**
  - D11: the timeline rule **stays strict** (events within `[start_timestamp, end_timestamp]`). A model that includes lead-up events fails with 422.
  - D12: `duration` is **computed by code** (`end - start`) and removed from the schema (`incident-contract-v2`).
  - Super failed D11 on this clip. It stays under observation until phase 1 shows its failure rate across the ground-truth set, and is dropped if the rate is material.

**Next (run 2).** The probe now records `finish_reason`, token usage, reasoning length and the full P1 report. It also adds:
- `--compare-base64`: URL vs inline A/B;
- `--p1-max-tokens`;
- `--fps` / `--num-frames`: sent as `media_io_kwargs`;
- `--sampling-tests`: whether `media_io_kwargs` reaches a validating server, and whether `num_frames` changes the answer.

Steps:
1. One clip with `--sampling-tests`, to learn whether frame control works through the gateway.
2. Three or more short clips from different categories with `--compare-base64 --p1-max-tokens 16384`, plus `--num-frames` or `--fps` if step 1 shows they take effect.

Decide the phase 1 model list and sampling settings from those results.

## 6. Risks

| Risk | Mitigation |
|---|---|
| The Switchyard proxy does not enforce `json_schema` for reasoning VLMs, or reasoning text leaks into `content` | The phase 0 check. A model that fails is dropped rather than parsed leniently. |
| A provider cannot fetch R2 presigned URLs | The phase 0 check. The URL is valid for 1 h, which covers the 240 s timeout. |
| Strict parsing raises the failure rate on weak models | That is intended. Failures become visible 422s and count in the benchmark as extraction failures. |
| Old reports use `persons` or camelCase, in both `incidentConsoleV2.report` and the reviewer-edited `incidentConsoleV2.editedReport` | The read-only legacy adapter covers both keys. It is never written. The report editor saves only the new shape. |
| Benchmark numbers change | Expected (D6, D9). Record both runs in `vlm_benchmark_results.md`. |

## 7. Open items

- **Resolved:** the RP1 model is fixed by `contracts/rp1_request.json` (`nvidia/nemotron-3-nano-30b-a3b`, eval's RP1 config) for eval, console and agent alike.
- **Resolved:** `title`, `severity_reason`, `location`, `timeline` and `uncertainties` stay in `model_runs.notes` until Option B.
- **Open:** which VLM the VM agent uses. Cosmos Super ignores `num_frames` and failed D11 on the road-accident clip; phase 1 results should decide.
- **Open:** phase 4 migration of live rows to the 5-label taxonomy.

