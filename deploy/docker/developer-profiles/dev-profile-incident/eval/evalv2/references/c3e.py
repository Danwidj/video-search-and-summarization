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

"""C3-E, the evidence-crop references (``eval/methodology/c3e-preregistration.md``): sampling, packets, records.

No model is called here. The passes are file handoffs (:class:`evalv2.references.passes.FilePass`) a Claude Code
session answers, as for RA1.

- **Box anchors** (:func:`anchors`): every whole second a Track B subject used as the evidence second of a located
  box (``box_seconds``, else ``timestamp_seconds``), per clip and predicted kind. Only the predicted kind and second
  are read: never the item matching, the predicted box or any score.
- **Decoys** (:func:`decoys`): per clip and kind, ``max(1, ceil(A / 4))`` extra seconds for ``A`` anchor seconds,
  seeded, drawn without replacement, half from within 3 s of an anchor and half from the whole clip. They blind the
  annotators to which seconds the pipeline chose and are never scored as evidence.
- **Box packets** (:func:`box_packets`): per ground-truth item of a kind with anchors, RA1's generator packet on the
  anchor and decoy seconds (in one sorted list, unlabelled) and its blind validator packet on the frames 0.5 s later,
  with the cached RA1 detector proposals. Answers become per-second boxes through RA1's own code.
- **Visibility sheets** (:func:`visibility_packets`): per clip, every item of the clip on 3x3 contact sheets, the
  generator on the even seconds and the blind validator on the odd ones; :func:`interval_proposal` merges both into
  proposed visible intervals and flags what a person must look at first.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from evalv2.references import boxes
from evalv2.references.ra1 import items_for

SAMPLER_VERSION = "c3e-sampler-v1"
DECOY_SEED = 20261104
DECOY_RATIO = 4  # one decoy per started block of four anchor seconds
DECOY_NEAR_S = 3
VISIBILITY_STEP_S = 2
SHEET_TILES = 9
VISIBILITY_GENERATOR_PROMPT = "gen-visibility-v1"
VISIBILITY_VALIDATOR_PROMPT = "gen-visibility-validate-v1"
VISIBILITY_ANSWER_FORMAT = {"answers": [{"t": "<tile time>", "visible": {"<item id>": "yes | no | unclear"}}]}
VOTES = ("yes", "no", "unclear")


class C3EError(ValueError):
    """A malformed run, packet or answer for C3-E."""


def items_for_query(row: Mapping[str, Any]) -> str:
    """RA1's detector query for a review item (an entity's type, an instrument's or asset's name)."""
    from evalv2.references.ra1 import detector_query

    label = str(row["text"]).partition(":")[0].strip()
    return detector_query(row["kind"], {"type": label, "name": label})


def evidence_seconds(run_dir: Path | str) -> list[dict[str, Any]]:
    """One row per stored evidence entry of a Track B run: clip, subject, repeat, predicted kind and second.

    The row says whether the entry is a located box (``has_box``); it carries nothing else from the prediction.
    """
    run_dir = Path(run_dir)
    rows, seen = [], set()
    checkpoint = run_dir / "checkpoint.jsonl"
    if not checkpoint.exists():
        return rows
    for line in checkpoint.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        ref = entry.get("prediction_ref") or ""
        if not ref.startswith("pipeline-prediction:") or ref in seen:
            continue
        seen.add(ref)
        digest = ref.split(":", 1)[1]
        path = run_dir / "store" / "objects" / "pipeline-prediction" / digest[:2] / f"{digest}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))["payload"]
        for item in payload.get("evidence") or []:
            second = item.get("box_seconds", item.get("timestamp_seconds"))
            if second is None or item.get("item_type") not in boxes.KINDS:
                continue
            if float(second) != int(float(second)):
                raise C3EError(f"{path}: evidence second {second!r} is not a whole second")
            rows.append({"clip": entry["item_id"], "subject": entry["subject"], "repeat": entry["repeat"],
                         "kind": item["item_type"], "second": int(float(second)),
                         "has_box": bool(item.get("located")) and bool(item.get("bounding_box"))})
    return rows


def anchors(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, list[int]]]:
    """``{clip: {kind: sorted anchor seconds}}`` from the located-box evidence rows of every subject and repeat."""
    out: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        if row["has_box"]:
            out[row["clip"]][row["kind"]].add(int(row["second"]))
    return {clip: {kind: sorted(s) for kind, s in sorted(kinds.items())} for clip, kinds in sorted(out.items())}


def valid_seconds(frame_end_s: float) -> list[int]:
    """Whole seconds with a decodable frame at ``t`` and at ``t + 0.5`` (the validator's frame)."""
    return [s for s in range(int(math.floor(frame_end_s)) + 1) if s + 0.5 < frame_end_s - 1e-9]


def _rng(clip: str, kind: str, seed: int) -> random.Random:
    digest = hashlib.sha256(f"c3e-decoy-v1|{seed}|{clip}|{kind}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def decoys(clip: str, kind: str, kind_anchors: Sequence[int], clip_anchors: Iterable[int], frame_end_s: float, *,
           seed: int = DECOY_SEED) -> list[int]:
    """The decoy seconds of one clip and kind (sorted): see the module docstring for the rule."""
    if not kind_anchors:
        return []
    taken = set(clip_anchors)
    candidates = [s for s in valid_seconds(frame_end_s) if s not in taken]
    want = max(1, math.ceil(len(kind_anchors) / DECOY_RATIO))
    rng, chosen = _rng(clip, kind, seed), []
    for _ in range(want):
        pool = [s for s in candidates if s not in chosen]
        if not pool:
            break
        near = [s for s in pool if any(abs(s - a) <= DECOY_NEAR_S for a in kind_anchors)]
        source = near if near and rng.random() < 0.5 else pool
        chosen.append(rng.choice(source))
    return sorted(chosen)


def plan(gt_index: Mapping[str, Any], clips: Sequence[str], frame_ends: Mapping[str, float],
         evidence: Iterable[Mapping[str, Any]], *, half: str, seed: int = DECOY_SEED) -> dict[str, Any]:
    """The C3-E sampling plan of one half: anchors, decoys and the seconds each item's box packets show."""
    by_clip = anchors(row for row in evidence if row["clip"] in set(clips))
    items = items_for(gt_index, clips)
    sampling, item_times = {}, {}
    for clip in clips:
        kinds = by_clip.get(clip, {})
        clip_anchors = sorted({s for secs in kinds.values() for s in secs})
        valid = set(valid_seconds(frame_ends[clip]))
        entry = {}
        for kind, secs in kinds.items():
            kept = [s for s in secs if s < frame_ends[clip]]
            entry[kind] = {"anchors": kept, "decoys": decoys(clip, kind, kept, clip_anchors, frame_ends[clip], seed=seed),
                           "anchors_without_validator_frame": [s for s in kept if s not in valid]}
        sampling[clip] = entry
        for item in items:
            if item["clip"] == clip and item["kind"] in entry:
                e = entry[item["kind"]]
                item_times[f"{clip}-{item['item_id']}"] = sorted(set(e["anchors"]) | set(e["decoys"]))
    return {"version": SAMPLER_VERSION, "half": half, "seed": seed, "clips": list(clips), "sampling": sampling,
            "item_times": item_times, "items": items, "frame_ends": {c: frame_ends[c] for c in clips}}


def _cached_proposals(proposals_dir: Path, clip: str) -> dict[float, list[boxes.Proposal]]:
    cached = json.loads((Path(proposals_dir) / f"{clip}.json").read_text(encoding="utf-8"))
    return {float(t): [boxes.Proposal(tuple(r["box"]), float(r["score"]), str(r.get("label", ""))) for r in rows]
            for t, rows in cached["frames"].items()}


def box_packets(planned: Mapping[str, Any], proposals_dir: Path | str, *, generator_prompt: str,
                validator_prompt: str) -> list[dict[str, Any]]:
    """Per item with sampled seconds: ``{"key", "item", "generator", "validator"}`` packets (validator blind-checked
    once the generator has answered, by the caller, as in RA1)."""
    out, cache = [], {}
    for item in planned["items"]:
        key = f"{item['clip']}-{item['item_id']}"
        times = planned["item_times"].get(key)
        if not times:
            continue
        clip = item["clip"]
        if clip not in cache:
            cache[clip] = _cached_proposals(Path(proposals_dir), clip)
        found = cache[clip]
        gen_times = [float(t) for t in times]
        val_times = [t + boxes.VALIDATOR_OFFSET_S for t in gen_times if t + boxes.VALIDATOR_OFFSET_S < planned["frame_ends"][clip] - 1e-9]
        missing = [t for t in gen_times + val_times if t not in found]
        if missing:
            raise C3EError(f"{clip}: no cached detector proposals at {missing[:5]}")
        query = item["query"]
        pick = lambda ts: {t: [p for p in found[t] if p.label.strip().lower() == query] for t in ts}  # noqa: E731
        out.append({"key": key, "item": item,
                    "generator": boxes.generator_packet(item, gen_times, pick(gen_times), prompt_id=generator_prompt),
                    "validator": boxes.validator_packet(item, val_times, pick(val_times), prompt_id=validator_prompt)})
    return out


def visibility_packets(gt_index: Mapping[str, Any], clips: Sequence[str], frame_ends: Mapping[str, float],
                       ) -> list[dict[str, Any]]:
    """Per clip: the generator packet (even seconds) and the blind validator packet (odd seconds), each listing the
    clip's items in ground-truth words and its 3x3 sheets. The packets name their sheet images; nothing else."""
    out = []
    for clip in clips:
        items = [{"item_id": i["item_id"], "kind": i["kind"], "text": i["text"]} for i in items_for(gt_index, [clip])]
        if not items:
            continue
        seconds = [s for s in range(int(math.floor(frame_ends[clip])) + 1) if s < frame_ends[clip] - 1e-9]
        packets = {}
        for role, parity, prompt in (("generator", 0, VISIBILITY_GENERATOR_PROMPT),
                                     ("validator", 1, VISIBILITY_VALIDATOR_PROMPT)):
            times = [float(s) for s in seconds if s % VISIBILITY_STEP_S == parity]
            sheets = [{"sheet": f"{clip}/visibility/{role}/sheet{n:03d}.jpg", "tiles": times[i:i + SHEET_TILES]}
                      for n, i in enumerate(range(0, len(times), SHEET_TILES))]
            packets[role] = {"role": role, "prompt": prompt, "clip": clip, "items": items, "sheets": sheets,
                             "answer_format": VISIBILITY_ANSWER_FORMAT}
        out.append({"clip": clip, **packets})
    return out


def assert_visibility_blind(validator: Mapping[str, Any], generator: Mapping[str, Any]) -> None:
    """The validator packet shows the same items, none of the generator's frames and no answer field."""
    if validator.get("role") != "validator" or generator.get("role") != "generator":
        raise C3EError("packets must be a generator and a validator packet")
    if validator["items"] != generator["items"] or validator["clip"] != generator["clip"]:
        raise C3EError("the validator packet shows other items")
    gen_times = {t for s in generator["sheets"] for t in s["tiles"]}
    if gen_times & {t for s in validator["sheets"] for t in s["tiles"]}:
        raise C3EError("the validator packet shows a frame the generator saw")
    text = json.dumps({k: v for k, v in validator.items() if k != "answer_format"}, sort_keys=True)
    if '"answers"' in text or '"visible"' in text:
        raise C3EError("the validator packet holds an answer field")


def visibility_votes(packet: Mapping[str, Any], answer: Mapping[str, Any]) -> dict[str, dict[int, str]]:
    """``{item id: {second: vote}}`` from one pass's answer; every tile and item must be answered exactly once."""
    rows = answer.get("answers") if isinstance(answer, Mapping) else None
    if not isinstance(rows, list):
        raise C3EError('a visibility answer is {"answers": [...]} with one entry per tile')
    tiles = [t for s in packet["sheets"] for t in s["tiles"]]
    ids = [i["item_id"] for i in packet["items"]]
    by_t = {}
    for row in rows:
        t = float(row["t"])
        if t in by_t:
            raise C3EError(f"tile {t} answered twice")
        by_t[t] = row.get("visible") or {}
    if sorted(by_t) != sorted(tiles):
        raise C3EError(f"answers cover tiles {sorted(by_t)[:6]}..., the packet {sorted(tiles)[:6]}...")
    votes: dict[str, dict[int, str]] = {i: {} for i in ids}
    for t, visible in by_t.items():
        if set(visible) != set(ids):
            raise C3EError(f"tile {t}: answers name {sorted(visible)}, the packet's items are {sorted(ids)}")
        for item_id, vote in visible.items():
            if vote not in VOTES:
                raise C3EError(f"tile {t} item {item_id}: vote {vote!r} is not one of {VOTES}")
            votes[item_id][int(t)] = vote
    return votes


def interval_proposal(generated: Mapping[int, str], validated: Mapping[int, str], frame_end_s: float
                      ) -> dict[str, Any]:
    """Proposed visible spans of one item from the two passes' votes, with the flags a reviewer looks at first.

    A second is visible when its vote is "yes". An "unclear" second, or a second neither pass voted on, between two
    visible seconds is bridged. Flags: ``flicker`` (a vote that differs from both neighbours, which are the other
    pass's seconds), ``unclear`` (any unclear vote), ``never_visible`` and ``always_visible``.
    """
    last = int(math.floor(frame_end_s - 1e-9))
    votes = {**{int(s): v for s, v in generated.items()}, **{int(s): v for s, v in validated.items()}}
    state = [votes.get(s) for s in range(last + 1)]
    visible = [v == "yes" for v in state]
    for s in range(1, last):
        if not visible[s] and state[s] in (None, "unclear") and visible[s - 1] and visible[s + 1]:
            visible[s] = True
    spans, start = [], None
    for s, on in enumerate(visible + [False]):
        if on and start is None:
            start = s
        if not on and start is not None:
            spans.append([start, s - 1])
            start = None
    flicker = [s for s in range(1, last) if state[s] in ("yes", "no") and state[s - 1] in ("yes", "no")
               and state[s + 1] in ("yes", "no") and state[s] != state[s - 1] and state[s] != state[s + 1]]
    flags = []
    if flicker:
        flags.append("flicker")
    if any(v == "unclear" for v in state):
        flags.append("unclear")
    if not spans:
        flags.append("never_visible")
    if spans == [[0, last]]:
        flags.append("always_visible")
    return {"visible_spans": spans, "flicker_seconds": flicker,
            "unclear_seconds": [s for s, v in enumerate(state) if v == "unclear"], "flags": flags}


def render_sheet(frames_root: Path | str, clip: str, tiles: Sequence[float], out_path: Path | str, *,
                 tile_width: int = 512) -> None:
    """A 3x3 contact sheet of the clip's native frames at ``tiles``, each labelled with its time (PIL only)."""
    from PIL import Image, ImageDraw

    images = [Image.open(Path(frames_root) / clip / f"t{float(t):08.3f}.jpg").convert("RGB") for t in tiles]
    w = tile_width
    h = round(images[0].height * w / images[0].width)
    sheet = Image.new("RGB", (3 * w, math.ceil(len(images) / 3) * h), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    for n, (t, image) in enumerate(zip(tiles, images, strict=True)):
        x, y = (n % 3) * w, (n // 3) * h
        sheet.paste(image.resize((w, h)), (x, y))
        draw.rectangle([x, y, x + 74, y + 22], fill=(0, 0, 0))
        draw.text((x + 4, y + 4), f"t={float(t):.0f}s", fill=(255, 255, 0))
        draw.rectangle([x, y, x + w - 1, y + h - 1], outline=(80, 80, 80))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=88)


def draw_marks(frames_root: Path | str, clip: str, frame: Mapping[str, Any], out_path: Path | str, *,
               width: int = 1024) -> None:
    """One packet frame with its numbered marks drawn (PIL only; the same picture as ``v2_box_frames.py draw``)."""
    from PIL import Image, ImageDraw

    image = Image.open(Path(frames_root) / clip / f"t{float(frame['t']):08.3f}.jpg").convert("RGB")
    scale = width / image.width
    image = image.resize((width, round(image.height * scale)))
    draw = ImageDraw.Draw(image)
    colours = [(255, 64, 64), (64, 200, 255), (255, 210, 0), (120, 255, 120), (255, 120, 255), (255, 160, 60)]
    for n, (number, box) in enumerate(sorted(frame["marks"].items(), key=lambda kv: int(kv[0]))):
        ymin, xmin, ymax, xmax = box  # the agent's convention, 0-1000 (as scripts/v2_box_frames.py draw)
        x1, y1 = xmin / 1000 * image.width, ymin / 1000 * image.height
        x2, y2 = xmax / 1000 * image.width, ymax / 1000 * image.height
        colour = colours[n % len(colours)]
        draw.rectangle([x1, y1, x2, y2], outline=colour, width=3)
        draw.rectangle([x1, max(0, y1 - 20), x1 + 26, max(20, y1)], fill=colour)
        draw.text((x1 + 5, max(0, y1 - 18)), str(number), fill=(0, 0, 0))
    draw.rectangle([0, 0, 90, 22], fill=(0, 0, 0))
    draw.text((4, 4), f"t={float(frame['t']):.1f}s", fill=(255, 255, 0))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, quality=90)
