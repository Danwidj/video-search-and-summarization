# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""READ-ONLY reproducibility audit: why asset and instrument F1 differ between the old slide and C3 Track A.

Offline: stored score rows, stored MiniLM vectors, the unchanged ``matching.solve_assignment``. No VLM, judge or API
call. Nothing here rescores a run or changes a reported result. Repo outputs hold ids, counts and scores; anything with
GT or prediction text goes to ``PRIVATE``. Super on the evaluation half is the frozen 26-row snapshot, labelled
incomplete; A5-s is never read.

    export OMP_NUM_THREADS=1
    nice -n 19 uv run --frozen python scripts/v2_c2_c3_object_audit.py embed     # local MiniLM, rejected replies only
    nice -n 19 uv run --frozen python scripts/v2_c2_c3_object_audit.py audit     # every CSV and replay.json
    nice -n 19 uv run --frozen python scripts/v2_c2_c3_object_audit.py examples  # private candidates and the index

``embed`` is needed only by the ``salvage`` diagnostic. It uses the cached local model and no network.
"""

from __future__ import annotations

import collections
import csv
import hashlib
import importlib.util
import json
import os
import random
import statistics
import sys
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np  # noqa: E402

EVAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL))

_spec = importlib.util.spec_from_file_location("objsens", EVAL / "scripts" / "v2_object_threshold_sensitivity.py")
sens = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sens)

R = sens.R
DATA = R.parent
OUT = EVAL / "methodology" / "c2-c3-object-audit"
PRIVATE = DATA / "diagnostics" / "c2-c3-object-audit"
REPORT = DATA / "reports" / "track-a-five-models" / "track-a-report.json"
DEV_CSV = EVAL / "methodology" / "results" / "v2-dev" / "track_a_models.csv"
D2_CSV = EVAL / "methodology" / "presentation" / "data" / "d2_object_identification.csv"
SWEEP_CSV = {"dev": EVAL / "methodology" / "object-threshold-sensitivity" / "dev_sweep_by_kind.csv",
             "evaluation": EVAL / "methodology" / "object-threshold-sensitivity" / "evaluation_sweep_by_kind.csv"}
OFFLINE = "scoring/evalv2-score-stage-v3/primary/offline-videos.jsonl"
SUMMARY = "scoring/evalv2-score-stage-v3/primary/{}-summary.json"

KINDS = sens.KINDS
FOCUS = ("assets", "instruments")
MODELS = tuple(sens.MODELS)
COMPLETE = sens.COMPLETE
HALVES = {"dev": sens.DEV_RUNS, "evaluation": sens.EVAL_RUNS}
SPLIT_NAME = {"dev": "dev", "evaluation": "test"}
VIEWS = ("valid", "outputs")
OUTCOME_VIEW = {"valid": ("scored",), "outputs": sens.MODEL_OUTPUT}
TAU_GRID = (*sens.THRESHOLDS, 0.75)
SEED, RESAMPLES = sens.SEED, sens.RESAMPLES
EXAMPLE_SEED = 20261105
EXAMPLE_CELLS = (("gemma4-31b-openrouter", "assets"), ("omni-direct", "assets"), ("super-direct", "assets"),
                 ("qwen35-9b-openrouter", "instruments"))

# Values as given by the requester, and the deck's percentages (Evaluation_V2_Object_Identification_Three_Slides.pptx,
# slides 11 and 12). (asset F1, instrument F1).
SLIDE = {"nano-direct": (0.408, 0.235), "omni-direct": (0.500, 0.214), "super-direct": (0.409, 0.258),
         "qwen35-9b-openrouter": (0.423, 0.350), "gemma4-31b-openrouter": (0.704, 0.207)}
C3_CLAIM = {"nano-direct": (0.448, 0.286), "omni-direct": (0.271, 0.122), "super-direct": (0.217, 0.222),
            "qwen35-9b-openrouter": (0.468, 0.146), "gemma4-31b-openrouter": (0.425, 0.195)}
SHORT = {"nano-direct": "Nano", "omni-direct": "Omni", "super-direct": "Super", "qwen35-9b-openrouter": "Qwen",
         "gemma4-31b-openrouter": "Gemma"}


def f1(tp: float, fp: float, fn: float) -> float:
    return sens.f1(tp, fp, fn)


def prf(tp: float, fp: float, fn: float) -> dict:
    return {"precision": tp / (tp + fp) if tp + fp else 0.0, "recall": tp / (tp + fn) if tp + fn else 0.0,
            "f1": f1(tp, fp, fn)}


def r6(value: float | None) -> float | None:
    """Six places, so that a table rounding to three reads the exact value (0.21649 is 0.216, not 0.2165 then 0.217)."""
    return None if value is None else round(float(value), 6)


def in_view(block: dict, view: str) -> bool:
    return block["outcome"] in OUTCOME_VIEW[view]


def select(blocks: list, subject: str, kind: str, view: str, repeat: int | None = None) -> list:
    return [b for b in blocks if b["subject"] == subject and b["kind"] == kind and in_view(b, view)
            and (repeat is None or b["repeat"] == repeat)]


def pool(blocks: list, tau: float = sens.FROZEN) -> tuple[int, int, int]:
    """Micro counts: every block's tp, fp and fn summed before F1 is taken (the report's and the chart's rule)."""
    tp = fp = fn = 0
    for b in blocks:
        a, c, d = sens.counts(b, tau)
        tp, fp, fn = tp + a, fp + c, fn + d
    return tp, fp, fn


def f1_of(blocks: list, tau: float = sens.FROZEN) -> float | None:
    """Micro F1, or None when the slice holds no row (Super has no repeat 2 on the evaluation half)."""
    return f1(*pool(blocks, tau)) if blocks else None


def planned_counts(blocks: list, no_output_gt: int) -> tuple[int, int, int]:
    """Invalid as miss, and a planned item with no model output as a miss too (the chart leaves those rows out)."""
    tp, fp, fn = pool(blocks)
    return tp, fp, fn + no_output_gt


def drop_top_fp_row(blocks: list) -> list:
    """Sensitivity only: leave out the single row with the most false positives."""
    if not blocks:
        return blocks
    worst = max(blocks, key=lambda b: (sens.counts(b, sens.FROZEN)[1], b["clip"], b["repeat"]))
    return [b for b in blocks if b is not worst]


def macro_f1(blocks: list, tau: float = sens.FROZEN) -> float | None:
    """Per-clip macro: repeats pooled within a clip, F1 per clip, mean over clips with any GT or prediction."""
    by = collections.defaultdict(lambda: [0, 0, 0])
    for b in blocks:
        for i, v in enumerate(sens.counts(b, tau)):
            by[b["clip"]][i] += v
    scores = [f1(*v) for v in by.values() if sum(v)]
    return sum(scores) / len(scores) if scores else None


