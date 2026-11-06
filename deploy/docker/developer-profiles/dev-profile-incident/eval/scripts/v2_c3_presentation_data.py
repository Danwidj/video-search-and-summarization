# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Presentation data (offline, read-only on runs): every CSV/JSON is computed from scored files, nothing is typed in.

    cd <frozen A5 eval checkout> && uv run --frozen python <this script> OUT_DIR

Run from the frozen A5 checkout so `aggregate` and the scorer are the pinned ones. Provenance labels: original-C3,
contingency (A5-B), historical-V1 (A5-b), development. Denominators always stated; Super rows flagged incomplete.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.getcwd())
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("c3a", HERE / "v2_c3_analysis.py")
c3a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c3a)

from evalv2.datasets.ground_truth import load_gt_v1, load_gt_v1_sheets  # noqa: E402
from evalv2.tasks.incident_objects import v1  # noqa: E402
from evalv2.tasks.incident_objects.aggregate import aggregate  # noqa: E402
from evalv2.tasks.incident_objects.scoring import score_video  # noqa: E402

R = Path("/home/hengz/evalv2-data/v2/runs")
ROOT = "/home/hengz/evalv2-data"
LIVE, OFF = "scoring/evalv2-score-stage-v3/primary/live-videos.jsonl", "scoring/evalv2-score-stage-v3/primary/offline-videos.jsonl"
SPLIT = json.loads(Path(f"{ROOT}/ground_truth/ground-truth-v1.0/split-v2.json").read_text())
CATEGORY = {c: cat for cat, h in SPLIT["by_category"].items() for half in ("dev", "test") for c in h[half]}
KINDS = ("entities", "instruments", "assets")
SW = ["c3-track-a-switchyard", "c3-track-a-switchyard-recovery", "c3-track-a-switchyard-recovery-a5a",
      "c3-track-a-switchyard-recovery-a5s"]


class _NoJudge:
    def __call__(self, *a, **k):
        raise RuntimeError("no judge needed for an empty prediction")


def merged(runs, stage):
    out = {}
    for name in runs:
        run = R / name
        if not (run / "checkpoint.jsonl").exists():
            continue
        c3a.SCORE = LIVE if (run / LIVE).exists() else OFF
        for r in c3a.combined_rows([run], stage):
            k = (r["subject"], r["incident_id"], r["repeat"])
            if k not in out or out[k]["outcome"] not in c3a.MODEL_OUTPUT:
                out[k] = r
    return list(out.values())


def complete_a1(rows, sheets, gt):
    """The A1 item has no score block: an invalid output scores as a miss, computed from an empty prediction."""
    store = v1.gt_store(dict(sheets))
    for r in rows:
        if r.get("amendment") == "A1":
            clip, key = r["incident_id"], f"{r['subject']}#{r['repeat']}"
            v1.put_prediction(store, clip, key, v1.empty_prediction())
            entry = gt["by_incident_id"][clip]
            scored = score_video(store, clip, key, similarity=lambda *a: [], judge=_NoJudge(),
                                 out_of_taxonomy=v1.is_out_of_taxonomy({"ground_truth": entry["p1_shaped"]}))
            r.update(ground_truth=entry["p1_shaped"], prediction=v1.empty_prediction(), **scored)
    return rows


def write_csv(path, rows):
    keys = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def field(c, name):
    x = c["fields"][name]
    ci = x.get("ci95") or [None, None]
    acc = None if x.get("accuracy") is None else round(x["accuracy"], 4)
    return {f"{name}_acc": acc, f"{name}_ci_lo": ci[0], f"{name}_ci_hi": ci[1], f"{name}_n": x.get("n")}


