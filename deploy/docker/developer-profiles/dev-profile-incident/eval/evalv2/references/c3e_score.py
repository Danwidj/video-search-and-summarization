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

"""C3-E scoring (``c3e-preregistration.md`` §3 and §5): read-only on the Track B run directories.

Each evidence entry is scored by J5 (:func:`evalv2.tasks.pipeline.crops.score_run`, A8's scorer) through the
**stored** final-stage item matching of the run's pre-registered scoring file; nothing is re-matched and nothing is
written into a run directory. Each entry then gets exactly one taxonomy class, and missing evidence (a matched item
with no entry) is added per run. Rates come with clip-cluster bootstrap CIs.
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from evalv2.tasks.pipeline import crops

SCORE_FILE = ("scoring/evalv2-score-stage-v3/primary/live-videos.jsonl",
              "scoring/evalv2-score-stage-v3/primary/offline-videos.jsonl")
CLASSES = ("correct", "spatial_miss", "temporal_miss", "not_located", "missing_evidence", "unscorable",
           "unmatched_item")
MIN_CELL = 20
SEED, RESAMPLES = 20261027, 10000


def scored_rows(run_dir: Path | str) -> list[dict[str, Any]]:
    """The run's final-stage scored rows from its pre-registered scoring file (live preferred)."""
    for name in SCORE_FILE:
        path = Path(run_dir) / name
        if path.exists():
            return [r for r in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
                    if r.get("stage") == "final"]
    return []


def artifacts(run_dir: Path | str) -> dict[tuple[str, str, int], dict[str, Any]]:
    """``(subject, clip, repeat)`` to the stored pipeline prediction payload (read-only)."""
    run_dir, out = Path(run_dir), {}
    checkpoint = run_dir / "checkpoint.jsonl"
    if not checkpoint.exists():
        return out
    for line in checkpoint.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        ref = row.get("prediction_ref") or ""
        if ref.startswith("pipeline-prediction:"):
            digest = ref.split(":", 1)[1]
            path = run_dir / "store" / "objects" / "pipeline-prediction" / digest[:2] / f"{digest}.json"
            out[(row["subject"], row["item_id"], int(row["repeat"]))] = json.loads(path.read_text())["payload"]
    return out


def classify(entry: Mapping[str, Any], reference: Mapping[str, Any] | None) -> tuple[str, str | None]:
    """One J5 entry score to one taxonomy class and, for unscorable entries, the reason."""
    status = entry["status"]
    if status == "unmatched":
        return "unmatched_item", None
    if status == "unscorable":
        return "unscorable", str(entry.get("reason") or "")
    if status == "no_reference":
        return "unscorable", "no reference record"
    if status == "reference_rejected":
        return "unscorable", "reference rejected"
    if not entry["located"]:
        return "not_located", None
    if not entry["temporal_hit"]:
        return "temporal_miss", None
    if entry["correct"] is None:
        payload = (reference or {}).get("human", {}).get("edited_payload") or (reference or {}).get("payload") or {}
        rejected = (payload.get("rejected_seconds") or {}).get(str(entry.get("second")))
        if rejected == "reject_not_identifiable":
            return "unscorable", "reference rejected as not identifiable at that second"
        return "unscorable", "no verified reference box at that second"
    return ("correct" if entry["correct"] else "spatial_miss"), None