def clip_table(blocks: list, tau: float = sens.FROZEN) -> tuple[list, np.ndarray]:
    clips = sorted({b["clip"] for b in blocks})
    index = {c: i for i, c in enumerate(clips)}
    table = np.zeros((len(clips), 3))
    for b in blocks:
        table[index[b["clip"]]] += sens.counts(b, tau)
    return clips, table


def boot_draws(blocks: list, seed: int = SEED, n: int = RESAMPLES) -> np.ndarray | None:
    """F1 over clip-cluster resamples of the evaluated clips (repeats stay inside their clip)."""
    clips, table = clip_table(blocks)
    if not clips:
        return None
    return sens.f1_array(sens.resample_matrix(len(clips), seed, n) @ table)


def reweighted_f1(blocks: list, target: dict, tau: float = sens.FROZEN) -> float | None:
    """Direct standardisation: per-category mean tp, fp and fn per row, mixed in ``target``'s category proportions."""
    sums = collections.defaultdict(lambda: np.zeros(3))
    rows = collections.Counter()
    for b in blocks:
        c = sens.category(b["clip"])
        sums[c] += sens.counts(b, tau)
        rows[c] += 1
    shared = {c: w for c, w in target.items() if rows[c]}
    total = sum(shared.values())
    if not total:
        return None
    mixed = sum((w / total) * sums[c] / rows[c] for c, w in shared.items())
    return f1(*mixed)


def swap_effects(dev: tuple, c3: tuple) -> dict:
    """One-at-a-time: F1 with C3's precision and the dev recall, and with the dev precision and C3's recall."""
    a, b = prf(*dev), prf(*c3)

    def harmonic(p: float, r: float) -> float:
        return 2 * p * r / (p + r) if p + r else 0.0

    return {"f1_c3_precision_only": harmonic(b["precision"], a["recall"]),
            "f1_c3_recall_only": harmonic(a["precision"], b["recall"])}


