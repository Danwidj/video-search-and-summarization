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

Only the database-backed fields are scored. ``p1_failures`` are the responses
scored as a miss; ``contract_failures`` (not fully incident-contract valid),
``core_failures`` (database-backed fields invalid) and
``enrichment_violation_videos`` (unscored-field problems, e.g. a timeline
outside the incident window) are diagnostics, never part of a quality score.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import extraction_stats  # noqa: E402
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
    # Unscored values (pass is None: the judge or embedder could not score them) are counted,
    # never folded into a field as a fail (evaluation-methodology-v1.0).
    unscored = {field: 0 for field in ("type", "severity_level", "start_timestamp", "end_timestamp", "duration",
                                       "description")}
    unscored_kinds = {"entities": 0, "instruments": 0, "assets": 0}

    p1_failures = []
    rp1_failures = []

    contract_failures = []
    core_failures = []
    enrichment_violation_videos: dict[str, int] = {}
    for v in videos:
        raw = v["p1_raw"]
        # The validity that decided scoring: core_ok under core-scored-v1; older
        # results (written before it) were scored by full contract validity.
        scored_valid = raw.get("core_ok", raw.get("contract_ok", True))
        # A P1 failure is a failed call or a response whose scored fields were
        # invalid; both were scored as a miss (empty prediction).
        if not raw["ok"] or not scored_valid:
            p1_failures.append(v["filename"])
        # Diagnostics only, outside the quality scores: responses that were not
        # fully incident-contract valid, responses whose database-backed (core)
        # fields were invalid, and how many videos had each unscored-field
        # (enrichment) violation.
        if raw["ok"] and not raw.get("contract_ok", True):
            contract_failures.append(v["filename"])
        if raw["ok"] and not scored_valid:
            core_failures.append(v["filename"])
        for code in sorted({e["code"] for e in (v.get("validation") or {}).get("enrichment_violations", [])}):
            enrichment_violation_videos[code] = enrichment_violation_videos.get(code, 0) + 1
        # RP1 is skipped, not failed, when P1 produced nothing valid to report on.
        if not v["rp1_report"]["ok"] and not v["rp1_report"].get("skipped"):
            rp1_failures.append(v["filename"])

        fs = v["incident_field_scores"]
        # Eligibility comes from extraction_stats.field_status: a field counts only when it was
        # scored on a model output; the type of a confirmed out-of-taxonomy clip never counts.
        for field in field_pass:
            entry = fs.get(field, {})
            status, value = extraction_stats.field_status(v, field)
            if status == "unscored" and "pass" in entry:
                unscored[field] += 1
            if status != "scored":
                continue
            field_pass[field].append(bool(value))
            if field in field_abs_error and entry.get("expected") is not None and entry.get("predicted") is not None:
                try:
                    field_abs_error[field].append(abs(float(entry["expected"]) - float(entry["predicted"])))
                except (TypeError, ValueError):
                    pass
        status, _ = extraction_stats.field_status(v, "description")
        if status == "scored" and fs.get("description", {}).get("score") is not None:
            description_scores.append(fs["description"]["score"])
        elif status == "unscored":
            unscored["description"] += 1

        for kind in ("entities", "instruments", "assets"):
            counts = v[kind]["counts"]
            if counts is None:
                unscored_kinds[kind] += 1
                continue
            for k in ("tp", "fp", "fn"):
                pooled_counts[kind][k] += counts.get(k, 0)
            for m in v[kind]["matches"]:
                attrs = m.get("attribute_scores", {})
                for attr_name, attr_val in attrs.items():
                    if attr_name == "holder":
                        holder_status_counts[attr_val["status"]] = holder_status_counts.get(attr_val["status"], 0) + 1
                        continue
                    if attr_name in attribute_pass.get(kind, {}) and attr_val.get("pass") is not None:
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
        "contract_failures": contract_failures,
        "core_failures": core_failures,
        "enrichment_violation_videos": enrichment_violation_videos,
        "rp1_failures": rp1_failures,
        "unscored": {"fields": unscored, "kinds": unscored_kinds},
        # Denominators per field (eligible, scored, with a model output): pooling weights by these.
        "incident_field_n": {**{field: len(values) for field, values in field_pass.items()},
                             "description": len(description_scores)},
        "reliability": extraction_stats.reliability(videos),
        "out_of_taxonomy": extraction_stats.out_of_taxonomy_summary(videos),
        "severity": extraction_stats.severity_analysis(videos),
        "instrument_attributes": extraction_stats.instrument_attributes(videos),
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
    contract_failures = [f for a in aggregates for f in a.get("contract_failures", [])]
    core_failures = [f for a in aggregates for f in a.get("core_failures", [])]
    enrichment_violation_videos: dict[str, int] = {}
    for a in aggregates:
        for code, count in a.get("enrichment_violation_videos", {}).items():
            enrichment_violation_videos[code] = enrichment_violation_videos.get(code, 0) + count
    rp1_failures = [f for a in aggregates for f in a["rp1_failures"]]

    def weight(a, name):
        # Each field's own eligible count; results written before v1.0 have none, so videos.
        return (a.get("incident_field_n") or {}).get(name, a["num_videos"])

    def pool_field(name, sub=None):
        vals, errs = [], []
        for a in aggregates:
            block = a["incident_field_accuracy"][name]
            if sub:
                pct, n_ = (block["tolerance_accuracy_pct"], weight(a, name))
                if pct is not None:
                    vals.append((pct, n_))
                if block["mean_abs_error_s"] is not None:
                    errs.append((block["mean_abs_error_s"], n_))
            else:
                pct = block
                if pct is not None:
                    vals.append((pct, weight(a, name)))
        total = sum(w for _, w in vals)
        weighted = sum(p * w for p, w in vals) / total if vals and total else None
        rounded = round(weighted, 1) if weighted is not None else None
        result = {"tolerance_accuracy_pct": rounded} if sub else rounded
        if sub:
            error_weight = sum(w for _, w in errs)
            result["mean_abs_error_s"] = (round(sum(e * w for e, w in errs) / error_weight, 2)
                                          if errs and error_weight else None)
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

    pooled_n: dict[str, int] = {}
    for a in aggregates:
        for name in ("type", "severity_level", "start_timestamp", "end_timestamp", "duration", "description"):
            pooled_n[name] = pooled_n.get(name, 0) + weight(a, name)

    return {
        "num_videos": n,
        "p1_failures": p1_failures,
        "contract_failures": contract_failures,
        "core_failures": core_failures,
        "enrichment_violation_videos": dict(sorted(enrichment_violation_videos.items())),
        "rp1_failures": rp1_failures,
        "incident_field_n": pooled_n,
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


LEGACY_METHODOLOGY = "legacy (before evaluation-methodology-v1.0)"
OUT_OF_TAXONOMY_CATEGORY = "Outside the five types"


class MixedMethodologyError(ValueError):
    """Result files scored under different methodology versions cannot be pooled."""


def methodology_version(data: dict) -> str:
    return (data.get("methodology") or {}).get("methodology_version") or LEGACY_METHODOLOGY


def summarize(files: list[Path]) -> dict:
    """The summary of a set of result files; refuses to pool different methodology versions."""
    by_category_and_model: dict[str, dict[str, dict]] = {}
    by_model_raw: dict[str, list[dict]] = {}
    videos_by_model: dict[str, list[dict]] = {}
    outside_by_model: dict[str, list[dict]] = {}
    models_seen = {}
    versions: dict[str, set[str]] = {}
    pins: dict[str, dict] = {}

    for f in files:
        data = json.loads(f.read_text())
        version = methodology_version(data)
        versions.setdefault(version, set()).add(f.name)
        if data.get("methodology"):
            pins[version] = data["methodology"]
        category, model = data["category"], data["model_id"]
        # Confirmed out-of-taxonomy clips (from the ground truth) get their own breakdown row,
        # never the nearest category's.
        in_taxonomy = [v for v in data["videos"] if not extraction_stats.is_out_of_taxonomy(v)]
        outside_by_model.setdefault(model, []).extend(v for v in data["videos"] if extraction_stats.is_out_of_taxonomy(v))
        if in_taxonomy:
            agg = aggregate_one({**data, "videos": in_taxonomy})
            by_category_and_model.setdefault(category, {})[model] = agg
            by_model_raw.setdefault(model, []).append(agg)
        videos_by_model.setdefault(model, []).extend(data["videos"])
        seen = models_seen.setdefault(model, {"model_id": model, "validation_policies": []})
        seen.update({"prompt_version": data["prompt_version"], "inference_config": data["inference_config"]})
        # Results written before core-scored-v1 were scored by full contract validity.
        policy = data.get("validation_policy", "full-contract (before core-scored-v1)")
        if policy not in seen["validation_policies"]:
            seen["validation_policies"].append(policy)

    for model, outside in outside_by_model.items():
        if outside:
            agg = aggregate_one({"videos": outside})
            by_category_and_model.setdefault(OUT_OF_TAXONOMY_CATEGORY, {})[model] = agg
            by_model_raw.setdefault(model, []).append(agg)

    if len(versions) > 1:
        detail = "; ".join(f"{v}: {len(names)} file(s)" for v, names in sorted(versions.items()))
        raise MixedMethodologyError(f"results come from different methodology versions ({detail}); "
                                    "aggregate each version separately")

    def with_statistics(block: dict, videos: list[dict]) -> dict:
        block["field_intervals"] = extraction_stats.field_intervals(videos)
        block["severity"] = extraction_stats.severity_analysis(videos)
        block["instrument_attributes"] = extraction_stats.instrument_attributes(videos)
        block["reliability"] = extraction_stats.reliability(videos)
        block["out_of_taxonomy"] = extraction_stats.out_of_taxonomy_summary(videos)
        return block

    by_model = {model: with_statistics(pool_aggregates(aggs), videos_by_model[model])
                for model, aggs in by_model_raw.items()}
    overall = with_statistics(pool_aggregates([agg for aggs in by_model_raw.values() for agg in aggs]),
                              [v for videos in videos_by_model.values() for v in videos])
    version = next(iter(versions), LEGACY_METHODOLOGY)
    return {
        "methodology_version": version,
        "methodology": pins.get(version),
        "models": list(models_seen.values()),
        "by_category_and_model": by_category_and_model,
        "by_model": by_model,
        "overall": overall,
    }


def main() -> None:
    # Only eval_run.py's per-(category, model) files, named "<category>__<model>.json";
    # other JSON beside them (summary.json, dataset_stats.json) is not a results file.
    summary = summarize(sorted(RESULTS_DIR.glob("*__*.json")))
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(), **summary}
    out_path = RESULTS_DIR / "summary.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