def score_runs(run_dirs: Sequence[Path | str], records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per evidence entry (plus one per matched item without evidence) over the runs."""
    out = []
    by_id = {r["record_id"]: r for r in records}
    for run_dir in run_dirs:
        stored = artifacts(run_dir)
        for row in scored_rows(run_dir):
            key = (row["subject"], row["incident_id"], int(row["repeat"]))
            artifact = stored.get(key)
            if artifact is None or row.get("outcome") != "scored":
                continue
            clip = row["incident_id"]
            index = crops.reference_index(records, clip)
            entries = crops.score_run(artifact, row, index)
            seen = set()
            for entry in entries:
                gt_id = entry.get("gt_item_id")
                kind = entry.get("item_type")
                reference = by_id.get(f"box:{clip}:{gt_id}") if gt_id else None
                cls, reason = classify(entry, reference)
                seen.add((kind, str(entry.get("item_id"))))
                out.append({"subject": row["subject"], "clip": clip, "repeat": row["repeat"], "kind": kind,
                            "gt_item_id": gt_id, "class": cls, "reason": reason, "tier": entry.get("tier"),
                            "iou": entry.get("iou"), "temporal_hit": entry.get("temporal_hit")})
            for kind, plural in (("entity", "entities"), ("instrument", "instruments"), ("asset", "assets")):
                id_field = {"entity": "entity_id", "instrument": "instrument_id", "asset": "asset_id"}[kind]
                for match in (row.get(plural) or {}).get("matches") or []:
                    if (kind, str(match[id_field])) not in seen:
                        out.append({"subject": row["subject"], "clip": clip, "repeat": row["repeat"], "kind": kind,
                                    "gt_item_id": str(match[f"gt_{id_field}"]), "class": "missing_evidence",
                                    "reason": None, "tier": (by_id.get(f"box:{clip}:{match[f'gt_{id_field}']}") or {})
                                    .get("tier"), "iou": None, "temporal_hit": None})
    return out


def _boot(per_clip: Mapping[str, list[tuple[float, float]]]) -> list[float] | None:
    keys = sorted(per_clip)
    if not keys:
        return None
    rnd, vals = random.Random(SEED), []
    for _ in range(RESAMPLES):
        num = den = 0.0
        for _ in keys:
            for a, b in per_clip[keys[rnd.randrange(len(keys))]]:
                num, den = num + a, den + b
        if den:
            vals.append(num / den)
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 4), round(vals[int(0.975 * len(vals)) - 1], 4)] if vals else None


def rate(rows: Iterable[Mapping[str, Any]], hit, include) -> dict[str, Any]:
    per, n, k = defaultdict(list), 0, 0
    for r in rows:
        if include(r):
            per[r["clip"]].append((1.0 if hit(r) else 0.0, 1.0))
            n, k = n + 1, k + bool(hit(r))
    return {"n": n, "value": round(k / n, 4) if n else None, "ci95": _boot(per) if n else None}


def summarise(rows: Sequence[Mapping[str, Any]], *, tier: str) -> dict[str, Any]:
    """Pre-registered metrics for one subject's rows on one reference tier."""
    tiered = [r for r in rows if r["tier"] == tier]
    judged = lambda r: r["class"] in ("correct", "spatial_miss", "temporal_miss", "not_located")  # noqa: E731
    temporal = lambda r: r["class"] in ("correct", "spatial_miss", "temporal_miss")  # noqa: E731
    ious = sorted(r["iou"] for r in tiered if r["iou"] is not None)
    out = {"classes": dict(Counter(r["class"] for r in tiered)),
           "correct_evidence_rate": rate(tiered, lambda r: r["class"] == "correct", judged),
           "temporal_alignment_rate": rate(tiered, lambda r: r["class"] != "temporal_miss", temporal),
           "iou": {"n": len(ious), "median": ious[len(ious) // 2] if ious else None,
                   "share_ge_0_5": round(sum(i >= 0.5 for i in ious) / len(ious), 4) if ious else None},
           "by_kind": {}}
    for kind in ("entity", "instrument", "asset"):
        cell = [r for r in tiered if r["kind"] == kind]
        n = sum(1 for r in cell if judged(r))
        out["by_kind"][kind] = ({"correct_evidence_rate": rate(cell, lambda r: r["class"] == "correct", judged)}
                                if n >= MIN_CELL else {"n": n, "counts_only": dict(Counter(r["class"] for r in cell))})
    return out


def report(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Per subject: verified (primary), provisional AI-assisted, and the untiered classes (unmatched, unscorable
    without a record) with their reasons."""
    out = {}
    for subject in sorted({r["subject"] for r in rows}):
        mine = [r for r in rows if r["subject"] == subject]
        out[subject] = {"entries": len(mine), "classes": dict(Counter(r["class"] for r in mine)),
                        "unscorable_reasons": dict(Counter(r["reason"] for r in mine if r["class"] == "unscorable")),
                        "verified": summarise(mine, tier="human_verified"),
                        "provisional_ai_validated": summarise(mine, tier="ai_validated"),
                        "provisional_ai_proposed": summarise(mine, tier="ai_proposed")}
    return out


# ---- v0.2: AI-referenced tiers (c3e-preregistration-v0.2.md §3-§4) ---------------------------------------------

TIER_RANK = {"consensus": 2, "adjudicated": 1}


def _weaker(*tiers: str | None) -> str | None:
    known = [t for t in tiers if t in TIER_RANK]
    return None if len(known) < len([t for t in tiers if t is not None]) or not known else min(known, key=TIER_RANK.get)


def classify_v2(entry: Mapping[str, Any], visibility: Mapping[str, Any] | None, box: Mapping[str, Any] | None,
                *, iou_threshold: float = 0.5, identity_flagged: bool = False) -> dict[str, Any]:
    """One matched evidence entry against the v0.2 reference at its second: class, reason, tier and IoU.

    ``visibility`` and ``box`` are the second's tier records (``box`` is absent where the second was not sampled).
    """
    from evalv2.tasks.crops import scoring as crop_scoring

    if identity_flagged:
        return {"class": "unscorable", "reason": "GT identity words contradicted (notes v1)", "tier": None}
    reason = crop_scoring.unscorable_reason(entry)
    if reason is not None:
        return {"class": "unscorable", "reason": reason, "tier": None}
    if not visibility or visibility.get("tier") not in TIER_RANK:
        return {"class": "unscorable", "reason": "visibility unresolved at that second", "tier": None}
    vis_tier = visibility["tier"]
    predicted, _ = crop_scoring.predicted_box(entry)
    if entry.get("located") is False or predicted is None:
        return {"class": "not_located", "reason": None, "tier": vis_tier}
    if not visibility.get("visible"):
        return {"class": "temporal_miss", "reason": None, "tier": vis_tier}
    if not box or box.get("tier") not in TIER_RANK or box.get("box") is None:
        why = (box or {}).get("reason") or ("second not sampled" if not box else "no reference box")
        return {"class": "unscorable_iou", "reason": f"temporal hit; no resolved reference box ({why})", "tier": vis_tier}
    overlap = crop_scoring.iou(predicted, box["box"])
    return {"class": "correct" if overlap >= iou_threshold else "spatial_miss", "reason": None,
            "tier": _weaker(vis_tier, box["tier"]), "iou": overlap}


def score_runs_v2(run_dirs: Sequence[Path | str], visibility: Mapping[str, Mapping[str, Any]],
                  box_tiers: Mapping[str, Mapping[str, Any]], identity_flags: Iterable[str] = (),
                  *, iou_threshold: float = 0.5) -> list[dict[str, Any]]:
    """Every evidence entry of the runs through the stored final-stage matching (read-only), classified by v0.2,
    plus one ``missing_evidence`` row per matched item with no entry whose reference has a resolved visible second."""
    flagged = set(identity_flags)
    out = []
    kinds = (("entity", "entities", "entity_id"), ("instrument", "instruments", "instrument_id"),
             ("asset", "assets", "asset_id"))
    for run_dir in run_dirs:
        stored = artifacts(run_dir)
        for row in scored_rows(run_dir):
            artifact = stored.get((row["subject"], row["incident_id"], int(row["repeat"])))
            if artifact is None or row.get("outcome") != "scored":
                continue
            clip = row["incident_id"]
            matches = crops.item_matches(row)
            seen = set()
            for entry in artifact.get("evidence") or []:
                kind = entry.get("item_type")
                plural = {"entity": "entities", "instrument": "instruments", "asset": "assets"}.get(str(kind))
                gt_id = (matches.get(plural) or {}).get(str(entry.get("item_id"))) if plural else None
                base = {"subject": row["subject"], "clip": clip, "repeat": row["repeat"], "kind": kind,
                        "gt_item_id": gt_id}
                if gt_id is None:
                    out.append({**base, "class": "unmatched_item", "reason": None, "tier": None})
                    continue
                seen.add((kind, gt_id))
                from evalv2.tasks.crops import scoring as crop_scoring

                second = crop_scoring.evidence_second(entry)
                key = f"{clip}-{gt_id}"
                vis = (visibility.get(key) or {}).get(str(second)) if second is not None else None
                box = (box_tiers.get(key) or {}).get(str(second)) if second is not None else None
                out.append({**base, "second": second,
                            **classify_v2(entry, vis, box, iou_threshold=iou_threshold, identity_flagged=key in flagged)})
            for kind, plural, id_field in kinds:
                for match in (row.get(plural) or {}).get("matches") or []:
                    gt_id = str(match[f"gt_{id_field}"])
                    if (kind, gt_id) in seen:
                        continue
                    key = f"{clip}-{gt_id}"
                    states = [s for s in (visibility.get(key) or {}).values() if s.get("tier") in TIER_RANK and s.get("visible")]
                    if key in flagged or not states:
                        out.append({"subject": row["subject"], "clip": clip, "repeat": row["repeat"], "kind": kind,
                                    "gt_item_id": gt_id, "class": "unscorable",
                                    "reason": "missing evidence; reference unresolved", "tier": None})
                    else:
                        tier = max((s["tier"] for s in states), key=TIER_RANK.get)
                        out.append({"subject": row["subject"], "clip": clip, "repeat": row["repeat"], "kind": kind,
                                    "gt_item_id": gt_id, "class": "missing_evidence", "reason": None, "tier": tier})
    return out


JUDGED = ("correct", "spatial_miss", "temporal_miss", "not_located", "missing_evidence")


def summarise_v2(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Per subject: coverage, correct-evidence rate per tier set, temporal alignment, IoU, by kind, and the bounds."""
    out = {}
    for subject in sorted({r["subject"] for r in rows}):
        mine = [r for r in rows if r["subject"] == subject and r["class"] != "unmatched_item"]
        block = {"entries_of_matched_items": len(mine), "classes": dict(Counter(r["class"] for r in mine)),
                 "unscorable_reasons": dict(Counter(r["reason"] for r in mine if r["class"].startswith("unscorable"))),
                 "unmatched_items": sum(1 for r in rows if r["subject"] == subject and r["class"] == "unmatched_item")}
        for name, tiers in (("consensus_only", {"consensus"}), ("adjudicated_only", {"adjudicated"}),
                            ("combined", {"consensus", "adjudicated"})):
            judged = [r for r in mine if r["class"] in JUDGED and r["tier"] in tiers]
            ious = sorted(r["iou"] for r in judged if r.get("iou") is not None)
            block[name] = {
                "correct_evidence": rate(judged, lambda r: r["class"] == "correct", lambda r: True),
                "coverage": {"scorable": len(judged), "of": len(mine),
                             "share": round(len(judged) / len(mine), 4) if mine else None},
                "temporal_alignment": rate([r for r in mine if r["tier"] in tiers and r["class"] in
                                            ("correct", "spatial_miss", "temporal_miss", "unscorable_iou")],
                                           lambda r: r["class"] != "temporal_miss", lambda r: True),
                "iou": {"n": len(ious), "median": ious[len(ious) // 2] if ious else None,
                        "share_ge_0_5": round(sum(i >= 0.5 for i in ious) / len(ious), 4) if ious else None},
                "by_kind": {k: (rate([r for r in judged if r["kind"] == k], lambda r: r["class"] == "correct",
                                     lambda r: True) if sum(r["kind"] == k for r in judged) >= MIN_CELL
                                else {"n": sum(r["kind"] == k for r in judged), "counts_only": True})
                            for k in ("entity", "instrument", "asset")}}
        unresolved = [r for r in mine if r["class"].startswith("unscorable")]
        judged = [r for r in mine if r["class"] in JUDGED]
        hits = sum(r["class"] == "correct" for r in judged)
        n = len(judged) + len(unresolved)
        block["bounds_unresolved"] = {"worst": round(hits / n, 4) if n else None,
                                      "best": round((hits + len(unresolved)) / n, 4) if n else None,
                                      "note": "bounds treat every unresolved entry as a miss / a hit; not estimates"}
        out[subject] = block
    return out
