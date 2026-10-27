# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Batch runner: P1 -> GT scoring -> RP1, for every held-out video x every
model, with everything except ``model`` held fixed (same contract prompt and
schema, same fixed inference config, same held-out split, same evaluator).
No few-shot examples: the earlier category-specific few-shot block leaked the
answer (see .docs/prompt-contract-plan.md).

For each (category, model, evaluation video):
  1. Resolve the video to its single R2 object and sign a URL
     (``eval_video_resolution``, exact-basename only).
  2. Call P1: signed URL + contract prompt, schema enforced via response_format.
  3. Judge the raw response under validation policy core-scored-v1
     (``contract.evaluate_policy``), with the video's real length read from its
     MP4 header (``video_duration``). Full incident-contract validity is
     recorded as ``contract_ok``; the prediction is scored when its
     database-backed fields are valid (``core_ok``) and is otherwise an empty
     prediction (a miss). A failure confined to the unscored enrichment fields
     (title, severity_reason, location, timeline, uncertainties) never empties
     it. Nothing is repaired.
  4. Persist the prediction to the scoring store under this model's own
     ``model_run_id``. By default the store is an in-memory ``OfflineEvalStore``
     loaded from the GT workbook: no database is opened, connected to or created
     (the finals Supabase project has none of the eval tables). ``--db`` uses the
     legacy database path instead (``INCIDENT_DB_DSN`` / PostgREST), and only
     ``--db --init-schema`` creates missing tables.
  5. Score it against GT (``eval_gt.run_evaluation`` - reuses ``matching.py``
     unchanged; entity/instrument/asset matches will be empty until a real
     embeddings endpoint is configured, see ``config.embedding_base_url()``).
     Both stores give the same scores (``tests/test_offline_store.py``).
  6. Call RP1 (one fixed report-generation model/config, same for every P1
     model) on a core-valid (core_ok) prediction with unchanged input; report is
     persisted, never scored. Skipped otherwise.
  7. Accumulate the Step 7 per-video result; write one JSON file per
     (category, model) once the category's videos are done, plus an immutable copy
     under ``results/runs/<run start>/`` (``write_results``).

Order: video by video, every model on each video before the next, with the model
order rotated per video, so drift in a shared endpoint's load over the run is
spread across models rather than landing on whichever ran last. Calls are
sequential, never concurrent. Each P1 call's processing time (one HTTP round trip,
``eval_vlm_client.chat_completion``) and the video's size and length are recorded
per video (``timing``, ``video``).

``--incident-only`` (the VLM benchmark): steps 5-6 score the incident fields only
- no entity/instrument/asset matching (so no embedding server) and no RP1.

Usage::

    .venv/bin/python3 scripts/eval_run.py --models nvidia/cosmos-3-nano-reasoner \\
        --categories Assault --limit 1     # small, safe smoke run
    .venv/bin/python3 scripts/eval_run.py  # full run: all models, all categories
    .venv/bin/python3 scripts/eval_run.py --incident-only   # VLM benchmark: incident fields + timing
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: F401,E402
import contract  # noqa: E402
import db as db_module  # noqa: E402
import eval_gt  # noqa: E402
import methodology  # noqa: E402
import r2_videos  # noqa: E402
from db_postgrest import PostgrestIncidentDB  # noqa: E402
from db_postgrest import configured as postgrest_configured  # noqa: E402
from eval_gt_schema import load_gt_index  # noqa: E402
from eval_ingest_gt import EVAL_DATA_DIR, load_offline_gt  # noqa: E402
from eval_run_lib import (  # noqa: E402
    RP1_INFERENCE_CONFIG,
    RP1_MODEL,
    EvaluatorDependencyError,
    check_embedding_server_healthy,
    check_judge_ok,
    check_scoring_complete,
    classify_outcome,
    coerce_int_or_none,
    model_run_id_for,
    safe_model_id,
    score_matches_summary,
)
from eval_video_resolution import (  # noqa: E402
    ResolutionError,
    build_basename_index,
    resolve_filename,
    signed_url,
)
from eval_vlm_client import (  # noqa: E402
    MODELS,
    P1_RATE_LIMIT_POLICY,
    P1_TIMEOUT_SECONDS,
    analyze_video_with_p1_rate_limited,
    gateway_credentials,
    generate_report_with_rp1,
    p1_request_config,
)
from video_duration import r2_video_metadata  # noqa: E402