def views(rows, planned, split):
    """The pre-registered views with clip-cluster CIs: valid-only type and severity, and end-to-end over all planned."""
    half = "test" if split.startswith("test") else "dev"
    clips = [c for h in SPLIT["by_category"].values() for c in h[half]]
    got = {(r["incident_id"], r["repeat"]): r for r in rows}
    reps = planned // len(clips)
    grid = [(c, k, got.get((c, k))) for c in clips for k in range(1, reps + 1)]

    def t_ok(r):
        return 1.0 if r and r["outcome"] == "scored" and (r["incident_field_scores"].get("type") or {}).get("pass") else 0.0

    def sev(r):
        x = (r or {}).get("incident_field_scores", {}).get("severity_level") or {}
        return None if x.get("expected") is None or x.get("predicted") is None else abs(float(x["predicted"]) - float(x["expected"]))
    valid = [r for r in rows if r["outcome"] == "scored"]
    clip = lambda r: r["incident_id"]  # noqa: E731
    tv = c3a.ratio(valid, clip, t_ok, lambda r: 1.0 if (r["incident_field_scores"].get("type") or {}).get("expected") else 0.0)
    sv = c3a.ratio(valid, clip, lambda r: sev(r) or 0.0, lambda r: 1.0 if sev(r) is not None else 0.0)
    et = c3a.ratio(grid, lambda x: x[0], lambda x: t_ok(x[2]), lambda x: 1.0)
    us = c3a.ratio(grid, lambda x: x[0], lambda x: 1.0 if x[2] and x[2]["outcome"] == "scored" and sev(x[2]) is not None and sev(x[2]) <= 1 else 0.0, lambda x: 1.0)
    vr = c3a.ratio(grid, lambda x: x[0], lambda x: 1.0 if x[2] and x[2]["outcome"] == "scored" else 0.0, lambda x: 1.0)
    flat = {}
    for name, m in (("type_valid", tv), ("severity_mae_valid2", sv), ("e2e_type_of_planned", et), ("usable_severity_of_planned", us), ("contract_valid_of_planned", vr)):
        ci = m["ci95"] or [None, None]
        flat.update({name: m["value"], f"{name}_n": m["denominator"], f"{name}_ci_lo": ci[0], f"{name}_ci_hi": ci[1]})
    return flat


def d1_row(label, prov, split, planned, subject, rows, stage):
    a = aggregate(rows)
    c, t, s = a["continuity_v1"], a["timestamps"], a["severity"]
    sev = c["severity"]
    valid = sum(1 for r in rows if r["outcome"] == "scored")
    outputs = sum(1 for r in rows if r["outcome"] in c3a.MODEL_OUTPUT)
    return {"config": label, "provenance": prov, "split": split, "subject": subject, "stage": stage, "planned": planned,
            "rows": len(rows), "model_outputs": outputs, "contract_valid": valid,
            "contract_valid_rate_of_planned": round(valid / planned, 4), "no_output": planned - outputs,
            **field(c, "type"), **field(c, "severity_level"), **field(c, "description"),
            **field(c, "start_timestamp"), **field(c, "end_timestamp"),
            "severity_mae_valid": sev.get("mae"), "severity_exact_valid": sev.get("exact"),
            "severity_n_valid": s.get("n") or round((sev.get("coverage") or 0) * (sev.get("attempted") or 0)),
            "start_mae_s": t["start_timestamp"]["mean_abs_error_s"], "start_median_s": t["start_timestamp"]["median_abs_error_s"],
            "end_mae_s": t["end_timestamp"]["mean_abs_error_s"], "end_median_s": t["end_timestamp"]["median_abs_error_s"],
            "window_iou": t["window_iou"]["mean"], "window_iou_n": t["window_iou"]["n"], **views(rows, planned, split)}


def d2_rows(label, prov, split, subject, rows, stage):
    a = aggregate(rows)["continuity_v1"]["items"]
    out = []
    for kind in KINDS:
        x = a[kind]
        out.append({"config": label, "provenance": prov, "split": split, "subject": subject, "stage": stage, "kind": kind,
                    "tp": x["tp"], "fp": x["fp"], "fn": x["fn"], "precision": round(x["precision"], 4),
                    "recall": round(x["recall"], 4), "f1": round(x["f1"], 4)})
    c = {k: a[k] for k in KINDS}
    ent = c["entities"]
    tp, fp, fn = (sum(c[k][m] for k in ("instruments", "assets")) for m in ("tp", "fp", "fn"))
    obj = c3a._f1(tp, fp, fn)
    out.append({"config": label, "provenance": prov, "split": split, "subject": subject, "stage": stage,
                "kind": "object_score (mean of entity F1 and pooled instrument+asset F1)", "tp": ent["tp"] + tp, "fp": ent["fp"] + fp,
                "fn": ent["fn"] + fn, "precision": None, "recall": None, "f1": round((ent["f1"] + obj) / 2, 4)})
    return out


