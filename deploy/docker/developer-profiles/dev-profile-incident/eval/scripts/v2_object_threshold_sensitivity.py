# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""EXPLORATORY post-hoc sensitivity of the object-matching threshold. tau = 0.40 stays primary; nothing here rescores.

Offline and read-only: stored score rows and stored MiniLM vectors, the unchanged ``matching.solve_assignment``. No
VLM, LLM, judge or embedding call; a text with no stored vector leaves its block unavailable and counted. Repo outputs
hold ids, counts and scores; anything with GT or prediction text goes to the private directory.

    OMP_NUM_THREADS=1 nice -n 19 uv run --frozen python scripts/v2_object_threshold_sensitivity.py replay
    OMP_NUM_THREADS=1 nice -n 19 uv run --frozen python scripts/v2_object_threshold_sensitivity.py dev
    OMP_NUM_THREADS=1 nice -n 19 uv run --frozen python scripts/v2_object_threshold_sensitivity.py sample
    OMP_NUM_THREADS=1 nice -n 19 uv run --frozen python scripts/v2_object_threshold_sensitivity.py tally
    OMP_NUM_THREADS=1 nice -n 19 uv run --frozen python scripts/v2_object_threshold_sensitivity.py seal
    OMP_NUM_THREADS=1 nice -n 19 uv run --frozen python scripts/v2_object_threshold_sensitivity.py evaluation
    nice -n 19 ~/.cache/vss-agent-venv/bin/python scripts/v2_object_threshold_sensitivity.py plots

``evaluation`` refuses to run until ``seal`` has recorded the hash of ``dev-selection.md``. Super on the evaluation half
is the frozen snapshot (``c3-track-a-switchyard`` and ``-recovery``, 26 rows), labelled incomplete; A5-s is never read.
"""

from __future__ import annotations

import collections
import csv
import hashlib
import json
import math
import os
import random
import re
import sys
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np  # noqa: E402

EVAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL))

R = Path("/home/hengz/evalv2-data/v2/runs")
OUT = EVAL / "methodology" / "object-threshold-sensitivity"
PRIVATE = Path("/home/hengz/evalv2-data/v2/diagnostics/object-threshold")
SPLIT_FILE = Path("/home/hengz/evalv2-data/ground_truth/ground-truth-v1.0/split-v2.json")
CALIBRATION = EVAL / "methodology" / "calibration" / "matching-v1.2-calibration-v2.json"
SCORE = "scoring/evalv2-score-stage-v3/primary/live-videos.jsonl"
EMBEDDER = "sentence-transformers/all-MiniLM-L6-v2"

FROZEN = 0.40
THRESHOLDS = (0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60)
LOWER = tuple(t for t in THRESHOLDS if t < FROZEN)
KINDS = ("entities", "instruments", "assets")
ID_FIELD = {"entities": "entity_id", "instruments": "instrument_id", "assets": "asset_id"}
MODELS = {"nano-direct": "Cosmos 3 Nano", "gemma4-31b-openrouter": "Gemma 4 31B", "qwen35-9b-openrouter": "Qwen3.5-9B",
          "omni-direct": "Nemotron 3 Nano Omni", "super-direct": "Cosmos 3 Super"}
COMPLETE = tuple(s for s in MODELS if s != "super-direct")
MODEL_OUTPUT = ("scored", "contract_invalid", "parse_failure")
# c1a holds Nano, Omni and Super, c1a-recovery Super. The two OpenRouter models' dev rows are in c1e and c1f.
DEV_RUNS = ("c1a", "c1a-recovery", "c1e-openrouter-gemma4-31b", "c1f-openrouter-qwen35-9b")
EVAL_RUNS = ("c3-track-a-switchyard", "c3-track-a-switchyard-recovery", "c3-track-a-switchyard-recovery-a5a",
             "c3-track-a-openrouter")
FORBIDDEN_RUN = "c3-track-a-switchyard-recovery-a5s"
SEED, RESAMPLES = 20261027, 2000
SAMPLE_SEED = 20261105
BANDS = ((0.35, 0.40, 30), (0.30, 0.35, 30), (0.25, 0.30, 18), (0.20, 0.25, 12), (0.40, 0.45, 36), (0.45, 0.50, 14))
LABELS = ("same", "different", "cannot_tell")
MODES = ("same_exact", "synonym", "general_vs_specific", "distinct_similar", "role_confusion", "instrument_vs_asset",
         "too_generic")
SELECTION = OUT / "dev-selection.md"
RULE = OUT / "selection-rule.md"
LEDGER = OUT / "selection-ledger.json"


def category(clip: str) -> str:
    return re.match(r"[A-Za-z]+", clip).group(0)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def f1(tp: float, fp: float, fn: float) -> float:
    """Pooled F1 as ``eval_gt.prf1`` and the chart compute it: 0 when nothing is defined."""
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def object_score(entity: tuple, instrument: tuple, asset: tuple) -> float:
    """The chart's object score: the mean of entity F1 and the F1 of instruments and assets pooled."""
    return (f1(*entity) + f1(*(a + b for a, b in zip(instrument, asset, strict=True)))) / 2


