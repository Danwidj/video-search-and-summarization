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

"""C3-E human review: AI proposals into review items, reviewer assignment, review import and agreement.

- :func:`proposals` turns the passes' answers into what a reviewer checks per item: proposed visible spans with
  their flags, and per sampled second the proposed box (the generator's when the passes agree or only it saw a box;
  the validator's, marked as a suggestion, when only it did). Which seconds were anchors is not in it.
- :func:`assign` makes the review configuration: a primary reviewer per clip (round robin over the configured
  reviewer ids, never names in code) and a stratified 10% second-review sample with another reviewer.
- :func:`apply_review` turns one primary review of an item into its ``human_verified`` record; an item is verified
  only when its spans and every sampled box were decided by a person.
- :func:`agreement` compares primary and second reviews: interval boundaries within 1 s, per-second visibility κ,
  box decision κ and IoU between the reviewers' boxes.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from evalv2.datasets import records
from evalv2.references import boxes

DECISIONS = ("accept", "redraw", "reject_not_visible", "reject_not_identifiable")
SECOND_SAMPLE_SHARE = 0.10
SECOND_SAMPLE_SEED = 20261104


class ReviewError(ValueError):
    """A malformed review or configuration."""


def proposals(item: Mapping[str, Any], interval: Mapping[str, Any] | None, generated: Mapping[int, Any],
              validated: Mapping[int, Any], seconds: Sequence[int]) -> dict[str, Any]:
    """One review item: spans and flags, then one row per sampled second (sorted, unlabelled)."""
    rows, flags = [], list((interval or {}).get("flags") or [])
    if interval is None:
        flags.append("no_interval_proposal")  # a visibility pass is missing: never ai_validated
    for s in sorted(int(x) for x in seconds):
        a, b = generated.get(s), validated.get(s)
        if a is not None and b is not None:
            status = "agree" if boxes.iou(a, b) >= boxes.AGREEMENT_IOU else "disagree"
            box = a
        elif a is not None:
            status, box = "generator_only", a
        elif b is not None:
            status, box = "validator_only", b
        else:
            status, box = "none_fits", None
        rows.append({"second": s, "box": list(box) if box else None, "status": status})
    if any(r["status"] in ("disagree", "generator_only", "validator_only") for r in rows):
        flags.append("box_disagreement")
    if any(r["status"] == "none_fits" for r in rows):
        flags.append("none_fits")
    priority = (3 * ("box_disagreement" in flags) + 2 * ("flicker" in flags) + ("unclear" in flags)
                + ("none_fits" in flags))
    return {"key": f"{item['clip']}-{item['item_id']}", "clip": item["clip"], "kind": item["kind"],
            "item_id": item["item_id"], "text": item["text"],
            "visible_spans": [list(s) for s in (interval or {}).get("visible_spans") or []],
            "flags": sorted(set(flags)), "priority": priority, "boxes": rows}


def _stratum(item: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(item.get("half")), str(item["kind"]), str(item.get("category")))


def assign(items: Sequence[Mapping[str, Any]], reviewers: Sequence[str], *, share: float = SECOND_SAMPLE_SHARE,
           seed: int = SECOND_SAMPLE_SEED) -> dict[str, Any]:
    """Primary reviewer per clip and the stratified second-review sample (each stratum rounds up, at least one)."""
    reviewers = [str(r) for r in reviewers]
    if len(reviewers) < 2 or len(set(reviewers)) != len(reviewers):
        raise ReviewError("at least two distinct reviewer ids are needed (a second review needs another person)")
    clips = sorted({i["clip"] for i in items})
    primary = {clip: reviewers[n % len(reviewers)] for n, clip in enumerate(clips)}
    strata: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for item in sorted(items, key=lambda i: i["key"]):
        strata[_stratum(item)].append(item["key"])
    second = {}
    for stratum, keys in sorted(strata.items()):
        digest = hashlib.sha256(f"c3e-second-v1|{seed}|{'|'.join(stratum)}".encode()).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        for key in sorted(rng.sample(keys, max(1, math.ceil(share * len(keys))))):
            clip = next(i["clip"] for i in items if i["key"] == key)
            others = [r for r in reviewers if r != primary[clip]]
            second[key] = others[int.from_bytes(hashlib.sha256(key.encode()).digest()[:4], "big") % len(others)]
    return {"version": "c3e-review-config-v1", "reviewers": reviewers, "primary": primary, "second": second,
            "share": share, "seed": seed}


def check_review(review: Mapping[str, Any], item: Mapping[str, Any]) -> list[str]:
    """Problems with one reviewer's decisions on one item (empty when complete and well formed)."""
    problems = []
    if not str(review.get("reviewer") or "").strip():
        problems.append("no reviewer id")
    spans = review.get("visible_spans")
    if not isinstance(spans, list) or not all(isinstance(s, list) and len(s) == 2 and 0 <= s[0] <= s[1]
                                              for s in spans):
        problems.append("visible_spans must be [[start, end], ...] whole seconds")
    decided = {int(d["second"]): d for d in review.get("boxes") or []}
    for row in item["boxes"]:
        d = decided.get(row["second"])
        if d is None or d.get("decision") not in DECISIONS:
            problems.append(f"second {row['second']}: no decision")
        elif d["decision"] == "accept" and row["box"] is None:
            problems.append(f"second {row['second']}: accepted, but there is no proposed box (redraw or reject)")
        elif d["decision"] == "redraw" and not (d.get("box") and boxes.valid_box(d["box"])):
            problems.append(f"second {row['second']}: redraw needs a valid box")
    return problems


