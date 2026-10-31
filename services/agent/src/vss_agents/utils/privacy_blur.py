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

"""Privacy blur for stored incident evidence (``blur_faces`` on ``/analyze``).

No face model: a face is blurred by blurring the head of every person the analysis knows about at the second a
frame was read. The heads come from two places, in order:

1. **Person tracks** (``INCIDENT_TRACKING_ENABLED``): the head region (:func:`head_region`, the top
   :data:`HEAD_FRACTION` of the box, padded) of every track's visible sample within :data:`TRACK_WINDOW_SECONDS` of
   the frame's second, from all tracks, not only those matched to a report entity. Tracker-only boxes that drift
   away from the last real detection are not blurred.
2. **The open-vocabulary detector**: for a person item no *solid* track head covers (a ghost track does not count),
   one ``detect`` call for ``"the head of <label>"`` on the unblurred frame (one call against the request's
   ``CropCallBudget`` when it has one). The detected head is blurred wherever it is, because the item's own box may
   be wrong; the head region of the item's own box is blurred too unless the detected head sits inside it, and is
   the only head when the detector finds nothing.

Every stored frame is blurred on all those heads at its second (a person item's heads also apply to the other
items' frames at the same second), and the crop is cut from the blurred frame, so a crop of an object shows a
blurred head only where one overlaps it. The blur is a strong pixelation (:data:`PIXEL_BLOCKS` blocks across the
region). It runs on the decoded frame before the JPEG is encoded, so no unblurred head reaches storage; the
zoomed second look and every model call still see the unblurred image.
"""

from collections.abc import Iterable
from collections.abc import Sequence
from dataclasses import dataclass
import math
from typing import Any

import cv2
import numpy as np

from vss_agents.utils import track_evidence

Box = tuple[int, int, int, int]  # [ymin, xmin, ymax, xmax] normalised to 0..1000

# The head is the top part of a person box: 30 % of its height, widened and raised by 10 % of the box so a head at
# the box edge (a detector box often cuts the crown) is still covered.
HEAD_FRACTION = 0.3
HEAD_PADDING = 0.1
# A detector head box is padded by a quarter of its own size on every side.
DETECTED_HEAD_PADDING = 0.25
# A track sample counts for a frame when it is this close to the frame's second (the tracks hold five samples a second).
TRACK_WINDOW_SECONDS = 0.5
# The blurred region is reduced to at most this many blocks across its longer side, then scaled back.
PIXEL_BLOCKS = 6
HEAD_QUERY = "the head of {label}"


def _clamp(value: float) -> int:
    return max(0, min(1000, round(value)))


def valid_box(box: Sequence[float]) -> bool:
    """Four coordinates with a positive height and width."""
    return len(box) == 4 and box[0] < box[2] and box[1] < box[3]


def pad_box(box: Sequence[float], fraction: float) -> Box:
    """``box`` grown by ``fraction`` of its own height and width on every side, clamped to 0..1000."""
    ymin, xmin, ymax, xmax = box
    dy, dx = (ymax - ymin) * fraction, (xmax - xmin) * fraction
    return (_clamp(ymin - dy), _clamp(xmin - dx), _clamp(ymax + dy), _clamp(xmax + dx))


def head_region(box: Sequence[float]) -> Box:
    """The head region of a person ``box``: its top :data:`HEAD_FRACTION`, padded by :data:`HEAD_PADDING`.

    The region is raised and widened by ``HEAD_PADDING`` of the box's height and width, and clamped to the frame.
    """
    ymin, xmin, ymax, xmax = box
    height, width = ymax - ymin, xmax - xmin
    return (
        _clamp(ymin - HEAD_PADDING * height),
        _clamp(xmin - HEAD_PADDING * width),
        _clamp(ymin + HEAD_FRACTION * height),
        _clamp(xmax + HEAD_PADDING * width),
    )


def centre_inside(region: Sequence[float], box: Sequence[float]) -> bool:
    """Whether the centre of ``region`` lies inside ``box`` (edges included)."""
    cy, cx = (region[0] + region[2]) / 2, (region[1] + region[3]) / 2
    return box[0] <= cy <= box[2] and box[1] <= cx <= box[3]


