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

"""Severity reporting extension (evaluation-methodology-v1.3, reporting only).

Computed from saved results; no score in a result changes and no model or judge is called.

- **Valid severity prediction:** a video-run with a model output whose severity field was scored and holds a
  level 1-5 (``extraction_stats.field_status`` = scored and a predicted level). Request failures and invalid
  outputs (no predicted level) are **not** given a severity value; they are counted in coverage.
- **Primary:** MAE = mean |predicted - expected| over valid predictions, in severity levels.
- **Supporting:** mean signed error (predicted - expected), exact and within-one accuracy over valid predictions,
  the confusion matrix (``extraction_stats.severity_analysis``, unchanged), coverage and failure categories.
- **Paired comparison:** per video, the mean over its repeats with a valid prediction; a video counts when both
  sides have one. 95% video-level cluster bootstrap (repeats move with their video), seed and resamples
  from ``methodology``.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterable

import extraction_stats
import methodology

REPORT_VERSION = "severity-report-v1.3"


def run_errors(video: dict) -> dict:
    """``{"status", "expected", "predicted", "error"}`` for one video-run (error ``None`` unless valid)."""
    status, _ = extraction_stats.field_status(video, "severity_level")
    entry = (video.get("incident_field_scores") or {}).get("severity_level") or {}
    expected = extraction_stats._as_level(entry.get("expected"))
    predicted = extraction_stats._as_level(entry.get("predicted"))
    if status == "scored" and expected is not None and predicted is not None:
        return {"status": "valid", "expected": expected, "predicted": predicted, "error": predicted - expected}
    if status == "no_model_output":
        return {"status": "no_model_output", "expected": expected, "predicted": None, "error": None}
    if status == "scored":
        return {"status": "no_predicted_level", "expected": expected, "predicted": None, "error": None}
    return {"status": status, "expected": expected, "predicted": None, "error": None}


def summarise(videos: Iterable[dict]) -> dict:
    videos = list(videos)
    rows = [run_errors(v) for v in videos]
    errors = [r["error"] for r in rows if r["status"] == "valid"]
    n = len(errors)
    return {
        "attempted": len(videos),
        "valid": n,
        "coverage": round(n / len(videos), 4) if videos else None,
        "failure_categories": dict(Counter(r["status"] for r in rows if r["status"] != "valid")),
        "outcomes_without_valid_severity": dict(Counter(v.get("outcome") for v, r in zip(videos, rows, strict=True)
                                                        if r["status"] != "valid")),
        "mae": round(sum(abs(e) for e in errors) / n, 4) if n else None,
        "mean_signed_error": round(sum(errors) / n, 4) if n else None,
        "exact": round(sum(e == 0 for e in errors) / n, 4) if n else None,
        "within_one": round(sum(abs(e) <= 1 for e in errors) / n, 4) if n else None,
        "over_rated": sum(e > 0 for e in errors), "under_rated": sum(e < 0 for e in errors),
        "confusion": extraction_stats.severity_analysis(videos)["confusion"],
    }


def per_video(videos: Iterable[dict]) -> dict[str, dict[str, float]]:
    """Per video, the mean absolute and signed error over its repeats with a valid prediction."""
    errors: dict[str, list[int]] = {}
    for video in videos:
        row = run_errors(video)
        if row["status"] == "valid":
            errors.setdefault(video["incident_id"], []).append(row["error"])
    return {v: {"abs": sum(abs(e) for e in es) / len(es), "signed": sum(es) / len(es)} for v, es in errors.items()}


def _ci(values: list[float], resamples: int, seed: int) -> list[float] | None:
    if not values:
        return None
    rng = random.Random(seed)
    means = sorted(sum(values[rng.randrange(len(values))] for _ in values) / len(values) for _ in range(resamples))
    return [round(means[int(0.025 * (resamples - 1))], 4), round(means[int(0.975 * (resamples - 1))], 4)]


def paired(baseline: Iterable[dict], candidate: Iterable[dict], *, resamples: int | None = None,
           seed: int | None = None) -> dict:
    """Candidate minus baseline per video (MAE and signed error), with 95% video-cluster bootstrap intervals.

    A negative MAE difference means a smaller severity error than the baseline.
    """
    resamples = resamples or methodology.BOOTSTRAP_RESAMPLES
    seed = methodology.BOOTSTRAP_SEED if seed is None else seed
    a, b = per_video(baseline), per_video(candidate)
    videos = sorted(set(a) & set(b))
    out = {"pairs": len(videos)}
    for key in ("abs", "signed"):
        diffs = [b[v][key] - a[v][key] for v in videos]
        name = "mae_difference" if key == "abs" else "signed_error_difference"
        out[name] = round(sum(diffs) / len(diffs), 4) if diffs else None
        out[f"{name}_ci95"] = _ci(diffs, resamples, seed)
    out["baseline_mae_on_pairs"] = round(sum(a[v]["abs"] for v in videos) / len(videos), 4) if videos else None
    out["candidate_mae_on_pairs"] = round(sum(b[v]["abs"] for v in videos) / len(videos), 4) if videos else None
    return out
