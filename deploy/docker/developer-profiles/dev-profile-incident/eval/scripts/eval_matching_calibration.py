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

"""Item-matching calibration for evaluation-methodology-v1.2 (no model or judge call).

    build     sample dev blocks and write the blind label sheet (no similarity anywhere in it)
    evaluate  labels + local embedder -> threshold table, selected threshold, false matches

From ``eval/``::

    uv run python scripts/eval_matching_calibration.py build <dev results.json>...
    uv run python scripts/eval_matching_calibration.py evaluate --labels <labels.jsonl>

``evaluate`` needs the local embedding server (``INCIDENT_EMBEDDING_BASE_URL``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(EVAL_DIR), str(EVAL_DIR / "scripts")]

import matching_calibration as mc  # noqa: E402

WORK = EVAL_DIR / "eval_data" / "matching_calibration"
REPORT = EVAL_DIR / "methodology" / "calibration" / "matching-v1.2-calibration.md"
SUMMARY = EVAL_DIR / "methodology" / "calibration" / "matching-v1.2-calibration.json"


def cmd_build(args) -> int:
    records = [json.loads(Path(p).read_text()) for p in args.results]
    blocks = mc.sample(mc.eligible_blocks(records))
    WORK.mkdir(parents=True, exist_ok=True)
    sheet_path = WORK / "label-sheet.json"
    if sheet_path.exists():
        print(f"REFUSED: {sheet_path} exists (the sheet is built once)", file=sys.stderr)
        return 2
    sheet_path.write_text(json.dumps(mc.label_sheet(blocks), indent=2, ensure_ascii=False) + "\n")
    # Provenance kept apart from the sheet, so the labeller never sees which arm wrote an item.
    (WORK / "blocks-provenance.json").write_text(json.dumps(
        {"seed": mc.SEED, "quota": mc.PAIR_QUOTA, "max_block_pairs": mc.MAX_BLOCK_PAIRS,
         "sources": [str(p) for p in args.results],
         "blocks": [{k: b[k] for k in ("block_id", "experiment_id", "incident_id", "category", "repeat", "kind")}
                    for b in blocks]}, indent=2) + "\n")
    pairs = sum(len(b["predicted"]) * len(b["ground_truth"]) for b in blocks)
    print(json.dumps({"sheet": str(sheet_path), "sha256": mc.sha256_file(sheet_path), "blocks": len(blocks),
                      "pairs": pairs}))
    return 0


def cmd_extend(args) -> int:
    """Calibration v2: the v1 sheet unchanged plus four random large blocks (their own sheet for the labeller)."""
    v1 = json.loads((WORK / "label-sheet.json").read_text())
    records = [json.loads(Path(p).read_text()) for p in args.results]
    large = mc.sample_large(mc.eligible_blocks(records, large=True), first_number=len(v1["blocks"]) + 1)
    paths = {"sheet": WORK / "label-sheet-v2.json", "large": WORK / "label-sheet-v2-large.json"}
    if any(p.exists() for p in paths.values()):
        print("REFUSED: a v2 sheet exists (sheets are built once)", file=sys.stderr)
        return 2
    large_sheet = mc.label_sheet(large)
    paths["large"].write_text(json.dumps(large_sheet, indent=2, ensure_ascii=False) + "\n")
    paths["sheet"].write_text(json.dumps({**v1, "version": "v2", "blocks": v1["blocks"] + large_sheet["blocks"]},
                                         indent=2, ensure_ascii=False) + "\n")
    (WORK / "blocks-provenance-v2.json").write_text(json.dumps(
        {"seed": mc.LARGE_SEED, "count": mc.LARGE_BLOCKS, "rule": "blocks of more than MAX_BLOCK_PAIRS pairs, "
         "shuffled under the seed, at most one per clip; never by similarity or score",
         "v1_sheet_sha256": mc.sha256_file(WORK / "label-sheet.json"), "sources": [str(p) for p in args.results],
         "blocks": [{k: b[k] for k in ("block_id", "experiment_id", "incident_id", "category", "repeat", "kind")}
                    for b in large]}, indent=2) + "\n")
    print(json.dumps({k: {"path": str(p), "sha256": mc.sha256_file(p)} for k, p in paths.items()} |
                     {"large_pairs": sum(len(b["predicted"]) * len(b["ground_truth"]) for b in large)}))
    return 0


def cmd_evaluate(args) -> int:
    sheet = json.loads((WORK / "label-sheet.json").read_text())
    labels = mc.load_jsonl(args.labels)
    problems = mc.validate_labels(sheet, labels)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    sims = mc.similarity_blocks(sheet)
    table = [mc.score_threshold(sheet, labels, sims, t) for t in mc.GRID]
    chosen = mc.select_threshold(table)
    at = next(r for r in table if r["threshold"] == chosen)
    old = next(r for r in table if r["threshold"] == 0.75)
    sensitivity = {mode: mc.score_threshold(sheet, labels, sims, chosen, ambiguous=mode) for mode in ("same", "different")}
    counts = {lab: sum(1 for x in labels if x["label"] == lab) for lab in mc.LABELS}
    summary = {"label_sheet_sha256": mc.sha256_file(WORK / "label-sheet.json"),
               "labels_sha256": mc.sha256_file(args.labels), "labeller": sorted({x.get("labeller", "?") for x in labels}),
               "label_counts": counts, "grid": list(mc.GRID), "selected_threshold": chosen,
               "f1_ci95": mc.f1_interval(at),
               "table": [{"threshold": r["threshold"], **{k: {m: r["by_kind"][k][m] for m in ("tp", "fp", "fn", "precision",
                                                                                          "recall", "f1")}
                                                          for k in (*mc.KINDS, "all")}} for r in table],
               "false_matches_at_selected": {k: at["by_kind"][k]["false_matches"] for k in mc.KINDS},
               "false_matches_at_0.75": {k: old["by_kind"][k]["false_matches"] for k in mc.KINDS},
               "sensitivity_ambiguous": {m: {k: {x: s["by_kind"][k][x] for x in ("precision", "recall", "f1")}
                                             for k in (*mc.KINDS, "all")} for m, s in sensitivity.items()}}
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("selected_threshold", "f1_ci95", "label_counts")}))
    return 0


def cmd_evaluate_v2(args) -> int:
    """Calibration v2 by the rules fixed in methodology v1.2 before any v2 label existed."""
    sheet = json.loads((WORK / "label-sheet-v2.json").read_text())
    labels = mc.load_jsonl(WORK / "labels-v2.jsonl")
    problems = mc.validate_labels(sheet, labels)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    sims = mc.similarity_blocks(sheet)
    grid = mc.GRID_V2
    table = {t: mc.score_threshold(sheet, labels, sims, t) for t in grid}
    selected = mc.select_threshold(list(table.values()))
    per_t = {t: table[t]["by_kind"]["all"]["blocks"] for t in grid}
    stability = mc.selection_stability(per_t)
    fallback = mc.conservative_choice(per_t, selected, stability)
    small = {b["block_id"] for b in sheet["blocks"][:22]}

    def subset(t, ids):
        rows = [per_t[t][b] for b in sorted(per_t[t]) if b in ids]
        tp, fp, fn = (sum(r[i] for r in rows) for i in range(3))
        return {"tp": tp, "fp": fp, "fn": fn, **mc._prf(tp, fp, fn)}

    large = set(per_t[selected]) - small
    pick = lambda r: {k: r[k] for k in ("tp", "fp", "fn", "precision", "recall", "f1")}  # noqa: E731
    audited = [x for x in labels if "audit" in x]
    summary = {
        "calibration_version": "v2", "label_sheet_sha256": mc.sha256_file(WORK / "label-sheet-v2.json"),
        "labels_sha256": mc.sha256_file(WORK / "labels-v2.jsonl"),
        "blocks": len(sheet["blocks"]), "pairs": len(labels),
        "label_counts": {lab: sum(1 for x in labels if x["label"] == lab) for lab in mc.LABELS},
        "audit": {"pairs": len(audited), "agree": sum(1 for x in audited if x["resolution"] == "audit agrees"),
                  "resolved_ambiguous": sum(1 for x in audited if x["resolution"].startswith("audit resolved")),
                  "disputed": sum(1 for x in audited if "human review" in x["resolution"])},
        "grid": list(grid), "selected_threshold": selected, "f1_ci95_at_selected": mc.f1_interval(table[selected]),
        "selection_stability": stability, "conservative_fallback": fallback,
        "table": [{"threshold": t, **{k: pick(table[t]["by_kind"][k]) for k in (*mc.KINDS, "all")},
                   "small_blocks": subset(t, small), "large_blocks": subset(t, large)} for t in grid],
        "false_matches": {str(t): {k: table[t]["by_kind"][k]["false_matches"] for k in mc.KINDS} for t in grid},
        "sensitivity_ambiguous": {mode: {str(t): pick(mc.score_threshold(sheet, labels, sims, t, ambiguous=mode)
                                                      ["by_kind"]["all"]) for t in grid} for mode in ("same", "different")},
    }
    out = SUMMARY.with_name("matching-v1.2-calibration-v2.json")
    out.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("selected_threshold", "f1_ci95_at_selected", "conservative_fallback",
                                              "label_counts", "audit")}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("results", nargs="+", type=Path)
    sub.add_parser("evaluate-v2")
    extend = sub.add_parser("extend")
    extend.add_argument("results", nargs="+", type=Path)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--labels", type=Path, required=True)
    args = parser.parse_args()
    return {"build": cmd_build, "extend": cmd_extend, "evaluate": cmd_evaluate, "evaluate-v2": cmd_evaluate_v2}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
