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

"""C3-E v0.2, AI-referenced tiers (``eval/methodology/c3e-preregistration-v0.2.md``). No model is called here.

- :func:`descriptive_queries`: the extra OWLv2 queries of one ground-truth item (fixed rule).
- :func:`union_proposals`: RA1's proposals for the item's query plus the extra pass's for its descriptive queries.
- :func:`box_adjudication_packets`: per contested second, the candidates in two orders (``a`` and ``b``, numbers
  reversed); which pass proposed which candidate is never shown.
- :func:`resolve_box`: the second's tier from the passes' boxes and the two adjudication answers.
- :func:`visibility_state`: the per-second visibility tier from the two visibility passes, box consensus and the
  visibility adjudication.
Thresholds: pass agreement IoU >= 0.5; a validator box maps to the generator's second when a proposal there overlaps
it with IoU >= 0.3; candidates overlapping at IoU >= 0.7 are one candidate; adjudication needs the same answer in both
orders, each with confidence >= 0.6.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evalv2.references import boxes

V2_VERSION = "c3e-v0.2"
AGREE_IOU = boxes.AGREEMENT_IOU  # 0.5
MAP_IOU = 0.3
SAME_CANDIDATE_IOU = 0.7
ADJ_CONFIDENCE = 0.6
VIS_ADJ_MAX_SECONDS = 12
BOX_ADJ_PROMPT = "gen-box-adjudicate-v1"
VIS_ADJ_PROMPT = "gen-visibility-adjudicate-v1"
BOX_ADJ_ANSWERS = ("not_visible", "cannot_identify")
VIS_ADJ_ANSWERS = ("yes", "no", "cannot_identify")
BOX_ADJ_FORMAT = {"answer": {"choice": "<candidate number, or not_visible, or cannot_identify>", "confidence": "<0 to 1>"}}
VIS_ADJ_FORMAT = {"answers": [{"t": "<tile time>", "visible": "yes | no | cannot_identify", "confidence": "<0 to 1>"}]}


class C3EV2Error(ValueError):
    """A malformed packet or answer for C3-E v0.2."""


def _label_and_words(item: Mapping[str, Any]) -> tuple[str, str]:
    label, _, words = str(item["text"]).partition(":")
    return " ".join(label.split()).lower(), " ".join(words.split())


def descriptive_queries(item: Mapping[str, Any]) -> list[str]:
    """Extra queries: the description's head phrase (up to the first ; . or (, commas dropped, at most five words),
    for an instrument also "<name> in a hand", and for an instrument or asset "a <name>"; never the RA1 query."""
    label, words = _label_and_words(item)
    head = " ".join(re.split(r"[;.(]", words, maxsplit=1)[0].replace(",", " ").lower().split()[:5])
    out = [head] if head else []
    if item["kind"] == "instrument" and label:
        out.append(f"{label} in a hand")
    if item["kind"] in ("instrument", "asset") and label and f"a {label}" != item["query"]:
        out.append(f"a {label}")
    seen, kept = {item["query"]}, []
    for q in out:
        if q and q not in seen:
            seen.add(q)
            kept.append(q)
    return kept


def union_proposals(ra1: Mapping[float, Sequence[boxes.Proposal]], extra: Mapping[float, Sequence[boxes.Proposal]],
                    item: Mapping[str, Any], t: float) -> list[boxes.Proposal]:
    """The item's candidates at ``t``: RA1's for its query, then the extra pass's for its descriptive queries
    (a near-duplicate of an earlier box, IoU >= 0.9, is dropped)."""
    queries = set(descriptive_queries(item))
    out = [p for p in ra1.get(t, ()) if p.label.strip().lower() == item["query"]]
    for p in extra.get(t, ()):
        if p.label.strip().lower() in queries and all(boxes.iou(p.box, q.box) < 0.9 for q in out):
            out.append(p)
    return out


def map_box(box: Sequence[float] | None, proposals: Sequence[boxes.Proposal]) -> list[float] | None:
    """A box from the validator's frame (0.5 s later) as the best-overlapping proposal at the second (IoU >= 0.3)."""
    if box is None:
        return None
    best = max(proposals, key=lambda p: boxes.iou(p.box, box), default=None)
    return list(best.box) if best is not None and boxes.iou(best.box, box) >= MAP_IOU else None