def load_rows(runs: tuple[str, ...]) -> dict:
    """One row per (subject, clip, repeat): a model output from an earlier run wins (v2_c3_analysis.combined_rows)."""
    if FORBIDDEN_RUN in runs:
        raise ValueError("A5-s output is not part of this analysis")
    rows: dict = {}
    for run in runs:
        for line in (R / run / SCORE).read_text().splitlines():
            r = json.loads(line)
            if r.get("stage", "p1") != "p1" or r["subject"] not in MODELS:
                continue
            key = (r["subject"], r["incident_id"], r["repeat"])
            if key not in rows or rows[key]["outcome"] not in MODEL_OUTPUT:
                r["_run"] = run
                rows[key] = r
        amendment = R / run / "amendment-a1-records.jsonl"
        if amendment.exists():  # a crashed item, an invalid output: a miss with no score block
            for line in amendment.read_text().splitlines():
                x = json.loads(line)
                rows.setdefault((x["subject"], x["item_id"], x["repeat"]),
                                {"subject": x["subject"], "incident_id": x["item_id"], "repeat": x["repeat"],
                                 "outcome": x["outcome"], "amendment": "A1", "_run": run})
    return rows


def load_vectors(runs: tuple[str, ...]) -> dict:
    vectors: dict = {}
    for run in runs:
        with (R / run / "scoring/embeddings.jsonl").open() as handle:
            for line in handle:
                x = json.loads(line)
                vectors[x["key"]] = x["vector"]
    return vectors


def build_blocks(rows: dict, vectors: dict) -> tuple[list, dict]:
    """Per row and kind, the items and the similarity matrix, built from stored vectors only."""
    import matching
    from evalv2.core.hashing import sha256_json
    from evalv2.tasks.incident_objects import v1

    gt_by_clip = {r["incident_id"]: r["ground_truth"] for r in rows.values() if "ground_truth" in r}
    blocks, audit = [], collections.Counter()
    for (subject, clip, repeat), r in sorted(rows.items()):
        if r["outcome"] not in MODEL_OUTPUT:
            audit["rows_without_model_output"] += 1
            continue
        audit["rows_with_model_output"] += 1
        for kind in KINDS:
            model_rows = (r.get("prediction") or {}).get(kind) or []
            gt_rows = (r.get("ground_truth") or gt_by_clip.get(clip) or {}).get(kind) or []
            block = {"subject": subject, "clip": clip, "repeat": repeat, "kind": kind, "outcome": r["outcome"],
                     "n_pred": len(model_rows), "n_gt": len(gt_rows), "model_rows": model_rows, "gt_rows": gt_rows,
                     "matrix": None, "unavailable": False, "stored": (r.get(kind) or {}).get("counts"),
                     "stored_matches": (r.get(kind) or {}).get("matches")}
            if model_rows and gt_rows:
                model_texts = [v1.TEXT[kind](x) for x in model_rows]
                gt_texts = [v1.TEXT[kind](x) for x in gt_rows]
                got = [vectors.get(sha256_json({"model": EMBEDDER, "text": t})) for t in model_texts + gt_texts]
                if any(v is None for v in got):
                    block["unavailable"] = True
                    audit["blocks_missing_a_vector"] += 1
                    audit["texts_missing_a_vector"] += sum(v is None for v in got)
                else:
                    n = len(model_texts)
                    block["matrix"] = matching._cosine_similarity_matrix(got[:n], got[n:]).tolist()
            blocks.append(block)
    return blocks, audit


def assign(block: dict, threshold: float) -> list:
    """The original matcher at ``threshold``, unchanged, on one block."""
    import matching

    return matching.solve_assignment(block["matrix"], threshold=threshold) if block["matrix"] is not None else []


def counts(block: dict, threshold: float) -> tuple[int, int, int]:
    tp = len(assign(block, threshold))
    return tp, block["n_pred"] - tp, block["n_gt"] - tp


def threshold_first(matrix: list, threshold: float) -> list:
    """Diagnostic only: forbid sub-threshold edges, then maximise matches, then total similarity."""
    from scipy.optimize import linear_sum_assignment

    m = np.asarray(matrix, dtype=float)
    weight = np.where(m >= threshold, 1000.0 + m, 0.0)
    rows, cols = linear_sum_assignment(-weight)
    return [(int(r), int(c), float(m[r, c])) for r, c in zip(rows, cols, strict=True) if m[r, c] >= threshold]


def replay_check(blocks: list) -> dict:
    """Stored tp/fp/fn and stored pairs against the replay at the frozen threshold, block by block."""
    out = collections.Counter()
    differences = []
    for b in blocks:
        if b["stored"] is None:
            out["blocks_without_stored_counts"] += 1
            continue
        out["blocks_compared"] += 1
        tp, fp, fn = counts(b, FROZEN)
        s = b["stored"]
        if (tp, fp, fn) != (s["tp"], s["fp"], s["fn"]):
            out["count_mismatches"] += 1
            differences.append({"subject": b["subject"], "clip": b["clip"], "repeat": b["repeat"], "kind": b["kind"],
                                "stored": [s["tp"], s["fp"], s["fn"]], "replay": [tp, fp, fn],
                                "outcome": b["outcome"], "unavailable": b["unavailable"]})
        id_field = ID_FIELD[b["kind"]]
        got = {(b["model_rows"][a.index][id_field], b["gt_rows"][a.gt_index][id_field]) for a in assign(b, FROZEN)}
        stored = {(m[id_field], m[f"gt_{id_field}"]) for m in b["stored_matches"] or []}
        out["stored_pairs"] += len(stored)
        if got != stored:
            out["blocks_with_a_different_pairing"] += 1
    return {**out, "differences": differences}