def final_box(row: Mapping[str, Any], decision: Mapping[str, Any]) -> list[float] | None:
    if decision["decision"] == "accept":
        return list(row["box"])
    if decision["decision"] == "redraw":
        return list(decision["box"])
    return None


def apply_review(record: Mapping[str, Any], item: Mapping[str, Any], review: Mapping[str, Any], *,
                 source_sha256: str) -> dict[str, Any]:
    """The item's record ``human_verified`` through the record schema's :class:`HumanDecision`.

    The decision is "accept" when the person kept the AI spans and every proposed box, else "edit" with the
    person's spans and boxes. Refused when incomplete, when the reviewer id names a model, or when the record changed
    since the review page was built.
    """
    problems = check_review(review, item)
    if problems:
        raise ReviewError(f"{item['key']}: " + "; ".join(problems[:5]))
    decided = {int(d["second"]): d for d in review["boxes"]}
    verified, rejected = {}, {}
    for row in item["boxes"]:
        d = decided[row["second"]]
        box = final_box(row, d)
        if box is None:
            rejected[str(row["second"])] = d["decision"]
        else:
            verified[str(row["second"])] = box
    edited = dict(record["payload"])
    edited.update({"visible_spans": [list(x) for x in review["visible_spans"]], "boxes": verified,
                   "rejected_seconds": rejected})
    unchanged = (edited["visible_spans"] == [list(x) for x in record["payload"].get("visible_spans") or []]
                 and verified == record["payload"].get("boxes") and not rejected)
    decision = records.HumanDecision(
        record_id=record["record_id"], decision="accept" if unchanged else "edit", reviewer=str(review["reviewer"]),
        decided_at=str(review.get("at") or ""), payload_sha256=records.payload_sha256(record),
        source_sha256=source_sha256, edited_payload=None if unchanged else edited,
        note=f"c3e-review-v1 primary; decisions {dict(Counter(d['decision'] for d in review['boxes']))}")
    return records.apply_human_decision(record, decision)


def _seconds(spans: Iterable[Sequence[int]], last: int) -> list[int]:
    on = [0] * (last + 1)
    for a, b in spans:
        for s in range(max(0, int(a)), min(last, int(b)) + 1):
            on[s] = 1
    return on


def kappa(a: Sequence[Any], b: Sequence[Any]) -> float | None:
    """Cohen's κ of two equal-length label sequences (None when undefined)."""
    if len(a) != len(b) or not a:
        return None
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return None if expected == 1 else round((observed - expected) / (1 - expected), 4)


def agreement(items: Mapping[str, Mapping[str, Any]], primary: Mapping[str, Mapping[str, Any]],
              second: Mapping[str, Mapping[str, Any]], last_second: Mapping[str, int]) -> dict[str, Any]:
    """Primary versus second review on the doubly reviewed items."""
    keys = sorted(set(primary) & set(second))
    vis_a, vis_b, dec_a, dec_b, ious, boundary = [], [], [], [], [], []
    for key in keys:
        item, p, s = items[key], primary[key], second[key]
        last = last_second[item["clip"]]
        vis_a += _seconds(p["visible_spans"], last)
        vis_b += _seconds(s["visible_spans"], last)
        pb = [list(x) for x in p["visible_spans"]]
        sb = [list(x) for x in s["visible_spans"]]
        boundary.append(len(pb) == len(sb) and all(abs(x[0] - y[0]) <= 1 and abs(x[1] - y[1]) <= 1
                                                   for x, y in zip(pb, sb, strict=True)))
        dp = {int(d["second"]): d for d in p["boxes"]}
        ds = {int(d["second"]): d for d in s["boxes"]}
        for row in item["boxes"]:
            a, b = dp[row["second"]], ds[row["second"]]
            dec_a.append(a["decision"] in ("accept", "redraw"))
            dec_b.append(b["decision"] in ("accept", "redraw"))
            ba, bb = final_box(row, a), final_box(row, b)
            if ba is not None and bb is not None:
                ious.append(boxes.iou(ba, bb))
    ious.sort()
    return {"items": len(keys), "seconds": len(vis_a), "boxes": len(dec_a),
            "visibility_kappa": kappa(vis_a, vis_b), "boundaries_within_1s": sum(boundary),
            "box_decision_kappa": kappa(dec_a, dec_b),
            "box_iou_median": ious[len(ious) // 2] if ious else None,
            "box_iou_share_ge_0_5": round(sum(i >= 0.5 for i in ious) / len(ious), 4) if ious else None,
            "box_pairs": len(ious)}
