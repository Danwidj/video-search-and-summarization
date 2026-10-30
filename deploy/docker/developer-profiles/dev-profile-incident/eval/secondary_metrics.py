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

"""Secondary metrics of the original plan (§B.2), computed offline from saved results. Reporting only.

Every figure comes from the scores and matches already stored in each video-run: no model, embedding or judge
call. Nothing here changes a score, D9 v2, a primary metric or a selection; these are descriptive tables.

- **Macro accuracy:** the mean over categories of each incident field's conditional accuracy (the primary
  tables are micro, i.e. video-weighted).
- **Per-video mean item F1:** the mean over video-runs with a model output and at least one item on either
  side (both sides empty is excluded, as in methodology v1.0); the primary item figures are pooled.
- **Instrument attributes on matched instruments:** threat level exact and within ±1, and holder accuracy
  ``correct / (correct + incorrect)`` with unresolved cases counted apart (plan §B.2).
- **Stricter-threshold sensitivity:** item P/R/F1 keeping only saved matches with similarity ≥ τ' for
  τ' above the frozen τ = 0.40. A re-match at τ' could pair more items than this filter keeps, so the true
  positives and F1 shown are **lower bounds**. The plan's 0.65 and 0.85 points (set around the original
  τ = 0.75) are both stricter than the frozen 0.40, so they are covered; a threshold below 0.40 would need new
  embedding calls and is not computed.
"""

from __future__ import annotations

import extraction_stats

KINDS = ("entities", "instruments", "assets")
STRICTER_THRESHOLDS = (0.50, 0.65, 0.75, 0.85)


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4)}


def macro_accuracy(videos: list[dict]) -> dict:
    """Per incident field: micro (video-weighted) and macro (category-mean) conditional accuracy."""
    out = {}
    for field in extraction_stats.INCIDENT_FIELDS:
        by_category: dict[str, list[float]] = {}
        for video in videos:
            value = extraction_stats.field_value(video, field)
            if value is not None:
                by_category.setdefault(video["category"], []).append(value)
        values = [v for vs in by_category.values() for v in vs]
        means = {c: round(sum(vs) / len(vs), 4) for c, vs in sorted(by_category.items())}
        out[field] = {"micro": round(sum(values) / len(values), 4) if values else None,
                      "macro": round(sum(means.values()) / len(means), 4) if means else None,
                      "by_category": means}
    return out


def _counts(video: dict, kind: str) -> dict:
    return (video.get(kind) or {}).get("counts") or {}


def item_means(videos: list[dict]) -> dict:
    """Per kind: pooled P/R/F1, the per-video mean F1, and macro (category-mean of pooled) F1."""
    out = {}
    for kind in KINDS:
        pooled = {"tp": 0, "fp": 0, "fn": 0}
        per_video, by_category, excluded = [], {}, 0
        for video in videos:
            if not extraction_stats.has_model_output(video):
                continue
            counts = _counts(video, kind)
            tp, fp, fn = (int(counts.get(k) or 0) for k in ("tp", "fp", "fn"))
            for key, value in (("tp", tp), ("fp", fp), ("fn", fn)):
                pooled[key] += value
            category = by_category.setdefault(video["category"], {"tp": 0, "fp": 0, "fn": 0})
            for key, value in (("tp", tp), ("fp", fp), ("fn", fn)):
                category[key] += value
            if tp + fp + fn == 0:
                excluded += 1  # both sides empty
                continue
            per_video.append(_prf(tp, fp, fn)["f1"])
        macro = [_prf(**c)["f1"] for c in by_category.values()]
        out[kind] = {"pooled": _prf(**pooled), "per_video_mean_f1": round(sum(per_video) / len(per_video), 4)
                     if per_video else None, "per_video_n": len(per_video), "both_empty_excluded": excluded,
                     "macro_f1": round(sum(macro) / len(macro), 4) if macro else None}
    return out