def candidates(generated: Sequence[float] | None, validated_mapped: Sequence[float] | None,
               extra_best: Sequence[float] | None) -> list[list[float]]:
    """Distinct candidate boxes (IoU >= 0.7 merges), in a fixed order: generator, mapped validator, extra."""
    out: list[list[float]] = []
    for box in (generated, validated_mapped, extra_best):
        if box is not None and all(boxes.iou(box, b) < SAME_CANDIDATE_IOU for b in out):
            out.append(list(box))
    return out


def _order(key: str, n: int) -> list[int]:
    rng = random.Random(int.from_bytes(hashlib.sha256(f"c3e-adj-v1|{key}".encode()).digest()[:8], "big"))
    order = list(range(n))
    rng.shuffle(order)
    return order


def box_adjudication_packets(item: Mapping[str, Any], second: int, cands: Sequence[Sequence[float]], image_root: str
                             ) -> dict[str, dict[str, Any]]:
    """Packets ``a`` and ``b`` for one contested second: the same candidates, ``b`` numbered in reverse of ``a``.

    The packet shows the item's ground-truth words, the frame at the second with numbered boxes and the unmarked frames
    a second either side (one composite image per order). It holds no source of any candidate.
    """
    if not cands:
        raise C3EV2Error("no candidate to adjudicate")
    order_a = _order(f"{item['clip']}|{item['item_id']}|{second}", len(cands))
    order_b = list(reversed(order_a))
    out = {}
    for name, order in (("a", order_a), ("b", order_b)):
        marks = {str(n + 1): list(cands[i]) for n, i in enumerate(order)}
        out[name] = {"role": "adjudicator", "prompt": BOX_ADJ_PROMPT, "order": name, "second": int(second),
                     "item": {"clip": item["clip"], "kind": item["kind"], "item_id": item["item_id"],
                              "text": item["text"]},
                     "image": f"{image_root}/{item['clip']}/{item['item_id']}/t{int(second):04d}-{name}.jpg",
                     "marks": marks, "answer_format": BOX_ADJ_FORMAT}
    return out


def _box_choice(packet: Mapping[str, Any], answer: Mapping[str, Any]) -> tuple[Any, float]:
    body = answer.get("answer", answer) if isinstance(answer, Mapping) else {}
    choice, conf = body.get("choice"), float(body.get("confidence", 0))
    if choice in BOX_ADJ_ANSWERS:
        return choice, conf
    if str(choice) in packet["marks"]:
        return tuple(packet["marks"][str(choice)]), conf
    raise C3EV2Error(f"adjudication answer {choice!r} is not a shown mark or {BOX_ADJ_ANSWERS}")


def resolve_box(generated: Sequence[float] | None, validated: Sequence[float] | None,
                adjudication: Mapping[str, tuple[Mapping[str, Any], Mapping[str, Any] | None]] | None,
                has_candidates: bool) -> dict[str, Any]:
    """The tier of one sampled second's box reference.

    ``adjudication`` maps ``a``/``b`` to ``(packet, answer)``. Consensus when both passes chose boxes with IoU >= 0.5;
    adjudicated when both orders name the same box (or both say not visible), each with confidence >= 0.6.
    """
    if generated is not None and validated is not None and boxes.iou(generated, validated) >= AGREE_IOU:
        return {"tier": "consensus", "box": list(generated), "visible": True}
    if not has_candidates:
        return {"tier": "unresolved", "reason": "no candidate box", "box": None}
    if not adjudication or any(answer is None for _, answer in adjudication.values()):
        return {"tier": "pending", "box": None}
    (pa, aa), (pb, ab) = adjudication["a"], adjudication["b"]
    ca, conf_a = _box_choice(pa, aa)
    cb, conf_b = _box_choice(pb, ab)
    if min(conf_a, conf_b) < ADJ_CONFIDENCE:
        return {"tier": "unresolved", "reason": "adjudicator confidence below 0.6", "box": None}
    if ca != cb:
        return {"tier": "unresolved", "reason": "adjudicator inconsistent across orders", "box": None}
    if ca == "cannot_identify":
        return {"tier": "unresolved", "reason": "cannot identify", "box": None}
    if ca == "not_visible":
        return {"tier": "adjudicated", "box": None, "visible": False}
    return {"tier": "adjudicated", "box": list(ca), "visible": True}