def clip_counts(blocks: list, thresholds: tuple) -> tuple[list, dict]:
    """``{(subject, kind, tau): array[clip, 3]}`` over one shared clip order."""
    clips = sorted({b["clip"] for b in blocks})
    index = {c: i for i, c in enumerate(clips)}
    table: dict = {}
    for b in blocks:
        if b["unavailable"]:
            continue
        for t in thresholds:
            cell = table.setdefault((b["subject"], b["kind"], t), np.zeros((len(clips), 3)))
            cell[index[b["clip"]]] += counts(b, t)
    return clips, table


def f1_array(c: np.ndarray) -> np.ndarray:
    """F1 for an array of pooled (tp, fp, fn) on its last axis."""
    tp, fp, fn = c[..., 0], c[..., 1], c[..., 2]
    den = 2 * tp + fp + fn
    return np.divide(2 * tp, den, out=np.zeros_like(tp, dtype=float), where=den > 0)


def resample_matrix(n_clips: int, seed: int = SEED, n: int = RESAMPLES) -> np.ndarray:
    """Clip weights of a cluster bootstrap, shared by every model, kind and threshold."""
    rng = np.random.default_rng(seed)
    return rng.multinomial(n_clips, [1 / n_clips] * n_clips, size=n).astype(float)


def interval(values: np.ndarray) -> tuple[float, float]:
    return float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))


def sweep(blocks: list, split: str, thresholds: tuple = THRESHOLDS) -> dict:
    """Per model and kind: counts, P/R/F1, object score, intervals, and paired changes against the frozen threshold."""
    clips, table = clip_counts(blocks, thresholds)
    weights = resample_matrix(len(clips))
    subjects = sorted({k[0] for k in table}, key=list(MODELS).index)
    per_kind, per_object, draws = [], [], {}
    for s in subjects:
        base = {k: table[(s, k, FROZEN)] for k in KINDS}
        base_boot = {k: f1_array(weights @ base[k]) for k in KINDS}
        base_object = (f1_array(weights @ base["entities"])
                       + f1_array(weights @ (base["instruments"] + base["assets"]))) / 2
        for t in thresholds:
            cell = {k: table[(s, k, t)] for k in KINDS}
            for k in KINDS:
                tp, fp, fn = cell[k].sum(axis=0)
                boot = f1_array(weights @ cell[k])
                lo, hi = interval(boot)
                dlo, dhi = interval(boot - base_boot[k])
                b_tp, b_fp, b_fn = base[k].sum(axis=0)
                per_kind.append({"split": split, "subject": s, "kind": k, "tau": t, "tp": int(tp), "fp": int(fp),
                                 "fn": int(fn), "matched_predictions": int(tp), "unmatched_predictions": int(fp),
                                 "unmatched_gt": int(fn), "precision": _round(tp / (tp + fp) if tp + fp else None),
                                 "recall": _round(tp / (tp + fn) if tp + fn else None), "f1": _round(f1(tp, fp, fn)),
                                 "f1_lo": _round(lo), "f1_hi": _round(hi),
                                 "delta_f1_vs_040": _round(f1(tp, fp, fn) - f1(b_tp, b_fp, b_fn)),
                                 "delta_lo": _round(dlo), "delta_hi": _round(dhi)})
            pooled = cell["instruments"] + cell["assets"]
            boot = (f1_array(weights @ cell["entities"]) + f1_array(weights @ pooled)) / 2
            draws[(s, t)] = boot
            lo, hi = interval(boot)
            dlo, dhi = interval(boot - base_object)
            value = object_score(*(tuple(cell[k].sum(axis=0)) for k in KINDS))
            frozen = object_score(*(tuple(base[k].sum(axis=0)) for k in KINDS))
            per_object.append({"split": split, "subject": s, "tau": t, "object_score": _round(value),
                               "object_lo": _round(lo), "object_hi": _round(hi), "delta_vs_040": _round(value - frozen),
                               "delta_lo": _round(dlo), "delta_hi": _round(dhi)})
    return {"per_kind": per_kind, "per_object": per_object, "draws": draws, "subjects": subjects, "clips": clips,
            "table": table}


def rankings(result: dict, split: str, thresholds: tuple = THRESHOLDS) -> list:
    """Object-score rank per threshold (complete models), with how often each model is first over the resamples."""
    out = []
    complete = [s for s in result["subjects"] if s in COMPLETE]
    point = {(r["subject"], r["tau"]): r["object_score"] for r in result["per_object"]}
    frozen_order = sorted(complete, key=lambda s: -point[(s, FROZEN)])
    for t in thresholds:
        order = sorted(complete, key=lambda s: -point[(s, t)])
        stack = np.stack([result["draws"][(s, t)] for s in complete])
        first = collections.Counter(np.argmax(stack, axis=0).tolist())
        row = {"split": split, "tau": t, "order": " > ".join(order), "same_as_040": order == frozen_order,
               "swaps_vs_040": _swaps(frozen_order, order)}
        for i, s in enumerate(complete):
            row[f"first_share_{s}"] = _round(first[i] / stack.shape[1])
        if "super-direct" in result["subjects"]:
            row["super_object_score_incomplete_or_dev"] = point[("super-direct", t)]
        out.append(row)
    return out


