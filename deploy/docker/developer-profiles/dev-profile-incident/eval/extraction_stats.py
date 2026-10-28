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

"""Per-video statistics for the P1 extraction benchmark (``evaluation-methodology-v1.0``).

Pure functions over ``eval_run.py`` result records (``videos`` entries). The video is the
unit: field accuracies, their 95% bootstrap intervals and paired differences between two
runs on the same videos all resample videos, with the seed pinned in ``methodology.py``.
An unscored value (``pass`` is ``None``) is left out of its field and counted, never
treated as a fail.
"""

from __future__ import annotations

from collections.abc import Iterable

import methodology
from retrieval_metrics import bootstrap_interval

INCIDENT_FIELDS = ("type", "severity_level", "start_timestamp", "end_timestamp", "duration", "description")
# No model output (request failures): excluded from accuracy and from paired comparisons, and counted.
# A model output that is invalid (contract_invalid, parse_failure) stays in, scored as a miss.
NO_MODEL_OUTPUT = ("timeout", "rate_limited", "host_suspended", "http_error")


INVALID_MODEL_OUTPUT = ("contract_invalid", "parse_failure")


def has_model_output(video: dict) -> bool:
    return video.get("outcome") not in NO_MODEL_OUTPUT


def is_out_of_taxonomy(video: dict) -> bool:
    """Confirmed out-of-taxonomy status, from the video's ground truth only (never the prediction)."""
    return bool(((video.get("ground_truth") or {}).get("incident") or {}).get("out_of_taxonomy"))


def field_status(video: dict, field: str) -> tuple[str, float | None]:
    """Why a field does or does not count for one video, and its value when it does.

    ``("out_of_taxonomy", None)`` for the type of a confirmed out-of-taxonomy clip (not an
    eligible field); ``("no_model_output", None)`` after a request failure; ``("unscored", None)``
    when the scorer could not score it; otherwise ``("scored", 1.0 | 0.0)``.
    """
    if field == "type" and is_out_of_taxonomy(video):
        return "out_of_taxonomy", None
    if not has_model_output(video):
        return "no_model_output", None
    entry = (video.get("incident_field_scores") or {}).get(field) or {}
    passed = entry.get("pass")
    if passed is None:
        return "unscored", None
    return "scored", 1.0 if passed else 0.0
SEVERITY_LEVELS = (1, 2, 3, 4, 5)


def field_value(video: dict, field: str) -> float | None:
    """1.0 pass, 0.0 fail, or ``None`` when the field does not count for this video (see ``field_status``)."""
    return field_status(video, field)[1]


def _interval(values: list[float]) -> list[float] | None:
    interval = bootstrap_interval(values, resamples=methodology.BOOTSTRAP_RESAMPLES, seed=methodology.BOOTSTRAP_SEED,
                                  confidence=methodology.BOOTSTRAP_CONFIDENCE)
    return [round(interval[0], 4), round(interval[1], 4)] if interval else None


def field_intervals(videos: Iterable[dict]) -> dict[str, dict]:
    """Per incident field: eligible videos by status, conditional and end-to-end accuracy with 95% intervals.

    - **Conditional accuracy** (``accuracy``): over videos with a model output and a scored value.
      An invalid model output is scored as a miss and stays in.
    - **End-to-end accuracy** (``end_to_end``): over every attempted video for which the field is
      eligible, with a request failure (no model output) counted as a miss.
    - The type of a confirmed out-of-taxonomy clip is not eligible: it is left out of both and
      counted (``out_of_taxonomy``). Unscored values are left out of both and counted.
    """
    videos = list(videos)
    out = {}
    for field in INCIDENT_FIELDS:
        statuses = [field_status(video, field) for video in videos]
        counts = {s: sum(1 for status, _ in statuses if status == s)
                  for s in ("scored", "no_model_output", "unscored", "out_of_taxonomy")}
        conditional = [v for status, v in statuses if status == "scored"]
        end_to_end = conditional + [0.0] * counts["no_model_output"]
        out[field] = {
            "n": counts["scored"],
            "no_model_output": counts["no_model_output"],
            "unscored": counts["unscored"],
            "out_of_taxonomy": counts["out_of_taxonomy"],
            "accuracy": round(sum(conditional) / len(conditional), 4) if conditional else None,
            "ci95": _interval(conditional),
            "end_to_end": {
                "n": len(end_to_end),
                "accuracy": round(sum(end_to_end) / len(end_to_end), 4) if end_to_end else None,
                "ci95": _interval(end_to_end),
            },
        }
    return out