def visibility_consensus(generated: Mapping[int, str], validated: Mapping[int, str], second: int) -> str | None:
    """"yes"/"no" when the pass that sampled ``second`` voted clearly and a neighbour of the other pass agrees."""
    own, other = (generated, validated) if second % 2 == 0 else (validated, generated)
    vote = own.get(second)
    if vote not in ("yes", "no"):
        return None
    return vote if vote in (other.get(second - 1), other.get(second + 1)) else None


def visibility_adjudication_seconds(generated: Mapping[int, str], validated: Mapping[int, str], last: int,
                                    sampled: Sequence[int] = ()) -> list[int]:
    """The seconds a visibility adjudication shows: every non-consensus box-sampled second (anchors and decoys, not
    told apart), then evenly spaced non-consensus seconds, up to 12 in all (more only if sampled seconds need it)."""
    open_ = [s for s in range(last + 1) if visibility_consensus(generated, validated, s) is None]
    first = sorted(s for s in set(sampled) if s in open_)
    rest = [s for s in open_ if s not in first]
    room = max(0, VIS_ADJ_MAX_SECONDS - len(first))
    if room and rest:
        step = len(rest) / room
        rest = sorted({rest[min(len(rest) - 1, math.floor(i * step))] for i in range(min(room, len(rest)))})
    else:
        rest = []
    return sorted(first + rest)


def visibility_adjudication_packets(item: Mapping[str, Any], seconds: Sequence[int], image_root: str
                                    ) -> dict[str, dict[str, Any]]:
    """Orders ``a`` and ``b`` of one item's visibility adjudication: 2x2 sheets, tile order shuffled between them."""
    seconds = sorted(int(s) for s in seconds)
    order_a = [seconds[i] for i in _order(f"vis|{item['clip']}|{item['item_id']}", len(seconds))]
    order_b = list(reversed(order_a))
    out = {}
    for name, order in (("a", order_a), ("b", order_b)):
        sheets = [{"sheet": f"{image_root}/{item['clip']}/{item['item_id']}/{name}{n:02d}.jpg",
                   "tiles": [float(t) for t in order[i:i + 4]]} for n, i in enumerate(range(0, len(order), 4))]
        out[name] = {"role": "adjudicator", "prompt": VIS_ADJ_PROMPT, "order": name,
                     "item": {"clip": item["clip"], "kind": item["kind"], "item_id": item["item_id"],
                              "text": item["text"]},
                     "sheets": sheets, "answer_format": VIS_ADJ_FORMAT}
    return out


def visibility_adjudicated(packets: Mapping[str, Mapping[str, Any]], answers: Mapping[str, Mapping[str, Any] | None]
                           ) -> dict[int, dict[str, Any]]:
    """Per adjudicated second: ``{"visible": "yes"/"no", "tier": "adjudicated"}`` when both orders agree with
    confidence >= 0.6, else unresolved with its reason."""
    per: dict[str, dict[int, tuple[str, float]]] = {}
    for name in ("a", "b"):
        answer = answers.get(name)
        if answer is None:
            return {}
        tiles = {t for s in packets[name]["sheets"] for t in s["tiles"]}
        rows = answer.get("answers") if isinstance(answer, Mapping) else None
        if not isinstance(rows, list) or {float(r["t"]) for r in rows} != tiles or len(rows) != len(tiles):
            raise C3EV2Error(f"order {name}: answers must cover every tile exactly once")
        for r in rows:
            if r["visible"] not in VIS_ADJ_ANSWERS:
                raise C3EV2Error(f"order {name}: {r['visible']!r} is not one of {VIS_ADJ_ANSWERS}")
        per[name] = {int(float(r["t"])): (r["visible"], float(r.get("confidence", 0))) for r in rows}
    out = {}
    for s in per["a"]:
        (va, ca), (vb, cb) = per["a"][s], per["b"][s]
        if va == vb and va in ("yes", "no") and min(ca, cb) >= ADJ_CONFIDENCE:
            out[s] = {"tier": "adjudicated", "visible": va}
        else:
            reason = ("cannot identify" if "cannot_identify" in (va, vb) else
                      "adjudicator inconsistent across orders" if va != vb else "adjudicator confidence below 0.6")
            out[s] = {"tier": "unresolved", "reason": reason}
    return out