def _swaps(a: list, b: list) -> int:
    position = {s: i for i, s in enumerate(b)}
    return sum(1 for i in range(len(a)) for j in range(i + 1, len(a)) if position[a[i]] > position[a[j]])


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def by_category(blocks: list, split: str) -> list:
    acc: dict = collections.defaultdict(lambda: [0, 0, 0])
    clips: dict = collections.defaultdict(set)
    for b in blocks:
        if b["unavailable"]:
            continue
        for t in THRESHOLDS:
            for i, v in enumerate(counts(b, t)):
                acc[(b["subject"], category(b["clip"]), b["kind"], t)][i] += v
            clips[(b["subject"], category(b["clip"]), b["kind"], t)].add(b["clip"])
    rows = []
    for (s, c, k, t), (tp, fp, fn) in sorted(acc.items(), key=lambda x: (list(MODELS).index(x[0][0]), *x[0][1:])):
        rows.append({"split": split, "subject": s, "category": c, "kind": k, "tau": t, "tp": tp, "fp": fp, "fn": fn,
                     "f1": _round(f1(tp, fp, fn)), "gt_items": tp + fn, "clips": len(clips[(s, c, k, t)]),
                     "reportable": tp + fn >= 10})
    return rows


def assigned_pairs(blocks: list) -> list:
    """Every assigned pair, accepted or not, in ids and similarity. The assignment does not depend on tau."""
    rows = []
    for b in blocks:
        if b["matrix"] is None:
            continue
        id_field = ID_FIELD[b["kind"]]
        for a in assign(b, -2.0):
            rows.append({"subject": b["subject"], "clip": b["clip"], "repeat": b["repeat"], "kind": b["kind"],
                         "model_id": b["model_rows"][a.index][id_field], "gt_id": b["gt_rows"][a.gt_index][id_field],
                         "similarity": a.similarity, "_index": a.index, "_gt_index": a.gt_index})
    return rows


def assignment_diagnostic(blocks: list, split: str) -> list:
    """How the assign-then-filter order compares with filtering first (a diagnostic; the frozen matcher is unchanged)."""
    rows = []
    for s in sorted({b["subject"] for b in blocks}, key=list(MODELS).index):
        for t in THRESHOLDS:
            lost = differs = blocks_lost = accepted = 0
            for b in blocks:
                if b["subject"] != s or b["matrix"] is None:
                    continue
                got = {(a.index, a.gt_index) for a in assign(b, t)}
                other = {(r, c) for r, c, _ in threshold_first(b["matrix"], t)}
                accepted += len(got)
                lost += len(other) - len(got)
                blocks_lost += len(other) > len(got)
                differs += got != other
            rows.append({"split": split, "subject": s, "tau": t, "accepted_assign_then_filter": accepted,
                         "extra_matches_if_filtered_first": lost, "blocks_losing_a_match": blocks_lost,
                         "blocks_with_different_pairs": differs})
    return rows


def similarity_summary(pairs: list, split: str) -> list:
    rows = []
    groups: dict = collections.defaultdict(list)
    for p in pairs:
        groups[(p["subject"], p["kind"])].append(p["similarity"])
        groups[("all", p["kind"])].append(p["similarity"])
    for (s, k), v in sorted(groups.items()):
        q = np.percentile(v, [10, 25, 50, 75, 90])
        rows.append({"split": split, "subject": s, "kind": k, "assigned_pairs": len(v),
                     **{f"p{n}": _round(x, 3) for n, x in zip((10, 25, 50, 75, 90), q, strict=True)},
                     "share_below_040": _round(sum(x < FROZEN for x in v) / len(v), 3),
                     "share_035_to_040": _round(sum(0.35 <= x < FROZEN for x in v) / len(v), 3)})
    return rows


def band_of(similarity: float) -> tuple | None:
    for lo, hi, _ in BANDS:
        if lo <= similarity < hi:
            return (lo, hi)
    return None


def draw_sample(pairs: list, seed: int = SAMPLE_SEED) -> list:
    """Per band, stratified by (kind, model): round-robin over shuffled cells, so rare cells are taken first."""
    rng = random.Random(seed)
    chosen = []
    for lo, hi, quota in BANDS:
        cells: dict = collections.defaultdict(list)
        for p in sorted(pairs, key=lambda x: (x["subject"], x["clip"], x["repeat"], x["kind"], x["model_id"], x["gt_id"])):
            if band_of(p["similarity"]) == (lo, hi):
                cells[(p["kind"], p["subject"])].append(p)
        order = sorted(cells)
        rng.shuffle(order)
        for cell in order:
            rng.shuffle(cells[cell])
        taken = 0
        while taken < quota and any(cells.values()):
            for cell in order:
                if cells[cell] and taken < quota:
                    chosen.append({**cells[cell].pop(), "band": f"{lo:.2f}-{hi:.2f}"})
                    taken += 1
    rng.shuffle(chosen)
    for number, p in enumerate(chosen, 1):
        p["sample_id"] = f"P{number:03d}"
    return chosen


def population(pairs: list) -> dict:
    cells: dict = collections.Counter()
    for p in pairs:
        band = band_of(p["similarity"])
        if band:
            cells[(f"{band[0]:.2f}-{band[1]:.2f}", p["kind"], p["subject"])] += 1
    return cells


def weighted_precision(labelled: list, cells: dict, *, exclude_cannot_tell: bool = False) -> float | None:
    """Population-weighted precision over the labelled cells; a cell with no labelled pair drops out of the weights."""
    by: dict = collections.defaultdict(list)
    for x in labelled:
        by[(x["band"], x["kind"], x["subject"])].append(x["label"])
    num = den = 0.0
    for cell, labels in by.items():
        usable = [v for v in labels if v != "cannot_tell"] if exclude_cannot_tell else labels
        if not usable:
            continue
        weight = cells[cell]
        num += weight * sum(v == "same" for v in usable) / len(usable)
        den += weight
    return num / den if den else None


