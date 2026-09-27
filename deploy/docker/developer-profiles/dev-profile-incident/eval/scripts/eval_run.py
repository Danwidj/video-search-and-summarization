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
  4. Persist the prediction to the DB under this model's own ``model_run_id``.
  5. Score it against GT (``eval_gt.run_evaluation`` - reuses ``matching.py``
     unchanged; entity/instrument/asset matches will be empty until a real
     embeddings endpoint is configured, see ``config.embedding_base_url()``).
  6. Call RP1 (one fixed report-generation model/config, same for every P1
     model) on a fully contract-valid prediction; report is persisted, never
     scored. Skipped otherwise.
  7. Accumulate the Step 7 per-video result; write one JSON file per
     (category, model) once that pair's videos are done, plus an immutable copy
     under ``results/runs/<run start>/`` (``write_results``).

Usage::

    .venv/bin/python3 scripts/eval_run.py --models nvidia/cosmos-3-nano-reasoner \\
        --categories Assault --limit 1     # small, safe smoke run
    .venv/bin/python3 scripts/eval_run.py  # full run: all models, all categories
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: F401,E402
import contract  # noqa: E402
import db as db_module  # noqa: E402
from db_postgrest import PostgrestIncidentDB  # noqa: E402
from db_postgrest import configured as postgrest_configured  # noqa: E402
import eval_gt  # noqa: E402
from eval_gt_schema import load_gt_index  # noqa: E402
from eval_ingest_gt import EVAL_DATA_DIR  # noqa: E402
from eval_run_lib import (  # noqa: E402
    RP1_INFERENCE_CONFIG,
    RP1_MODEL,
    EvaluatorDependencyError,
    check_embedding_server_healthy,
    check_judge_ok,
    coerce_int_or_none,
    model_run_id_for,
    safe_model_id,
    score_matches_summary,
)
from eval_vlm_client import MODELS, analyze_video_with_p1, generate_report_with_rp1, p1_request_config  # noqa: E402
from eval_video_resolution import ResolutionError, build_basename_index, resolve_and_sign  # noqa: E402
import r2_videos  # noqa: E402
from video_duration import r2_video_duration_seconds  # noqa: E402

RESULTS_DIR = EVAL_DATA_DIR / "results"
EMPTY_PREDICTION = {"incident": {}, "entities": [], "instruments": [], "assets": []}

# Frozen for the entire benchmark, per explicit confirmation - never changed
# based on results observed during the run. Checked, not just assumed: the
# embedding server's own /health response must report this exact model on
# every check, or the run aborts.
FROZEN_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
FROZEN_EMBEDDING_BASE_URL = "http://127.0.0.1:8811/v1"