def write_csv(name: str, rows: list) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def jsonl(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_half(half: str) -> tuple[dict, list, dict]:
    rows = sens.load_rows(HALVES[half])
    vectors = sens.load_vectors(HALVES[half])
    blocks, audit = sens.build_blocks(rows, vectors)  # run vectors only; the private cache never enters a block
    return rows, blocks, {"audit": dict(audit), "vectors": {**vectors, **private_vectors()}}


def gt_by_clip(rows: dict) -> dict:
    return {r["incident_id"]: r["ground_truth"] for r in rows.values() if "ground_truth" in r}


def durations() -> dict:
    from evalv2.executor import load_manifest_clips

    return {c["incident_id"]: c.get("duration_seconds") for c in load_manifest_clips()}


def split_ids() -> dict:
    data = json.loads(sens.SPLIT_FILE.read_text())
    return {"dev": data["dev"], "evaluation": data["test"]}


# --- the source chain -----------------------------------------------------------------------------------------------

def source_figures(blocks: list) -> tuple[list, dict]:
    """Slide value against the CSV, the saved report, and two recomputations from raw rows (offline and live)."""
    from evalv2 import track_a_report

    report = json.loads(REPORT.read_text())
    csv_rows = {r["model"]: r for r in read_csv(DEV_CSV)}
    videos, _ = track_a_report.load([R / r for r in sens.DEV_RUNS], "evalv2-score-stage-v3")
    d2 = {(r["subject"], r["kind"]): r for r in read_csv(D2_CSV) if r["split"] == "dev-25" and r["stage"] == "p1"
          and r["config"] == "Track A pilot"}
    c1a_only_super = [r for r in jsonl(R / "c1a" / OFFLINE) if r["subject"] == "super-direct"]
    out = []
    for s in MODELS:
        offline = track_a_report._valid([v for v in videos if v["subject"] == s])  # noqa: SLF001
        for kind, position in (("assets", 0), ("instruments", 1)):
            live = pool(select(blocks, s, kind, "valid"))
            source = report["subjects"][s]["valid"]["objects"][kind]
            row_blocks = select(blocks, s, kind, "valid")
            value = csv_rows[sens.MODELS[s]][f"{kind}_f1"]
            recomputed = offline["objects"][kind]
            out.append({
                "model": SHORT[s], "kind": kind, "slide_value": SLIDE[s][position], "csv_value": r6(float(value)),
                "report_value": r6(source["f1"]), "offline_rows_f1": r6(recomputed["f1"]), "live_rows_f1": r6(f1(*live)),
                "tp": live[0], "fp": live[1], "fn": live[2], "gt_objects": live[0] + live[2],
                "predicted_objects": live[0] + live[1], "rows": len(row_blocks),
                "clips": len({b["clip"] for b in row_blocks}),
                "matches_slide_at_3dp": round(f1(*live), 3) == SLIDE[s][position],
                "macro_per_clip_f1": r6(macro_f1(row_blocks)),
                "d2_dev_f1_invalid_as_miss": r6(f1(*(int(d2[(s, kind)][m]) for m in ("tp", "fp", "fn")))),
                "d2_tp": int(d2[(s, kind)]["tp"]), "d2_fp": int(d2[(s, kind)]["fp"]), "d2_fn": int(d2[(s, kind)]["fn"])})
    pre = {k: track_a_report._valid(c1a_only_super)["objects"][k]["f1"] for k in FOCUS}  # noqa: SLF001
    return out, {"super_c1a_only_rows": len(c1a_only_super), "super_c1a_only_valid_f1": {k: r6(v) for k, v in pre.items()}}


def provenance() -> list:
    out = []
    for half, runs in HALVES.items():
        for run in runs:
            m = json.loads((R / run / "manifest.start.json").read_text())
            summary = json.loads((R / run / SUMMARY.format("live")).read_text())
            offline = json.loads((R / run / SUMMARY.format("offline")).read_text())
            p1 = m["requests"]["p1"]
            scorer = summary["scorer"]["files_sha256"]
            config = m["config"]
            out.append({
                "half": half, "run": run, "experiment": m["run_id"], "created_at": m["created_at"], "purpose": m["purpose"],
                "split": f"{config['split']['version']}/{config['split']['half']}", "repeats": config["repeats"],
                "planned_items": m["plan"]["incident_objects"]["items"], "run_git_sha": m["code"]["git_sha"][:9],
                "subjects": ";".join(s["id"] for s in config["subjects"]),
                "endpoint_models": ";".join(f"{s['endpoint']}:{s['model']}" for s in config["subjects"]),
                "provider_order": ";".join(",".join(s["request"]["extra_body"]["provider"]["order"]) for s in config["subjects"]
                                           if s.get("request")),
                "contract": p1["contract_version"], "prompt_id": p1["prompt_id"], "prompt_sha256": p1["prompt_sha256"][:12],
                "response_format_sha256": p1["response_format_sha256"][:12], "settings_sha256": p1["settings_sha256"][:12],
                "gt_sha256": m["inputs"]["ground-truth-v1.0/ground_truth.json"][:12],
                "split_sha256": m["inputs"]["ground-truth-v1.0/split-v2.json"][:12],
                "freeze_manifest": (config.get("freeze_manifest") or "none")[:12], "retry_policy": config["retry_policy"],
                "score_version": summary["score_version"], "offline_scorer_sha": offline["scorer"]["git_sha"][:9],
                "live_scorer_sha": summary["scorer"]["git_sha"][:9],
                "aggregate_py": scorer["evalv2/tasks/incident_objects/aggregate.py"][:8],
                "scoring_py": scorer["evalv2/tasks/incident_objects/scoring.py"][:8],
                "score_stage_py": scorer["evalv2/score_stage.py"][:8]})
    return out


def replay_checks(blocks_by_half: dict) -> dict:
    """Stored counts against the replay at 0.40; invalid rows hold no prediction; chart and sweep cells match."""
    import methodology

    out: dict = {"methodology_version": methodology.METHODOLOGY_VERSION, "match_threshold": methodology.MATCH_THRESHOLD,
                 "embedding_model": methodology.EMBEDDING_MODEL, "a5s_read": False}
    d2 = read_csv(D2_CSV)
    for half, blocks in blocks_by_half.items():
        replay = sens.replay_check(blocks)
        lowest = min((m["similarity_score"] for b in blocks for m in b["stored_matches"] or []), default=None)
        out[half] = {
            "blocks_compared": replay.get("blocks_compared", 0), "count_mismatches": replay.get("count_mismatches", 0),
            "stored_pairs": replay.get("stored_pairs", 0),
            "blocks_pairing_differently_ties": replay.get("blocks_with_a_different_pairing", 0),
            "lowest_stored_similarity": r6(lowest),
            "stored_pairs_at_or_above_075": sum(m["similarity_score"] >= 0.75 for b in blocks
                                                for m in b["stored_matches"] or []),
            "invalid_blocks_with_predictions": sum(1 for b in blocks if b["outcome"] != "scored" and b["n_pred"])}
        split, config = ("dev-25", "Track A pilot") if half == "dev" else ("test-55", "Track A direct VLM, frozen P1 v4")
        cells = bad = 0
        for s in MODELS:
            for kind in KINDS:
                chart = next(r for r in d2 if r["split"] == split and r["config"] == config and r["subject"] == s
                             and r["kind"] == kind and r["stage"] == "p1")
                got = pool(select(blocks, s, kind, "outputs"))
                cells += 1
                bad += got != (int(chart["tp"]), int(chart["fp"]), int(chart["fn"]))
        out[half]["chart_cells"], out[half]["chart_cell_mismatches"] = cells, bad
        sweep = read_csv(SWEEP_CSV[half])
        compared = wrong = 0
        for r in sweep:
            got = pool(select(blocks, r["subject"], r["kind"], "outputs"), float(r["tau"]))
            compared += 1
            wrong += got != (int(r["tp"]), int(r["fp"]), int(r["fn"]))
        out[half]["sweep_cells"], out[half]["sweep_cell_mismatches"] = compared, wrong
    return out


# --- populations ----------------------------------------------------------------------------------------------------

def populations(rows_by_half: dict) -> list:
    ids, seconds, out = split_ids(), durations(), []
    gts = {half: gt_by_clip(rows) for half, rows in rows_by_half.items()}
    overlap = set(ids["dev"]) & set(ids["evaluation"])
    for half, clips in ids.items():
        missing = [c for c in clips if c not in gts[half]]
        for category in ("ALL", *sorted({sens.category(c) for c in clips})):
            members = [c for c in clips if category in ("ALL", sens.category(c)) and c in gts[half]]
            lengths = [seconds[c] for c in members if seconds.get(c)]
            row = {"half": half, "category": category, "clips": len(members), "clip_overlap_with_other_half": len(overlap),
                   "clips_without_gt_row": len(missing), "median_duration_s": r6(statistics.median(lengths)),
                   "mean_duration_s": r6(statistics.mean(lengths))}
            for kind in KINDS:
                items = [(c, x) for c in members for x in gts[half][c].get(kind) or []]
                per = collections.Counter(c for c, _ in items)
                words = [len(sens_text(kind, x).split()) for _, x in items]
                row[f"gt_{kind}"] = len(items)
                row[f"clips_with_{kind}"] = len(per)
                row[f"{kind}_per_clip"] = r6(len(items) / len(members))
                row[f"{kind}_top3_clip_share"] = r6(sum(v for _, v in per.most_common(3)) / len(items)) if items else None
                row[f"{kind}_mean_words"] = r6(statistics.mean(words)) if words else None
            out.append(row)
    return out


def sens_text(kind: str, item: dict) -> str:
    from evalv2.tasks.incident_objects import v1

    return v1.TEXT[kind](item)


def outcome_mix(rows_by_half: dict, blocks_by_half: dict) -> list:
    seconds, out = durations(), []
    ids = split_ids()
    for half, rows in rows_by_half.items():
        for s in MODELS:
            got = [r for k, r in rows.items() if k[0] == s]
            outcomes = collections.Counter(r["outcome"] for r in got)
            valid = [r for r in got if r["outcome"] == "scored"]
            planned = len(ids[half]) * 2
            row = {"half": half, "model": SHORT[s], "complete": not (half == "evaluation" and s == "super-direct"),
                   "planned": planned, "rows": len(got), "scored": outcomes["scored"],
                   "contract_invalid": outcomes["contract_invalid"], "parse_failure": outcomes["parse_failure"],
                   "no_output": planned - sum(outcomes[o] for o in sens.MODEL_OUTPUT),
                   "contract_valid_rate_of_planned": r6(outcomes["scored"] / planned),
                   "valid_clips": len({r["incident_id"] for r in valid}),
                   "valid_mean_duration_s": r6(statistics.mean(seconds[r["incident_id"]] for r in valid)),
                   "invalid_mean_duration_s": None}
            bad = [r for r in got if r["outcome"] in ("contract_invalid", "parse_failure")]
            if bad:
                row["invalid_mean_duration_s"] = r6(statistics.mean(seconds[r["incident_id"]] for r in bad))
            mix = collections.Counter(sens.category(r["incident_id"]) for r in valid)
            for c in ("Animal", "Assault", "Burglary", "Explosion", "RoadAccidents"):
                row[f"valid_rows_{c}"] = mix[c]
            for kind in FOCUS:
                all_b = select(blocks_by_half[half], s, kind, "outputs")
                val_b = select(blocks_by_half[half], s, kind, "valid")
                row[f"gt_{kind}_all_rows"] = sum(b["n_gt"] for b in all_b)
                row[f"gt_{kind}_valid_rows"] = sum(b["n_gt"] for b in val_b)
                row[f"gt_{kind}_per_valid_row"] = r6(sum(b["n_gt"] for b in val_b) / len(val_b)) if val_b else None
            out.append(row)
    return out


# --- decomposition --------------------------------------------------------------------------------------------------

def duplicates(block: dict, vectors: dict) -> int:
    """Predicted items in one block whose cosine to an earlier item of that block is at least 0.85."""
    from evalv2.core.hashing import sha256_json

    texts = [sens_text(block["kind"], x) for x in block["model_rows"]]
    got = [vectors.get(sha256_json({"model": sens.EMBEDDER, "text": t})) for t in texts]
    if len(got) < 2 or any(v is None for v in got):
        return 0
    m = np.asarray(got, dtype=float)
    m = m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-9, None)
    sim = m @ m.T
    return sum(1 for i in range(1, len(got)) if sim[i, :i].max() >= 0.85)


