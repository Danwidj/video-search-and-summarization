# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Final comparison: efficiency and EXPLORATORY subgroups (offline). Not part of the frozen primary family.

    python3 scripts/v2_final_comparison_extras.py OUT_DIR

Subgroups use the frozen paired method on each subset; Holm runs over all subgroup tests of a metric. Small subgroups
are descriptive only. Runs are read, never written.
"""

from __future__ import annotations

import collections
import csv
import importlib.util
import json
import re
import statistics as st
import sys
from pathlib import Path

R = Path("/home/hengz/evalv2-data/v2/runs")
V = "final-comparison-vss-nano"
DIRECT = ("c3-track-a-switchyard", "c3-track-a-switchyard-recovery", "c3-track-a-switchyard-recovery-a5a")
FROZEN = Path("/home/hengz/vss-wt-final/deploy/docker/developer-profiles/dev-profile-incident/eval/scripts/v2_final_comparison_analysis.py")
MANIFEST = Path(__file__).resolve().parents[1] / "eval_reproducibility" / "dataset-manifest-v1.json"
spec = importlib.util.spec_from_file_location("fa", FROZEN)
fa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fa)
fa.N = 2000


def pct(v: list, q: float) -> float | None:
    v = sorted(v)
    return round(v[min(len(v) - 1, int(q * (len(v) - 1) + .5))], 2) if v else None


def attempts(run: str) -> list:
    return [json.loads(x) for x in (R / run / "attempts.jsonl").read_text().splitlines()]


def efficiency() -> tuple[list, list]:
    vss = attempts(V)
    direct = [a for run in DIRECT for a in attempts(run) if a["subject"] == "nano-direct"]
    rows = []
    for name, data, ok in (("VSS final (Nano-only, no person tracking)", vss, "answered"), ("Direct Nano (stored C3)", direct, "ok")):
        lat_ok = [a["latency_ms"] / 1000 for a in data if a["outcome"] == ok and a.get("latency_ms") is not None]
        lat_all = [a["latency_ms"] / 1000 for a in data if a.get("latency_ms") is not None]
        tok = []
        for a in data:
            if a["outcome"] != ok:
                continue
            t = a.get("tokens") or {}
            tok.append(t["total"] if "total" in t else sum(v.get("tokens") or 0 for v in t.values() if isinstance(v, dict)))
        c = collections.Counter(a["outcome"] for a in data)
        rows.append({"config": name, "attempts": len(data), **{f"outcome_{k}": v for k, v in sorted(c.items())}, "answered": len(lat_ok),
                     "tokens_median": pct(tok, .5), "tokens_p95": pct(tok, .95), "tokens_total_answered": sum(tok),
                     "latency_p50_answered_s": pct(lat_ok, .5), "latency_p95_answered_s": pct(lat_ok, .95),
                     "latency_p50_all_s": pct(lat_all, .5), "latency_p95_all_s": pct(lat_all, .95)})
    stages = collections.defaultdict(lambda: [0, 0, 0])
    for a in vss:
        if a["outcome"] == "answered":
            for s, v in (a.get("tokens") or {}).items():
                if isinstance(v, dict):
                    stages[s][0] += v.get("tokens") or 0
                    stages[s][1] += v.get("attempts") or 0
                    stages[s][2] += 1
    return rows, [{"stage": s, "tokens_total": v[0], "calls_total": v[1], "runs_with_stage": v[2], "tokens_per_answered_run": round(v[0] / sum(a["outcome"] == "answered" for a in vss), 1)} for s, v in sorted(stages.items())]


def subgroups() -> list:
    direct: dict = {}
    for run in DIRECT:
        for r in fa.run_rows(R / run):
            if r["subject"] != "nano-direct" or r.get("stage", "p1") != "p1":
                continue
            k = (r["incident_id"], r["repeat"])
            if k not in direct or direct[k]["outcome"] not in fa.MODEL_OUTPUT:
                direct[k] = r
    vss = {(r["incident_id"], r["repeat"]): r for r in fa.run_rows(R / V) if r.get("stage") == "final"}
    ctx, zoom, track = {}, {}, {}
    for a in attempts(V):
        if a["outcome"] != "answered":
            continue
        h = a["response_ref"].split(":")[1]
        b = json.loads((R / V / "store/objects/vss-response" / h[:2] / f"{h}.json").read_text())["payload"]["body"]
        k = (a["item_id"], a["repeat"])
        ctx[k] = bool((b["experiment"].get("caption") or {}).get("context_sent"))
        zoom[k] = sum(1 for e in b.get("evidence") or [] if e.get("name_before") or e.get("description_before"))
        track[k] = int((b.get("object_tracking") or {}).get("tracked") or 0)
    dur = {c["incident_id"]: float(c["duration_seconds"]) for c in json.loads(MANIFEST.read_text())["clips"]}
    ref = {r["incident_id"]: {k: len(r["ground_truth"][k]) for k in fa.KINDS} for r in [*direct.values(), *vss.values()]}
    planned = [(c, rep) for c in sorted({k[0] for k in direct}) for rep in (1, 2)]
    objs = sorted(sum(ref[c].values()) for c in ref)
    t1, t2 = objs[len(objs) // 3], objs[2 * len(objs) // 3]
    ds = sorted(dur[c] for c in ref)
    d1, d2 = ds[len(ds) // 3], ds[2 * len(ds) // 3]

    def label(key: tuple) -> dict:
        c = key[0]
        n = sum(ref[c].values())
        return {"category": re.match(r"[A-Za-z]+", c).group(0), "duration": "short" if dur[c] <= d1 else "mid" if dur[c] <= d2 else "long",
                "gt_objects": "few" if n <= t1 else "mid" if n <= t2 else "many", "captions_reached_p1": str(ctx.get(key, "no VSS output")),
                "names_changed_by_zoom": ("no VSS output" if key not in zoom else "yes" if zoom[key] else "no"),
                "object_tracking_ran": ("no VSS output" if key not in track else "yes" if track[key] else "no")}

    groups: dict = collections.defaultdict(list)
    for k in planned:
        for dim, val in label(k).items():
            groups[(dim, val)].append(k)
    out = []
    for (dim, val), keys in sorted(groups.items()):
        valid = [k for k in keys if k in vss and k in direct and vss[k]["outcome"] == "scored" and direct[k]["outcome"] == "scored"]

        def e2e_type(ks):
            return fa.mean([fa.type_ok(vss.get(k)) for k in ks]), fa.mean([fa.type_ok(direct.get(k)) for k in ks])

        def e2e_obj(ks):
            return (fa.pooled([fa.counts(vss.get(k), ref[k[0]]) for k in ks])["object_score"], fa.pooled([fa.counts(direct.get(k), ref[k[0]]) for k in ks])["object_score"])

        def sev(ks):
            p = [(fa.sev_error(vss[k]), fa.sev_error(direct[k])) for k in ks]
            p = [x for x in p if None not in x]
            return fa.mean([x[0] for x in p]), fa.mean([x[1] for x in p])

        for metric, res in (("type_e2e", fa.boot(keys, e2e_type)), ("object_score_e2e", fa.boot(keys, e2e_obj)), ("severity_mae_valid", fa.boot(valid, sev) if len(valid) > 1 else {"pairs": len(valid), "clips": 0})):
            out.append({"dimension": dim, "subgroup": val, "metric": metric, "pairs": res.get("pairs"), "clips": res.get("clips"), "vss": res.get("a"), "direct": res.get("b"), "diff": res.get("diff"),
                        "ci_low": (res.get("ci95") or [None, None])[0], "ci_high": (res.get("ci95") or [None, None])[1], "p": res.get("p")})
    for metric in ("type_e2e", "object_score_e2e", "severity_mae_valid"):
        idx = [i for i, r in enumerate(out) if r["metric"] == metric and r["p"] is not None and r["subgroup"] != "no VSS output"]
        for i, h in zip(idx, fa.holm([out[i]["p"] for i in idx]), strict=True):
            out[i]["p_holm_within_metric"] = h
    return out


def write(p: Path, rows: list) -> None:
    cols: list = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    o = Path(sys.argv[1])
    o.mkdir(parents=True, exist_ok=True)
    e, s = efficiency()
    write(o / "final_efficiency.csv", e)
    write(o / "final_stage_tokens.csv", s)
    g = subgroups()
    write(o / "final_subgroups.csv", g)
    print(json.dumps(e, indent=0)[:1400])
    print(s)
    for r in g:
        if r.get("p") is not None and (r.get("p_holm_within_metric") or 1) < .2 or (r.get("ci_low") or -1) > 0 or (r.get("ci_high") or 1) < 0:
            print(r)