def visibility_state(second: int, generated: Mapping[int, str], validated: Mapping[int, str],
                     box_tier: Mapping[str, Any] | None, adjudicated: Mapping[int, Mapping[str, Any]]
                     ) -> dict[str, Any]:
    """The visibility tier at one second: pass consensus, then a consensus box (visible), then the visibility
    adjudication, then an adjudicated box answer; otherwise unresolved."""
    vote = visibility_consensus(generated, validated, second)
    if vote is not None:
        return {"tier": "consensus", "visible": vote == "yes"}
    if box_tier and box_tier.get("tier") == "consensus":
        return {"tier": "consensus", "visible": True, "source": "box passes agree"}
    adj = adjudicated.get(second)
    if adj and adj["tier"] == "adjudicated":
        return {"tier": "adjudicated", "visible": adj["visible"] == "yes"}
    if box_tier and box_tier.get("tier") == "adjudicated":
        return {"tier": "adjudicated", "visible": bool(box_tier.get("visible")), "source": "box adjudication"}
    return {"tier": "unresolved", "reason": (adj or {}).get("reason") or "no consensus and not adjudicated"}


def render_adjudication(frames_root: Path | str, clip: str, packet: Mapping[str, Any], out_root: Path | str,
                        frame_end_s: float) -> None:
    """The composite image of a box adjudication packet: the marked frame, and the frames one second either side."""
    from PIL import Image, ImageDraw

    second = int(packet["second"])
    path = lambda t: Path(frames_root) / clip / f"t{float(t):08.3f}.jpg"  # noqa: E731
    main = Image.open(path(second)).convert("RGB")
    w = 1024
    main = main.resize((w, round(main.height * w / main.width)))
    draw = ImageDraw.Draw(main)
    colours = [(255, 64, 64), (64, 200, 255), (255, 210, 0)]
    for n, (number, box) in enumerate(sorted(packet["marks"].items(), key=lambda kv: int(kv[0]))):
        ymin, xmin, ymax, xmax = box
        x1, y1, x2, y2 = xmin / 1000 * main.width, ymin / 1000 * main.height, xmax / 1000 * main.width, ymax / 1000 * main.height
        draw.rectangle([x1, y1, x2, y2], outline=colours[n % 3], width=3)
        draw.rectangle([x1, max(0, y1 - 20), x1 + 26, max(20, y1)], fill=colours[n % 3])
        draw.text((x1 + 5, max(0, y1 - 18)), number, fill=(0, 0, 0))
    draw.rectangle([0, 0, 120, 22], fill=(0, 0, 0))
    draw.text((4, 4), f"t={second}s (marked)", fill=(255, 255, 0))
    half_w, half_h = w // 2, round(main.height / 2)
    sheet = Image.new("RGB", (w, main.height + half_h), (0, 0, 0))
    sheet.paste(main, (0, 0))
    for k, t in enumerate((second - 1, second + 1)):
        if 0 <= t and t < frame_end_s and path(t).exists():
            side = Image.open(path(t)).convert("RGB").resize((half_w, half_h))
            sd = ImageDraw.Draw(side)
            sd.rectangle([0, 0, 70, 20], fill=(0, 0, 0))
            sd.text((4, 4), f"t={t}s", fill=(255, 255, 0))
            sheet.paste(side, (k * half_w, main.height))
    target = Path(out_root) / packet["image"]
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target, quality=90)


def render_visibility_sheet(frames_root: Path | str, clip: str, tiles: Sequence[float], out_path: Path | str) -> None:
    """A 2x2 sheet of native frames at 768 px per tile, each labelled with its time."""
    from PIL import Image, ImageDraw

    images = [Image.open(Path(frames_root) / clip / f"t{float(t):08.3f}.jpg").convert("RGB") for t in tiles]
    w = 768
    h = round(images[0].height * w / images[0].width)
    sheet = Image.new("RGB", (2 * w, math.ceil(len(images) / 2) * h), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    for n, (t, image) in enumerate(zip(tiles, images, strict=True)):
        x, y = (n % 2) * w, (n // 2) * h
        sheet.paste(image.resize((w, h)), (x, y))
        draw.rectangle([x, y, x + 84, y + 24], fill=(0, 0, 0))
        draw.text((x + 4, y + 5), f"t={float(t):.0f}s", fill=(255, 255, 0))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=90)
