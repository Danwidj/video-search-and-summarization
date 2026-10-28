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

"""Calibrating the item-matching threshold (evaluation-methodology-v1.2) against labelled pairs.

A **block** is one video-run's predicted items and ground-truth items of one kind. Blocks are sampled
from **dev** results only, at random under a fixed seed, never by similarity, and labelled
blind to any score: each (prediction, ground truth) pair is ``same``, ``different`` or ``ambiguous``.
``evaluate`` then runs the unchanged matcher (MiniLM cosine, one-to-one Hungarian assignment) on
every block at each candidate threshold and scores its accepted pairs against the labels.

The threshold is chosen by the rule fixed in the methodology before ``evaluate`` is run
(``select_threshold``): the highest pooled assignment F1, ties within ``TIE_MARGIN`` to the higher
threshold. Stage 1 model scores never enter the choice.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import matching

KINDS = ("entities", "instruments", "assets")
LABELS = ("same", "different", "ambiguous")
SEED = 20261028
# Pairs drawn per kind; instruments are rare in the dev split, so every eligible block is taken first.
PAIR_QUOTA = {"entities": 25, "instruments": 12, "assets": 25}
MAX_BLOCK_PAIRS = 9
GRID = tuple(round(0.30 + 0.05 * i, 2) for i in range(11))  # 0.30 .. 0.80
TIE_MARGIN = 0.01
TEXT = {"entities": matching._entity_text, "instruments": matching._named_text, "assets": matching._named_text}


def eligible_blocks(records: list[dict], *, large: bool = False) -> list[dict]:
    """Blocks with items on both sides, from dev records with a model output. Never reads a score.

    ``large``: the blocks of more than ``MAX_BLOCK_PAIRS`` pairs instead (the calibration v2 extension).
    """
    blocks = []
    for record in records:
        if record["split"]["half"] != "dev":
            raise ValueError(f"{record['experiment_id']} is a {record['split']['half']} record: calibration "
                             "uses dev results only")
        for video in record["videos"]:
            if video["outcome"] not in ("scored", "contract_invalid"):
                continue
            prediction = video.get("prediction") or {}
            gt = video.get("ground_truth") or {}
            for kind in KINDS:
                model_rows, gt_rows = prediction.get(kind) or [], gt.get(kind) or []
                pairs = len(model_rows) * len(gt_rows)
                if model_rows and gt_rows and (pairs > MAX_BLOCK_PAIRS if large else pairs <= MAX_BLOCK_PAIRS):
                    blocks.append({"experiment_id": record["experiment_id"], "incident_id": video["incident_id"],
                                   "category": video["category"], "repeat": video["repeat"], "kind": kind,
                                   "predicted": [_strip(r, kind) for r in model_rows],
                                   "ground_truth": [_strip(r, kind) for r in gt_rows]})
    return blocks


def _strip(row: dict, kind: str) -> dict:
    keys = ("entity_id", "type", "description") if kind == "entities" else \
        (("instrument_id", "asset_id")[kind == "assets"], "name", "description")
    return {k: row.get(k) for k in keys}


def sample(blocks: list[dict], *, seed: int = SEED, quota: dict | None = None) -> list[dict]:
    """Random blocks per kind until the pair quota is met; at most one block per (clip, kind)."""
    quota = quota or PAIR_QUOTA
    rng = random.Random(seed)
    chosen = []
    for kind in KINDS:
        pool = [b for b in blocks if b["kind"] == kind]
        rng.shuffle(pool)
        seen, pairs = set(), 0
        for block in pool:
            if pairs >= quota[kind]:
                break
            if block["incident_id"] in seen:
                continue
            seen.add(block["incident_id"])
            chosen.append(block)
            pairs += len(block["predicted"]) * len(block["ground_truth"])
    for number, block in enumerate(chosen, 1):
        block["block_id"] = f"B{number:02d}"
    return chosen


# Calibration v2 (2026-10-28): four large blocks, drawn at random under their own seed, at most one per clip.
LARGE_SEED = 20261029
LARGE_BLOCKS = 4
GRID_V2 = tuple(round(0.10 + 0.05 * i, 2) for i in range(15))  # 0.10 .. 0.80


def sample_large(blocks: list[dict], *, first_number: int, seed: int = LARGE_SEED, count: int = LARGE_BLOCKS) -> list[dict]:
    """``count`` large blocks drawn uniformly at random (never by similarity or score), one per clip."""
    pool = sorted(blocks, key=lambda b: (b["experiment_id"], b["incident_id"], b["repeat"], b["kind"]))
    random.Random(seed).shuffle(pool)
    chosen, clips = [], set()
    for block in pool:
        if len(chosen) == count:
            break
        if block["incident_id"] not in clips:
            clips.add(block["incident_id"])
            chosen.append(block)
    for number, block in enumerate(chosen, first_number):
        block["block_id"] = f"B{number:02d}"
    return chosen


def label_sheet(blocks: list[dict]) -> dict:
    """What the labeller sees: texts and ids only, no similarity, no model or arm name."""
    return {"instructions": "For every predicted item and every ground-truth item in a block, label the pair "
                            "'same' (they refer to the same person, animal or object in the clip), 'different', "
                            "or 'ambiguous' (cannot be decided from the texts and the clip).",
            "blocks": [{"block_id": b["block_id"], "incident_id": b["incident_id"], "kind": b["kind"],
                        "predicted": b["predicted"], "ground_truth": b["ground_truth"]} for b in blocks]}


def _id(row: dict) -> str:
    return row.get("entity_id") or row.get("instrument_id") or row.get("asset_id")


def validate_labels(sheet: dict, labels: list[dict]) -> list[str]:
    """Every pair of every block labelled exactly once with a known label."""
    expected = {(b["block_id"], _id(p), _id(g)) for b in sheet["blocks"] for p in b["predicted"]
                for g in b["ground_truth"]}
    got = [(lab["block_id"], lab["predicted_id"], lab["gt_id"]) for lab in labels]
    problems = [f"unknown pair {k}" for k in set(got) - expected]
    problems += [f"unlabelled pair {k}" for k in sorted(expected - set(got))]
    problems += [f"duplicate pair {k}" for k in {k for k in got if got.count(k) > 1}]
    problems += [f"bad label {lab['label']!r} for {lab['block_id']}" for lab in labels if lab["label"] not in LABELS]
    return problems


def similarity_blocks(sheet: dict, embed=None) -> dict[str, list[list[float]]]:
    """Per block, the matcher's cosine matrix (predicted rows × ground-truth columns)."""
    embed = embed or matching.embed_texts
    out = {}
    for block in sheet["blocks"]:
        text = TEXT[block["kind"]]
        texts = [text(r) for r in block["predicted"]] + [text(r) for r in block["ground_truth"]]
        result = embed(texts)
        if not result.ok:
            raise matching.EmbeddingUnavailableError(result.error or "embedding request failed")
        n = len(block["predicted"])
        out[block["block_id"]] = matching._cosine_similarity_matrix(result.data[:n], result.data[n:]).tolist()
    return out


