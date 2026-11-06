# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""C3 final analysis (offline, read-only): the pre-registered views, kept apart by provenance.

    uv run --frozen python scripts/v2_c3_final_report.py OUT.json

Blocks: ORIGINAL C3 (Track A Switchyard runs combined in the pre-registered order, Track A OpenRouter, Track B
historical); HISTORICAL (A5-b, V1 Super re-scored, 1 repeat); CONTINGENCY (Track B with Nano grounding). Uses
`scripts/v2_c3_analysis.py` (the pre-tested functions) unchanged; a run's judged scores when present, else its
offline scores. Paired Nano - Super is on items both answered validly; Holm across the three primary metrics.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("c3a", HERE / "v2_c3_analysis.py")
c3a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c3a)
R = Path("/home/hengz/evalv2-data/v2/runs")
LIVE = "scoring/evalv2-score-stage-v3/primary/live-videos.jsonl"
OFF = "scoring/evalv2-score-stage-v3/primary/offline-videos.jsonl"


def score_path(run: Path) -> str:
    return LIVE if (run / LIVE).exists() else OFF


def rows(runs, stage):
    """combined_rows over runs, each read from its judged file if it exists (else offline)."""
    out = {}
    for run in runs:
        c3a.SCORE = score_path(run)
        for r in c3a.combined_rows([run], stage):
            k = (r["subject"], r["incident_id"], r["repeat"])
            old = out.get(k)
            if old is None or old["outcome"] not in c3a.MODEL_OUTPUT:
                out[k] = r
    return list(out.values())


def summary(runs, stage, repeats):
    """summarise() with each run's own score file (judged if present)."""
    merged = rows(runs, stage)
    tmp = R / "c3" / "_final_tmp"
    tmp.mkdir(exist_ok=True)
    (tmp / "scoring/evalv2-score-stage-v3/primary").mkdir(parents=True, exist_ok=True)
    (tmp / OFF).write_text("".join(json.dumps(r) + "\n" for r in merged))
    c3a.SCORE = OFF
    return c3a.summarise([tmp], stage, "test", repeats), merged


def paired_block(merged, a, b, rows_b=None):
    ra = [r for r in merged if r["subject"] == a]
    rb = rows_b if rows_b is not None else [r for r in merged if r["subject"] == b]
    p = c3a.paired(ra, rb)
    metrics = [m for m in ("type_accuracy", "severity_mae", "object_score") if p.get(m)]
    adj = c3a.holm([p[m]["p"] for m in metrics]) if metrics else []
    for m, h in zip(metrics, adj, strict=True):
        p[m]["p_holm"] = h
    return p


def main() -> int:
    out = {"labels": {"original": "ORIGINAL C3 (pre-registered; A1-A5 amendments)",
                      "historical": "V1 HISTORICAL observation re-scored (A5-b): NOT a C3 run",
                      "contingency": "CONTINGENCY profile (A5-B): NOT the pre-registered Track B"}}
    sw = [R / n for n in ("c3-track-a-switchyard", "c3-track-a-switchyard-recovery", "c3-track-a-switchyard-recovery-a5a",
                          "c3-track-a-switchyard-recovery-a5s") if (R / n / "checkpoint.jsonl").exists()]
    s_sw, m_sw = summary(sw, "p1", 2)
    s_or, m_or = summary([R / "c3-track-a-openrouter"], "p1", 2)
    out["original_track_a"] = {"runs": [p.name for p in sw] + ["c3-track-a-openrouter"], "summaries": {**s_sw, **s_or}}
    out["original_paired_nano_minus_super"] = paired_block(m_sw, "nano-direct", "super-direct")
    s_v1, m_v1 = summary([R / "a5b-v1-super-rescore"], "p1", 1)
    out["historical_v1_super"] = s_v1
    nano_r1 = [dict(r) for r in m_sw if r["subject"] == "nano-direct" and r["repeat"] == 1]
    out["sensitivity_nano_rep1_minus_v1_super"] = paired_block(nano_r1, "nano-direct", None,
                                                               rows_b=[r for r in m_v1])
    tb = [R / n for n in ("c3-track-b-historical", "c3-track-b-historical-recovery") if (R / n / "checkpoint.jsonl").exists()]
    for stage in ("p1", "final"):
        out[f"original_track_b_{stage}"] = summary(tb, stage, 1)[0]
        out[f"contingency_track_b_{stage}"] = summary([R / "c3-track-b-contingency-nano-grounding"], stage, 1)[0]
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n")
    print(json.dumps({"written": sys.argv[1], "runs_track_a_switchyard": [p.name for p in sw]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