def decomposition(blocks_by_half: dict, extras: dict) -> tuple[list, dict]:
    out, draws = [], {}
    for half, blocks in blocks_by_half.items():
        vectors = extras[half]["vectors"]
        for s in MODELS:
            for kind in KINDS:
                for view in VIEWS:
                    chosen = select(blocks, s, kind, view)
                    tp, fp, fn = pool(chosen)
                    draw = boot_draws(chosen, SEED if half == "dev" else SEED + 1)
                    draws[(half, s, kind, view)] = draw
                    lo, hi = sens.interval(draw) if draw is not None else (None, None)
                    scores = prf(tp, fp, fn)
                    per_row_fp = sorted((sens.counts(b, sens.FROZEN)[1] for b in chosen), reverse=True)
                    clip_tp = collections.Counter()
                    for b in chosen:
                        clip_tp[b["clip"]] += sens.counts(b, sens.FROZEN)[0]
                    clip_tp = +clip_tp
                    invalid_fn = sum(b["n_gt"] for b in chosen if b["outcome"] != "scored")
                    assigned = [a.similarity for b in chosen for a in sens.assign(b, -1.0)]
                    accepted = [v for v in assigned if v >= sens.FROZEN]
                    pred_words = [len(sens_text(kind, x).split()) for b in chosen for x in b["model_rows"]]
                    out.append({
                        "half": half, "model": SHORT[s], "kind": kind, "view": view,
                        "complete": not (half == "evaluation" and s == "super-direct"),
                        "rows": len(chosen), "clips": len({b["clip"] for b in chosen}), "gt_objects": tp + fn,
                        "predicted_objects": tp + fp, "tp": tp, "fp": fp, "fn": fn, "fn_from_invalid_rows": invalid_fn,
                        "precision": r6(scores["precision"]), "recall": r6(scores["recall"]), "f1": r6(scores["f1"]),
                        "f1_lo": r6(lo), "f1_hi": r6(hi), "macro_per_clip_f1": r6(macro_f1(chosen)),
                        "f1_repeat_1": r6(f1_of(select(blocks, s, kind, view, 1))),
                        "f1_repeat_2": r6(f1_of(select(blocks, s, kind, view, 2))),
                        "gt_per_row": r6((tp + fn) / len(chosen)) if chosen else None,
                        "pred_per_row": r6((tp + fp) / len(chosen)) if chosen else None,
                        "top5_rows_fp_share": r6(sum(per_row_fp[:5]) / fp) if fp else None,
                        "clips_with_tp": len(clip_tp), "top_clip_tp_share": r6(max(clip_tp.values()) / tp) if tp else None,
                        "near_duplicate_predictions": sum(duplicates(b, vectors) for b in chosen),
                        "median_accepted_similarity": r6(statistics.median(accepted)) if accepted else None,
                        "assigned_pairs": len(assigned), "assigned_below_tau": sum(v < sens.FROZEN for v in assigned),
                        "mean_pred_words": r6(statistics.mean(pred_words)) if pred_words else None})
    return out, draws


def no_output_gt(rows: dict, subject: str, kind: str) -> int:
    gts = gt_by_clip(rows)
    return sum(len(gts.get(r["incident_id"], {}).get(kind) or []) for k, r in rows.items()
               if k[0] == subject and r["outcome"] not in sens.MODEL_OUTPUT)


def gap_rows(blocks_by_half: dict, draws: dict, rows_by_half: dict) -> list:
    """The reported gap split into invalid handling and the like-for-like remainder, both orders, per model and kind."""
    dev, ev, out = blocks_by_half["dev"], blocks_by_half["evaluation"], []
    for s in MODELS:
        for kind in KINDS:
            a = pool(select(dev, s, kind, "valid"))
            a2 = pool(select(dev, s, kind, "outputs"))
            b = pool(select(ev, s, kind, "valid"))
            b2 = pool(select(ev, s, kind, "outputs"))
            lo, hi = sens.interval(draws[("evaluation", s, kind, "valid")] - draws[("dev", s, kind, "valid")])
            lo2, hi2 = sens.interval(draws[("evaluation", s, kind, "outputs")] - draws[("dev", s, kind, "outputs")])
            swap = swap_effects(a, b)
            pa, pb = prf(*a), prf(*b)
            planned_dev = planned_counts(select(dev, s, kind, "outputs"), no_output_gt(rows_by_half["dev"], s, kind))
            planned_c3 = planned_counts(select(ev, s, kind, "outputs"), no_output_gt(rows_by_half["evaluation"], s, kind))
            reported = f1(*b2) - f1(*a)
            handling = f1(*b2) - f1(*b)
            claim = dict(zip(FOCUS, C3_CLAIM[s], strict=True)).get(kind)
            out.append({
                "model": SHORT[s], "kind": kind, "c3_complete": s != "super-direct", "c3_claim": claim,
                "c3_claim_equals_exact_at_3dp": None if claim is None else round(f1(*b2), 3) == claim,
                "f1_source_dev_valid": r6(f1(*a)), "f1_dev_invalid_as_miss": r6(f1(*a2)),
                "f1_c3_valid": r6(f1(*b)), "f1_c3_reported_invalid_as_miss": r6(f1(*b2)),
                "f1_dev_all_planned": r6(f1(*planned_dev)),
                "f1_c3_all_planned": r6(f1(*planned_c3)) if s != "super-direct" else None,
                "reported_gap": r6(reported),
                "c3_invalid_handling_effect": r6(handling),
                "like_for_like_valid_gap": r6(f1(*b) - f1(*a)),
                "like_for_like_valid_gap_lo": r6(lo), "like_for_like_valid_gap_hi": r6(hi),
                "like_for_like_invalid_as_miss_gap": r6(f1(*b2) - f1(*a2)),
                "like_for_like_invalid_as_miss_gap_lo": r6(lo2), "like_for_like_invalid_as_miss_gap_hi": r6(hi2),
                "share_of_gap_from_invalid_handling": r6(handling / reported) if abs(reported) >= 0.01 else None,
                "precision_dev_valid": r6(pa["precision"]), "precision_c3_valid": r6(pb["precision"]),
                "recall_dev_valid": r6(pa["recall"]), "recall_c3_valid": r6(pb["recall"]),
                "f1_change_if_only_precision_moved": r6(swap["f1_c3_precision_only"] - f1(*a)),
                "f1_change_if_only_recall_moved": r6(swap["f1_c3_recall_only"] - f1(*a))})
    return out