def d2_category(label, prov, subject, rows):
    per = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    for r in rows:
        if r["outcome"] not in ("scored", "contract_invalid", "parse_failure"):
            continue
        for k in KINDS:
            cc = r[k]["counts"]
            acc = per[CATEGORY[r["incident_id"]]][k]
            acc[0] += cc["tp"]
            acc[1] += cc["fp"]
            acc[2] += cc["fn"]
    return [{"config": label, "provenance": prov, "subject": subject, "category": cat, "kind": k, "tp": v[0], "fp": v[1], "fn": v[2],
             "f1": round(c3a._f1(*v), 4)} for cat, kinds in sorted(per.items()) for k, v in kinds.items()]


def pair_row(name, prov, split, a, b, note):
    p = c3a.paired(a, b)
    row = {"comparison": name, "provenance": prov, "split": split, "paired_items": p.get("paired_items"), "clips": p.get("clips"), "note": note}
    ps = [p[m]["p"] for m in ("type_accuracy", "severity_mae", "object_score") if p.get(m)]
    adj = c3a.holm(ps) if ps else []
    for i, m in enumerate(m for m in ("type_accuracy", "severity_mae", "object_score") if p.get(m)):
        row.update({f"{m}_diff": p[m]["diff"], f"{m}_ci_lo": p[m]["ci95"][0], f"{m}_ci_hi": p[m]["ci95"][1],
                    f"{m}_p": p[m]["p"], f"{m}_p_holm": adj[i]})
    return row


