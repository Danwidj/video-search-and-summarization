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
model, with everything except ``model`` held fixed (same P1 prompt, same 5
few-shot demonstrations per category in the same serialization/order, same
fixed inference config, same held-out split, same evaluator).

For each (category, model, evaluation video):
  1. Resolve + cache the video (``eval_video_resolution``, exact-basename only).
  2. Call P1 with the category's fixed few-shot block (``eval_few_shot``).
  3. Parse the JSON prediction (``eval_vlm_client.extract_json``).
  4. Persist the prediction to the DB under this model's own ``model_run_id``.
  5. Score it against GT (``eval_gt.run_evaluation`` - reuses ``matching.py``
     unchanged; entity/instrument/asset matches will be empty until a real
     embeddings endpoint is configured, see ``config.embedding_base_url()``).
  6. Call RP1 (one fixed report-generation model/config, same for every P1
     model) on the prediction; report is persisted, never scored.
  7. Accumulate the Step 7 per-video result; write one JSON file per
     (category, model) once that pair's videos are done.

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
import db as db_module  # noqa: E402
from db_postgrest import PostgrestIncidentDB  # noqa: E402
from db_postgrest import configured as postgrest_configured  # noqa: E402
import eval_gt  # noqa: E402
from eval_few_shot import build_few_shot_block  # noqa: E402
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
from eval_vlm_client import MODELS, analyze_video_with_p1, extract_json, generate_report_with_rp1  # noqa: E402
from eval_video_resolution import ResolutionError, build_basename_index, resolve_and_cache  # noqa: E402
from prompts import P1_INCIDENT_EXTRACTION_PROMPT, P1_PROMPT_VERSION, RP1_PROMPT_VERSION, RP1_REPORT_GENERATION_PROMPT  # noqa: E402
import r2_videos  # noqa: E402

RESULTS_DIR = EVAL_DATA_DIR / "results"

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


def run_one_video(
    db, *, model: str, category: str, filename: str, incident_id: str, r2_object_key: str, local_video_path: Path,
    few_shot_block: str, gt_p1_shaped: dict, model_run_id: str, split_manifest_ref: str,
) -> dict:
    """Steps 2-7 for one (model, video) pair. Returns the Step 7 per-video result dict.

    Raises ``EvaluatorDependencyError`` (aborting the whole run) if the
    embedding server or LLM judge is unavailable or invalid for this video -
    never silently continues with a missing/default score treated as valid.
    """
    check_embedding_server_healthy(FROZEN_EMBEDDING_BASE_URL, expected_model=FROZEN_EMBEDDING_MODEL)

    p1_result = analyze_video_with_p1(model, local_video_path, P1_INCIDENT_EXTRACTION_PROMPT, few_shot_block=few_shot_block)
    prediction = extract_json(p1_result.content) or extract_json(p1_result.reasoning_content) or {}
    prediction.setdefault("incident", {})
    prediction.setdefault("entities", [])
    prediction.setdefault("instruments", [])
    prediction.setdefault("assets", [])

    persist_prediction(db, incident_id, model_run_id, prediction)

    eval_result = eval_gt.run_evaluation(db, incident_id, model_run_id)
    check_judge_ok(eval_result)

    rp1_result = generate_report_with_rp1(RP1_MODEL, RP1_REPORT_GENERATION_PROMPT, prediction, inference_config=RP1_INFERENCE_CONFIG)
    rp1_report = {
        "text": rp1_result.content or rp1_result.reasoning_content or "",
        "model_id": RP1_MODEL,
        "prompt_version": RP1_PROMPT_VERSION,
        "inference_config": RP1_INFERENCE_CONFIG,
        "ok": rp1_result.ok,
        "error": rp1_result.error,
    }

    return {
        "filename": filename,
        "incident_id": incident_id,
        "category": category,
        "model_id": model,
        "prompt_version": P1_PROMPT_VERSION,
        "inference_config": eval_vlm_client_fixed_config(),
        "split_manifest_ref": split_manifest_ref,
        "run_id": model_run_id,
        "r2_object_key": r2_object_key,
        "ground_truth": gt_p1_shaped,
        "prediction": prediction,
        "p1_raw": {"content": p1_result.content, "reasoning_content": p1_result.reasoning_content,
                   "finish_reason": p1_result.finish_reason, "ok": p1_result.ok, "error": p1_result.error},
        "rp1_report": rp1_report,
        "incident_field_scores": eval_result.fields,
        "entities": score_matches_summary(eval_result, "entities"),
        "instruments": score_matches_summary(eval_result, "instruments"),
        "assets": score_matches_summary(eval_result, "assets"),
    }


def eval_vlm_client_fixed_config() -> dict:
    from eval_vlm_client import FIXED_INFERENCE_CONFIG

    return dict(FIXED_INFERENCE_CONFIG)


def run(*, models: list[str], categories: list[str] | None, limit: int | None) -> None:
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
        db.insert_model_run(model_run_id, model_name=model, prompt_version=P1_PROMPT_VERSION)

        for category in target_categories:
            manifest_path = EVAL_DATA_DIR / f"split_{category.lower().replace(' ', '_')}.json"
            if not manifest_path.exists():
                print(f"SKIP {category}: no split manifest at {manifest_path} (run eval_generate_split.py first)")
                continue
            manifest = json.loads(manifest_path.read_text())

            few_shot_examples = [
                gt_index["by_incident_id"][gt_index_lookup(gt_index, fn)]["p1_shaped"]
                for fn in manifest["few_shot_demo_videos"]
            ]
            few_shot_block = build_few_shot_block(few_shot_examples)

            eval_filenames = manifest["evaluation_videos"][:limit] if limit else manifest["evaluation_videos"]
            results = []
            for filename in eval_filenames:
                incident_id = gt_index_lookup(gt_index, filename)
                r2_object_key = manifest["evaluation_videos_r2_keys"][filename]
                try:
                    _, local_path = resolve_and_cache(filename, basename_index)
                except ResolutionError as exc:
                    print(f"  {model} / {category} / {filename}: SKIP, {exc}")
                    continue

                print(f"  {model} / {category} / {filename} ...", end=" ", flush=True)
                result = run_one_video(
                    db, model=model, category=category, filename=filename, incident_id=incident_id,
                    r2_object_key=r2_object_key, local_video_path=local_path, few_shot_block=few_shot_block,
                    gt_p1_shaped=gt_index["by_incident_id"][incident_id]["p1_shaped"],
                    model_run_id=model_run_id, split_manifest_ref=str(manifest_path),
                )
                results.append(result)
                print(f"P1 ok={result['p1_raw']['ok']} finish={result['p1_raw']['finish_reason']} "
                      f"type_pass={result['incident_field_scores'].get('type', {}).get('pass')} "
                      f"RP1 ok={result['rp1_report']['ok']}")

            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            out_path = RESULTS_DIR / f"{category.lower().replace(' ', '_')}__{safe_model_id(model)}.json"
            out_path.write_text(json.dumps({
                "category": category,
                "model_id": model,
                "prompt_version": P1_PROMPT_VERSION,
                "inference_config": eval_vlm_client_fixed_config(),
                "split_manifest_ref": str(manifest_path),
                "run_id": model_run_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "few_shot_demo_videos": manifest["few_shot_demo_videos"],
                "videos": results,
            }, indent=2))
            print(f"  -> wrote {out_path} ({len(results)} videos)")


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
