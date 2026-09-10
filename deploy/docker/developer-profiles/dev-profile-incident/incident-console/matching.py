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

"""Similarity-based matching between one model run's evidence and ground truth.

For one incident + model run, each evidence kind (entities / instruments /
assets) is scored against that incident's ground-truth counterparts using
embedding similarity over the fields that actually identify the object
(``type`` + ``description`` for entities, ``name`` + ``description`` for
instruments/assets - not arbitrary free text). The resulting similarity matrix
is solved as an optimal one-to-one assignment (Hungarian algorithm, via
``scipy.optimize.linear_sum_assignment``), and only pairings clearing
``config.MIN_MATCH_SIMILARITY`` are persisted: a forced low-similarity pairing
is a miss (missed detection or false positive), not a match. An absent row in
``entity_matches`` / ``instrument_matches`` / ``asset_matches`` means exactly
that - "no accepted match".

``solve_assignment`` is a pure function over a plain similarity matrix so the
assignment logic is testable without an embedding endpoint or a database.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

import config
from embed_client import embed_texts


@dataclass(frozen=True)
class Assignment:
    """One accepted pairing: row ``index`` (model output) <-> column ``gt_index`` (ground truth)."""

    index: int
    gt_index: int
    similarity: float


def solve_assignment(similarity: list[list[float]], *, threshold: float | None = None) -> list[Assignment]:
    """Optimal one-to-one assignment over a similarity matrix, threshold-filtered.

    Rows are model-output items, columns are ground-truth items. Uses the
    Hungarian algorithm to maximize total similarity, then discards any pairing
    whose score falls below ``threshold`` (default ``config.MIN_MATCH_SIMILARITY``).
    """
    threshold = config.MIN_MATCH_SIMILARITY if threshold is None else threshold
    matrix = np.asarray(similarity, dtype=float)
    if matrix.size == 0:
        return []
    row_idx, col_idx = linear_sum_assignment(-matrix)  # maximize similarity == minimize its negation
    return [
        Assignment(index=int(r), gt_index=int(c), similarity=float(matrix[r, c]))
        for r, c in zip(row_idx, col_idx, strict=True)
        if matrix[r, c] >= threshold
    ]


def _cosine_similarity_matrix(rows: list[list[float]], columns: list[list[float]]) -> np.ndarray:
    a = np.asarray(rows, dtype=float)
    b = np.asarray(columns, dtype=float)
    a = a / np.clip(np.linalg.norm(a, axis=1, keepdims=True), 1e-9, None)
    b = b / np.clip(np.linalg.norm(b, axis=1, keepdims=True), 1e-9, None)
    return a @ b.T


def _entity_text(row: dict) -> str:
    return f"{row.get('type') or ''} {row.get('description') or ''}".strip()


def _named_text(row: dict) -> str:
    return f"{row.get('name') or ''} {row.get('description') or ''}".strip()


# Per-kind: (identifying-text builder, id column, list method, gt-list method, record method).
_KIND_CONFIG = {
    "entities": (_entity_text, "entity_id", "list_incident_entities", "list_gt_entities", "record_entity_match"),
    "instruments": (
        _named_text,
        "instrument_id",
        "list_incident_instruments",
        "list_gt_instruments",
        "record_instrument_match",
    ),
    "assets": (_named_text, "asset_id", "list_incident_assets", "list_gt_assets", "record_asset_match"),
}


def match_kind(db, kind: str, incident_id: str, model_run_id: str, *, threshold: float | None = None) -> list[dict]:
    """Match and persist one evidence kind for one incident + model run.

    Returns the accepted matches as plain dicts (``{<id>, gt_<id>, similarity_score}``).
    Fails soft to ``[]`` when either side is empty or the embedding endpoint is
    unavailable - nothing is persisted in that case.
    """
    text_fn, id_field, list_method, gt_list_method, record_method = _KIND_CONFIG[kind]
    model_rows = getattr(db, list_method)(incident_id, model_run_id)
    gt_rows = getattr(db, gt_list_method)(incident_id)
    if not model_rows or not gt_rows:
        return []

    result = embed_texts([text_fn(r) for r in model_rows] + [text_fn(r) for r in gt_rows])
    if not result.ok:
        return []
    vectors = result.data
    model_vectors, gt_vectors = vectors[: len(model_rows)], vectors[len(model_rows) :]
    similarity = _cosine_similarity_matrix(model_vectors, gt_vectors)

    record = getattr(db, record_method)
    gt_id_field = f"gt_{id_field}"
    persisted: list[dict] = []
    for assignment in solve_assignment(similarity.tolist(), threshold=threshold):
        model_id = model_rows[assignment.index][id_field]
        gt_id = gt_rows[assignment.gt_index][id_field]
        record(
            incident_id=incident_id,
            model_run_id=model_run_id,
            **{id_field: model_id, gt_id_field: gt_id},
            similarity_score=assignment.similarity,
        )
        persisted.append({id_field: model_id, gt_id_field: gt_id, "similarity_score": assignment.similarity})
    return persisted


def match_incident(db, incident_id: str, model_run_id: str, *, threshold: float | None = None) -> dict[str, list[dict]]:
    """Match and persist all three evidence kinds for one incident + model run."""
    return {kind: match_kind(db, kind, incident_id, model_run_id, threshold=threshold) for kind in _KIND_CONFIG}
