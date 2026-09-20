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

"""Tier 1 ground-truth evaluation: GT (``gt_*`` tables) vs. one model run.

Colocated with ``matching.py`` and following the same pure-logic-plus-one-DB-
boundary shape: ``compare_incident_fields`` and ``prf1`` are pure, the only
network call is ``judge_description_similarity`` (an ``agent_client``-style
fail-soft HTTP client), and ``run_evaluation`` is the one orchestration
function that touches the database, calling ``matching.match_incident``
unchanged rather than re-implementing entity/instrument/asset matching here.

This is Tier 1 methodology only: it adapts NVIDIA VSS's Pipeline A
semantic-equivalence rubric *as a prompt string*, calling the incident-console's
own LLM infrastructure (``INCIDENT_LLM_BASE_URL`` / chat completions). It never
imports ``vss_agents``, NAT, or LangChain, and never touches Pipeline A's
evaluator classes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx

import config
import matching
from incident_report import extract_message_content, timestamp_to_seconds

# --------------------------------------------------------------------------- #
# Pure scoring helpers
# --------------------------------------------------------------------------- #


def _normalized_type(value: str | None) -> str:
    return (value or "").strip().lower()


def _timestamp_seconds(value: str | int | float | None) -> int | None:
    """``HH:MM:SS`` (or bare seconds) -> seconds; ``None`` stays missing, not 0."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return timestamp_to_seconds(value)


def _tolerance_result(expected: int | None, predicted: int | None, *, tolerance: float) -> dict:
    if expected is None or predicted is None:
        return {"expected": expected, "predicted": predicted, "pass": False}
    return {"expected": expected, "predicted": predicted, "pass": abs(expected - predicted) <= tolerance}


def compare_incident_fields(gt: dict, model: dict) -> dict:
    """Per-field expected/predicted/pass (or ``score`` for description).

    Pure - takes plain GT/model incident dicts (as returned by
    ``db.get_gt_incident`` / ``db.get_incident``) and never touches the network
    or the database itself; the caller supplies the description score.
    """
    tolerance = config.EVAL_TIMESTAMP_TOLERANCE_SECONDS
    gt_type, model_type = _normalized_type(gt.get("type")), _normalized_type(model.get("type"))
    gt_severity, model_severity = gt.get("severity_level"), model.get("severity_level")

    return {
        "type": {
            "expected": gt.get("type"),
            "predicted": model.get("type"),
            "pass": bool(gt_type) and gt_type == model_type,
        },
        "severity_level": {
            "expected": gt_severity,
            "predicted": model_severity,
            "pass": gt_severity is not None and gt_severity == model_severity,
        },
        "description": {
            "expected": gt.get("description"),
            "predicted": model.get("description"),
        },
        "start_timestamp": _tolerance_result(
            _timestamp_seconds(gt.get("start_timestamp")),
            _timestamp_seconds(model.get("start_timestamp")),
            tolerance=tolerance,
        ),
        "end_timestamp": _tolerance_result(
            _timestamp_seconds(gt.get("end_timestamp")),
            _timestamp_seconds(model.get("end_timestamp")),
            tolerance=tolerance,
        ),
        "duration": _tolerance_result(gt.get("duration"), model.get("duration"), tolerance=tolerance),
    }


def prf1(tp: int, fp: int, fn: int) -> dict:
    """Precision/Recall/F1, divide-by-zero-safe (0.0 when a denominator is 0)."""
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


# --------------------------------------------------------------------------- #
# LLM-as-a-judge description scoring (agent_client.py's exact _post/Result
# /fail-soft pattern - a plain function here since there's exactly one call).
# --------------------------------------------------------------------------- #


@dataclass
class Result:
    ok: bool
    data: float | None = None
    error: str = ""
    status_code: int | None = None


# Adapted (as prompt text, never imported code) from Pipeline A's
# semantic-equivalence rubric (services/agent/.../evaluators/), scoring 0.0-1.0
# for two incident descriptions describing the same underlying event.
_JUDGE_SYSTEM_PROMPT = """INCIDENT_JUDGE_REQUEST
You are scoring whether two incident descriptions describe the same underlying
event, allowing for different wording, phrasing, and level of detail. Score
0.0 (unrelated events) to 1.0 (semantically equivalent). Respond with a JSON
object: {"score": <float 0.0-1.0>, "reasoning": "<one sentence>"}."""

_SCORE_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_SCORE_BARE_OBJECT = re.compile(r"(\{[\s\S]*\"score\"[\s\S]*\})")
_SCORE_FALLBACK = re.compile(r"([01](?:\.\d+)?)")


