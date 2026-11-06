# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""EXPLORATORY post-hoc threshold sensitivity for incident descriptions. The frozen 0.50 pass rule is unchanged.

    uv run --frozen python scripts/v2_description_threshold_sensitivity.py

Offline and read-only: stored score rows and judge caches only, no model or judge call. Repo outputs hold ids and
scores; anything with description text goes to the private directory. Super is the frozen 26-row snapshot (the
c3-track-a-switchyard and -recovery runs), labelled incomplete; later A5-s output is deliberately not read.
"""

from __future__ import annotations

import collections
import csv
import glob
import json
import os
import random
import re
import statistics as st
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL))

R = Path("/home/hengz/evalv2-data/v2/runs")
OUT = EVAL / "methodology" / "description-threshold-sensitivity"
PRIVATE = Path("/home/hengz/evalv2-data/v2/diagnostics/description-threshold")
THRESHOLDS = (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70)
FROZEN = 0.50
MODELS = {"nano-direct": "Cosmos 3 Nano", "omni-direct": "Nemotron 3 Nano Omni", "gemma4-31b-openrouter": "Gemma 4 31B",
          "qwen35-9b-openrouter": "Qwen3.5-9B", "super-direct": "Cosmos 3 Super (INCOMPLETE snapshot)"}
COMPLETE = tuple(s for s in MODELS if s != "super-direct")
RUNS = ("c3-track-a-switchyard", "c3-track-a-switchyard-recovery", "c3-track-a-switchyard-recovery-a5a", "c3-track-a-openrouter")
MODEL_OUTPUT = ("scored", "contract_invalid", "parse_failure")
SEED, RESAMPLES = 20261027, 5000
PLANNED = 110
STRATA = ((0.0, 0.1, 12), (0.2, 0.2, 6), (0.3, 0.3, 12), (0.4, 0.4, 14), (0.45, 0.55, 99), (0.6, 0.6, 14), (0.65, 0.75, 6),
          (0.8, 0.85, 8), (0.9, 1.0, 5))


def category(clip: str) -> str:
    return re.match(r"[A-Za-z]+", clip).group(0)


def passes(score: float, threshold: float) -> bool:
    return score >= threshold


def load_rows() -> dict:
    rows: dict = {}
    for run in RUNS:
        path = R / run / "scoring/evalv2-score-stage-v3/primary/live-videos.jsonl"
        for line in path.read_text().splitlines():
            r = json.loads(line)
            if r.get("stage", "p1") != "p1" or r["subject"] not in MODELS:
                continue
            key = (r["subject"], r["incident_id"], r["repeat"])
            if key not in rows or rows[key]["outcome"] not in MODEL_OUTPUT:
                r["_run"] = run
                rows[key] = r
    return rows


def judged(rows: dict) -> list:
    out = []
    for (subject, clip, repeat), r in sorted(rows.items()):
        if r["outcome"] != "scored":
            continue
        d = r["incident_field_scores"].get("description") or {}
        out.append({"subject": subject, "clip": clip, "repeat": repeat, "run": r["_run"], "category": category(clip),
                    "score": d.get("score"), "frozen_pass": d.get("pass"), "judged": bool(d.get("judged")),
                    "error": d.get("error"), "expected": d.get("expected"), "predicted": d.get("predicted"),
                    "type_pass": bool((r["incident_field_scores"].get("type") or {}).get("pass"))})
    return out


def rate(items: list, threshold: float) -> float | None:
    return sum(passes(x["score"], threshold) for x in items) / len(items) if items else None


def bootstrap(items_by_subject: dict, seed: int = SEED, n: int = RESAMPLES) -> dict:
    """Clip-cluster bootstrap, one resample of clips shared by all models: rate CIs and rank frequencies."""
    clips = sorted({x["clip"] for v in items_by_subject.values() for x in v})
    by = {s: collections.defaultdict(list) for s in items_by_subject}
    for s, v in items_by_subject.items():
        for x in v:
            by[s][x["clip"]].append(x["score"])
    rnd = random.Random(seed)
    draws: dict = {(s, t): [] for s in items_by_subject for t in THRESHOLDS}
    top: dict = {t: collections.Counter() for t in THRESHOLDS}
    for _ in range(n):
        pick = [clips[rnd.randrange(len(clips))] for _ in clips]
        for t in THRESHOLDS:
            cur = {}
            for s in items_by_subject:
                vals = [v for c in pick for v in by[s].get(c, [])]
                if vals:
                    cur[s] = sum(v >= t for v in vals) / len(vals)
                    draws[(s, t)].append(cur[s])
            ranked = [s for s in cur if s in COMPLETE]
            if ranked:
                top[t][max(ranked, key=lambda s: cur[s])] += 1
    ci = {}
    for k, v in draws.items():
        v.sort()
        ci[k] = (v[int(.025 * len(v))], v[int(.975 * len(v)) - 1])
    return {"ci": ci, "top": top, "n": n}


def write(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols: list = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def repeatability(items: list) -> dict:
    """Identical (GT, prediction) pairs that hold verdicts from more than one run's cache: incident descriptions only."""
    from evalv2.tasks import judges as jm

    registry = jm.load_judges()
    spec = next(j for j in (registry.judges.values() if hasattr(registry, "judges") else registry) if j.id == "openrouter-gpt-oss-20b-c3-v1")
    identity = jm.judge_identity(spec, "incident")
    cache: dict = collections.defaultdict(dict)
    for run in (*RUNS, "c3-track-b-contingency-nano-grounding"):
        for p in glob.glob(str(R / run / "scoring/judge-cache/*.incident.jsonl")):
            for line in open(p):
                e = json.loads(line)
                cache[e["key"]][run] = e["score"]
    all_multi = sum(len(v) > 1 for v in cache.values())
    all_flip = sum(len({s >= FROZEN for s in v.values()}) > 1 for v in cache.values() if len(v) > 1)
    pairs = {}
    for x in items:
        if x["score"] is None:
            continue
        pairs.setdefault(identity.key(x["expected"], x["predicted"]), x)
    rows = []
    for key, x in pairs.items():
        scores = cache.get(key, {})
        if len(scores) > 1:
            v = list(scores.values())
            rows.append({"subject": x["subject"], "clip": x["clip"], "runs": len(v), "min": min(v), "max": max(v), "range": round(max(v) - min(v), 3),
                         **{f"flip_{t:.2f}": len({s >= t for s in v}) > 1 for t in THRESHOLDS}})
    return {"rows": rows, "all_judge_pairs_multi": all_multi, "all_judge_pairs_flip_050": all_flip, "unique_description_pairs": len(pairs),
            "cache": cache, "identity": identity}