def reliability(videos: Iterable[dict]) -> dict:
    """Outcome counts and rates, so end-to-end reliability is reported apart from conditional accuracy."""
    videos = list(videos)
    outcomes: dict[str, int] = {}
    for video in videos:
        outcome = video.get("outcome") or "unknown"
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    attempted = len(videos)
    no_output = sum(outcomes.get(o, 0) for o in NO_MODEL_OUTPUT)
    invalid = sum(outcomes.get(o, 0) for o in INVALID_MODEL_OUTPUT)
    rate = (lambda k: round(k / attempted, 4) if attempted else None)  # noqa: E731
    return {
        "attempted": attempted,
        "outcomes": dict(sorted(outcomes.items())),
        "no_model_output": no_output,
        "invalid_model_output": invalid,
        "model_output_rate": rate(attempted - no_output),
        "valid_output_rate": rate(attempted - no_output - invalid),
    }


def out_of_taxonomy_summary(videos: Iterable[dict]) -> dict:
    """The confirmed out-of-taxonomy clips (from the ground truth) and, secondarily, nearest-type agreement."""
    clips = [video for video in videos if is_out_of_taxonomy(video)]
    agree = n = 0
    for video in clips:
        nearest = ((video.get("ground_truth") or {}).get("incident") or {}).get("nearest_type")
        predicted = (((video.get("incident_field_scores") or {}).get("type") or {}).get("predicted"))
        if nearest and has_model_output(video) and predicted:
            n += 1
            agree += str(predicted).strip().lower() == nearest
    return {
        "count": len(clips),
        "incident_ids": sorted({video.get("incident_id") for video in clips}),
        "nearest_type_agreement": {"agree": agree, "n": n},
    }


def _as_level(value) -> int | None:
    try:
        level = float(value)
    except (TypeError, ValueError):
        return None
    return int(level) if level.is_integer() and int(level) in SEVERITY_LEVELS else None


def severity_analysis(videos: Iterable[dict]) -> dict:
    """Exact and within-one accuracy, mean signed error (predicted - expected) and the confusion matrix.

    Rows are ground-truth levels, columns predicted levels plus ``missing`` (no valid prediction).
    A missing prediction counts against exact and within-one accuracy, as a miss does in the field score.
    """
    confusion = {str(gt): {**{str(p): 0 for p in SEVERITY_LEVELS}, "missing": 0} for gt in SEVERITY_LEVELS}
    exact = within_one = n = 0
    errors = []
    for video in videos:
        if field_status(video, "severity_level")[0] != "scored":
            continue
        entry = (video.get("incident_field_scores") or {}).get("severity_level") or {}
        expected, predicted = _as_level(entry.get("expected")), _as_level(entry.get("predicted"))
        if expected is None:
            continue
        n += 1
        if predicted is None:
            confusion[str(expected)]["missing"] += 1
            continue
        confusion[str(expected)][str(predicted)] += 1
        exact += predicted == expected
        within_one += abs(predicted - expected) <= 1
        errors.append(predicted - expected)
    return {
        "n": n,
        "exact": round(exact / n, 4) if n else None,
        "within_one": round(within_one / n, 4) if n else None,
        "mean_signed_error": round(sum(errors) / len(errors), 4) if errors else None,
        "predicted": len(errors),
        "confusion": confusion,
    }


def instrument_attributes(videos: Iterable[dict]) -> dict:
    """Threat level (exact, within one) and holder accuracy over matched instruments, with counts."""
    threat_exact = threat_within = threat_n = 0
    holder = {"correct": 0, "incorrect": 0, "unresolved": 0}
    for video in videos:
        for match in (video.get("instruments") or {}).get("matches", []):
            scores = match.get("attribute_scores", {})
            threat = scores.get("threat_level") or {}
            expected, predicted = _as_level(threat.get("expected")), _as_level(threat.get("predicted"))
            if expected is not None:
                threat_n += 1
                if predicted is not None:
                    threat_exact += predicted == expected
                    threat_within += abs(predicted - expected) <= 1
            status = (scores.get("holder") or {}).get("status")
            if status in holder:
                holder[status] += 1
    resolved = holder["correct"] + holder["incorrect"]
    return {
        "threat_level": {"n": threat_n, "exact": round(threat_exact / threat_n, 4) if threat_n else None,
                         "within_one": round(threat_within / threat_n, 4) if threat_n else None},
        "holder": {**holder, "accuracy": round(holder["correct"] / resolved, 4) if resolved else None},
    }


def paired_difference(videos_a: Iterable[dict], videos_b: Iterable[dict], field: str) -> dict:
    """Mean of (B - A) per video over videos scored in both runs, with its 95% interval.

    Videos are paired by ``incident_id``; a video unscored or absent on either side is left out
    and counted, so both sides always cover the same videos.
    """
    a = {v["incident_id"]: field_value(v, field) for v in videos_a}
    b = {v["incident_id"]: field_value(v, field) for v in videos_b}
    shared = sorted(set(a) & set(b))
    differences = [b[i] - a[i] for i in shared if a[i] is not None and b[i] is not None]
    return {
        "field": field,
        "n_pairs": len(differences),
        "excluded": len(set(a) | set(b)) - len(differences),
        "mean_difference": round(sum(differences) / len(differences), 4) if differences else None,
        "ci95": _interval(differences),
    }