def _extract_score(content: str) -> float | None:
    """Fenced/bare-JSON fallback, mirroring ``incident_report.parse_incident_report``."""
    import json

    if not content:
        return None
    for pattern in (_SCORE_JSON_BLOCK, _SCORE_BARE_OBJECT):
        match = pattern.search(content)
        if not match:
            continue
        try:
            score = json.loads(match.group(1)).get("score")
            return max(0.0, min(1.0, float(score)))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    match = _SCORE_FALLBACK.search(content)
    if match:
        try:
            return max(0.0, min(1.0, float(match.group(1))))
        except ValueError:
            return None
    return None


def judge_description_similarity(expected: str, predicted: str, *, timeout: float | None = None) -> Result:
    """LLM-as-a-judge 0.0-1.0 semantic score for two incident descriptions.

    Fails soft (``ok=False``) when ``INCIDENT_LLM_BASE_URL`` is unset, the
    request fails, or the response cannot be parsed into a score - never
    raises, matching ``agent_client.py`` / ``embed_client.py``.
    """
    base_url = config.llm_base_url()
    if not base_url:
        return Result(ok=False, error="INCIDENT_LLM_BASE_URL is not set")
    prompt = f"EXPECTED: {expected or ''}\nPREDICTED: {predicted or ''}"
    try:
        resp = httpx.post(
            f"{base_url}/chat/completions",
            json={
                "model": "incident-judge",
                "messages": [
                    {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=timeout or config.http_timeout_seconds(),
        )
    except httpx.HTTPError as exc:
        return Result(ok=False, error=f"{type(exc).__name__}: {exc}")
    if resp.status_code >= 400:
        return Result(ok=False, status_code=resp.status_code, error=f"HTTP {resp.status_code}: {resp.text[:400]}")
    try:
        body = resp.json()
    except ValueError:
        return Result(ok=False, error="judge endpoint returned a non-JSON body")
    score = _extract_score(extract_message_content(body))
    if score is None:
        return Result(ok=False, error=f"could not extract a score from judge response: {body!r}")
    return Result(ok=True, data=score, status_code=resp.status_code)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


@dataclass
class EvaluationResult:
    incident_id: str
    model_run_id: str
    fields: dict = field(default_factory=dict)
    description_score: float | None = None
    description_error: str = ""
    matches: dict[str, list[dict]] = field(default_factory=dict)
    counts: dict[str, dict] = field(default_factory=dict)
    unmatched: dict[str, dict[str, list[dict]]] = field(default_factory=dict)


_KIND_ID_FIELD = {"entities": "entity_id", "instruments": "instrument_id", "assets": "asset_id"}
_KIND_LIST_METHOD = {
    "entities": "list_incident_entities",
    "instruments": "list_incident_instruments",
    "assets": "list_incident_assets",
}
_KIND_GT_LIST_METHOD = {
    "entities": "list_gt_entities",
    "instruments": "list_gt_instruments",
    "assets": "list_gt_assets",
}


def _unmatched_rows(rows: list[dict], id_field: str, matched_ids: set[str]) -> list[dict]:
    return [r for r in rows if r.get(id_field) not in matched_ids]


def run_evaluation(db, incident_id: str, model_run_id: str) -> EvaluationResult:
    """Load GT + model rows, score incident fields, match evidence, tally P/R/F1."""
    gt_incident = db.get_gt_incident(incident_id)
    model_incident = db.get_incident(incident_id, model_run_id)

    fields = compare_incident_fields(gt_incident, model_incident)
    judge = judge_description_similarity(gt_incident.get("description"), model_incident.get("description"))
    result = EvaluationResult(incident_id=incident_id, model_run_id=model_run_id, fields=fields)
    if judge.ok:
        result.description_score = judge.data
        fields["description"]["score"] = judge.data
        fields["description"]["pass"] = judge.data >= 0.5
    else:
        result.description_error = judge.error
        fields["description"]["score"] = None
        fields["description"]["pass"] = False

    matches = matching.match_incident(db, incident_id, model_run_id)
    result.matches = matches

    for kind, id_field in _KIND_ID_FIELD.items():
        model_rows = getattr(db, _KIND_LIST_METHOD[kind])(incident_id, model_run_id)
        gt_rows = getattr(db, _KIND_GT_LIST_METHOD[kind])(incident_id)
        kind_matches = matches.get(kind, [])
        tp = len(kind_matches)
        fp = len(model_rows) - tp
        fn = len(gt_rows) - tp
        result.counts[kind] = prf1(tp, fp, fn)

        matched_model_ids = {m[id_field] for m in kind_matches}
        matched_gt_ids = {m[f"gt_{id_field}"] for m in kind_matches}
        result.unmatched[kind] = {
            "model": _unmatched_rows(model_rows, id_field, matched_model_ids),
            "gt": _unmatched_rows(gt_rows, id_field, matched_gt_ids),
        }

    return result