def main() -> int:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    sheets, gt = load_gt_v1_sheets(data_root=ROOT), load_gt_v1(data_root=ROOT)
    a_rows = complete_a1(merged(SW, "p1"), sheets, gt) + merged(["c3-track-a-openrouter"], "p1")
    by = defaultdict(list)
    for r in a_rows:
        by[r["subject"]].append(r)
    v1rows = merged(["a5b-v1-super-rescore"], "p1")
    cont_p1, cont_final = merged(["c3-track-b-contingency-nano-grounding"], "p1"), merged(["c3-track-b-contingency-nano-grounding"], "final")
    orig_b = merged(["c3-track-b-historical", "c3-track-b-historical-recovery"], "final")
    dev_a = merged(["c1a", "c1a-recovery"], "p1") + merged(["c1e-openrouter-gemma4-31b"], "p1") + merged(["c1f-openrouter-qwen35-9b"], "p1")
    dev_b_final, dev_b_p1 = merged(["c1b"], "final"), merged(["c1b"], "p1")
    d1, d2, d2c = [], [], []
    for s in ("nano-direct", "super-direct", "omni-direct", "gemma4-31b-openrouter", "qwen35-9b-openrouter"):
        label = "Track A direct VLM, frozen P1 v4"
        prov = "original-C3 (INCOMPLETE: Super outage)" if s == "super-direct" else "original-C3"
        d1.append(d1_row(label, prov, "test-55", 110, s, by[s], "p1"))
        d2 += d2_rows(label, prov, "test-55", s, by[s], "p1")
        d2c += d2_category(label, prov, s, by[s])
    d1.append(d1_row("V1 Stage 3 C1 direct Super, re-scored", "historical-V1 (A5-b): NOT C3", "test-55", 55, "super-direct-v1-historical", v1rows, "p1"))
    d2 += d2_rows("V1 Stage 3 C1 direct Super, re-scored", "historical-V1 (A5-b): NOT C3", "test-55", "super-direct-v1-historical", v1rows, "p1")
    for stage, rows in (("p1", cont_p1), ("final", cont_final)):
        lab = "Track B CONTINGENCY: historical agent, Nano grounding, tracking off"
        d1.append(d1_row(lab, "contingency (A5-B): NOT pre-registered Track B", "test-55", 55, "nano-pipeline-nanoground", rows, stage))
        d2 += d2_rows(lab, "contingency (A5-B): NOT pre-registered Track B", "test-55", "nano-pipeline-nanoground", rows, stage)
    for s in ("nano-direct", "super-direct", "omni-direct", "gemma4-31b-openrouter", "qwen35-9b-openrouter"):
        rows = [r for r in dev_a if r["subject"] == s]
        if rows:
            d1.append(d1_row("Track A pilot", "development", "dev-25", 50, s, rows, "p1"))
            d2 += d2_rows("Track A pilot", "development", "dev-25", s, rows, "p1")
    for s in ("nano-pipeline", "super-pipeline"):
        for stage, src in (("p1", dev_b_p1), ("final", dev_b_final)):
            rows = [r for r in src if r["subject"] == s]
            if rows:
                d1.append(d1_row("Track B pilot C1b (historical profile, Super grounding)", "development", "dev-25", 25, s, rows, stage))
                d2 += d2_rows("Track B pilot C1b (historical profile, Super grounding)", "development", "dev-25", s, rows, stage)
    write_csv(out / "d1_incident_extraction.csv", d1)
    write_csv(out / "d2_object_identification.csv", d2)
    write_csv(out / "d2_object_f1_by_category.csv", d2c)

    def rep(rows, n):
        return [r for r in rows if r["repeat"] == n]
    nano = by["nano-direct"]
    pairs = [
        pair_row("Nano direct - Super direct (pre-registered primary; INCOMPLETE: Super 50/110)", "original-C3", "test-55", nano, by["super-direct"], "Holm across 3 metrics; A - B on items both valid"),
        pair_row("Nano direct (repeat 1) - Super V1 historical (sensitivity)", "original-C3 vs historical-V1", "test-55", rep(nano, 1), v1rows, "NOT the pre-registered comparison"),
        pair_row("VSS contingency final - Nano direct repeat 1", "contingency vs original-C3", "test-55", cont_final, rep(nano, 1), "VSS minus direct; VSS arm is Nano-only contingency"),
        pair_row("VSS contingency final - Nano direct repeat 2", "contingency vs original-C3", "test-55", cont_final, [dict(r, repeat=1) for r in rep(nano, 2)], "sensitivity to the direct repeat"),
        pair_row("VSS contingency P1 stage - Nano direct repeat 1 (captions effect)", "contingency vs original-C3", "test-55", cont_p1, rep(nano, 1), "captions in VSS P1, before zoom"),
        pair_row("VSS contingency final - VSS contingency P1 stage (zoom effect)", "contingency", "test-55", cont_final, cont_p1, "within-run, same P1 reply"),
    ]
    for s, d in (("nano", "nano-direct"), ("super", "super-direct")):
        da = [r for r in dev_a if r["subject"] == d and r["repeat"] == 1]
        pairs.append(pair_row(f"VSS C1b final - {s} direct C1a repeat 1", "development", "dev-25", [r for r in dev_b_final if r["subject"] == f"{s}-pipeline"], da, "VSS minus direct on dev; Super grounding"))
        pairs.append(pair_row(f"VSS C1b final - VSS C1b P1 stage ({s}, zoom effect)", "development", "dev-25", [r for r in dev_b_final if r["subject"] == f"{s}-pipeline"], [r for r in dev_b_p1 if r["subject"] == f"{s}-pipeline"], "within-run"))
    write_csv(out / "vlm_vs_vss_paired.csv", pairs)
    (out / "row_counts.json").write_text(json.dumps({"track_a": {k: len(v) for k, v in by.items()}, "v1": len(v1rows), "contingency_final": len(cont_final),
                                                     "original_track_b_final": len(orig_b), "dev_a": len(dev_a), "dev_b_final": len(dev_b_final)}, indent=1))
    print(json.dumps({"written": str(out), "d1": len(d1), "d2": len(d2), "pairs": len(pairs)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