def ladder(blocks_by_half: dict) -> list:
    """Step by step, from the slide's definition to C3's as reported; each step's effect is on the C3 side's F1."""
    dev, ev, out = blocks_by_half["dev"], blocks_by_half["evaluation"], []
    for s in MODELS:
        for kind in FOCUS:
            source = f1(*pool(select(dev, s, kind, "valid")))
            reported = f1(*pool(select(ev, s, kind, "outputs")))
            steps = [
                ("0 source: dev, valid only, micro, tau 0.40, both repeats", source, "dev"),
                ("1 C3 as reported: evaluation, invalid as miss, micro, tau 0.40, both repeats", reported, "evaluation"),
                ("2 same tau: replay at 0.40 from vectors (both sides already 0.40)", f1(*pool(select(ev, s, kind, "outputs"), 0.40)), "evaluation"),
                ("3 same matcher: unchanged solve_assignment (both sides already this)", f1(*pool(select(ev, s, kind, "outputs"))), "evaluation"),
                ("4 same aggregation: micro (both sides already micro)", f1(*pool(select(ev, s, kind, "outputs"))), "evaluation"),
                ("5 same repeats: both repeats (both sides already 2)", f1(*pool(select(ev, s, kind, "outputs"))), "evaluation"),
                ("6 same invalid handling: C3 valid only (the slide's rule)", f1(*pool(select(ev, s, kind, "valid"))), "evaluation"),
                ("6b other direction: dev invalid as miss (C3's rule)", f1(*pool(select(dev, s, kind, "outputs"))), "dev"),
                ("alt macro: dev valid, per-clip macro F1", macro_f1(select(dev, s, kind, "valid")), "dev"),
                ("alt macro: C3 valid, per-clip macro F1", macro_f1(select(ev, s, kind, "valid")), "evaluation"),
                ("alt repeat 1 only: dev valid", f1_of(select(dev, s, kind, "valid", 1)), "dev"),
                ("alt repeat 1 only: C3 valid", f1_of(select(ev, s, kind, "valid", 1)), "evaluation"),
                ("alt repeat 2 only: dev valid", f1_of(select(dev, s, kind, "valid", 2)), "dev"),
                ("alt repeat 2 only: C3 valid", f1_of(select(ev, s, kind, "valid", 2)), "evaluation")]
            previous = None
            for label, value, side in steps:
                out.append({"model": SHORT[s], "kind": kind, "step": label, "side": side, "c3_complete": s != "super-direct",
                            "f1": r6(value), "gap_to_source": r6(value - source) if value is not None else None,
                            "effect_vs_previous_step": r6(value - previous) if label[0] in "23456" and label[:2] != "6b"
                            else None})
                previous = value if label[0] in "12345" else previous
    return out


def object_rows(blocks_by_half: dict, rows_by_half: dict) -> list:
    """Object score (mean of entity F1 and pooled instrument+asset F1) in the three denominators, with clip intervals."""
    out = []
    for half, blocks in blocks_by_half.items():
        for s in MODELS:
            row = {"half": half, "model": SHORT[s], "c3_complete": not (half == "evaluation" and s == "super-direct")}
            for view, name in (("valid", "preregistered_conditional"), ("outputs", "chart_invalid_as_miss")):
                cells = {k: select(blocks, s, k, view) for k in KINDS}
                row[name] = r6(sens.object_score(*(pool(cells[k]) for k in KINDS)))
                clips = sorted({b["clip"] for b in cells["entities"]})
                index = {c: i for i, c in enumerate(clips)}
                tables = {k: np.zeros((len(clips), 3)) for k in KINDS}
                for k in KINDS:
                    for b in cells[k]:
                        tables[k][index[b["clip"]]] += sens.counts(b, sens.FROZEN)
                w = sens.resample_matrix(len(clips))
                draw = (sens.f1_array(w @ tables["entities"]) + sens.f1_array(w @ (tables["instruments"] + tables["assets"]))) / 2
                lo, hi = sens.interval(draw)
                row[f"{name}_lo"], row[f"{name}_hi"] = r6(lo), r6(hi)
            complete = row["c3_complete"]
            planned = {k: planned_counts(select(blocks, s, k, "outputs"), no_output_gt(rows_by_half[half], s, k)) for k in KINDS}
            row["preregistered_end_to_end"] = r6(sens.object_score(*(planned[k] for k in KINDS))) if complete else None
            out.append(row)
    return out


def row_mix(blocks: list) -> dict:
    return dict(collections.Counter(sens.category(b["clip"]) for b in blocks))


def common_keys(blocks: list, subjects: tuple) -> set:
    sets = [{(b["clip"], b["repeat"]) for b in blocks if b["subject"] == s and b["outcome"] == "scored"} for s in subjects]
    return set.intersection(*sets)


def closest_views(blocks_by_half: dict) -> list:
    """The nearest valid stand-ins for a same-clip comparison, which the disjoint split rules out."""
    dev, ev, out = blocks_by_half["dev"], blocks_by_half["evaluation"], []
    uniform = {c: 1.0 for c in ("Animal", "Assault", "Burglary", "Explosion", "RoadAccidents")}
    keys = {"dev": common_keys(dev, COMPLETE), "evaluation": common_keys(ev, COMPLETE)}
    for s in MODELS:
        for kind in KINDS:
            d, e = select(dev, s, kind, "valid"), select(ev, s, kind, "valid")
            row = {"model": SHORT[s], "kind": kind, "c3_complete": s != "super-direct",
                   "dev_valid": r6(f1(*pool(d))), "c3_valid": r6(f1(*pool(e))),
                   "dev_valid_without_top_fp_row": r6(f1_of(drop_top_fp_row(d))),
                   "c3_valid_without_top_fp_row": r6(f1_of(drop_top_fp_row(e))),
                   "c3_valid_at_dev_category_mix": r6(reweighted_f1(e, row_mix(d))),
                   "dev_valid_at_c3_category_mix": r6(reweighted_f1(d, row_mix(e))),
                   "dev_valid_equal_categories": r6(reweighted_f1(d, uniform)),
                   "c3_valid_equal_categories": r6(reweighted_f1(e, uniform))}
            for half, source in (("dev", d), ("c3", e)):
                name = "dev" if half == "dev" else "evaluation"
                chosen = [b for b in source if (b["clip"], b["repeat"]) in keys[name]] if s in COMPLETE else []
                row[f"{half}_common_valid_rows"] = len(chosen)
                row[f"{half}_common_valid_clips"] = len({b["clip"] for b in chosen})
                row[f"{half}_common_valid_f1"] = r6(f1(*pool(chosen))) if chosen else None
            out.append(row)
    return out


def categories(blocks_by_half: dict) -> list:
    out = []
    for half, blocks in blocks_by_half.items():
        for s in MODELS:
            for kind in FOCUS:
                for view in VIEWS:
                    chosen = select(blocks, s, kind, view)
                    for c in sorted({sens.category(b["clip"]) for b in chosen}):
                        part = [b for b in chosen if sens.category(b["clip"]) == c]
                        tp, fp, fn = pool(part)
                        out.append({"half": half, "model": SHORT[s], "kind": kind, "view": view, "category": c,
                                    "rows": len(part), "clips": len({b["clip"] for b in part}), "gt_objects": tp + fn,
                                    "tp": tp, "fp": fp, "fn": fn, "f1": r6(f1(tp, fp, fn)),
                                    "reportable": tp + fn >= 10})
    return out