def precision_interval(labelled: list, cells: dict, *, seed: int = SEED, n: int = RESAMPLES) -> tuple | None:
    """Clip-cluster bootstrap of the weighted precision."""
    clips = sorted({x["clip"] for x in labelled})
    if not clips:
        return None
    by = collections.defaultdict(list)
    for x in labelled:
        by[x["clip"]].append(x)
    rnd = random.Random(seed)
    values = []
    for _ in range(n):
        drawn = [x for _ in clips for x in by[clips[rnd.randrange(len(clips))]]]
        value = weighted_precision(drawn, cells)
        if value is not None:
            values.append(value)
    return interval(np.asarray(values))


def wilson(k: int, n: int, z: float = 1.959964) -> tuple:
    if not n:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def in_range(band: str, lo: float, hi: float) -> bool:
    a, b = (float(x) for x in band.split("-"))
    return a >= lo - 1e-9 and b <= hi + 1e-9


def quality_row(group: str, labelled: list, cells: dict) -> dict:
    n = len(labelled)
    same = sum(x["label"] == "same" for x in labelled)
    different = sum(x["label"] == "different" for x in labelled)
    ci = precision_interval(labelled, cells) or (None, None)
    wlo, whi = wilson(same, n)
    return {"group": group, "labelled": n, "same": same, "different": different, "cannot_tell": n - same - different,
            "raw_precision": _round(same / n if n else None, 3), "wilson_lo": wlo, "wilson_hi": whi,
            "weighted_precision": _round(weighted_precision(labelled, cells), 3),
            "weighted_precision_decided_only": _round(weighted_precision(labelled, cells, exclude_cannot_tell=True), 3),
            "cluster_lo": _round(ci[0], 3), "cluster_hi": _round(ci[1], 3)}


def gate_table(labelled: list, cells: dict, objects: list, calibration: list) -> list:
    """The pre-registered gates of selection-rule.md for each candidate."""
    above = [x for x in labelled if x["band"] == "0.40-0.45"]
    above_precision = weighted_precision(above, cells)
    out = []
    for t in sorted(LOWER, reverse=True):
        new = [x for x in labelled if in_range(x["band"], t, FROZEN)]
        point = weighted_precision(new, cells)
        ci = precision_interval(new, cells)
        kinds = {k: [x for x in new if x["kind"] == k] for k in KINDS}
        kind_p = {k: weighted_precision(v, cells) for k, v in kinds.items()}
        models = {s: [x for x in new if x["subject"] == s] for s in MODELS}
        model_p = {s: weighted_precision(v, cells) for s, v in models.items() if len(v) >= 10}
        effect = {r["subject"]: r for r in objects if r["tau"] == t}
        cal = {r["tau"]: r["f1"] for r in calibration}
        l2_instruments = "not assessable" if len(kinds["instruments"]) < 10 else kind_p["instruments"] >= 0.50
        gates = {"L1": point >= 0.75 and ci[0] >= 0.60, "L2": kind_p["entities"] >= 0.70 and kind_p["assets"] >= 0.70
                 and l2_instruments is not False, "L3": all(v >= 0.60 for v in model_p.values()),
                 "L4": all(effect[s]["delta_vs_040"] >= 0.02 and effect[s]["delta_lo"] > 0 for s in COMPLETE),
                 "L5": point >= above_precision - 0.10, "L6": cal[t] >= cal[FROZEN] - 0.01}
        out.append({"tau": t, "newly_accepted_labelled": len(new), "precision": _round(point, 3),
                    "ci_lo": _round(ci[0], 3), "ci_hi": _round(ci[1], 3),
                    "precision_decided_only": _round(weighted_precision(new, cells, exclude_cannot_tell=True), 3),
                    "precision_entities": _round(kind_p["entities"], 3), "precision_assets": _round(kind_p["assets"], 3),
                    "precision_instruments": _round(kind_p["instruments"], 3), "instruments_labelled": len(kinds["instruments"]),
                    "min_model_precision": _round(min(model_p.values()), 3) if model_p else None,
                    "precision_040_045": _round(above_precision, 3), "calibration_f1": cal[t],
                    **{k: bool(v) for k, v in gates.items()}, "all_pass": all(bool(v) for v in gates.values())})
    ci = precision_interval(above, cells)
    out.append({"tau": 0.45, "newly_accepted_labelled": len(above), "precision": _round(above_precision, 3),
                "ci_lo": _round(ci[0], 3), "ci_hi": _round(ci[1], 3),
                "precision_decided_only": _round(weighted_precision(above, cells, exclude_cannot_tell=True), 3),
                "all_pass": above_precision <= 0.50 and ci[1] <= 0.65})
    return out


def band_estimates(labelled: list, cells: dict) -> list:
    """Assigned pairs per band with the weighted shares labelled same, different and cannot tell, applied to the band."""
    rows = []
    for lo, hi, _ in sorted(BANDS):
        band = f"{lo:.2f}-{hi:.2f}"
        got = [x for x in labelled if x["band"] == band]
        total = sum(n for c, n in cells.items() if c[0] == band)
        shares = {}
        for label in LABELS:
            recoded = [{**x, "label": "same" if x["label"] == label else "other"} for x in got]
            shares[label] = weighted_precision(recoded, cells)
        rows.append({"band": band, "assigned_pairs": total, "labelled": len(got),
                     **{f"share_{k}": _round(v, 3) for k, v in shares.items()},
                     **{f"estimated_{k}": round(v * total) for k, v in shares.items()}})
    return rows