def overlaps(a: Sequence[float], b: Sequence[float]) -> bool:
    """Whether two boxes share any area."""
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def track_heads_at(
    tracks: Iterable[track_evidence.Track],
    seconds: float,
    window: float = TRACK_WINDOW_SECONDS,
    solid_only: bool = False,
) -> list[Box]:
    """The head region of every track's visible sample nearest to ``seconds``, for tracks with one within ``window``.

    Visible samples are real detections and tracker-only boxes soon after one (:func:`track_evidence.visible_samples`):
    a ghost track's drifting boxes blur nothing. With ``solid_only`` only solid tracks count
    (:func:`track_evidence.is_solid`), which is what decides whether a person's head is known from the tracks.
    """
    heads: list[Box] = []
    for track in tracks:
        if solid_only and not track_evidence.is_solid(track):
            continue
        samples = track_evidence.visible_samples(track)
        if not samples:
            continue
        nearest = min(samples, key=lambda sample: abs(sample.t - seconds))
        if abs(nearest.t - seconds) <= window and valid_box(nearest.box):
            heads.append(head_region(nearest.box))
    return heads


def unique_regions(regions: Iterable[Sequence[float]]) -> list[Box]:
    """Valid regions in first-seen order, without exact duplicates."""
    seen: dict[Box, None] = {}
    for region in regions:
        if len(region) == 4:
            box: Box = (_clamp(region[0]), _clamp(region[1]), _clamp(region[2]), _clamp(region[3]))
            if valid_box(box):
                seen.setdefault(box, None)
    return list(seen)


def pixel_box(region: Sequence[float], frame_w: int, frame_h: int) -> tuple[int, int, int, int]:
    """A normalised region as clamped pixel ``(y0, x0, y1, x1)``, rounded outwards so the region is fully covered."""
    y0 = max(0, math.floor(region[0] * frame_h / 1000.0))
    x0 = max(0, math.floor(region[1] * frame_w / 1000.0))
    y1 = min(frame_h, math.ceil(region[2] * frame_h / 1000.0))
    x1 = min(frame_w, math.ceil(region[3] * frame_w / 1000.0))
    return y0, x0, y1, x1


def _pixelate(patch: np.ndarray) -> np.ndarray:
    height, width = patch.shape[:2]
    block = max(1, math.ceil(max(height, width) / PIXEL_BLOCKS))
    small = (max(1, math.ceil(width / block)), max(1, math.ceil(height / block)))
    reduced = cv2.resize(patch, small, interpolation=cv2.INTER_AREA)
    return np.asarray(cv2.resize(reduced, (width, height), interpolation=cv2.INTER_NEAREST))


def blur_frame(frame: np.ndarray, regions: Iterable[Sequence[float]]) -> np.ndarray:
    """A copy of ``frame`` with every normalised region pixelated; ``frame`` itself is never changed."""
    blurred = frame.copy()
    frame_h, frame_w = frame.shape[:2]
    for region in regions:
        y0, x0, y1, x1 = pixel_box(region, frame_w, frame_h)
        if y0 < y1 and x0 < x1:
            blurred[y0:y1, x0:x1] = _pixelate(np.ascontiguousarray(blurred[y0:y1, x0:x1]))
    return blurred


@dataclass
class PrivacySummary:
    """What ``/analyze`` reports about the privacy blur (``privacy``) of a request that asked for it."""

    blur_faces: bool = True
    regions: int = 0  # head regions blurred, counted per stored frame
    frames: int = 0  # stored frames that had at least one region blurred
    track_heads: int = 0  # person items whose head came from a track
    detector_heads: int = 0  # person items whose head the detector found
    box_heads: int = 0  # person items whose head is the top of their own box (the detector found none)
    unblurred_people: int = 0  # person items with no head anywhere (not located, and the detector found none)
    head_queries: int = 0  # detector calls asking for a head
    failed: int = 0  # items whose images were dropped because the blur failed (never stored unblurred)

    def to_dict(self) -> dict[str, Any]:
        return {
            "blur_faces": self.blur_faces,
            "regions": self.regions,
            "frames": self.frames,
            "heads": {
                "track": self.track_heads,
                "detector": self.detector_heads,
                "box": self.box_heads,
                "none": self.unblurred_people,
            },
            "head_queries": self.head_queries,
            "failed": self.failed,
        }