RESULTS_DIR = EVAL_DATA_DIR / "results"
EMPTY_PREDICTION = {"incident": {}, "entities": [], "instruments": [], "assets": []}

# Frozen for the entire benchmark, per explicit confirmation - never changed
# based on results observed during the run. Checked, not just assumed: the
# embedding server's own /health response must report this exact model on
# every check, or the run aborts.
FROZEN_EMBEDDING_MODEL = methodology.EMBEDDING_MODEL
FROZEN_EMBEDDING_BASE_URL = methodology.EMBEDDING_BASE_URL


def get_db(*, init_schema: bool = False):
    """The legacy database backend - used only with ``--db``."""
    db = db_module.get_db(init_schema=init_schema)
    if db is not None:
        return db
    if postgrest_configured():
        return PostgrestIncidentDB()
    raise RuntimeError("no DB backend reachable (direct Postgres and PostgREST both unavailable)")


def persist_prediction(db, incident_id: str, model_run_id: str, prediction: dict) -> None:
    """Write P1's parsed JSON into incidents/entities/instruments/assets.

    ``duration``/``severity_level``/``threat_level`` are coerced to int (see
    ``coerce_int_or_none``) since P1 can legitimately emit e.g. ``6.0`` for an
    integer-schema field - the DB columns are strict INTEGER and reject that
    as-is. The raw, uncoerced prediction is still what's persisted in the
    result JSON returned by ``run_one_video`` - only this DB write is affected.
    """
    incident_fields = prediction.get("incident", {}) or {}
    db.insert_incident(
        incident_id,
        model_run_id,
        fields={
            "type": incident_fields.get("type"),
            "start_timestamp": incident_fields.get("start_timestamp"),
            "end_timestamp": incident_fields.get("end_timestamp"),
            "duration": coerce_int_or_none(incident_fields.get("duration")),
            "description": incident_fields.get("description"),
            "severity_level": coerce_int_or_none(incident_fields.get("severity_level")),
            "confidence_score": incident_fields.get("confidence_score"),
        },
    )
    for e in prediction.get("entities", []) or []:
        db.add_incident_entity(
            incident_id, model_run_id, entity_id=e.get("entity_id"), type=e.get("type"), description=e.get("description")
        )
    for i in prediction.get("instruments", []) or []:
        db.add_incident_instrument(
            incident_id, model_run_id, instrument_id=i.get("instrument_id"), entity_id=i.get("entity_id"),
            name=i.get("name"), description=i.get("description"),
            threat_level=coerce_int_or_none(i.get("threat_level")),
        )
    for a in prediction.get("assets", []) or []:
        db.add_incident_asset(
            incident_id, model_run_id, asset_id=a.get("asset_id"), name=a.get("name"), description=a.get("description")
        )


def generate_rp1_report(prediction: dict, *, max_retries: int = 2) -> dict:
    """One RP1 call (with bounded retry) -> the Step 7 ``rp1_report`` shape.

    ``reasoning_content`` is never treated as a valid report: this reasoning
    model (nemotron-3-nano-30b-a3b) can return an empty ``content`` with its
    entire scratchpad in ``reasoning_content`` instead - confirmed live to
    happen reliably without ``chat_template_kwargs.enable_thinking=False`` in
    ``RP1_INFERENCE_CONFIG`` (see eval_run_lib.py), and occasionally even with
    it. Missing/empty final content is always recorded as a failure
    (``ok: False``), never silently backfilled from reasoning text.

    Retries (bounded, ``max_retries`` extra attempts beyond the first) apply
    only when the call itself succeeded (``rp1_result.ok``) but returned no
    usable final content - never on a network/HTTP failure, mirroring the
    judge's existing retry policy in ``eval_gt.py``.
    """
    attempts = 0
    last_result = None
    while attempts <= max_retries:
        attempts += 1
        rp1_result = generate_report_with_rp1(RP1_MODEL, prediction, inference_config=RP1_INFERENCE_CONFIG)
        last_result = rp1_result
        content = (rp1_result.content or "").strip()
        if rp1_result.ok and content:
            return {
                "text": content,
                "model_id": RP1_MODEL,
                "prompt_version": contract.contract_version(),
                "inference_config": RP1_INFERENCE_CONFIG,
                "ok": True,
                "error": "",
                "attempts": attempts,
            }
        if not rp1_result.ok:
            break  # network/HTTP failure - not retried

    error = last_result.error if last_result and not last_result.ok else (
        "RP1 returned no final content after retries (reasoning_content present but not treated as a report)"
        if last_result and last_result.reasoning_content else "RP1 returned empty content after retries"
    )
    return {
        "text": "",
        "model_id": RP1_MODEL,
        "prompt_version": contract.contract_version(),
        "inference_config": RP1_INFERENCE_CONFIG,
        "ok": False,
        "error": error,
        "attempts": attempts,
    }