def calibration_rows() -> list:
    """Calibration v2's stored table: the 132 AI-labelled dev pairs, ambiguous pairs left out."""
    data = json.loads(CALIBRATION.read_text())
    rows = []
    for x in data["table"]:
        t = round(x["threshold"], 2)
        for kind in ("all", *KINDS):
            c = x[kind]
            plo, phi = wilson(c["tp"], c["tp"] + c["fp"])
            rlo, rhi = wilson(c["tp"], c["tp"] + c["fn"])
            rows.append({"tau": t, "kind": kind, "tp": c["tp"], "fp": c["fp"], "fn": c["fn"],
                         "precision": _round(c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else None, 3),
                         "precision_lo": plo, "precision_hi": phi,
                         "recall": _round(c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else None, 3),
                         "recall_lo": rlo, "recall_hi": rhi, "f1": _round(f1(c["tp"], c["fp"], c["fn"]), 3)})
    return rows


def write(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(k for r in rows for k in r if not k.startswith("_")))
    with path.open("w", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def read_csv(path: Path) -> list:
    with path.open() as handle:
        return list(csv.DictReader(handle))


def load_half(runs: tuple[str, ...]) -> tuple[dict, list, dict]:
    rows = load_rows(runs)
    blocks, audit = build_blocks(rows, load_vectors(runs))
    return rows, blocks, audit


def clips_of(half: str) -> set:
    return set(json.loads(SPLIT_FILE.read_text())[half])


def cmd_replay() -> int:
    """The replay at tau = 0.40 only: no other threshold is computed on the evaluation half here."""
    report = {}
    for name, runs, half in (("dev", DEV_RUNS, "dev"), ("evaluation", EVAL_RUNS, "test")):
        rows, blocks, audit = load_half(runs)
        check = replay_check(blocks)
        by = collections.Counter((k[0], r["outcome"]) for k, r in rows.items())
        kept = sorted({k[1] for k in rows})
        totals = collections.defaultdict(lambda: [0, 0, 0])
        for b in blocks:
            for i, v in enumerate(counts(b, FROZEN)):
                totals[f"{b['subject']}|{b['kind']}"][i] += v
        report[name] = {"runs": runs, "rows": len(rows), "clips": len(kept), "all_clips_in_half": set(kept) <= clips_of(half),
                        "outcomes": {f"{a}|{b}": n for (a, b), n in sorted(by.items())}, "audit": dict(audit), "replay": check,
                        "totals_at_040": {k: v for k, v in sorted(totals.items())}}
    (OUT / "replay.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: {x: v[x] for x in ("rows", "clips", "all_clips_in_half", "audit")} | {
        "replay": {a: b for a, b in v["replay"].items() if a != "differences"},
        "differences": v["replay"]["differences"][:6]} for k, v in report.items()}, indent=1))
    return 0


def cmd_dev() -> int:
    _, blocks, _ = load_half(DEV_RUNS)
    result = sweep(blocks, "dev")
    write(OUT / "dev_sweep_by_kind.csv", result["per_kind"])
    write(OUT / "dev_object_score.csv", result["per_object"])
    write(OUT / "dev_rankings.csv", rankings(result, "dev"))
    write(OUT / "dev_by_category.csv", by_category(blocks, "dev"))
    write(OUT / "dev_assignment_diagnostic.csv", assignment_diagnostic(blocks, "dev"))
    pairs = assigned_pairs(blocks)
    write(OUT / "dev_similarity_distribution.csv", similarity_summary(pairs, "dev"))
    write(OUT / "dev_assigned_pairs.csv", [{k: (round(v, 4) if k == "similarity" else v) for k, v in p.items()} for p in pairs])
    write(OUT / "calibration_v2_by_tau.csv", calibration_rows())
    return 0


def cmd_sample() -> int:
    """The blind sheet (private: texts, no similarity, model, clip or band) and its key (ids and scores)."""
    _, blocks, _ = load_half(DEV_RUNS)
    pairs = assigned_pairs(blocks)
    sample = draw_sample(pairs)
    lookup = {(b["subject"], b["clip"], b["repeat"], b["kind"]): b for b in blocks}
    from evalv2.tasks.incident_objects import v1

    sheet = []
    for p in sorted(sample, key=lambda x: x["sample_id"]):
        b = lookup[(p["subject"], p["clip"], p["repeat"], p["kind"])]
        others = [v1.TEXT[p["kind"]](g) for i, g in enumerate(b["gt_rows"]) if i != p["_gt_index"]]
        sheet.append({"sample_id": p["sample_id"], "kind": p["kind"], "prediction": v1.TEXT[p["kind"]](b["model_rows"][p["_index"]]),
                      "ground_truth": v1.TEXT[p["kind"]](b["gt_rows"][p["_gt_index"]]), "other_gt_same_kind": others})
    PRIVATE.mkdir(parents=True, exist_ok=True)
    (PRIVATE / "label-sheet.json").write_text(json.dumps(sheet, indent=0, ensure_ascii=False) + "\n")
    write(PRIVATE / "label-key.csv", [{k: (round(v, 4) if k == "similarity" else v) for k, v in p.items()} for p in sample])
    write(OUT / "dev_band_population.csv", [{"band": c[0], "kind": c[1], "subject": c[2], "assigned_pairs": n}
                                            for c, n in sorted(population(pairs).items())])
    print(len(sample), collections.Counter(p["band"] for p in sample), collections.Counter(p["kind"] for p in sample),
          collections.Counter(p["subject"] for p in sample))
    return 0


