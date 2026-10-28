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

"""Offline re-matching of saved results at another item-matching threshold (no model or judge call).

Re-runs only the item matcher (same embedder, texts and Hungarian assignment) on each saved
video-run's prediction and ground truth, and writes a **new**, versioned record; the original is
never changed. Incident fields are carried over unchanged (their rules do not differ between
methodology versions). A pair matched under both thresholds keeps its attribute scores; a newly
matched pair gets the deterministic entity-type check and is marked ``attributes_rescored: false``
for the judged attributes, which only a judge re-score (``eval_experiment.py rescore``) fills in.
Item P/R/F1 and D9's item components need only the match counts.
"""

from __future__ import annotations

import copy

import matching
from matching_calibration import KINDS, TEXT

ID_FIELD = {"entities": "entity_id", "instruments": "instrument_id", "assets": "asset_id"}


def _summary(kind: str, model_rows: list[dict], gt_rows: list[dict], threshold: float, old: dict, embed) -> dict:
    id_field = ID_FIELD[kind]
    gt_id_field = f"gt_{id_field}"
    previous = {(m[id_field], m[gt_id_field]): m for m in old.get("matches", [])}
    matches = []
    if model_rows and gt_rows:
        texts = [TEXT[kind](r) for r in model_rows] + [TEXT[kind](r) for r in gt_rows]
        result = embed(texts)
        if not result.ok:
            raise matching.EmbeddingUnavailableError(f"{kind}: {result.error or 'embedding request failed'}")
        n = len(model_rows)
        sims = matching._cosine_similarity_matrix(result.data[:n], result.data[n:]).tolist()
        for a in matching.solve_assignment(sims, threshold=threshold):
            model, gt = model_rows[a.index], gt_rows[a.gt_index]
            key = (model[id_field], gt[id_field])
            if key in previous:
                matches.append({**previous[key], "similarity_score": a.similarity})
                continue
            entry = {id_field: key[0], gt_id_field: key[1], "similarity_score": a.similarity,
                     "attributes_rescored": False}
            if kind == "entities":
                entry["attribute_scores"] = {"type": {"expected": gt.get("type"), "predicted": model.get("type"),
                                                      "pass": gt.get("type") == model.get("type")}}
            matches.append(entry)
    matched_model = {m[id_field] for m in matches}
    matched_gt = {m[gt_id_field] for m in matches}
    unmatched_model = [r for r in model_rows if r[id_field] not in matched_model]
    unmatched_gt = [r for r in gt_rows if r[id_field] not in matched_gt]
    tp, fp, fn = len(matches), len(unmatched_model), len(unmatched_gt)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0
    return {"matches": matches, "unmatched_model": unmatched_model, "unmatched_gt": unmatched_gt,
            "counts": {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}}


def rematch(record: dict, *, threshold: float, methodology_version: str, source: str, source_sha256: str,
            provisional: bool, embed=None) -> dict:
    """A new record: ``record`` with every model-output video's items re-matched at ``threshold``."""
    embed = embed or matching.embed_texts
    out = copy.deepcopy(record)
    for video in out["videos"]:
        if video.get("outcome") not in ("scored", "contract_invalid", "parse_failure"):
            continue
        prediction, gt = video.get("prediction") or {}, video.get("ground_truth") or {}
        for kind in KINDS:
            video[kind] = _summary(kind, prediction.get(kind) or [], gt.get(kind) or [], threshold,
                                   video.get(kind) or {}, embed)
        video["methodology_version"] = methodology_version
    out["methodology"] = {**(record.get("methodology") or {}), "methodology_version": methodology_version,
                          "match_threshold": threshold, "match_threshold_provisional": provisional}
    out["rematched_from"] = {"results": source, "results_sha256": source_sha256,
                             "methodology_version": (record.get("methodology") or {}).get("methodology_version"),
                             "note": "items re-matched offline; incident fields carried over; no model or judge call"}
    return out
