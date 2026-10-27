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

"""The Stage 2 prompt-selection rule, D9 v2 (``.docs/mvp2/experiment-decision-record.md``).

Pure functions over saved results. Nothing here is used until the rule is pre-registered in
``.docs/decisions.md``; ``select_d9`` refuses otherwise, and refuses test-split, pilot and
unfrozen-ground-truth records.

**Primary metric** ``ΔI``: the equally weighted mean of three component differences,
candidate minus the VSS baseline, each a paired mean over the dev videos eligible for it:

1. **incident fields**: per video, the mean of the eligible ones among type (exact; not eligible
   for a confirmed out-of-taxonomy clip), severity (exact), start and end (±5 s) and description
   (judge ≥ 0.5); duration is derived and not used;
2. **entity F1**: per video, ``2TP / (2TP + FP + FN)`` from the 1-to-1 matching;
3. **object F1**: per video, the mean of the eligible ones among instrument F1 and asset F1.

**Secondary metric** ``ΔI8``: the original per-video mean of the eight scores (the five incident
fields and the three item F1s), paired the same way. It is reported, and it is the second tie-breaker.

Per video and score:
- **repeats:** averaged first, leaving out a repeat with no value;
- **no model output** (request failure) in a repeat: that repeat gives no value; a video with no
  output in any repeat drops out of every pair it would be in;
- **invalid output** (contract or parse failure): scored as a miss, so incident fields are 0
  and the prediction is empty;
- **item F1 not eligible** when the ground truth and the prediction are both empty (nothing to
  find, nothing claimed); ground truth empty with a prediction gives 0 (all false positives);
  ground truth present with an empty prediction gives 0.

A pair counts for a component only when both sides have a value for that video. A component with
no eligible pair is left out of ``ΔI`` and recorded.
"""

from __future__ import annotations

import random
from pathlib import Path

import experiment_runner as er
import extraction_stats
import methodology
import prompt_registry

INCIDENT_SCORES = ("type", "severity_level", "start_timestamp", "end_timestamp", "description")
ITEM_KINDS = ("entities", "instruments", "assets")
COMPONENTS = ("incident", "entity_f1", "object_f1")
EIGHT_SCORES = (*INCIDENT_SCORES, "entities", "instruments", "assets")
MIN_IMPROVEMENT = 0.02
TIE_MARGIN = 0.01
REGRESSION_POINT = -0.05
VALID_OUTPUT_SLACK = 1  # video-runs


class SelectionRefused(RuntimeError):
    """Selection was asked to use test, pilot or unfrozen results, or the rule is not pre-registered."""


def item_f1(video: dict, kind: str) -> float | None:
    if not extraction_stats.has_model_output(video):
        return None
    summary = video.get(kind) or {}
    tp, fp = len(summary.get("matches", [])), len(summary.get("unmatched_model", []))
    fn = len(summary.get("unmatched_gt", []))
    return None if tp + fp + fn == 0 else 2 * tp / (2 * tp + fp + fn)


def video_scores(video: dict) -> dict[str, float | None]:
    """The eight scores of one video-run (``None`` = not eligible or no model output)."""
    scores = {field: extraction_stats.field_value(video, field) for field in INCIDENT_SCORES}
    scores.update({kind: item_f1(video, kind) for kind in ITEM_KINDS})
    return scores


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def per_video(record: dict) -> dict[str, dict[str, float | None]]:
    """``{incident_id: {score or component: value}}`` with repeats averaged first."""
    runs: dict[str, list[dict]] = {}
    for video in record["videos"]:
        runs.setdefault(video["incident_id"], []).append(video_scores(video))
    out = {}
    for incident_id, repeats in runs.items():
        scores = {name: _mean(r[name] for r in repeats) for name in EIGHT_SCORES}
        scores["incident"] = _mean(scores[f] for f in INCIDENT_SCORES)
        scores["entity_f1"] = scores["entities"]
        scores["object_f1"] = _mean((scores["instruments"], scores["assets"]))
        scores["eight"] = _mean(scores[name] for name in EIGHT_SCORES)
        out[incident_id] = scores
    return out


def _paired(a: dict, b: dict, name: str, ids) -> list[float]:
    return [b[i][name] - a[i][name] for i in ids if a[i][name] is not None and b[i][name] is not None]


def deltas(baseline: dict, candidate: dict, ids) -> dict:
    """Component, secondary and per-score paired mean differences over ``ids`` (a list, repeats allowed)."""
    out = {}
    for name in (*COMPONENTS, "eight", *EIGHT_SCORES):
        values = _paired(baseline, candidate, name, ids)
        out[name] = sum(values) / len(values) if values else None
    available = [out[c] for c in COMPONENTS if out[c] is not None]
    out["primary"] = sum(available) / len(available) if available else None
    return out


def compare(baseline_record: dict, candidate_record: dict, *, resamples: int | None = None,
            seed: int | None = None) -> dict:
    """``ΔI`` (primary), ``ΔI8`` (secondary) and every score's difference, each with a 95% video-cluster bootstrap.

    The bootstrap resamples videos (all scores of a resampled video move together) with the
    methodology's seed and resample count.
    """
    base, cand = per_video(baseline_record), per_video(candidate_record)
    ids = sorted(set(base) & set(cand))
    point = deltas(base, cand, ids)
    rng = random.Random(methodology.BOOTSTRAP_SEED if seed is None else seed)
    draws: dict[str, list[float]] = {name: [] for name in point}
    for _ in range(resamples or methodology.BOOTSTRAP_RESAMPLES):
        sample = [ids[rng.randrange(len(ids))] for _ in ids] if ids else []
        for name, value in deltas(base, cand, sample).items():
            if value is not None:
                draws[name].append(value)

    def interval(values: list[float]):
        if not values:
            return None
        ordered = sorted(values)
        return [round(ordered[int(0.025 * (len(ordered) - 1))], 4), round(ordered[int(0.975 * (len(ordered) - 1))], 4)]

    pairs = {name: len(_paired(base, cand, name, ids)) for name in (*COMPONENTS, "eight", *EIGHT_SCORES)}
    return {"videos": len(ids), "pairs": pairs,
            "components_used": [c for c in COMPONENTS if point[c] is not None],
            "point": {k: None if v is None else round(v, 4) for k, v in point.items()},
            "ci95": {name: interval(values) for name, values in draws.items()}}