def threshold_rows(blocks_by_half: dict) -> list:
    out = []
    for s in MODELS:
        for kind in FOCUS:
            for tau in TAU_GRID:
                row = {"model": SHORT[s], "kind": kind, "tau": tau, "c3_complete": s != "super-direct"}
                for half, blocks in blocks_by_half.items():
                    for view in VIEWS:
                        row[f"{half}_{view}_f1"] = r6(f1(*pool(select(blocks, s, kind, view), tau)))
                row["c3_minus_dev_valid"] = r6(row["evaluation_valid_f1"] - row["dev_valid_f1"])
                row["c3_minus_dev_invalid_as_miss"] = r6(row["evaluation_outputs_f1"] - row["dev_outputs_f1"])
                out.append(row)
    return out


def rank_rows(blocks_by_half: dict) -> list:
    out = []
    subjects = COMPLETE
    for kind in FOCUS:
        for half, blocks in blocks_by_half.items():
            for view in VIEWS:
                scores = {s: f1(*pool(select(blocks, s, kind, view))) for s in subjects}
                order = sorted(subjects, key=lambda s: -scores[s])
                out.append({"kind": kind, "half": half, "view": view, "models": "four complete models",
                            "order": " > ".join(SHORT[s] for s in order),
                            "scores": " ".join(f"{SHORT[s]}={scores[s]:.3f}" for s in order)})
    return out


def cross_kind(blocks_by_half: dict, extras: dict) -> list:
    """Unmatched GT items of one focus kind against predictions filed under the other kind (valid rows, diagnostic)."""
    from evalv2.core.hashing import sha256_json

    def vector(half: str, kind: str, item: dict):
        return extras[half]["vectors"].get(sha256_json({"model": sens.EMBEDDER, "text": sens_text(kind, item)}))

    out = []
    for half, blocks in blocks_by_half.items():
        by = {(b["subject"], b["clip"], b["repeat"], b["kind"]): b for b in blocks}
        for s in MODELS:
            for kind, other in (("instruments", "assets"), ("assets", "instruments")):
                missed = reachable = unknown = 0
                for b in select(blocks, s, kind, "valid"):
                    taken = {a.gt_index for a in sens.assign(b, sens.FROZEN)}
                    twin = by[(s, b["clip"], b["repeat"], other)]
                    for i, item in enumerate(b["gt_rows"]):
                        if i in taken:
                            continue
                        missed += 1
                        g = vector(half, kind, item)
                        cand = [vector(half, other, x) for x in twin["model_rows"]]
                        cand = [c for c in cand if c is not None]
                        if g is None or (twin["model_rows"] and not cand):
                            unknown += 1
                        elif cand and float(np.asarray(sens_matrix([g], cand)).max()) >= sens.FROZEN:
                            reachable += 1
                out.append({"half": half, "model": SHORT[s], "gt_kind": kind, "other_kind": other, "gt_missed_valid_rows": missed,
                            "reachable_in_other_kind_at_040": reachable, "vector_unavailable": unknown})
    return out


def sens_matrix(a: list, b: list):
    import matching

    return matching._cosine_similarity_matrix(a, b)  # noqa: SLF001


# --- salvage: a diagnostic, never a score ---------------------------------------------------------------------------

def artifact(run: str, ref: str):
    kind, digest = ref.split(":")
    path = R / run / "store" / "objects" / kind / digest[:2] / f"{digest}.json"
    return json.loads(path.read_text())["payload"] if path.exists() else None


def rejected_replies(rows: dict) -> list:
    """Every contract_invalid or parse_failure row with what its stored reply held: parsed object, or None."""
    checkpoints: dict = {}
    out = []
    for key, r in sorted(rows.items()):
        if r["outcome"] not in ("contract_invalid", "parse_failure"):
            continue
        run = r["_run"]
        if run not in checkpoints:
            checkpoints[run] = {(c["subject"], c["item_id"], int(c["repeat"])): c for c in jsonl(R / run / "checkpoint.jsonl")}
        c = checkpoints[run].get(key)
        stored = artifact(run, c["prediction_ref"]) if c and c.get("prediction_ref") else None
        raw = (stored or {}).get("raw")
        try:
            parsed = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            parsed = None
        codes = sorted({v.get("code") for v in ((stored or {}).get("validation") or {}).get("core_violations") or []})
        out.append({"key": key, "row": r, "parsed": parsed if isinstance(parsed, dict) else None, "codes": codes})
    return out


def rejected_items(entry: dict, kind: str) -> list:
    return [x for x in (entry["parsed"] or {}).get(kind) or [] if isinstance(x, dict) and sens_text(kind, x)]


def private_vectors() -> dict:
    path = PRIVATE / "extra-embeddings.jsonl"
    return {d["key"]: d["vector"] for d in jsonl(path)} if path.exists() else {}


def embed_missing() -> dict:
    """Local MiniLM on one thread, offline, for texts of rejected replies that no run's cache holds."""
    from evalv2.core.hashing import sha256_json

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    PRIVATE.mkdir(parents=True, exist_ok=True)
    have = private_vectors()
    todo: dict = {}
    stored_probe: list = []
    for half in HALVES:
        rows = sens.load_rows(HALVES[half])
        vectors = sens.load_vectors(HALVES[half])
        if not stored_probe:
            stored_probe = [(sens_text(k, x), x) for r in rows.values() if "ground_truth" in r for k in KINDS
                            for x in r["ground_truth"].get(k) or []][:25]
            probe_vectors = vectors
        for entry in rejected_replies(rows):
            for kind in KINDS:
                for item in rejected_items(entry, kind):
                    text = sens_text(kind, item)
                    key = sha256_json({"model": sens.EMBEDDER, "text": text})
                    if key not in vectors and key not in have:
                        todo[key] = text
        for r in rows.values():  # one-sided blocks were never embedded; the cross-kind and duplicate checks need them
            for side in ("prediction", "ground_truth"):
                for kind in KINDS:
                    for item in (r.get(side) or {}).get(kind) or []:
                        text = sens_text(kind, item)
                        key = sha256_json({"model": sens.EMBEDDER, "text": text})
                        if text and key not in vectors and key not in have:
                            todo[key] = text
    import torch

    torch.set_num_threads(1)
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(sens.EMBEDDER, device="cpu")
    texts = [t for t, _ in stored_probe]
    fresh = model.encode(texts, normalize_embeddings=False, batch_size=8, show_progress_bar=False)
    agreement = []
    for text, vec in zip(texts, fresh, strict=True):
        ref = probe_vectors.get(sha256_json({"model": sens.EMBEDDER, "text": text}))
        if ref is not None:
            agreement.append(float(np.dot(vec, ref) / (np.linalg.norm(vec) * np.linalg.norm(ref))))
    keys = sorted(todo)
    with (PRIVATE / "extra-embeddings.jsonl").open("a", encoding="utf-8") as handle:
        for i in range(0, len(keys), 16):
            part = keys[i:i + 16]
            for key, vec in zip(part, model.encode([todo[k] for k in part], normalize_embeddings=False, batch_size=16,
                                                   show_progress_bar=False).tolist(), strict=True):
                handle.write(json.dumps({"key": key, "vector": vec}) + "\n")
    return {"computed": len(keys), "probe_texts": len(agreement), "lowest_cosine_to_stored": min(agreement) if agreement else None}