def run_one_video(
    db, *, model: str, category: str, filename: str, incident_id: str, r2_object_key: str, video_url: str,
    gt_p1_shaped: dict, model_run_id: str, split_manifest_ref: str, video_duration_seconds: float | None = None,
    video_size_bytes: int | None = None, incident_only: bool = False,
) -> dict:
    """Steps 2-7 for one (model, video) pair. Returns the Step 7 per-video result dict.

    Validity follows validation policy core-scored-v1 (``contract.evaluate_policy``):
    the prediction is scored and persisted when its database-backed fields are
    valid (``core_ok``); a failure confined to the unscored enrichment fields
    (e.g. a timeline outside the incident window) does not empty it. The window is
    also checked against ``video_duration_seconds`` when that is known.
    ``p1_raw.contract_ok`` keeps its original meaning, full incident-contract
    validity. RP1 runs when ``core_ok`` with unchanged input.

    ``incident_only`` scores the incident fields only: no embedding check, no
    entity/instrument/asset matching and no RP1 (recorded as skipped).

    Raises ``EvaluatorDependencyError`` (aborting the whole run) if the
    embedding server or LLM judge is unavailable or invalid for this video -
    never silently continues with a missing/default score treated as valid.
    """
    if not incident_only:
        check_embedding_server_healthy(FROZEN_EMBEDDING_BASE_URL, expected_model=FROZEN_EMBEDDING_MODEL)

    p1_outcome = analyze_video_with_p1_rate_limited(model, video_url)
    p1_result = p1_outcome.result
    contract_error = ""
    if not p1_result.ok:
        contract_error = f"P1 call failed: {p1_result.error}"
        policy = {"validation_policy": contract.POLICY_ID, "full_contract_ok": False, "core_ok": False,
                  "core": [], "enrichment": [], "video_bounds_checked": False, "report": None}
    else:
        policy = contract.evaluate_policy(p1_result.content, video_duration_seconds)
        if not policy["full_contract_ok"]:
            try:
                contract.parse_report(p1_result.content)
            except contract.ContractError as exc:
                contract_error = str(exc)
    contract_ok = p1_result.ok and policy["full_contract_ok"]
    core_ok = p1_result.ok and policy["core_ok"]
    prediction = policy["report"] if core_ok else dict(EMPTY_PREDICTION)

    persist_prediction(db, incident_id, model_run_id, prediction)

    judge_calls_before = eval_gt.JUDGE_HTTP_CALLS
    eval_result = eval_gt.run_evaluation(db, incident_id, model_run_id, incident_only=incident_only)
    judge_calls = eval_gt.JUDGE_HTTP_CALLS - judge_calls_before
    check_judge_ok(eval_result)
    check_scoring_complete(eval_result)
    if (gt_p1_shaped.get("incident") or {}).get("out_of_taxonomy"):
        # Ground-truth status, independent of the prediction: the type is not an eligible field.
        eval_result.fields.setdefault("type", {})["excluded"] = "out_of_taxonomy"

    if incident_only:
        rp1_report = {
            "text": "", "model_id": RP1_MODEL, "prompt_version": contract.contract_version(),
            "inference_config": RP1_INFERENCE_CONFIG, "ok": False, "skipped": True,
            "error": "skipped: --incident-only benchmark", "attempts": 0,
        }
    elif core_ok:
        rp1_report = generate_rp1_report(prediction)
    else:
        rp1_report = {
            "text": "", "model_id": RP1_MODEL, "prompt_version": contract.contract_version(),
            "inference_config": RP1_INFERENCE_CONFIG, "ok": False, "skipped": True,
            "error": "skipped: RP1 runs only on a core-valid P1 report", "attempts": 0,
        }

    result = {
        "filename": filename,
        "incident_id": incident_id,
        "category": category,
        "model_id": model,
        "prompt_version": contract.contract_version(),
        "inference_config": recorded_p1_config(),
        "split_manifest_ref": split_manifest_ref,
        "run_id": model_run_id,
        "r2_object_key": r2_object_key,
        "video": {
            "r2_object_key": r2_object_key,
            "size_bytes": video_size_bytes,
            "duration_seconds": video_duration_seconds,
            "duration_source": "mp4_mvhd" if video_duration_seconds is not None else None,
        },
        # Processing time = the successful P1 HTTP round trip only
        # (eval_vlm_client.chat_completion); None when no attempt succeeded. R2
        # signing, the MP4 header read, pacing and rate-limit waits, validation, DB
        # writes, scoring and RP1 are all outside. Each attempt's own timing is in
        # p1_raw.rate_limit.attempts.
        "timing": {
            "scope": "p1_http_round_trip",
            "p1_elapsed_s": p1_result.elapsed_s if p1_result.ok else None,
            "final_attempt_elapsed_s": p1_result.elapsed_s,
            "started_at": p1_result.started_at,
            "finished_at": p1_result.finished_at,
            "timeout_s": P1_TIMEOUT_SECONDS,
        },
        "ground_truth": gt_p1_shaped,
        "prediction": prediction,
        # contract_ok = full incident-contract validity (unchanged meaning);
        # core_ok = core-scored-v1 validity, which decides scoring (see "validation").
        "p1_raw": {"content": p1_result.content, "reasoning_content": p1_result.reasoning_content,
                   "finish_reason": p1_result.finish_reason, "ok": p1_result.ok, "error": p1_result.error,
                   "status_code": p1_result.status_code, "failure_kind": p1_result.failure_kind,
                   "rate_limit": p1_outcome.summary(),
                   "usage": (p1_result.raw or {}).get("usage") or {},
                   "contract_ok": contract_ok, "contract_error": contract_error, "core_ok": core_ok},
        "validation": {
            "contract_version": contract.contract_version(),
            "validation_policy": contract.POLICY_ID,
            "full_contract_ok": contract_ok,
            "core_ok": core_ok,
            "core_violations": policy["core"],
            "enrichment_violations": policy["enrichment"],
            "video_duration_seconds": video_duration_seconds,
            "video_bounds_checked": policy["video_bounds_checked"],
        },
        "rp1_report": rp1_report,
        "judge_calls": judge_calls,
        "methodology_version": methodology.METHODOLOGY_VERSION,
        "scoring_errors": list(eval_result.scoring_errors),
        "incident_field_scores": eval_result.fields,
        "entities": score_matches_summary(eval_result, "entities"),
        "instruments": score_matches_summary(eval_result, "instruments"),
        "assets": score_matches_summary(eval_result, "assets"),
    }
    # scored | contract_invalid | parse_failure are model outputs; timeout,
    # rate_limited and http_error are not and never count as a wrong prediction.
    result["outcome"] = classify_outcome(result["p1_raw"], result["validation"])
    return result


