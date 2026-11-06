# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Master results table for the presentation package, generated only from methodology/presentation/data/.

    python3 scripts/v2_c3_presentation_master.py DATA_DIR OUT_MD

Writes DATA_DIR/master_results.csv and OUT_MD. Nothing is typed in by hand except labels: every number is read from a
chart-data file, so a re-run after new data changes the table and nothing else. Baselines are reported as levels; a
Difference appears only where a paired analysis exists.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

COLS = ("Dimension", "Metric", "Baseline", "Final / Latest", "Model", "Dataset / N", "Difference", "CI / Significance",
        "Evidence status", "Source")
D1, D2, D3, D4, D5, D6 = ("1 Incident Extraction", "2 Object Identification", "3 Evidence Crops", "4 Chatbot Querying",
                          "5 AI Dashboard", "6 Model Efficiency")
NOT_PAIRED = "not computed (no paired analysis)"
V1 = "super-direct-v1-historical"
NAMES = {"nano-direct": "Cosmos 3 Nano, direct P1 v4 (original C3)",
         "super-direct": "Cosmos 3 Super, direct P1 v4 (original C3, INCOMPLETE)",
         "omni-direct": "Nemotron 3 Nano Omni, direct P1 v4 (original C3)",
         "gemma4-31b-openrouter": "Gemma 4 31B, direct P1 v4 (original C3)",
         "qwen35-9b-openrouter": "Qwen3.5-9B, direct P1 v4 (original C3)",
         "nano-pipeline-nanoground": "VSS Nano-only CONTINGENCY, final stage (historical agent, tracking off)"}


def f(x, n=3):
    if x in (None, ""):
        return "n/a"
    v = float(x)
    return f"{v:.{n}f}"


def ci(lo, hi):
    return f"95% CI [{f(lo)}, {f(hi)}]" if lo not in (None, "") else "no CI"


def load(d: Path, name: str) -> list:
    p = d / name
    return list(csv.DictReader(p.open())) if p.exists() else []


def status(subject: str) -> str:
    if subject == "super-direct":
        return "incomplete"
    return "final (contingency)" if "nanoground" in subject else "final"


def d1_rows(d: Path) -> list:
    rows = load(d, "d1_incident_extraction.csv")
    held = {(r["subject"], r["stage"]): r for r in rows if r["split"] == "test-55"}
    base = held[(V1, "p1")]
    out = []
    specs = (("Contract-valid output rate (of planned)", "contract_valid_of_planned", True),
             ("Type accuracy, valid outputs only", "type_valid", True),
             ("Type accuracy, end to end (failures are misses)", "e2e_type_of_planned", True),
             ("Severity MAE, valid outputs only (lower is better)", "severity_mae_valid2", True),
             ("Usable severity rate, end to end", "usable_severity_of_planned", True))
    for label, key, _ in specs:
        for subject, name in NAMES.items():
            stage = "final" if "nanoground" in subject else "p1"
            r = held.get((subject, stage))
            if r is None or r.get(key) in (None, ""):
                continue
            n = r.get(f"{key}_n") or r["planned"]
            out.append({"Dimension": D1, "Metric": label,
                        "Baseline": f"{f(base.get(key))} (V1 Super, historical re-score, n={float(base.get(f'{key}_n') or 0):.0f})",
                        "Final / Latest": f(r[key]), "Model": name,
                        "Dataset / N": f"55 test clips (previously exposed); n={float(n):.0f} of {r['planned']} planned",
                        "Difference": NOT_PAIRED, "CI / Significance": ci(r.get(f"{key}_ci_lo"), r.get(f"{key}_ci_hi")),
                        "Evidence status": status(subject),
                        "Source": f"data/d1_incident_extraction.csv:{subject}/{stage}/{key}"})
    return out


def d2_rows(d: Path) -> list:
    names = {"nano-direct": NAMES["nano-direct"], "omni-direct": NAMES["omni-direct"], "super-direct": NAMES["super-direct"],
             "gemma4-31b-openrouter": NAMES["gemma4-31b-openrouter"], "qwen35-9b-openrouter": NAMES["qwen35-9b-openrouter"]}
    labels = {"object_score": "Object score", "entities_f1": "Entity F1", "instruments_f1": "Instrument F1", "assets_f1": "Asset F1"}
    out = []
    for r in load(d, "d2_object_views.csv"):
        if r["view"] == "mixed_chart":
            continue
        for key, label in labels.items():
            out.append({"Dimension": D2, "Metric": f"{label} ({r['view'].replace('_', ' ')})", "Baseline": "see V1 row in d2_object_identification.csv",
                        "Final / Latest": f(r[key]), "Model": names[r["subject"]],
                        "Dataset / N": f"55 test clips; {r['valid_runs']} valid of 110 planned", "Difference": NOT_PAIRED,
                        "CI / Significance": "pooled count; no CI", "Evidence status": status(r["subject"]),
                        "Source": f"data/d2_object_views.csv:{r['subject']}/{r['view']}/{key}"})
    return out