def salvage_rows(rows_by_half: dict, blocks_by_half: dict, extras: dict) -> tuple[list, dict]:
    """DIAGNOSTIC ONLY. Replies the contract rejected are parsed and re-matched; unparseable ones stay misses."""
    import matching
    from evalv2.core.hashing import sha256_json

    out, notes = [], {}
    for half, rows in rows_by_half.items():
        vectors = extras[half]["vectors"]
        gts = gt_by_clip(rows)
        replies = rejected_replies(rows)
        notes[half] = {}
        for s in MODELS:
            mine = [e for e in replies if e["key"][0] == s]
            tally = collections.Counter()
            for e in mine:
                tally["parsed" if e["parsed"] else "unparseable"] += 1
                for code in e["codes"]:
                    tally[code] += 1
            notes[half][SHORT[s]] = dict(tally)
            for kind in KINDS:
                tp, fp, fn = pool(select(blocks_by_half[half], s, kind, "valid"))
                missing = 0
                for e in mine:
                    gt = gts.get(e["key"][1], {}).get(kind) or []
                    items = rejected_items(e, kind)
                    if not items or not gt:
                        fp, fn = fp + len(items), fn + len(gt)
                        continue
                    got = [vectors.get(sha256_json({"model": sens.EMBEDDER, "text": sens_text(kind, x)})) for x in [*items, *gt]]
                    if any(v is None for v in got):
                        missing += 1
                        fp, fn = fp + len(items), fn + len(gt)
                        continue
                    n = len(items)
                    hits = len(matching.solve_assignment(sens_matrix(got[:n], got[n:]).tolist(), threshold=sens.FROZEN))
                    tp, fp, fn = tp + hits, fp + n - hits, fn + len(gt) - hits
                scores = prf(tp, fp, fn)
                out.append({"half": half, "model": SHORT[s], "kind": kind, "tp": tp, "fp": fp, "fn": fn,
                            "precision": r6(scores["precision"]), "recall": r6(scores["recall"]), "f1": r6(scores["f1"]),
                            "rejected_replies": len(mine), "rejected_replies_parsed": tally["parsed"],
                            "blocks_missing_a_vector": missing, "status": "diagnostic, not a score"})
    return out, notes


# --- examples -------------------------------------------------------------------------------------------------------

def pair_records(block: dict) -> list:
    """Every assigned or unassigned item of one block, with similarity, outcome and text (private use only)."""
    id_field = sens.ID_FIELD[block["kind"]]
    base = {"subject": block["subject"], "clip": block["clip"], "repeat": block["repeat"], "kind": block["kind"],
            "row_outcome": block["outcome"]}
    records = []
    matrix = np.asarray(block["matrix"]) if block["matrix"] is not None else None
    pairs = sens.assign(block, -1.0)
    used_p, used_g = {a.index for a in pairs}, {a.gt_index for a in pairs}
    for a in pairs:
        p, g = block["model_rows"][a.index], block["gt_rows"][a.gt_index]
        records.append({**base, "gt_id": g[id_field], "pred_id": p[id_field], "similarity": round(a.similarity, 4),
                        "match": "tp" if a.similarity >= sens.FROZEN else "fp_fn_below_tau",
                        "gt_text": sens_text(block["kind"], g), "pred_text": sens_text(block["kind"], p)})
    for i, p in enumerate(block["model_rows"]):
        if i not in used_p:
            best = float(matrix[i].max()) if matrix is not None else None
            records.append({**base, "gt_id": None, "pred_id": p[id_field], "similarity": r6(best), "match": "fp_unassigned",
                            "gt_text": None, "pred_text": sens_text(block["kind"], p)})
    for j, g in enumerate(block["gt_rows"]):
        if j not in used_g:
            best = float(matrix[:, j].max()) if matrix is not None else None
            kind = "fn_rejected_row" if block["outcome"] != "scored" else "fn_unassigned"
            records.append({**base, "gt_id": g[id_field], "pred_id": None, "similarity": r6(best), "match": kind,
                            "gt_text": sens_text(block["kind"], g), "pred_text": None})
    return records


def salvage_records(entry: dict, kind: str, gt: list, vectors: dict) -> list:
    """Assignments a rejected reply would have got: read as evidence of what the empty-prediction rule discarded."""
    import matching
    from evalv2.core.hashing import sha256_json

    items = rejected_items(entry, kind)
    if not items or not gt:
        return []
    got = [vectors.get(sha256_json({"model": sens.EMBEDDER, "text": sens_text(kind, x)})) for x in [*items, *gt]]
    if any(v is None for v in got):
        return []
    n = len(items)
    id_field = sens.ID_FIELD[kind]
    subject, clip, repeat = entry["key"]
    return [{"subject": subject, "clip": clip, "repeat": repeat, "kind": kind, "row_outcome": entry["row"]["outcome"],
             "gt_id": gt[a.gt_index][id_field], "pred_id": items[a.index].get(id_field), "similarity": round(a.similarity, 4),
             "match": "discarded_by_contract_would_match", "codes": entry["codes"],
             "gt_text": sens_text(kind, gt[a.gt_index]), "pred_text": sens_text(kind, items[a.index])}
            for a in matching.solve_assignment(sens_matrix(got[:n], got[n:]).tolist(), threshold=sens.FROZEN)]


def example_candidates(rows_by_half: dict, blocks_by_half: dict, extras: dict) -> list:
    """All real records of the four named cells; a seeded draw per side and match class (hand-classified afterwards)."""
    picked = []
    for s, kind in EXAMPLE_CELLS:
        for half, blocks in blocks_by_half.items():
            records = [x for b in select(blocks, s, kind, "outputs") for x in pair_records(b)]
            vectors = extras[half]["vectors"]
            gts = gt_by_clip(rows_by_half[half])
            for e in rejected_replies(rows_by_half[half]):
                if e["key"][0] == s:
                    records += salvage_records(e, kind, gts.get(e["key"][1], {}).get(kind) or [], vectors)
            groups = collections.defaultdict(list)
            for x in records:
                groups[x["match"]].append(x)
            for match, members in sorted(groups.items()):
                members.sort(key=lambda x: (x["clip"], x["repeat"], str(x["gt_id"]), str(x["pred_id"])))
                rng = random.Random(f"{EXAMPLE_SEED}-{s}-{kind}-{half}-{match}")
                for x in rng.sample(members, min(6, len(members))):
                    picked.append({"cell": f"{SHORT[s]} {kind}", "half": half, "pool_size": len(members), **x})
    picked += cross_kind_records("qwen35-9b-openrouter", blocks_by_half, extras)  # appended: earlier ids stay stable
    return picked