def recorded_p1_config() -> dict:
    """The P1 config as stored in results: the schema is named by contract version, not inlined."""
    recorded = dict(p1_request_config())
    recorded["response_format"] = f"json_schema:incident_report ({contract.contract_version()}, strict)"
    return recorded


def rotated(models: list[str], index: int) -> list[str]:
    """``models`` rotated left by ``index``: video 0 runs A,B,C; video 1 B,C,A; video 2 C,A,B ..."""
    if not models:
        return []
    shift = index % len(models)
    return models[shift:] + models[:shift]


def scoring_store(*, use_db: bool = False, init_schema: bool = False):
    """The store predictions are written to and scored from: offline unless ``use_db`` is set."""
    if init_schema and not use_db:
        raise ValueError("init_schema requires use_db: the offline store has no schema to create")
    if use_db:
        return get_db(init_schema=init_schema)
    return load_offline_gt()


def run(
    *, models: list[str], categories: list[str] | None, limit: int | None, incident_only: bool = False,
    use_db: bool = False, init_schema: bool = False,
) -> None:
    run_started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Fail fast, before burning any P1/RP1 calls, if either evaluator
    # dependency isn't already healthy at the frozen configuration.
    mismatch = methodology.judge_model_mismatch()
    if mismatch:
        raise EvaluatorDependencyError(mismatch)
    if not incident_only:
        # matching.py embeds through INCIDENT_EMBEDDING_BASE_URL; the health check must cover that same server.
        configured_embedding_url = config.embedding_base_url().rstrip("/")
        if configured_embedding_url != FROZEN_EMBEDDING_BASE_URL:
            raise EvaluatorDependencyError(
                f"INCIDENT_EMBEDDING_BASE_URL is {configured_embedding_url or '(unset)'!r}, but the frozen embedding "
                f"server is {FROZEN_EMBEDDING_BASE_URL!r}; set it to that URL so the checked server is the one used"
            )
        check_embedding_server_healthy(FROZEN_EMBEDDING_BASE_URL, expected_model=FROZEN_EMBEDDING_MODEL)
    from eval_gt import judge_description_similarity

    judge_probe = judge_description_similarity("a person opens a door", "an individual opens a door")
    if not judge_probe.ok:
        raise EvaluatorDependencyError(f"LLM judge preflight failed: {judge_probe.error}")
    embedding_note = "not needed (--incident-only)" if incident_only else f"({FROZEN_EMBEDDING_MODEL}) healthy"
    print(f"Preflight OK: embedding server {embedding_note}, LLM judge responding (probe score={judge_probe.data}).")

    db = scoring_store(use_db=use_db, init_schema=init_schema)
    gt_index = load_gt_index()
    basename_index = build_basename_index(r2_videos.list_video_keys())
    benchmark = {
        "incident_only": incident_only,
        "scoring_backend": "database" if use_db else "offline",
        "model_order": "interleaved-rotating",
        "models": list(models),
        "endpoint_host": urlparse(gateway_credentials()[0]).netloc,
        "p1_timeout_s": P1_TIMEOUT_SECONDS,
        "rate_limit_policy": dict(P1_RATE_LIMIT_POLICY),
    }

    all_categories = sorted(gt_index["by_category"])
    target_categories = categories or all_categories

    model_run_ids = {model: model_run_id_for(model) for model in models}
    for model, model_run_id in model_run_ids.items():
        db.insert_model_run(model_run_id, model_name=model, prompt_version=contract.contract_version())

    video_index = 0  # across categories, so the rotation never restarts at the same model
    for category in target_categories:
        manifest_path = EVAL_DATA_DIR / f"split_{category.lower().replace(' ', '_')}.json"
        if not manifest_path.exists():
            print(f"SKIP {category}: no split manifest at {manifest_path} (run eval_generate_split.py first)")
            continue
        manifest = json.loads(manifest_path.read_text())

        eval_filenames = manifest["evaluation_videos"][:limit] if limit else manifest["evaluation_videos"]
        results: dict[str, list[dict]] = {model: [] for model in models}
        # Videos never sent to any model (unresolvable R2 key) are listed, not dropped silently.
        skipped_videos: list[dict] = []
        for filename in eval_filenames:
            incident_id = gt_index_lookup(gt_index, filename)
            r2_object_key = manifest["evaluation_videos_r2_keys"][filename]
            try:
                resolved_key = resolve_filename(filename, basename_index)
            except ResolutionError as exc:
                print(f"  {category} / {filename}: SKIP, {exc}")
                skipped_videos.append({"filename": filename, "reason": str(exc)})
                continue
            if resolved_key != r2_object_key:
                reason = f"R2 key {resolved_key!r} differs from manifest {r2_object_key!r}"
                print(f"  {category} / {filename}: SKIP, {reason}")
                skipped_videos.append({"filename": filename, "reason": reason})
                continue
            # Read once per video, outside every timed region.
            video_metadata = r2_video_metadata(r2_object_key)

            for model in rotated(models, video_index):
                try:
                    video_url = signed_url(r2_object_key)
                except ResolutionError as exc:
                    print(f"  {model} / {category} / {filename}: SKIP, {exc}")
                    skipped_videos.append({"filename": filename, "model_id": model, "reason": str(exc)})
                    continue
                print(f"  {model} / {category} / {filename} ...", end=" ", flush=True)
                result = run_one_video(
                    db, model=model, category=category, filename=filename, incident_id=incident_id,
                    r2_object_key=r2_object_key, video_url=video_url,
                    gt_p1_shaped=gt_index["by_incident_id"][incident_id]["p1_shaped"],
                    model_run_id=model_run_ids[model], split_manifest_ref=str(manifest_path),
                    video_duration_seconds=video_metadata["duration_seconds"],
                    video_size_bytes=video_metadata["size_bytes"], incident_only=incident_only,
                )
                results[model].append(result)
                elapsed = result["timing"]["p1_elapsed_s"]
                elapsed_text = f"{elapsed:.1f}" if elapsed is not None else "None"
                print(f"outcome={result['outcome']} attempts={result['p1_raw']['rate_limit']['attempt_count']} "
                      f"judge_calls={result['judge_calls']} "
                      f"P1 ok={result['p1_raw']['ok']} contract_ok={result['p1_raw']['contract_ok']} "
                      f"core_ok={result['p1_raw']['core_ok']} finish={result['p1_raw']['finish_reason']} "
                      f"p1_s={elapsed_text} "
                      f"type_pass={result['incident_field_scores'].get('type', {}).get('pass')} "
                      f"RP1 ok={result['rp1_report']['ok']}")
            video_index += 1

        for model in models:
            out_path, archive_path = write_results({
                "category": category,
                "model_id": model,
                "prompt_version": contract.contract_version(),
                "validation_policy": contract.POLICY_ID,
                "methodology": methodology.record(),
                "inference_config": recorded_p1_config(),
                "split_manifest_ref": str(manifest_path),
                "run_id": model_run_ids[model],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "benchmark": benchmark,
                "skipped_videos": [v for v in skipped_videos if v.get("model_id") in (None, model)],
                "videos": results[model],
            }, run_started_at=run_started_at)
            print(f"  -> wrote {out_path} ({len(results[model])} videos); immutable copy {archive_path}")

    print(f"Judge HTTP calls this run: {eval_gt.JUDGE_HTTP_CALLS} (1 preflight probe, the rest description scoring)")