def load_labelled() -> list:
    key = {r["sample_id"]: r for r in read_csv(PRIVATE / "label-key.csv")}
    out = []
    for line in (PRIVATE / "labels-ai.jsonl").read_text().splitlines():
        x = json.loads(line)
        if x["label"] not in LABELS or x["mode"] not in MODES:
            raise ValueError(f"bad label {x}")
        out.append({**key[x["sample_id"]], "label": x["label"], "mode": x["mode"]})
    if len(out) != len(key) or len({x["sample_id"] for x in out}) != len(key):
        raise ValueError("every sampled pair must be labelled exactly once")
    return out


def cmd_tally() -> int:
    labelled = load_labelled()
    cells = {(r["band"], r["kind"], r["subject"]): int(r["assigned_pairs"]) for r in read_csv(OUT / "dev_band_population.csv")}
    write(OUT / "dev_labelled_pairs.csv", [{k: x[k] for k in ("sample_id", "subject", "clip", "repeat", "kind", "model_id", "gt_id",
                                                               "similarity", "band", "label", "mode")} for x in labelled])
    rows = []
    for lo, hi, _ in sorted(BANDS):
        band = f"{lo:.2f}-{hi:.2f}"
        rows.append(quality_row(f"band {band}", [x for x in labelled if x["band"] == band], cells))
    below = [x for x in labelled if float(x["band"][:4]) < FROZEN]
    just_above = [x for x in labelled if x["band"] == "0.40-0.45"]
    for name, group in (("below 0.40", below), ("0.40-0.45", just_above)):
        for k in KINDS:
            rows.append(quality_row(f"{name} | {k}", [x for x in group if x["kind"] == k], cells))
        for s in MODELS:
            rows.append(quality_row(f"{name} | {s}", [x for x in group if x["subject"] == s], cells))
    write(OUT / "dev_label_quality.csv", rows)
    modes = collections.Counter((("below" if x in below else "above"), x["label"], x["mode"]) for x in labelled)
    write(OUT / "dev_label_modes.csv", [{"side_of_040": a, "label": b, "mode": c, "pairs": n} for (a, b, c), n in sorted(modes.items())])
    calibration = [r for r in calibration_rows() if r["kind"] == "all"]
    objects = [{**r, "tau": float(r["tau"]), "delta_vs_040": float(r["delta_vs_040"]), "delta_lo": float(r["delta_lo"])}
               for r in read_csv(OUT / "dev_object_score.csv")]
    gates = gate_table(labelled, cells, objects, calibration)
    write(OUT / "dev_gates.csv", gates)
    write(OUT / "dev_band_estimates.csv", band_estimates(labelled, cells))
    print(json.dumps(gates, indent=1))
    return 0


def cmd_seal() -> int:
    """Record the rule and decision hashes. Run once, after dev-selection.md is written, before ``evaluation``."""
    if LEDGER.exists():
        raise SystemExit("the selection is already sealed")
    LEDGER.write_text(json.dumps({"selection_rule_sha256": sha256(RULE), "dev_selection_sha256": sha256(SELECTION),
                                  "dev_gates_sha256": sha256(OUT / "dev_gates.csv")}, indent=1) + "\n")
    print(LEDGER.read_text())
    return 0


def selection_sealed() -> bool:
    if not (LEDGER.exists() and SELECTION.exists() and RULE.exists()):
        return False
    ledger = json.loads(LEDGER.read_text())
    return ledger["dev_selection_sha256"] == sha256(SELECTION) and ledger["selection_rule_sha256"] == sha256(RULE)


def cmd_evaluation() -> int:
    if not selection_sealed():
        raise SystemExit("refused: dev-selection.md is missing, changed or unsealed; the evaluation sweep comes after it")
    _, blocks, _ = load_half(EVAL_RUNS)
    complete_blocks = [b for b in blocks if b["subject"] in COMPLETE]
    result = sweep(blocks, "evaluation")
    write(OUT / "evaluation_sweep_by_kind.csv", result["per_kind"])
    write(OUT / "evaluation_object_score.csv", result["per_object"])
    write(OUT / "evaluation_rankings.csv", rankings(result, "evaluation"))
    write(OUT / "evaluation_by_category.csv", by_category(blocks, "evaluation"))
    write(OUT / "evaluation_assignment_diagnostic.csv", assignment_diagnostic(complete_blocks, "evaluation"))
    pairs = assigned_pairs(blocks)
    write(OUT / "evaluation_similarity_distribution.csv", similarity_summary(pairs, "evaluation"))
    return 0


COLOURS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4")
MARKERS = ("o", "s", "^", "D", "v")
SHORT = {"nano-direct": "Nano", "gemma4-31b-openrouter": "Gemma", "qwen35-9b-openrouter": "Qwen", "omni-direct": "Omni",
         "super-direct": "Super"}