def valid_runs(record: dict) -> int:
    reliability = extraction_stats.reliability(record["videos"])
    return reliability["attempted"] - reliability["no_model_output"] - reliability["invalid_model_output"]


def guardrails(baseline_record: dict, candidate_record: dict, comparison: dict) -> list[str]:
    """G1 valid-output rate, G2 no credible regression on any of the eight scores, G3 same conditions."""
    problems = []
    if valid_runs(candidate_record) < valid_runs(baseline_record) - VALID_OUTPUT_SLACK:
        problems.append(f"G1: {valid_runs(candidate_record)} valid video-runs vs the baseline's "
                        f"{valid_runs(baseline_record)}")
    for name in EIGHT_SCORES:
        value, ci = comparison["point"][name], comparison["ci95"][name]
        if value is not None and ci and value <= REGRESSION_POINT and ci[1] < 0:
            problems.append(f"G2: {name} regresses by {value} (95% CI {ci})")
    for label, get in (("videos", lambda r: sorted({v["incident_id"] for v in r["videos"]})),
                       ("repeats", lambda r: r["plan"]["repeats"]), ("model", lambda r: r["model"]),
                       ("ground truth", lambda r: r["ground_truth"]["records_sha256"]),
                       ("split", lambda r: r["split"]["half"])):
        if get(baseline_record) != get(candidate_record):
            problems.append(f"G3: different {label}")
    return problems


def _order(prompt_id: str, registry: dict | None) -> int:
    ids = [e["id"] for e in (registry or prompt_registry.load())["prompts"]]
    return ids.index(prompt_id) if prompt_id in ids else len(ids)


def evaluate(baseline_record: dict, candidates: dict[str, dict], *, registry: dict | None = None,
             resamples: int | None = None) -> dict:
    """Every candidate's comparison, eligibility and rank; ``selected`` is a prompt id (the baseline if none qualifies)."""
    rows = []
    for name, record in candidates.items():
        comparison = compare(baseline_record, record, resamples=resamples)
        problems = guardrails(baseline_record, record, comparison)
        primary = comparison["point"]["primary"]
        meets = primary is not None and primary >= MIN_IMPROVEMENT
        rows.append({"name": name, "prompt_id": record["prompt"]["id"], "primary": primary,
                     "primary_ci95": comparison["ci95"]["primary"], "secondary": comparison["point"]["eight"],
                     "severity": comparison["point"]["severity_level"], "valid_runs": valid_runs(record),
                     "prompt_bytes": len(prompt_registry.prompt_text(record["prompt"]["id"], registry=registry)
                                         .encode()),
                     "registry_order": _order(record["prompt"]["id"], registry), "guardrail_problems": problems,
                     "eligible": not problems and meets, "comparison": comparison})
    eligible = [r for r in rows if r["eligible"]]
    eligible.sort(key=lambda r: -r["primary"])
    if eligible:
        best = eligible[0]["primary"]
        tied = [r for r in eligible if best - r["primary"] < TIE_MARGIN]
        # Tie-breakers, in order: higher ΔI lower bound, higher ΔI8, higher severity Δ, more valid runs,
        # shorter prompt, earlier registry entry.
        tied.sort(key=lambda r: (-(r["primary_ci95"] or [float("-inf")])[0], -(r["secondary"] or float("-inf")),
                                 -(r["severity"] or float("-inf")), -r["valid_runs"], r["prompt_bytes"],
                                 r["registry_order"]))
        selected = tied[0]["prompt_id"]
        tie = len(tied) > 1
    else:
        selected, tie = baseline_record["prompt"]["id"], False
    return {"selected": selected, "baseline": baseline_record["prompt"]["id"], "tie_break_used": tie,
            "rule": "D9 v2", "min_improvement": MIN_IMPROVEMENT, "candidates": rows}


def guard(records: dict[str, dict], *, rule_record: str, decisions_path: Path) -> None:
    if not er.selection_record_exists(rule_record, decisions_path):
        raise SelectionRefused(f"the selection rule {rule_record!r} is not pre-registered in decisions.md")
    for name, record in records.items():
        if record["split"]["half"] != "dev":
            raise SelectionRefused(f"{name} is a {record['split']['half']} record: selection uses dev results only")
        if record.get("purpose") == "pilot":
            raise SelectionRefused(f"{name} is a pilot record: pilots never feed selection")
        if not record.get("reportable"):
            raise SelectionRefused(f"{name} is not reportable (unfrozen ground truth)")
        if not record.get("complete"):
            raise SelectionRefused(f"{name} did not complete ({record.get('stopped')})")


def select_d9(baseline_record: dict, candidates: dict[str, dict], *, rule_record: str, decisions_path: Path,
              registry: dict | None = None, resamples: int | None = None) -> dict:
    guard({**candidates, "baseline": baseline_record}, rule_record=rule_record, decisions_path=decisions_path)
    return evaluate(baseline_record, candidates, registry=registry, resamples=resamples)