def get_db():
    db = db_module.get_db()
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
) -> dict:
    """Steps 2-7 for one (model, video) pair. Returns the Step 7 per-video result dict.

    Validity follows validation policy core-scored-v1 (``contract.evaluate_policy``):
    the prediction is scored and persisted when its database-backed fields are
    valid (``core_ok``); a failure confined to the unscored enrichment fields
    (e.g. a timeline outside the incident window) does not empty it. The window is
    also checked against ``video_duration_seconds`` when that is known.
    ``p1_raw.contract_ok`` keeps its original meaning, full incident-contract
    validity, and gates RP1 as before.

    Raises ``EvaluatorDependencyError`` (aborting the whole run) if the
    embedding server or LLM judge is unavailable or invalid for this video -
    never silently continues with a missing/default score treated as valid.
    """
    check_embedding_server_healthy(FROZEN_EMBEDDING_BASE_URL, expected_model=FROZEN_EMBEDDING_MODEL)

    p1_result = analyze_video_with_p1(model, video_url)
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

    eval_result = eval_gt.run_evaluation(db, incident_id, model_run_id)
    check_judge_ok(eval_result)

    if contract_ok:
        rp1_report = generate_rp1_report(prediction)
    else:
        rp1_report = {
            "text": "", "model_id": RP1_MODEL, "prompt_version": contract.contract_version(),
            "inference_config": RP1_INFERENCE_CONFIG, "ok": False, "skipped": True,
            "error": "skipped: RP1 runs only on a fully contract-valid P1 report", "attempts": 0,
        }

    return {
        "filename": filename,
        "incident_id": incident_id,
        "category": category,
        "model_id": model,
        "prompt_version": contract.contract_version(),
        "inference_config": recorded_p1_config(),
        "split_manifest_ref": split_manifest_ref,
        "run_id": model_run_id,
        "r2_object_key": r2_object_key,
        "ground_truth": gt_p1_shaped,
        "prediction": prediction,
        # contract_ok = full incident-contract validity (unchanged meaning);
        # core_ok = core-scored-v1 validity, which decides scoring (see "validation").
        "p1_raw": {"content": p1_result.content, "reasoning_content": p1_result.reasoning_content,
                   "finish_reason": p1_result.finish_reason, "ok": p1_result.ok, "error": p1_result.error,
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
        "incident_field_scores": eval_result.fields,
        "entities": score_matches_summary(eval_result, "entities"),
        "instruments": score_matches_summary(eval_result, "instruments"),
        "assets": score_matches_summary(eval_result, "assets"),
    }


def recorded_p1_config() -> dict:
    """The P1 config as stored in results: the schema is named by contract version, not inlined."""
    recorded = dict(p1_request_config())
    recorded["response_format"] = f"json_schema:incident_report ({contract.contract_version()}, strict)"
    return recorded


def run(*, models: list[str], categories: list[str] | None, limit: int | None) -> None:
    run_started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Fail fast, before burning any P1/RP1 calls, if either evaluator
    # dependency isn't already healthy at the frozen configuration.
    check_embedding_server_healthy(FROZEN_EMBEDDING_BASE_URL, expected_model=FROZEN_EMBEDDING_MODEL)
    from eval_gt import judge_description_similarity

    judge_probe = judge_description_similarity("a person opens a door", "an individual opens a door")
    if not judge_probe.ok:
        raise EvaluatorDependencyError(f"LLM judge preflight failed: {judge_probe.error}")
    print(f"Preflight OK: embedding server ({FROZEN_EMBEDDING_MODEL}) healthy, LLM judge responding (probe score={judge_probe.data}).")

    db = get_db()
    gt_index = load_gt_index()
    basename_index = build_basename_index(r2_videos.list_video_keys())

    all_categories = sorted(gt_index["by_category"])
    target_categories = categories or all_categories

    for model in models:
        model_run_id = model_run_id_for(model)
        db.insert_model_run(model_run_id, model_name=model, prompt_version=contract.contract_version())

        for category in target_categories:
            manifest_path = EVAL_DATA_DIR / f"split_{category.lower().replace(' ', '_')}.json"
            if not manifest_path.exists():
                print(f"SKIP {category}: no split manifest at {manifest_path} (run eval_generate_split.py first)")
                continue
            manifest = json.loads(manifest_path.read_text())

            eval_filenames = manifest["evaluation_videos"][:limit] if limit else manifest["evaluation_videos"]
            results = []
            for filename in eval_filenames:
                incident_id = gt_index_lookup(gt_index, filename)
                r2_object_key = manifest["evaluation_videos_r2_keys"][filename]
                try:
                    resolved_key, video_url = resolve_and_sign(filename, basename_index)
                except ResolutionError as exc:
                    print(f"  {model} / {category} / {filename}: SKIP, {exc}")
                    continue

                print(f"  {model} / {category} / {filename} ...", end=" ", flush=True)
                if resolved_key != r2_object_key:
                    print(f"  {model} / {category} / {filename}: SKIP, R2 key {resolved_key!r} differs from manifest {r2_object_key!r}")
                    continue
                result = run_one_video(
                    db, model=model, category=category, filename=filename, incident_id=incident_id,
                    r2_object_key=r2_object_key, video_url=video_url,
                    gt_p1_shaped=gt_index["by_incident_id"][incident_id]["p1_shaped"],
                    model_run_id=model_run_id, split_manifest_ref=str(manifest_path),
                    video_duration_seconds=r2_video_duration_seconds(r2_object_key),
                )
                results.append(result)
                print(f"P1 ok={result['p1_raw']['ok']} contract_ok={result['p1_raw']['contract_ok']} "
                      f"core_ok={result['p1_raw']['core_ok']} finish={result['p1_raw']['finish_reason']} "
                      f"type_pass={result['incident_field_scores'].get('type', {}).get('pass')} "
                      f"RP1 ok={result['rp1_report']['ok']}")

            out_path, archive_path = write_results({
                "category": category,
                "model_id": model,
                "prompt_version": contract.contract_version(),
                "validation_policy": contract.POLICY_ID,
                "inference_config": recorded_p1_config(),
                "split_manifest_ref": str(manifest_path),
                "run_id": model_run_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "videos": results,
            }, run_started_at=run_started_at)
            print(f"  -> wrote {out_path} ({len(results)} videos); immutable copy {archive_path}")


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
    args = parser.parse_args()
    run(models=args.models, categories=args.categories, limit=args.limit)