def write_results(payload: dict, *, run_started_at: str, results_dir: Path = RESULTS_DIR) -> tuple[Path, Path]:
    """Write one (category, model) results file, plus a never-overwritten copy.

    The top-level ``<category>__<model>.json`` is the current file that
    eval_aggregate / eval_regenerate_rp1 read, and a later run replaces it. The
    copy under ``runs/<run start>/`` is created exclusively, so each run's raw
    model responses, contract version, validation policy, validation
    diagnostics and inference settings stay available for re-scoring without
    another VLM call.
    """
    name = f"{payload['category'].lower().replace(' ', '_')}__{safe_model_id(payload['model_id'])}.json"
    text = json.dumps(payload, indent=2)
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / name
    out_path.write_text(text)
    archive_dir = results_dir / "runs" / run_started_at.replace(":", "-")
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / name
    with archive_path.open("x") as handle:  # never overwrite a past run's record
        handle.write(text)
    return out_path, archive_path


def gt_index_lookup(gt_index: dict, filename: str) -> str:
    for incident_id, row in gt_index["by_incident_id"].items():
        if row["filename"] == filename:
            return incident_id
    raise KeyError(f"no GT incident_id found for filename {filename!r}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="*", default=MODELS)
    parser.add_argument("--categories", nargs="*", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Cap evaluation videos per category (smoke runs).")
    parser.add_argument(
        "--incident-only", action="store_true",
        help="VLM benchmark: score incident fields only (no entity/instrument/asset matching, no RP1).",
    )
    parser.add_argument(
        "--db", action="store_true",
        help="Persist and score through the legacy database (INCIDENT_DB_DSN / PostgREST) instead of the default "
             "offline store. Finals has no eval tables.",
    )
    parser.add_argument("--init-schema", action="store_true",
                        help="With --db: create missing tables. Local or throwaway databases only.")
    args = parser.parse_args()
    if args.init_schema and not args.db:
        parser.error("--init-schema requires --db")
    run(models=args.models, categories=args.categories, limit=args.limit, incident_only=args.incident_only,
        use_db=args.db, init_schema=args.init_schema)