def score_threshold(sheet: dict, labels: list[dict], sims: dict, threshold: float, *,
                    ambiguous: str = "exclude") -> dict:
    """The matcher's accepted pairs at ``threshold`` against the labels, pooled and per kind.

    ``ambiguous``: ``exclude`` (primary; such a pair is neither a true nor a false match), ``same`` or
    ``different`` (sensitivity).
    """
    label = {(lab["block_id"], lab["predicted_id"], lab["gt_id"]): lab["label"] for lab in labels}
    rows = {kind: {"tp": 0, "fp": 0, "fn": 0, "false_matches": [], "blocks": {}} for kind in (*KINDS, "all")}
    for block in sheet["blocks"]:
        bid, kind = block["block_id"], block["kind"]
        p_ids, g_ids = [_id(r) for r in block["predicted"]], [_id(r) for r in block["ground_truth"]]

        def resolved(key):
            value = label[key]
            return value if value != "ambiguous" or ambiguous == "exclude" else ambiguous

        positives = {(p, g) for p in p_ids for g in g_ids if resolved((bid, p, g)) == "same"}
        accepted = {(p_ids[a.index], g_ids[a.gt_index]): a.similarity
                    for a in matching.solve_assignment(sims[bid], threshold=threshold)}
        counted = {k: v for k, v in accepted.items() if resolved((bid, *k)) != "ambiguous"}
        tp = sum(1 for k in counted if k in positives)
        fp = len(counted) - tp
        fn = len(positives - set(counted))
        for target in (kind, "all"):
            rows[target]["tp"] += tp
            rows[target]["fp"] += fp
            rows[target]["fn"] += fn
            rows[target]["blocks"][bid] = (tp, fp, fn)
        rows[kind]["false_matches"] += [{"block_id": bid, "predicted_id": p, "gt_id": g, "similarity": round(s, 3)}
                                        for (p, g), s in counted.items() if (p, g) not in positives]
    for row in rows.values():
        row.update(_prf(row["tp"], row["fp"], row["fn"]))
    return {"threshold": threshold, "ambiguous": ambiguous, "by_kind": rows}


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None
    return {"precision": precision, "recall": recall, "f1": f1}


def f1_interval(scored: dict, *, resamples: int = 2000, seed: int = SEED) -> tuple[float, float] | None:
    """95% block-bootstrap percentile interval of the pooled F1."""
    blocks = list(scored["by_kind"]["all"]["blocks"].values())
    if not blocks:
        return None
    rng = random.Random(seed)
    values = []
    for _ in range(resamples):
        sample = [blocks[rng.randrange(len(blocks))] for _ in blocks]
        tp, fp, fn = (sum(b[i] for b in sample) for i in range(3))
        values.append(2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0)
    values.sort()
    return values[int(0.025 * (resamples - 1))], values[int(0.975 * (resamples - 1))]


def select_threshold(table: list[dict]) -> float:
    """The pre-registered rule: highest pooled F1; within ``TIE_MARGIN`` of it, the higher threshold."""
    best = max(row["by_kind"]["all"]["f1"] or 0.0 for row in table)
    tied = [row["threshold"] for row in table if best - (row["by_kind"]["all"]["f1"] or 0.0) <= TIE_MARGIN]
    return max(tied)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