def cross_kind_records(subject: str, blocks_by_half: dict, extras: dict) -> list:
    """Missed GT instruments whose closest prediction was filed as an asset, at or above 0.40, in valid rows."""
    from evalv2.core.hashing import sha256_json

    out = []
    for half, blocks in blocks_by_half.items():
        vectors = extras[half]["vectors"]
        by = {(b["clip"], b["repeat"]): b for b in select(blocks, subject, "assets", "valid")}

        def vec(kind: str, item: dict, vectors: dict = vectors):
            return vectors[sha256_json({"model": sens.EMBEDDER, "text": sens_text(kind, item)})]

        for b in select(blocks, subject, "instruments", "valid"):
            taken = {a.gt_index for a in sens.assign(b, sens.FROZEN)}
            twin = by[(b["clip"], b["repeat"])]
            for i, gt in enumerate(b["gt_rows"]):
                if i in taken or not twin["model_rows"]:
                    continue
                sims = sens_matrix([vec("instruments", gt)], [vec("assets", x) for x in twin["model_rows"]])[0]
                best = int(np.argmax(sims))
                if sims[best] >= sens.FROZEN:
                    other = twin["model_rows"][best]
                    out.append({"cell": f"{SHORT[subject]} instruments", "half": half, "pool_size": None,
                                "subject": subject, "clip": b["clip"], "repeat": b["repeat"], "kind": "instruments",
                                "row_outcome": b["outcome"], "gt_id": gt["instrument_id"], "pred_id": other["asset_id"],
                                "similarity": round(float(sims[best]), 4), "match": "fn_filed_under_other_kind",
                                "gt_text": sens_text("instruments", gt), "pred_text": sens_text("assets", other)})
    return out


CLASSES = ("genuine prediction difference", "synonym or semantic-matching", "GT mismatch", "category ambiguity",
           "duplicate or hallucinated", "different evaluated clip", "scoring difference", "unresolved")
PRIVATE_HEADER = """# Private examples: real saved records, GT and prediction text (never commit)

The splits are disjoint, so no GT object appears on both sides. Rows sharing a group are parallel examples, not the same
object. Classes are one AI reader's, from stored text only; no frame was opened.

| Group | Cell | Half | Clip | Row outcome | GT object | Prediction | Similarity | Match outcome | Class |
|---|---|---|---|---|---|---|---|---|---|"""


# --- commands -------------------------------------------------------------------------------------------------------

def audit() -> dict:
    rows_by_half, blocks_by_half, extras = {}, {}, {}
    for half in HALVES:
        rows_by_half[half], blocks_by_half[half], extras[half] = load_half(half)
    source, super_note = source_figures(blocks_by_half["dev"])
    write_csv("source_figures.csv", source)
    write_csv("provenance.csv", provenance())
    write_csv("populations.csv", populations(rows_by_half))
    write_csv("outcomes_and_valid_subsets.csv", outcome_mix(rows_by_half, blocks_by_half))
    decomposed, draws = decomposition(blocks_by_half, extras)
    write_csv("decomposition.csv", decomposed)
    write_csv("gap_attribution.csv", gap_rows(blocks_by_half, draws, rows_by_half))
    write_csv("object_scores.csv", object_rows(blocks_by_half, rows_by_half))
    write_csv("harmonisation_ladder.csv", ladder(blocks_by_half))
    write_csv("closest_views.csv", closest_views(blocks_by_half))
    write_csv("category_cells.csv", categories(blocks_by_half))
    write_csv("threshold_by_view.csv", threshold_rows(blocks_by_half))
    write_csv("rankings.csv", rank_rows(blocks_by_half))
    write_csv("cross_kind.csv", cross_kind(blocks_by_half, extras))
    salvage, notes = salvage_rows(rows_by_half, blocks_by_half, extras)
    write_csv("salvage_diagnostic.csv", salvage)
    checks = replay_checks(blocks_by_half)
    ids = split_ids()
    summary = {"checks": checks, "super_before_recovery": super_note, "rejected_replies": notes,
               "split": {"dev": len(ids["dev"]), "evaluation": len(ids["evaluation"]),
                         "overlap": len(set(ids["dev"]) & set(ids["evaluation"]))},
               "row_audit": {h: extras[h]["audit"] for h in HALVES},
               "common_valid_items": {h: len(common_keys(blocks_by_half[h], COMPLETE)) for h in HALVES},
               "bootstrap": {"seed": SEED, "resamples": RESAMPLES, "unit": "clip"},
               "inputs_sha256": {"track-a-report.json": hashlib.sha256(REPORT.read_bytes()).hexdigest()[:16],
                                 "split-v2.json": sens.sha256(sens.SPLIT_FILE)[:16]}}
    (OUT / "replay.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def examples() -> dict:
    rows_by_half, blocks_by_half, extras = {}, {}, {}
    for half in HALVES:
        rows_by_half[half], blocks_by_half[half], extras[half] = load_half(half)
    picked = example_candidates(rows_by_half, blocks_by_half, extras)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    for i, x in enumerate(picked, 1):
        x["candidate_id"] = f"X{i:03d}"
    (PRIVATE / "example-candidates.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in picked),
                                                      encoding="utf-8")
    labels_path = PRIVATE / "example-labels.json"
    if labels_path.exists():
        labels = json.loads(labels_path.read_text())
        by_id = {x["candidate_id"]: x for x in picked}
        index, lines = [], [PRIVATE_HEADER]
        for label in labels:
            x = by_id[label["candidate_id"]]
            if label["class"] not in CLASSES:
                raise ValueError(label)
            index.append({"group": label["group"], "cell": x["cell"], "half": x["half"],
                          "run_side": "source dev run" if x["half"] == "dev" else "C3 run", "clip": x["clip"],
                          "repeat": x["repeat"], "row_outcome": x["row_outcome"], "gt_id": x["gt_id"], "pred_id": x["pred_id"],
                          "similarity": x["similarity"], "match_outcome": x["match"], "pool_size": x["pool_size"],
                          "class": label["class"], "labelled_by": "one AI reader, stored text only"})
            lines.append(f"| {label['group']} | {x['cell']} | {x['half']} | {x['clip']} r{x['repeat']} | {x['row_outcome']} | "
                         f"{x['gt_text'] or '-'} | {x['pred_text'] or '-'} | {x['similarity']} | {x['match']} | {label['class']} |")
        write_csv("examples_index.csv", index)
        (PRIVATE / "examples.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"candidates": len(picked)}


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "audit"
    result = {"embed": embed_missing, "audit": audit, "examples": examples}[command]()
    print(json.dumps(result, indent=1, sort_keys=True, default=str)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