def review_sample(items: list, seed: int = 20261105) -> tuple[list, list]:
    """A blinded stratified set: unique pairs, spread over models and categories; returns (sheet, key)."""
    rnd = random.Random(seed)
    seen, unique = set(), []
    for x in sorted((i for i in items if i["score"] is not None), key=lambda i: (i["clip"], i["subject"], i["repeat"])):
        k = (x["expected"], x["predicted"])
        if k not in seen:
            seen.add(k)
            unique.append(x)
    chosen = []
    for lo, hi, want in STRATA:
        pool = [x for x in unique if lo <= x["score"] <= hi]
        rnd.shuffle(pool)
        groups = collections.defaultdict(list)
        for x in pool:
            groups[(x["subject"], x["category"])].append(x)
        keys = sorted(groups)
        rnd.shuffle(keys)
        got = []
        while len(got) < min(want, len(pool)):
            for k in keys:
                if groups[k] and len(got) < want:
                    got.append(groups[k].pop())
        chosen += got
    rnd.shuffle(chosen)
    sheet, key = [], []
    for i, x in enumerate(chosen, 1):
        rid = f"R{i:03d}"
        sheet.append({"review_id": rid, "ground_truth_description": x["expected"], "generated_description": x["predicted"],
                      "central_event_correct(yes/no)": "", "contradiction_or_hallucination(none/minor/major)": "",
                      "essential_omission(none/minor/major)": "", "overall_acceptable(yes/no/cannot_tell)": "", "notes": ""})
        key.append({"review_id": rid, "subject": x["subject"], "clip": x["clip"], "repeat": x["repeat"], "category": x["category"], "score": x["score"]})
    return sheet, key