def _object_plot(plt, split: str, path: str) -> None:
    rows = read_csv(OUT / f"{split}_object_score.csv")
    fig, ax = plt.subplots(figsize=(8.6, 5))
    labels = []
    for i, s in enumerate(MODELS):
        got = [r for r in rows if r["subject"] == s]
        x = [float(r["tau"]) for r in got]
        y = [float(r["object_score"]) for r in got]
        name = MODELS[s] + (" (incomplete)" if s == "super-direct" and split == "evaluation" else "")
        ax.plot(x, y, color=COLOURS[i], marker=MARKERS[i], linestyle="--" if s == "super-direct" else "-", label=name)
        labels.append([y[0], name, COLOURS[i]])
    _spread(labels, 0.02)
    for y, name, colour in labels:
        ax.annotate(name, (0.20, y), xytext=(-8, 0), textcoords="offset points", ha="right", va="center", color=colour, fontsize=8.5)
    ax.axvline(FROZEN, color="#777777", linewidth=1)
    ax.text(FROZEN + 0.004, 0.02, "τ = 0.40 (primary)", color="#555555", fontsize=9, transform=ax.get_xaxis_transform())
    ax.set_xlim(0.03, 0.62)
    ax.set_ylim(bottom=0)
    ax.set_xticks([float(t) for t in THRESHOLDS])
    ax.set_xlabel("Matching threshold τ")
    ax.set_ylabel("Object score")
    ax.set_title(f"Object score by threshold, {'dev' if split == 'dev' else 'evaluation half'} (measured F1 cannot fall as τ falls)", fontsize=11)
    ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "plots" / path, dpi=160)
    plt.close(fig)


def _spread(labels: list, gap: float) -> None:
    labels.sort(key=lambda x: x[0])
    for a, b in zip(labels, labels[1:], strict=False):
        if b[0] - a[0] < gap:
            b[0] = a[0] + gap


def _kind_plot(plt, split: str, path: str) -> None:
    rows = read_csv(OUT / f"{split}_sweep_by_kind.csv")
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2), sharey=True)
    for ax, kind in zip(axes, KINDS, strict=True):
        ends: list = []
        for i, s in enumerate(MODELS):
            got = [r for r in rows if r["subject"] == s and r["kind"] == kind]
            name = MODELS[s] + (" (incomplete)" if s == "super-direct" and split == "evaluation" else "")
            ys = [float(r["f1"]) for r in got]
            ax.plot([float(r["tau"]) for r in got], ys, color=COLOURS[i], marker=MARKERS[i],
                    markersize=4.5, linestyle="--" if s == "super-direct" else "-", label=name)
            ends.append([ys[-1], SHORT[s], COLOURS[i]])
        _spread(ends, 0.04)
        for y, name, colour in ends:
            ax.annotate(name, (0.60, y), xytext=(7, 0), textcoords="offset points", va="center", color=colour, fontsize=8)
        ax.set_xlim(0.18, 0.70)
        ax.set_xticks([0.2, 0.3, 0.4, 0.5, 0.6])
        ax.axvline(FROZEN, color="#777777", linewidth=1)
        ax.set_title(kind.capitalize(), fontsize=11)
        ax.set_xlabel("Matching threshold τ")
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("F1")
    handles, names = axes[0].get_legend_handles_labels()
    fig.legend(handles, names, frameon=False, ncol=5, loc="lower center", fontsize=9)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(OUT / "plots" / path, dpi=160)
    plt.close(fig)


def _quality_plot(plt) -> None:
    rows = [r for r in read_csv(OUT / "dev_label_quality.csv") if r["group"].startswith("band ")]
    x = [sum(float(v) for v in r["group"][5:].split("-")) / 2 for r in rows]
    y = [float(r["weighted_precision"]) for r in rows]
    lo = [float(r["cluster_lo"]) for r in rows]
    hi = [float(r["cluster_hi"]) for r in rows]
    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    ax.errorbar(x, y, yerr=[[a - b for a, b in zip(y, lo, strict=True)], [b - a for a, b in zip(y, hi, strict=True)]],
                color=COLOURS[0], marker="o", capsize=3, label="Share labelled same object (one AI reader)")
    calibration = [r for r in calibration_rows() if r["kind"] == "all" and 0.20 <= r["tau"] <= 0.60]
    ax.plot([r["tau"] for r in calibration], [r["precision"] for r in calibration], color=COLOURS[1], marker="s",
            label="Calibration v2: precision of all pairs at or above τ")
    for a, b, n in zip(x, y, rows, strict=True):
        ax.annotate(f"n={n['labelled']}", (a, b), xytext=(6, -11), textcoords="offset points", fontsize=8, color=COLOURS[0])
    ax.annotate("Calibration v2", (0.50, 0.85), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=9, color=COLOURS[1])
    ax.annotate("Sampled pairs in each band", (0.475, 0.653), xytext=(10, -2), textcoords="offset points", fontsize=9, color=COLOURS[0])
    ax.axvline(FROZEN, color="#777777", linewidth=1)
    ax.text(FROZEN + 0.004, 0.965, "τ = 0.40", color="#555555", fontsize=9, transform=ax.get_xaxis_transform())
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("Similarity of the assigned pair (band midpoint), or τ for calibration v2")
    ax.set_ylabel("Precision")
    ax.set_title("Quality of assigned pairs by similarity, dev", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    handles, names = ax.get_legend_handles_labels()
    fig.legend(handles, names, frameon=False, fontsize=8.5, loc="lower center", ncol=2)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(OUT / "plots" / "dev_pair_quality.png", dpi=160)
    plt.close(fig)


def cmd_plots() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    (OUT / "plots").mkdir(exist_ok=True)
    for split in ("dev", "evaluation"):
        _object_plot(plt, split, f"{split}_object_score.png")
        _kind_plot(plt, split, f"{split}_f1_by_kind.png")
    _quality_plot(plt)
    return 0


COMMANDS = {"replay": cmd_replay, "dev": cmd_dev, "sample": cmd_sample, "tally": cmd_tally, "seal": cmd_seal,
            "evaluation": cmd_evaluation, "plots": cmd_plots}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        raise SystemExit(f"usage: {sys.argv[0]} {{{','.join(COMMANDS)}}}")
    sys.exit(COMMANDS[sys.argv[1]]())