def instrument_attributes(videos: list[dict]) -> dict:
    """Threat level and holder on matched instruments, with counts (the sample is small)."""
    threat_exact = threat_within_one = threat_n = 0
    holder = {"correct": 0, "incorrect": 0, "unresolved": 0, "ground_truth_without_holder": 0}
    for video in videos:
        for match in (video.get("instruments") or {}).get("matches") or []:
            scores = match.get("attribute_scores") or {}
            threat = scores.get("threat_level") or {}
            expected, predicted = threat.get("expected"), threat.get("predicted")
            if isinstance(expected, int) and isinstance(predicted, int):
                threat_n += 1
                threat_exact += expected == predicted
                threat_within_one += abs(expected - predicted) <= 1
            entry = scores.get("holder") or {}
            if entry.get("expected") in (None, ""):
                holder["ground_truth_without_holder"] += 1
            elif entry.get("status") in holder:
                holder[entry["status"]] += 1
    decided = holder["correct"] + holder["incorrect"]
    return {"matched_instruments_with_threat": threat_n,
            "threat_exact": round(threat_exact / threat_n, 4) if threat_n else None,
            "threat_within_one": round(threat_within_one / threat_n, 4) if threat_n else None,
            "holder": holder, "holder_accuracy": round(holder["correct"] / decided, 4) if decided else None}


def stricter_threshold(videos: list[dict], thresholds=STRICTER_THRESHOLDS) -> dict:
    """Pooled item P/R/F1 keeping only saved matches with similarity ≥ τ' (lower bounds on TP and F1)."""
    out = {}
    for tau in thresholds:
        row = {}
        for kind in KINDS:
            tp = fp = fn = 0
            for video in videos:
                if not extraction_stats.has_model_output(video):
                    continue
                counts = _counts(video, kind)
                kept = sum(1 for m in (video.get(kind) or {}).get("matches") or []
                           if (m.get("similarity_score") or 0.0) >= tau)
                dropped = int(counts.get("tp") or 0) - kept
                tp += kept
                fp += int(counts.get("fp") or 0) + dropped
                fn += int(counts.get("fn") or 0) + dropped
            row[kind] = _prf(tp, fp, fn)
        out[f"{tau:.2f}"] = row
    return out


def secondary(record: dict) -> dict:
    videos = record["videos"]
    return {"experiment_id": record["experiment_id"], "protocol": record.get("protocol", "original"),
            "incident_fields": macro_accuracy(videos), "items": item_means(videos),
            "instrument_attributes": instrument_attributes(videos), "stricter_threshold": stricter_threshold(videos)}


def render(summary: dict, title: str) -> str:
    configs = summary["configs"]
    names = list(configs)
    lines = [f"# {title}", "", "Reporting only, from saved results (no model, embedding or judge call). "
             "Nothing here changes D9 v2, a primary metric or a conclusion.", "",
             "## Incident fields: micro (primary, video-weighted) / macro (category mean)", "",
             "| Field | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for field in extraction_stats.INCIDENT_FIELDS:
        cells = [f"{configs[n]['incident_fields'][field]['micro']} / {configs[n]['incident_fields'][field]['macro']}"
                 for n in names]
        lines.append(f"| {field} | " + " | ".join(cells) + " |")
    lines += ["", "## Items: pooled F1 (primary) / per-video mean F1 / macro F1", "",
              "| Kind | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for kind in KINDS:
        cells = []
        for n in names:
            item = configs[n]["items"][kind]
            cells.append(f"{item['pooled']['f1']} / {item['per_video_mean_f1']} (n {item['per_video_n']}) / "
                         f"{item['macro_f1']}")
        lines.append(f"| {kind} | " + " | ".join(cells) + " |")
    lines += ["", "## Matched instruments: threat level and holder", "",
              "| Config | Matched (with threat) | Threat exact | Threat ±1 | Holder correct / incorrect / unresolved "
              "| Holder accuracy |", "|---|---|---|---|---|---|"]
    for n in names:
        a = configs[n]["instrument_attributes"]
        h = a["holder"]
        lines.append(f"| {n} | {a['matched_instruments_with_threat']} | {a['threat_exact']} | {a['threat_within_one']} "
                     f"| {h['correct']} / {h['incorrect']} / {h['unresolved']} | {a['holder_accuracy']} |")
    lines += ["", "## Stricter matching thresholds (pooled F1, lower bounds; frozen τ = 0.40)", "",
              "| τ' | Kind | " + " | ".join(names) + " |", "|---|---|" + "---|" * len(names)]
    for tau in configs[names[0]]["stricter_threshold"]:
        for kind in KINDS:
            lines.append(f"| {tau} | {kind} | " + " | ".join(str(configs[n]["stricter_threshold"][tau][kind]["f1"])
                                                         for n in names) + " |")
    return "\n".join(lines) + "\n"