def main() -> int:
    rows = load_rows()
    items = judged(rows)
    scored = [x for x in items if x["score"] is not None]
    by = {s: [x for x in scored if x["subject"] == s] for s in MODELS}
    boot = bootstrap(by)
    pm = []
    for s, name in MODELS.items():
        v = by[s]
        final = collections.Counter(r["outcome"] for k, r in rows.items() if k[0] == s)
        for t in THRESHOLDS:
            n = sum(passes(x["score"], t) for x in v)
            lo, hi = boot["ci"][(s, t)]
            pm.append({"model": name, "subject": s, "status": "incomplete snapshot" if s == "super-direct" else "complete", "threshold": t,
                       "frozen_threshold": t == FROZEN, "valid_outputs": final["scored"], "judged": len(v), "unjudged_valid": final["scored"] - len(v),
                       "planned": PLANNED, "passing": n, "pass_rate_valid": round(n / len(v), 4), "ci95_low": round(lo, 4), "ci95_high": round(hi, 4),
                       "change_pp_vs_050": round(100 * (rate(v, t) - rate(v, FROZEN)), 1), "pass_rate_of_planned": round(n / PLANNED, 4)})
    ranks = {}
    for t in THRESHOLDS:
        order = sorted(COMPLETE, key=lambda s: -rate(by[s], t))
        ranks[t] = order
        for r in pm:
            if r["threshold"] == t and r["subject"] in COMPLETE:
                r["rank_complete_models"] = order.index(r["subject"]) + 1
                r["bootstrap_share_ranked_first"] = round(boot["top"][t][r["subject"]] / boot["n"], 3)
    write(OUT / "per_model_pass_rates.csv", pm)
    per = [{k: x[k] for k in ("subject", "clip", "repeat", "run", "category", "score", "frozen_pass", "type_pass")} |
           {f"pass_{t:.2f}": (passes(x["score"], t) if x["score"] is not None else "") for t in THRESHOLDS} for x in items]
    write(OUT / "per_description_scores.csv", per)
    flips = []
    for s, name in MODELS.items():
        v = by[s]
        f = [x for x in v if 0.40 <= x["score"] < FROZEN]
        flips.append({"model": name, "judged": len(v), "fail_to_pass_050_to_040": len(f), "of_which_type_correct": sum(x["type_pass"] for x in f),
                      "scores_035_to_055": sum(0.35 <= x["score"] <= 0.55 for x in v), "scores_exactly_040": sum(x["score"] == 0.4 for x in v),
                      "scores_045_to_049": sum(0.45 <= x["score"] < 0.5 for x in v), "scores_050_to_055": sum(0.5 <= x["score"] <= 0.55 for x in v),
                      "mean": round(st.mean(x["score"] for x in v), 3), "median": st.median(x["score"] for x in v)})
    write(OUT / "fail_to_pass_050_to_040.csv", flips)
    cat = []
    for s, name in MODELS.items():
        for c in sorted({x["category"] for x in by[s]}):
            v = [x for x in by[s] if x["category"] == c]
            cat.append({"model": name, "category": c, "judged": len(v), "pass_050": sum(x["score"] >= .5 for x in v), "pass_040": sum(x["score"] >= .4 for x in v),
                        "rate_050": round(rate(v, .5), 3), "rate_040": round(rate(v, .4), 3), "small_sample": len(v) < 20})
    write(OUT / "category_breakdown.csv", cat)
    common = [(c, r) for c in sorted({x["clip"] for x in scored}) for r in (1, 2)
              if all(any(x["clip"] == c and x["repeat"] == r for x in by[s]) for s in COMPLETE)]
    com = []
    for s in COMPLETE:
        v = [x for x in by[s] if (x["clip"], x["repeat"]) in set(common)]
        com.append({"model": MODELS[s], "n": len(v), **{f"rate_{t:.2f}": round(rate(v, t), 3) for t in THRESHOLDS}})
    write(OUT / "common_valid_set_rates.csv", com)
    rep = repeatability(scored)
    rr = rep["rows"]
    summary = {"unique_description_pairs": rep["unique_description_pairs"], "pairs_with_repeat_verdicts": len(rr),
               "score_differs": sum(x["range"] > 0 for x in rr), "range_mean": round(st.mean(x["range"] for x in rr), 3) if rr else None, "range_max": max((x["range"] for x in rr), default=None),
               "flip_rate_by_threshold": {f"{t:.2f}": {"flips": sum(x[f"flip_{t:.2f}"] for x in rr), "rate": round(sum(x[f"flip_{t:.2f}"] for x in rr) / len(rr), 3)} for t in THRESHOLDS} if rr else {},
               "all_kinds_pairs_multi": rep["all_judge_pairs_multi"], "all_kinds_flip_050": rep["all_judge_pairs_flip_050"]}
    write(OUT / "judge_repeatability_pairs.csv", rr)
    sheet, key = review_sample(scored)
    write(PRIVATE / "blinded_review_sample.csv", sheet)
    write(PRIVATE / "review_key_DO_NOT_SHARE_WITH_REVIEWERS.csv", key)
    near = sorted((x for x in scored if 0.35 <= x["score"] <= 0.55), key=lambda x: (x["score"], x["subject"], x["clip"]))
    write(PRIVATE / "near_cutoff_texts.csv", [{k: x[k] for k in ("subject", "clip", "repeat", "score", "type_pass", "expected", "predicted")} for x in near])
    out = {"ranks": {f"{t:.2f}": [MODELS[s] for s in o] for t, o in ranks.items()}, "repeatability": summary, "common_pairs": len(common), "common_clips": len({c for c, _ in common}),
           "review_sample": {"n": len(sheet), "score_bands": collections.Counter(str(k["score"]) for k in key).most_common(), "subjects": collections.Counter(k["subject"] for k in key).most_common(),
                             "categories": collections.Counter(k["category"] for k in key).most_common()},
           "unjudged": [(x["subject"], x["clip"], x["repeat"], x["error"]) for x in items if x["score"] is None]}
    (OUT / "summary.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps(out, indent=0)[:2800])
    return 0


if __name__ == "__main__":
    sys.exit(main())