def final_rows(d: Path) -> list:
    p = d / "final_comparison_v1.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    out = []
    for fam, status_ in (("primary", "final, separately frozen, not original C3"), ("secondary", "descriptive, separately frozen")):
        for k, v in data[fam].items():
            ci_ = v.get("ci95") or [None, None]
            out.append({"Dimension": D1 if k.startswith(("type", "severity", "start", "end", "description")) else D2, "Metric": f"Final comparison: {k}",
                        "Baseline": f"{v.get('b')} (direct Nano, stored C3)", "Final / Latest": f"{v.get('a')} (VSS final, Nano-only, no person tracking)",
                        "Model": "Cosmos 3 Nano in every slot", "Dataset / N": f"55 test clips, 2 repeats; {v.get('pairs')} pairs", "Difference": v.get("diff"),
                        "CI / Significance": f"{ci(ci_[0], ci_[1])}; p={v.get('p')}; Holm p={v.get('p_holm')}", "Evidence status": status_,
                        "Source": f"data/final_comparison_v1.json:{fam}.{k}"})
    return out


def desc_rows(d: Path) -> list:
    p = d.parent.parent / "description-threshold-sensitivity" / "per_model_pass_rates.csv"
    out = []
    for r in (list(csv.DictReader(p.open())) if p.exists() else []):
        if r["threshold"] == "0.5":
            out.append({"Dimension": D1, "Metric": "Description pass, valid outputs (frozen 0.50; provisional judge)", "Baseline": "no comparable baseline",
                        "Final / Latest": f"{r['passing']}/{r['judged']} = {float(r['pass_rate_valid']):.3f}", "Model": r["model"], "Dataset / N": f"55 test clips; {r['judged']} judged of {r['planned']} planned",
                        "Difference": NOT_PAIRED, "CI / Significance": ci(r["ci95_low"], r["ci95_high"]), "Evidence status": "provisional AI-judged" + ("; incomplete" if r["status"] != "complete" else ""),
                        "Source": f"description-threshold-sensitivity/per_model_pass_rates.csv:{r['subject']}"})
    return out


def paired_rows(d: Path) -> list:
    out = []
    for r in load(d, "vlm_vs_vss_paired.csv"):
        dim = D1
        for key, label in (("type_accuracy", "Paired type accuracy"), ("severity_mae", "Paired severity MAE"),
                           ("object_score", "Paired object score")):
            if r.get(f"{key}_diff") in (None, ""):
                continue
            prov = r["provenance"]
            st = ("provisional (development)" if prov == "development" else
                  "incomplete" if "INCOMPLETE" in r["comparison"] else
                  "final (contingency)" if "contingency" in prov else "final (historical sensitivity)")
            sig = f"{ci(r[f'{key}_ci_lo'], r[f'{key}_ci_hi'])}"
            if r.get(f"{key}_p_holm") not in (None, ""):
                sig += f"; Holm p={f(r[f'{key}_p_holm'])}"
            elif r.get(f"{key}_p") not in (None, ""):
                sig += f"; p={f(r[f'{key}_p'])} (unadjusted)"
            out.append({"Dimension": D2 if key == "object_score" else dim, "Metric": f"{label}: {r['comparison']}",
                        "Baseline": "see comparison", "Final / Latest": "see comparison", "Model": r["comparison"],
                        "Dataset / N": f"{r['split']}; {r['paired_items']} paired items", "Difference": f(r[f"{key}_diff"], 4),
                        "CI / Significance": sig, "Evidence status": st,
                        "Source": f"data/vlm_vs_vss_paired.csv:{r['comparison']}/{key}"})
    return out


def d3_rows(d: Path) -> list:
    rows = load(d, "d3_evidence_crops.csv")
    out = []
    for r in rows:
        out.append({"Dimension": D3, "Metric": r["metric"], "Baseline": r.get("baseline") or "no baseline",
                    "Final / Latest": r["value"], "Model": r["subject"], "Dataset / N": r["dataset_n"],
                    "Difference": r.get("difference") or NOT_PAIRED, "CI / Significance": r.get("ci") or "no CI",
                    "Evidence status": r["status"], "Source": r["source"]})
    return out


