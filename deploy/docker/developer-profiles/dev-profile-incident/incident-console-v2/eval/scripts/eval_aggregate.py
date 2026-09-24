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

"""Cross-category, cross-model summary over the per-(category, model) result
files ``eval_run.py`` writes. Read-only: never re-scores, never re-runs
anything, never changes a threshold or a value - purely aggregates what is
already persisted. Metrics stay broken out throughout (by category x model,
by model pooled, overall pooled) - never collapsed into one blended score,
per the confirmed requirement.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_ingest_gt import EVAL_DATA_DIR  # noqa: E402

RESULTS_DIR = EVAL_DATA_DIR / "results"


def _pct(numerator: int, denominator: int) -> float | None:
    return round(100.0 * numerator / denominator, 1) if denominator else None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def aggregate_one(category_model: dict) -> dict:
    """One (category, model) pair's aggregate block, from its ``videos`` list."""
    videos = category_model["videos"]
    n = len(videos)

    field_pass = {"type": [], "severity_level": [], "start_timestamp": [], "end_timestamp": [], "duration": []}
    field_abs_error = {"start_timestamp": [], "end_timestamp": [], "duration": []}
    description_scores = []

    pooled_counts = {"entities": {"tp": 0, "fp": 0, "fn": 0}, "instruments": {"tp": 0, "fp": 0, "fn": 0}, "assets": {"tp": 0, "fp": 0, "fn": 0}}
    attribute_pass = {
        "entities": {"type": [], "description": []},
        "instruments": {"name": [], "description": [], "threat_level": []},
        "assets": {"name": [], "description": []},
    }
    holder_status_counts = {"correct": 0, "incorrect": 0, "unresolved": 0}

    p1_failures = []
    rp1_failures = []

    for v in videos:
        if not v["p1_raw"]["ok"]:
            p1_failures.append(v["filename"])
        if not v["rp1_report"]["ok"]:
            rp1_failures.append(v["filename"])

        fs = v["incident_field_scores"]
        for field in field_pass:
            entry = fs.get(field, {})
            if "pass" in entry:
                field_pass[field].append(bool(entry["pass"]))
            if field in field_abs_error and entry.get("expected") is not None and entry.get("predicted") is not None:
                try:
                    field_abs_error[field].append(abs(float(entry["expected"]) - float(entry["predicted"])))
                except (TypeError, ValueError):
                    pass
        if fs.get("description", {}).get("score") is not None:
            description_scores.append(fs["description"]["score"])

        for kind in ("entities", "instruments", "assets"):
            counts = v[kind]["counts"]
            for k in ("tp", "fp", "fn"):
                pooled_counts[kind][k] += counts.get(k, 0)
            for m in v[kind]["matches"]:
                attrs = m.get("attribute_scores", {})
                for attr_name, attr_val in attrs.items():
                    if attr_name == "holder":
                        holder_status_counts[attr_val["status"]] = holder_status_counts.get(attr_val["status"], 0) + 1
                        continue
                    if attr_name in attribute_pass.get(kind, {}) and "pass" in attr_val:
                        attribute_pass[kind][attr_name].append(bool(attr_val["pass"]))

    def _prf1(c: dict) -> dict:
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        return {"tp": tp, "fp": fp, "fn": fn, "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}

    return {
        "num_videos": n,
        "p1_failures": p1_failures,
        "rp1_failures": rp1_failures,
        "incident_field_accuracy": {
            "type": _pct(sum(field_pass["type"]), len(field_pass["type"])),
            "severity_level": _pct(sum(field_pass["severity_level"]), len(field_pass["severity_level"])),
            "start_timestamp": {"tolerance_accuracy_pct": _pct(sum(field_pass["start_timestamp"]), len(field_pass["start_timestamp"])), "mean_abs_error_s": _mean(field_abs_error["start_timestamp"])},
            "end_timestamp": {"tolerance_accuracy_pct": _pct(sum(field_pass["end_timestamp"]), len(field_pass["end_timestamp"])), "mean_abs_error_s": _mean(field_abs_error["end_timestamp"])},
            "duration": {"tolerance_accuracy_pct": _pct(sum(field_pass["duration"]), len(field_pass["duration"])), "mean_abs_error_s": _mean(field_abs_error["duration"])},
            "description": {"mean_score": _mean(description_scores), "n_scored": len(description_scores)},
        },
        "entities": {**_prf1(pooled_counts["entities"]), "attribute_accuracy": {k: _pct(sum(v), len(v)) for k, v in attribute_pass["entities"].items()}},
        "instruments": {**_prf1(pooled_counts["instruments"]), "attribute_accuracy": {k: _pct(sum(v), len(v)) for k, v in attribute_pass["instruments"].items()}, "holder_resolution": dict(holder_status_counts)},
        "assets": {**_prf1(pooled_counts["assets"]), "attribute_accuracy": {k: _pct(sum(v), len(v)) for k, v in attribute_pass["assets"].items()}},
    }


def pool_aggregates(aggregates: list[dict]) -> dict:
    """Pool several (category, model) aggregate blocks into one (micro-average)."""
    n = sum(a["num_videos"] for a in aggregates)
    p1_failures = [f for a in aggregates for f in a["p1_failures"]]
    rp1_failures = [f for a in aggregates for f in a["rp1_failures"]]

    def pool_field(name, sub=None):
        vals, errs = [], []
        for a in aggregates:
            block = a["incident_field_accuracy"][name]
            if sub:
                pct, n_ = (block["tolerance_accuracy_pct"], a["num_videos"])
                if pct is not None:
                    vals.append((pct, n_))
                if block["mean_abs_error_s"] is not None:
                    errs.append(block["mean_abs_error_s"])
            else:
                pct = block
                if pct is not None:
                    vals.append((pct, a["num_videos"]))
        weighted = sum(p * w for p, w in vals) / sum(w for _, w in vals) if vals else None
        result = {"tolerance_accuracy_pct": round(weighted, 1)} if sub else round(weighted, 1) if weighted is not None else None
        if sub:
            result["mean_abs_error_s"] = _mean(errs)
        return result

    description_scores_weighted = []
    for a in aggregates:
        d = a["incident_field_accuracy"]["description"]
        if d["mean_score"] is not None:
            description_scores_weighted.extend([d["mean_score"]] * d["n_scored"])

    def pool_kind(kind):
        tp = sum(a[kind]["tp"] for a in aggregates)
        fp = sum(a[kind]["fp"] for a in aggregates)
        fn = sum(a[kind]["fn"] for a in aggregates)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        attr_names = set()
        for a in aggregates:
            attr_names.update(a[kind]["attribute_accuracy"])
        attr_pooled = {}
        for name in attr_names:
            vals = [(a[kind]["attribute_accuracy"].get(name), a[kind]["tp"]) for a in aggregates if a[kind]["attribute_accuracy"].get(name) is not None]
            attr_pooled[name] = round(sum(p * w for p, w in vals) / sum(w for _, w in vals), 1) if vals and sum(w for _, w in vals) else None
        result = {"tp": tp, "fp": fp, "fn": fn, "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3), "attribute_accuracy": attr_pooled}
        if kind == "instruments":
            holder = {"correct": 0, "incorrect": 0, "unresolved": 0}
            for a in aggregates:
                for k, v in a[kind]["holder_resolution"].items():
                    holder[k] = holder.get(k, 0) + v
            result["holder_resolution"] = holder
        return result

    return {
        "num_videos": n,
        "p1_failures": p1_failures,
        "rp1_failures": rp1_failures,
        "incident_field_accuracy": {
            "type": pool_field("type"),
            "severity_level": pool_field("severity_level"),
            "start_timestamp": pool_field("start_timestamp", sub=True),
            "end_timestamp": pool_field("end_timestamp", sub=True),
            "duration": pool_field("duration", sub=True),
            "description": {"mean_score": _mean(description_scores_weighted), "n_scored": len(description_scores_weighted)},
        },
        "entities": pool_kind("entities"),
        "instruments": pool_kind("instruments"),
        "assets": pool_kind("assets"),
    }


def main() -> None:
    files = sorted(RESULTS_DIR.glob("*.json"))
    files = [f for f in files if f.name != "summary.json"]
    by_category_and_model: dict[str, dict[str, dict]] = {}
    by_model_raw: dict[str, list[dict]] = {}
    models_seen = {}

    for f in files:
        data = json.loads(f.read_text())
        category, model = data["category"], data["model_id"]
        agg = aggregate_one(data)
        by_category_and_model.setdefault(category, {})[model] = agg
        by_model_raw.setdefault(model, []).append(agg)
        models_seen[model] = {"model_id": model, "prompt_version": data["prompt_version"], "inference_config": data["inference_config"]}

    by_model = {model: pool_aggregates(aggs) for model, aggs in by_model_raw.items()}
    overall = pool_aggregates([agg for aggs in by_model_raw.values() for agg in aggs])

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "models": list(models_seen.values()),
        "by_category_and_model": by_category_and_model,
        "by_model": by_model,
        "overall": overall,
    }
    out_path = RESULTS_DIR / "summary.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