def d4_rows(d: Path) -> list:
    out = []
    want = {"exact_answer_accuracy": "Exact-answer accuracy", "judged_contradiction_rate": "Contradiction with GT (AI-judged)",
            "judged_unsupported_claim_rate": "Unsupported-claim rate (AI-judged)", "citation_precision": "Citation precision",
            "citation_recall": "Citation recall", "refusal_recall": "Refusal recall",
            "false_refusal_rate": "False-refusal rate", "retrieval_recall_at_5": "Retrieval recall@5"}
    for r in load(d, "d4_chat.csv"):
        if r["tier"] != "all" or r["metric"] not in want:
            continue
        cont = r["corpus"] == "system"
        out.append({"Dimension": D4, "Metric": want[r["metric"]], "Baseline": "no template-mode baseline was scored",
                    "Final / Latest": f(r["value"]),
                    "Model": f"Nemotron 3 Ultra grounded chat, {r['corpus']} corpus" + (" (CONTINGENCY Nano reports)" if cont else ""),
                    "Dataset / N": f"119 test questions; n={r['n']} for this metric; answered {r['answered']}/{r['planned']}",
                    "Difference": NOT_PAIRED, "CI / Significance": ci(r.get("ci_low"), r.get("ci_high")),
                    "Evidence status": ("provisional AI-judged" if "AI-judged" in want[r["metric"]] else "final (AI references)")
                    + (", contingency" if cont else ""), "Source": f"data/d4_chat.csv:{r['corpus']}/all/{r['metric']}"})
    return out


def d5_rows(d: Path) -> list:
    out = []
    for r in load(d, "d5_dashboard.csv"):
        if r.get("denominator") and r.get("numerator"):
            val = f"{r['numerator']}/{r['denominator']} = {f(r['value'])}"
        else:
            val = r["value"]
        out.append({"Dimension": D5, "Metric": r["metric"], "Baseline": "no held-out baseline", "Final / Latest": val,
                    "Model": "Nemotron 3 Ultra, Ask for a chart", "Dataset / N": "75 test requests (references ai_proposed; deterministic figures)",
                    "Difference": NOT_PAIRED, "CI / Significance": ci(r.get("ci_low"), r.get("ci_high")),
                    "Evidence status": "final", "Source": f"data/d5_dashboard.csv:{r['metric']}"})
    return out


def d6_rows(d: Path) -> list:
    out = []
    for r in load(d, "d6_efficiency.csv"):
        st = "incomplete" if r["subject"] in ("super-direct", "super-pipeline", "nano-pipeline") else (
            "final (contingency)" if "contingency" in r["group"] else "final")
        n = f"{r['attempts_total']} attempts; {r['valid_outputs']} valid"
        for label, key in (("Latency p50 s, answered", "latency_s_p50_answered"), ("Latency p95 s, all attempts", "latency_s_p95_all"),
                           ("Tokens per answered attempt, median", "tokens_median_answered"),
                           ("Attempts per valid output (derived)", "derived_attempts_per_valid_output"),
                           ("Measured cost USD", "measured_cost_usd")):
            if r.get(key) in (None, ""):
                continue
            out.append({"Dimension": D6, "Metric": label, "Baseline": "no comparable baseline", "Final / Latest": r[key],
                        "Model": f"{r['subject']} ({r['group']})", "Dataset / N": n, "Difference": NOT_PAIRED,
                        "CI / Significance": "descriptive", "Evidence status": st,
                        "Source": f"data/d6_efficiency.csv:{r['group']}/{r['subject']}/{key}"})
    return out


def main() -> int:
    d, md = Path(sys.argv[1]), Path(sys.argv[2])
    rows = d1_rows(d) + desc_rows(d) + d2_rows(d) + final_rows(d) + d3_rows(d) + d4_rows(d) + d5_rows(d) + d6_rows(d) + paired_rows(d)
    rows.sort(key=lambda r: r["Dimension"])
    with (d / "master_results.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    lines = ["# Master results table", "",
             "Generated by `scripts/v2_c3_presentation_master.py` from `data/`; do not edit by hand. "
             f"{len(rows)} rows. Baselines are levels; a Difference appears only where a paired analysis exists.", "",
             "| " + " | ".join(COLS) + " |", "|" + "---|" * len(COLS)]
    lines += ["| " + " | ".join(str(r[c]).replace("|", "/") for c in COLS) + " |" for r in rows]
    md.write_text("\n".join(lines) + "\n")
    print(json.dumps({"rows": len(rows)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
