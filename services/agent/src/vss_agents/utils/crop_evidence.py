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

"""Evidence crop service for natural-language search (MVP2 VM Step 3).

Finds each object in the video frame at VLM timestamp_seconds with an open-vocabulary detector port
(retrying one and two seconds either side when it finds nothing; each second tried is one budgeted detector
call), and stores two images per item through EvidenceStore (R2 in production): the whole frame at the video's
native size, which the console shows with the box drawn on it, and the object crop (5% margin padding clamped to
the frame, JPEG quality 85), which only evidence search embeds. When the object is not found the frame is stored
alone and the entry says so. The entries become the evidence of the AI revision the analysis run writes; the
console builds the searchable ``evidence_crops`` rows from a revision's evidence when it is made official.

Zoomed second look (``INCIDENT_ZOOM_NAMES_ENABLED``, default on): the whole-clip VLM pass names each item at
thumbnail resolution, so a crumpled bag seen at 25 pixels can become "soccer ball". Once an item is located, the
item is cut from the frame at native resolution with a 25% margin (upscaled to a short side of at least 256 px for
the model only; the stored crop is unchanged) and the same VLM the grounding detector uses is asked, with the
report's current name and description, to confirm or correct them. A correction is applied to the evidence entry
and to the matching item of the report payload when the model says ``changed`` with confidence at least 0.7; the
item id, label, timestamps and an entity's ``type`` are never changed. Zoom calls are outside ``CropCallBudget``
(the grounding cap of an experimental request) and a failed or slow call never fails the analysis.
"""

from abc import ABC
from abc import abstractmethod
import asyncio
import base64
from collections.abc import Iterable
from collections.abc import Sequence
import copy
from dataclasses import dataclass
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import threading
import time
from typing import Any
from typing import Protocol
from typing import runtime_checkable

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
import httpx
import numpy as np
from PIL import Image

from vss_agents.utils.optional_cv2 import ensure_codecs
from vss_agents.utils.r2 import get_r2_client
from vss_agents.utils.r2 import is_r2_configured

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Detection:
    """Bounding box detection produced by an open-vocabulary detector."""

    box: list[int]  # [ymin, xmin, ymax, xmax] normalized 0-1000
    score: float
    label: str = ""


@dataclass(frozen=True)
class CropResult:
    """One evidence item's frame and crop with the spatial grounding metadata.

    ``located`` is False when the detector found nothing at any second tried: the frame is kept, ``image_bytes``
    and ``normalized_box`` are None (never a whole-frame box), and ``box_seconds`` is the requested second.
    """

    image_bytes: bytes | None  # the object crop (evidence search embeds it); None when not located
    normalized_box: list[int] | None  # [ymin, xmin, ymax, xmax] normalized 0-1000; None when not located
    score: float
    frame_size: tuple[int, int]  # (width, height)
    frame_bytes: bytes | None = None  # the whole frame the box was found in, at the video's native size
    box_seconds: float | None = None  # the second the frame was read at (the requested one unless a retry hit)
    located: bool = True
    zoom_bytes: bytes | None = None  # the close-up the second look names (25% margin, upscaled); never stored


# Seconds tried, in order, around the requested one when the detector finds nothing there.
LOCATE_RETRY_OFFSETS: tuple[int, ...] = (1, -1, 2, -2)
FRAME_JPEG_QUALITY = 90
# Zoomed second look: the close-up's margin around the located box, the smallest short side the model sees, the
# confidence a correction needs before it is applied, and the flag that turns the second look off.
ZOOM_NAMES_ENV = "INCIDENT_ZOOM_NAMES_ENABLED"
ZOOM_CROP_PADDING = 0.25
ZOOM_MIN_SHORT_SIDE = 256
ZOOM_CONFIDENCE_THRESHOLD = 0.7
ZOOM_TIMEOUT_SECONDS = 60.0
_FALSE_FLAG_VALUES = frozenset({"0", "false", "no", "off"})


def zoom_names_enabled() -> bool:
    """Whether the zoomed second look runs: ``INCIDENT_ZOOM_NAMES_ENABLED`` unset or anything but 0/false/no/off."""
    return os.getenv(ZOOM_NAMES_ENV, "1").strip().lower() not in _FALSE_FLAG_VALUES


@dataclass(frozen=True)
class ZoomVerdict:
    """The second look's reply for one item: the name and description it stands by, and how sure it is."""

    name: str
    description: str
    confidence: float
    changed: bool


def parse_zoom_reply(data: dict[str, Any]) -> ZoomVerdict:
    """A strict ``{name, description, confidence, changed}`` object; anything else raises ``ValueError``."""
    name = data.get("name")
    description = data.get("description")
    confidence = data.get("confidence")
    changed = data.get("changed")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("zoom reply has no name")
    if not isinstance(description, str):
        raise ValueError("zoom reply has no description")
    if isinstance(confidence, bool) or not isinstance(confidence, int | float) or not 0.0 <= float(confidence) <= 1.0:
        raise ValueError(f"zoom reply confidence is not a number in 0..1: {confidence!r}")
    if not isinstance(changed, bool):
        raise ValueError(f"zoom reply changed is not a boolean: {changed!r}")
    return ZoomVerdict(
        name=" ".join(name.split()), description=description.strip(), confidence=float(confidence), changed=changed
    )


@runtime_checkable
class ZoomNamer(Protocol):
    """Port for the zoomed second look: one VLM call that names a close-up of a located item."""

    def zoom_name(self, jpeg: bytes, *, item_type: str, name: str, description: str) -> ZoomVerdict:
        """Confirm or correct ``name`` and ``description`` of an ``item_type`` item shown in the close-up ``jpeg``."""
        ...


def zoom_prompt(item_type: str, name: str, description: str) -> str:
    """The second-look question for one item; an entity's type is fixed, so only its description may change."""
    if item_type == "entity":
        subject = (
            f'This close-up shows an entity of type "{name}" from an incident report. The type is fixed and is not '
            f'yours to change. Current description: "{description}".'
        )
        task = (
            "If the description is wrong or misleading for what is visible, correct it in one sentence; otherwise "
            'keep it. Reply with the type unchanged as "name".'
        )
    else:
        subject = (
            f'This close-up shows an {item_type} from an incident report. Current name: "{name}". Current '
            f'description: "{description}".'
        )
        task = (
            "If the name or description is wrong for what is visible, correct them (a name is one to four plain "
            "words; a description is one sentence); otherwise keep them."
        )
    return (
        f"{subject} Judge only what is visible in this close-up. {task} Return JSON only, in the form "
        '{"name": "<name>", "description": "<description>", "confidence": <0 to 1: how sure you are of your '
        'name and description>, "changed": <true when either differs from the current one>}.'
    )


def zoom_crop(frame: np.ndarray, box: Sequence[int | float]) -> bytes | None:
    """The close-up the second look names: ``box`` cut from ``frame`` at native resolution with a 25% margin.

    A small cut is upscaled so its short side is at least ``ZOOM_MIN_SHORT_SIDE`` pixels (bicubic), which only
    helps the model read it; the stored evidence crop is cut separately and never upscaled.
    """
    frame_h, frame_w = frame.shape[:2]
    c_ymin, c_xmin, c_ymax, c_xmax = apply_box_padding(box, frame_w, frame_h, padding_fraction=ZOOM_CROP_PADDING)
    if c_ymin >= c_ymax or c_xmin >= c_xmax:
        return None
    cut = np.ascontiguousarray(frame[c_ymin:c_ymax, c_xmin:c_xmax])
    short_side = min(cut.shape[:2])
    if 0 < short_side < ZOOM_MIN_SHORT_SIDE:
        scale = ZOOM_MIN_SHORT_SIDE / short_side
        size = (max(1, round(cut.shape[1] * scale)), max(1, round(cut.shape[0] * scale)))
        cut = np.asarray(Image.fromarray(cut[..., ::-1]).resize(size, Image.Resampling.BICUBIC))[..., ::-1]
        cut = np.ascontiguousarray(cut)
    return encode_jpeg(cut, quality=85)


def evidence_key(video_key: str, batch_id: str, item_id: str) -> str:
    """Return the R2 key for one evidence crop image: ``evidence/<video key>/<batchId>/<itemId>.jpg``.

    ``video_key`` is the video's own R2 key (``uploads/clip.mp4``), so the path reads like the video.
    ``batch_id`` is ``run-<n>``, one per analysis run of that video (:meth:`EvidenceStore.next_batch_id`),
    so a key is never reused and an image a revision references is never overwritten. Item ids
    (``E1``, ``I1``, ``A1``) are unique across the three collections, so no collection folder is needed.
    """
    return f"evidence/{video_key}/{batch_id}/{item_id}.jpg"


def evidence_frame_key(video_key: str, batch_id: str, item_id: str) -> str:
    """Return the R2 key for one evidence item's whole frame: ``evidence/<video key>/<batchId>/<itemId>-frame.jpg``."""
    return f"evidence/{video_key}/{batch_id}/{item_id}-frame.jpg"


_BATCH_PATTERN = re.compile(r"^run-(\d+)$")


def next_run_batch_id(existing_batch_ids: Iterable[str]) -> str:
    """The batch id after the highest ``run-<n>`` in ``existing_batch_ids`` (``run-1`` when none)."""
    highest = 0
    for batch_id in existing_batch_ids:
        match = _BATCH_PATTERN.match(batch_id)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"run-{highest + 1}"


def apply_box_padding(
    box: Sequence[int | float],
    frame_w: int,
    frame_h: int,
    padding_fraction: float = 0.05,
) -> tuple[int, int, int, int]:
    """Denormalize coordinates and apply margin padding clamped to the frame boundaries.

    Args:
        box: [ymin, xmin, ymax, xmax] coordinates normalized to 0-1000.
        frame_w: Frame width in pixels.
        frame_h: Frame height in pixels.
        padding_fraction: Fractional padding margin (default 0.05 = 5%).

    Returns:
        Pixel coordinates (c_ymin, c_xmin, c_ymax, c_xmax) clamped to frame boundaries.
    """
    if len(box) != 4:
        raise ValueError(f"Expected 4 bounding box coordinates, got {len(box)}")

    ymin, xmin, ymax, xmax = box

    # Denormalize from 0-1000 to pixel coordinates
    p_ymin = round(ymin * frame_h / 1000.0)
    p_xmin = round(xmin * frame_w / 1000.0)
    p_ymax = round(ymax * frame_h / 1000.0)
    p_xmax = round(xmax * frame_w / 1000.0)

    bw = p_xmax - p_xmin
    bh = p_ymax - p_ymin
    px = max(1, round(bw * padding_fraction)) if bw > 0 else 0
    py = max(1, round(bh * padding_fraction)) if bh > 0 else 0

    c_ymin = max(0, p_ymin - py)
    c_xmin = max(0, p_xmin - px)
    c_ymax = min(frame_h, p_ymax + py)
    c_xmax = min(frame_w, p_xmax + px)

    return c_ymin, c_xmin, c_ymax, c_xmax


def normalize_box(
    c_ymin: int,
    c_xmin: int,
    c_ymax: int,
    c_xmax: int,
    frame_w: int,
    frame_h: int,
) -> list[int]:
    """Convert clamped pixel coordinates back to 0-1000 normalized integers."""
    if frame_h <= 0 or frame_w <= 0:
        return [0, 0, 0, 0]
    return [
        max(0, min(1000, round(c_ymin * 1000.0 / frame_h))),
        max(0, min(1000, round(c_xmin * 1000.0 / frame_w))),
        max(0, min(1000, round(c_ymax * 1000.0 / frame_h))),
        max(0, min(1000, round(c_xmax * 1000.0 / frame_w))),
    ]


def extract_frame(video_ref: str | Path, timestamp_seconds: int | float) -> np.ndarray | None:
    """Extract a single BGR video frame at the given timestamp in seconds.

    Supports local file paths and video URLs via OpenCV VideoCapture.
    """
    ensure_codecs(cv2)
    path_str = str(video_ref)
    cap = cv2.VideoCapture(path_str)
    if not cap.isOpened():
        logger.warning("Could not open video_ref: %s", path_str)
        return None

    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if fps > 0 and total_frames > 0:
            target_frame = min(total_frames - 1, max(0, math.floor(timestamp_seconds * fps)))
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        else:
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(timestamp_seconds * 1000.0)))

        ret, frame = cap.read()
        if not ret or frame is None or frame.size == 0:
            logger.warning("Could not read frame at %ss from %s", timestamp_seconds, path_str)
            return None
        return frame
    finally:
        cap.release()


def encode_jpeg(frame_crop: np.ndarray, quality: int = 85) -> bytes | None:
    """Encode an image crop as JPEG bytes with the specified quality (quality 85)."""
    if cv2 is not None:
        success, buf = cv2.imencode(".jpg", frame_crop, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if success and buf is not None:
            return bytes(buf.tobytes())

    try:
        if len(frame_crop.shape) == 3 and frame_crop.shape[2] == 3:
            rgb_crop = cv2.cvtColor(frame_crop, cv2.COLOR_BGR2RGB) if cv2 is not None else frame_crop[..., ::-1]
            img = Image.fromarray(rgb_crop)
        else:
            img = Image.fromarray(frame_crop)
        bio = io.BytesIO()
        img.save(bio, format="JPEG", quality=quality)
        return bio.getvalue()
    except Exception as exc:
        logger.warning("Failed to encode crop as JPEG: %s", exc)
        return None


@runtime_checkable
class OpenVocabularyDetector(Protocol):
    """Port interface for open-vocabulary object detectors."""

    def detect(self, frame: np.ndarray, query: str) -> Sequence[Detection | dict[str, Any]]:
        """Run detection on the frame with the given text query."""
        ...


DEFAULT_GROUNDING_BASE_URL = "https://switchyard-13doh4lsz.brevlab.com"
DEFAULT_GROUNDING_MODEL = "nvidia/cosmos-3-super-reasoner"
GROUNDING_MAX_EDGE_PIXELS = 1280
GROUNDING_MAX_ATTEMPTS = 4
# Items of one report cropped at once; each crop is a blocking frame read plus a grounding call.
EVIDENCE_CROP_CONCURRENCY = 4
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$")


class CropCallCapReachedError(RuntimeError):
    """An experimental request used up its grounding-call cap; the item keeps an ``image_gap``."""


class CropCallBudget:
    """The grounding HTTP attempts one experimental request may make (retries included), and what they used.

    One budget is shared by the request's concurrent crops, which run in worker threads, so it is locked.
    An attempt beyond ``limit`` is refused before it is sent (``CropCallCapReachedError``).
    """

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("a crop-call cap must be at least 1")
        self.limit = limit
        self.calls = 0
        self.refused = 0
        self.tokens = 0
        self.calls_without_usage = 0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            if self.calls >= self.limit:
                self.refused += 1
                raise CropCallCapReachedError(f"crop-call cap of {self.limit} reached")
            self.calls += 1

    def record_response(self, resp: httpx.Response) -> None:
        """Count the tokens a sent attempt reported; a reply without usage (other than a 429) is counted as such."""
        try:
            usage = resp.json().get("usage") or {}
        except (ValueError, AttributeError):
            usage = {}
        total = int(
            usage.get("total_tokens") or (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
        )
        with self._lock:
            if total:
                self.tokens += total
            elif resp.status_code != 429:
                self.calls_without_usage += 1

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "cap": self.limit,
                "calls": self.calls,
                "refused_by_cap": self.refused,
                "cap_reached": self.refused > 0,
                "tokens": self.tokens,
                "calls_without_usage": self.calls_without_usage,
            }


class BudgetedDetector:
    """Any detector under a ``CropCallBudget``: one budgeted call per ``detect``."""

    def __init__(self, detector: Any, budget: CropCallBudget) -> None:
        self.detector = detector
        self.budget = budget

    def is_available(self) -> bool:
        return bool(self.detector.is_available()) if hasattr(self.detector, "is_available") else True

    def detect(self, frame: np.ndarray, query: str) -> Sequence[Detection | dict[str, Any]]:
        self.budget.acquire()
        detections: Sequence[Detection | dict[str, Any]] = (
            self.detector.detect(frame, query) if hasattr(self.detector, "detect") else self.detector(frame, query)
        )
        return detections


def with_call_budget(detector: Any, budget: CropCallBudget) -> Any:
    """The detector for one budgeted request; ``DefaultDetector`` counts every HTTP attempt, including retries."""
    if isinstance(detector, DefaultDetector):
        return detector.with_call_budget(budget)
    return BudgetedDetector(detector, budget)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating Markdown code fences."""
    parsed = json.loads(_JSON_FENCE_PATTERN.sub("", text.strip()))
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected a JSON object, got {type(parsed).__name__}")
    return parsed


class DefaultDetector:
    """Open-vocabulary detector backed by the remote vision-language model.

    Sends the video frame and the item label to an OpenAI-compatible chat completions endpoint
    (Brev Switchyard) and asks for one tight bounding box, so no local detector weights are needed.
    Settings: ``VLM_GATEWAY_BASE_URL`` or ``VLM_BASE_URL``, ``VLM_GATEWAY_API_KEY`` or ``OPENAI_API_KEY``,
    and ``VLM_NAME`` (each overridable through the constructor).
    """

    def __init__(
        self,
        model_name: str | None = None,
        min_score: float = 0.2,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        call_budget: CropCallBudget | None = None,
    ) -> None:
        self.model_name = model_name or os.getenv("VLM_NAME") or DEFAULT_GROUNDING_MODEL
        self.min_score = min_score
        self.base_url = (
            base_url or os.getenv("VLM_GATEWAY_BASE_URL") or os.getenv("VLM_BASE_URL") or DEFAULT_GROUNDING_BASE_URL
        ).rstrip("/")
        self.api_key = (
            api_key if api_key is not None else os.getenv("VLM_GATEWAY_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        )
        self.timeout_seconds = timeout_seconds
        self.call_budget = call_budget

    def with_call_budget(self, budget: CropCallBudget) -> "DefaultDetector":
        """A copy for one request whose HTTP attempts draw on ``budget`` (the shared detector is unchanged)."""
        budgeted = copy.copy(self)
        budgeted.call_budget = budget
        return budgeted

    def is_available(self) -> bool:
        """Return True if the remote VLM endpoint is configured with credentials."""
        return bool(self.api_key)

    def _chat_url(self) -> str:
        root = self.base_url[: -len("/v1")] if self.base_url.endswith("/v1") else self.base_url
        return f"{root}/v1/chat/completions"

    def _request_box(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST the grounding request, retrying rate limits, server errors and unparseable replies."""
        for attempt in range(1, GROUNDING_MAX_ATTEMPTS + 1):
            if self.call_budget is not None:
                self.call_budget.acquire()  # before sending: a refused attempt is never made
            resp = httpx.post(
                self._chat_url(),
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout_seconds,
            )
            if self.call_budget is not None:
                self.call_budget.record_response(resp)
            last_attempt = attempt == GROUNDING_MAX_ATTEMPTS
            if resp.status_code in _RETRYABLE_STATUS_CODES and not last_attempt:
                time.sleep(float(resp.headers.get("retry-after") or 2.0 * attempt))
                continue
            resp.raise_for_status()
            try:
                return parse_json_object(resp.json()["choices"][0]["message"]["content"])
            except ValueError:
                if last_attempt:
                    raise
                logger.warning("Unparseable grounding reply (attempt %d); retrying", attempt)
        raise RuntimeError("unreachable")  # pragma: no cover

    def zoom_name(self, jpeg: bytes, *, item_type: str, name: str, description: str) -> ZoomVerdict:
        """One second-look call on the same endpoint and model as grounding; outside any ``CropCallBudget``.

        A single attempt with its own, shorter timeout: the caller treats any error as "not checked" and the
        analysis stands. Raises ``httpx.HTTPError`` on transport or status errors and ``ValueError`` on a reply
        that is not the strict zoom JSON.
        """
        body = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")},
                        },
                        {"type": "text", "text": zoom_prompt(item_type, name, description)},
                    ],
                }
            ],
            "temperature": 0.0,
            "max_tokens": 256,
            "response_format": {"type": "json_object"},
        }
        resp = httpx.post(
            self._chat_url(),
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=ZOOM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return parse_zoom_reply(parse_json_object(resp.json()["choices"][0]["message"]["content"]))

    def detect(self, frame: np.ndarray, query: str) -> list[Detection]:
        if not self.is_available():
            return []
        frame_h, frame_w = frame.shape[:2]
        scale = min(1.0, GROUNDING_MAX_EDGE_PIXELS / max(frame_h, frame_w))
        if scale < 1.0:
            frame = np.asarray(
                Image.fromarray(frame[..., ::-1]).resize((round(frame_w * scale), round(frame_h * scale)))
            )[..., ::-1]
        jpeg = encode_jpeg(np.ascontiguousarray(frame), quality=85)
        if not jpeg:
            return []

        prompt = (
            f'Locate the single best match for "{query}" in this image. Return JSON only, in the form '
            '{"bbox_2d": [xmin, ymin, xmax, ymax], "label": "<what the box contains>"} with integer coordinates '
            'normalised to 0-1000 (0,0 is the top-left corner). If it is not visible, return {"bbox_2d": null}.'
        )
        body = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "temperature": 0.0,
            "max_tokens": 512,
            "response_format": {"type": "json_object"},
        }
        data = self._request_box(body)
        raw_box = data.get("bbox_2d")
        if not isinstance(raw_box, list) or len(raw_box) != 4:
            return []
        xmin, ymin, xmax, ymax = (max(0, min(1000, round(float(v)))) for v in raw_box)
        return [Detection(box=[ymin, xmin, ymax, xmax], score=1.0, label=str(data.get("label") or query))]


class FakeDetector:
    """In-memory detector fixture for unit testing."""

    def __init__(self, detections: Sequence[Detection] | None = None) -> None:
        self.detections = list(detections) if detections is not None else []

    def is_available(self) -> bool:
        return True

    def detect(self, frame: np.ndarray, query: str) -> list[Detection]:  # noqa: ARG002
        return self.detections


class FakeZoomNamer:
    """In-memory second-look fixture: a canned reply per current item name.

    A reply is a parsed JSON dict, a raw reply string (parsed like a model's, so a malformed one raises) or an
    exception to raise. An item with no reply is confirmed unchanged at confidence 1. Every call is recorded.
    """

    def __init__(self, replies: dict[str, Any] | None = None) -> None:
        self.replies = dict(replies or {})
        self.calls: list[dict[str, Any]] = []

    def zoom_name(self, jpeg: bytes, *, item_type: str, name: str, description: str) -> ZoomVerdict:
        self.calls.append({"jpeg_bytes": len(jpeg), "item_type": item_type, "name": name, "description": description})
        reply = self.replies.get(name)
        if isinstance(reply, Exception):
            raise reply
        if reply is None:
            return ZoomVerdict(name=name, description=description, confidence=1.0, changed=False)
        return parse_zoom_reply(parse_json_object(reply) if isinstance(reply, str) else reply)


def _not_located_result(frame: np.ndarray, seconds: int | float) -> CropResult | None:
    """The frame alone: no crop and no box, so nothing downstream mistakes it for a located object."""
    frame_h, frame_w = frame.shape[:2]
    frame_bytes = encode_jpeg(frame, quality=FRAME_JPEG_QUALITY)
    if not frame_bytes:
        return None
    return CropResult(
        image_bytes=None,
        normalized_box=None,
        score=0.0,
        frame_size=(frame_w, frame_h),
        frame_bytes=frame_bytes,
        box_seconds=seconds,
        located=False,
    )


def _locate_in_frame(
    frame: np.ndarray, seconds: int | float, raw_detections: Any, label: str, min_score: float
) -> CropResult | None:
    """The crop of the best usable detection of one frame, or None when the detector found no usable box."""
    parsed_detections: list[Detection] = []
    for d in raw_detections or []:
        if isinstance(d, Detection):
            parsed_detections.append(d)
        elif isinstance(d, dict):
            box = d.get("box") or d.get("bounding_box") or [0, 0, 0, 0]
            score = float(d.get("score", 0.0))
            lbl = str(d.get("label", label))
            parsed_detections.append(Detection(box=list(box), score=score, label=lbl))
        elif hasattr(d, "box") and hasattr(d, "score"):
            parsed_detections.append(Detection(box=list(d.box), score=float(d.score), label=getattr(d, "label", label)))
    if not parsed_detections:
        return None

    best = max(parsed_detections, key=lambda d: d.score)
    if best.score < min_score or len(best.box) != 4:
        return None
    ymin, xmin, ymax, xmax = best.box
    if ymin >= ymax or xmin >= xmax:
        return None

    frame_h, frame_w = frame.shape[:2]
    c_ymin, c_xmin, c_ymax, c_xmax = apply_box_padding(best.box, frame_w, frame_h, padding_fraction=0.05)
    if c_ymin >= c_ymax or c_xmin >= c_xmax:
        return None
    jpeg_bytes = encode_jpeg(frame[c_ymin:c_ymax, c_xmin:c_xmax], quality=85)
    frame_bytes = encode_jpeg(frame, quality=FRAME_JPEG_QUALITY)
    if not jpeg_bytes or not frame_bytes:
        return None
    return CropResult(
        image_bytes=jpeg_bytes,
        normalized_box=normalize_box(c_ymin, c_xmin, c_ymax, c_xmax, frame_w, frame_h),
        score=best.score,
        frame_size=(frame_w, frame_h),
        frame_bytes=frame_bytes,
        box_seconds=seconds,
        zoom_bytes=zoom_crop(frame, best.box),
    )


def crop_evidence_item(
    video_ref: str | Path | np.ndarray,
    timestamp_seconds: int | float,
    label: str,
    detector: Any | None = None,
    min_score: float = 0.0,
    not_located_fallback: bool = False,
    retry_offsets: Sequence[int] = (),
) -> CropResult | None:
    """Locate an evidence object in a video at the specified timestamp using a detector.

    Args:
        video_ref: Video file path, URL, or pre-extracted BGR numpy frame (a frame is never retried at other seconds).
        timestamp_seconds: Seconds from video start where item is prominently visible.
        label: Short search query/label for the detector (e.g. 'crowbar', 'person in hoodie').
        detector: Detector port implementing detect(frame, query) or callable.
        min_score: Minimum confidence score threshold (default 0.0).
        not_located_fallback: When no second yields a usable box, return the requested second's frame alone
            (``located`` False, no crop, no box) instead of None. A missing frame still returns None.
        retry_offsets: Seconds added to ``timestamp_seconds`` and tried in order when the detector finds
            nothing there; the first hit wins and ``box_seconds`` records the second it was found at. Every
            second tried is one detector call against the request's crop-call budget.

    Returns:
        CropResult or None when nothing is found or detector is unavailable.

    Raises:
        CropCallCapReachedError: when the budgeted detector has no calls left (propagated, never swallowed).
    """
    if detector is None:
        return None

    if hasattr(detector, "is_available") and not detector.is_available():
        return None

    attempts = [0, *([] if isinstance(video_ref, np.ndarray) else retry_offsets)]
    first_frame: np.ndarray | None = None
    for offset in attempts:
        seconds = timestamp_seconds + offset
        if seconds < 0:
            continue
        frame: np.ndarray | None = video_ref if isinstance(video_ref, np.ndarray) else extract_frame(video_ref, seconds)
        if frame is None or frame.size == 0 or min(frame.shape[:2]) <= 0:
            continue
        if first_frame is None:
            first_frame = frame
        try:
            if hasattr(detector, "detect"):
                raw_detections = detector.detect(frame, label)
            elif callable(detector):
                raw_detections = detector(frame, label)
            else:
                return None
        except CropCallCapReachedError:
            raise
        except Exception as exc:
            logger.warning("Detector execution failed for query '%s': %s", label, exc)
            return None
        found = _locate_in_frame(frame, seconds, raw_detections, label, min_score)
        if found is not None:
            return found

    if not_located_fallback and first_frame is not None:
        return _not_located_result(first_frame, timestamp_seconds)
    return None


class EvidenceStore(ABC):
    """Port for persisting evidence crop images."""

    @abstractmethod
    async def put_image(self, key: str, image_bytes: bytes, content_type: str = "image/jpeg") -> str:
        """Store image bytes under the given key and return the key or accessible URL."""
        ...

    @abstractmethod
    async def get_image(self, key: str) -> bytes | None:
        """Retrieve stored image bytes by key."""
        ...

    @abstractmethod
    async def next_batch_id(self, video_key: str) -> str:
        """The next unused ``run-<n>`` batch id under ``evidence/<video_key>/``."""
        ...


class InMemoryEvidenceStore(EvidenceStore):
    """In-memory adapter for hermetic unit testing and zero-cloud environments."""

    def __init__(self) -> None:
        self.images: dict[str, bytes] = {}

    async def put_image(self, key: str, image_bytes: bytes, content_type: str = "image/jpeg") -> str:  # noqa: ARG002
        self.images[key] = image_bytes
        return key

    async def get_image(self, key: str) -> bytes | None:
        return self.images.get(key)

    async def next_batch_id(self, video_key: str) -> str:
        prefix = f"evidence/{video_key}/"
        return next_run_batch_id(key[len(prefix) :].split("/")[0] for key in self.images if key.startswith(prefix))


class R2EvidenceStore(EvidenceStore):
    """Cloudflare R2 adapter for evidence crop images (the production store)."""

    def __init__(self, bucket: str | None = None, client: Any = None) -> None:
        self.bucket = bucket or os.getenv("R2_BUCKET", "")
        self._client = client

    def _get_client(self) -> Any:
        return self._client if self._client is not None else get_r2_client()

    async def put_image(self, key: str, image_bytes: bytes, content_type: str = "image/jpeg") -> str:
        # IfNoneMatch="*" makes R2 refuse (412) a key that exists, so a stored crop is never overwritten.
        await asyncio.to_thread(
            self._get_client().put_object,
            Bucket=self.bucket,
            Key=key,
            Body=image_bytes,
            ContentType=content_type,
            IfNoneMatch="*",
        )
        return key

    async def next_batch_id(self, video_key: str) -> str:
        def _list_batches() -> list[str]:
            prefix = f"evidence/{video_key}/"
            batches: list[str] = []
            for page in (
                self._get_client()
                .get_paginator("list_objects_v2")
                .paginate(Bucket=self.bucket, Prefix=prefix, Delimiter="/")
            ):
                batches.extend(
                    str(entry["Prefix"])[len(prefix) :].rstrip("/") for entry in page.get("CommonPrefixes", [])
                )
            return batches

        return next_run_batch_id(await asyncio.to_thread(_list_batches))

    async def get_image(self, key: str) -> bytes | None:
        try:
            obj = await asyncio.to_thread(self._get_client().get_object, Bucket=self.bucket, Key=key)
            return bytes(obj["Body"].read())
        except Exception as exc:
            if getattr(exc, "response", {}).get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise


def evidence_items(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The entities, instruments and assets of an incident-contract-v4 report as evidence entries.

    Each entry carries the ``evidence_crops`` item columns (``item_type``, ``item_id``,
    ``item_name``, ``description``, ``threat_level``, ``holder_entity_id``, ``timestamp_seconds``)
    plus the detector ``label``. Entities also carry ``first_seen_seconds`` and ``last_seen_seconds``
    (reports stored before ``incident-contract-v4`` lack them, so they fall back to ``timestamp_seconds``); :meth:`CropEvidenceService.process_incident_report` adds
    ``bounding_box``, ``image`` and ``image_gap``.
    """
    items: list[dict[str, Any]] = []
    for entity in report.get("entities") or []:
        seen_at = _whole_seconds(entity.get("timestamp_seconds"))
        items.append(
            {
                "item_type": "entity",
                "item_id": str(entity.get("entity_id") or ""),
                "item_name": str(entity.get("type") or "entity"),
                "description": str(entity.get("description") or ""),
                "threat_level": None,
                "holder_entity_id": None,
                "timestamp_seconds": seen_at,
                "first_seen_seconds": _whole_seconds(entity.get("first_seen_seconds", seen_at)),
                "last_seen_seconds": _whole_seconds(entity.get("last_seen_seconds", seen_at)),
                "label": str(entity.get("label") or entity.get("description") or entity.get("type") or "person"),
            }
        )
    for instrument in report.get("instruments") or []:
        items.append(
            {
                "item_type": "instrument",
                "item_id": str(instrument.get("instrument_id") or ""),
                "item_name": str(instrument.get("name") or "instrument"),
                "description": str(instrument.get("description") or ""),
                "threat_level": instrument.get("threat_level"),
                "holder_entity_id": instrument.get("entity_id"),
                "timestamp_seconds": _whole_seconds(instrument.get("timestamp_seconds")),
                "label": str(instrument.get("label") or instrument.get("name") or "instrument"),
            }
        )
    for asset in report.get("assets") or []:
        items.append(
            {
                "item_type": "asset",
                "item_id": str(asset.get("asset_id") or ""),
                "item_name": str(asset.get("name") or "asset"),
                "description": str(asset.get("description") or ""),
                "threat_level": None,
                "holder_entity_id": None,
                "timestamp_seconds": _whole_seconds(asset.get("timestamp_seconds")),
                "label": str(asset.get("label") or asset.get("name") or "asset"),
            }
        )
    return [item for item in items if item["item_id"]]


ZOOM_ENTRY_FIELDS: dict[str, Any] = {
    "zoom_checked": False,
    "zoom_confidence": None,
    "name_before": None,
    "zoom_gap": None,
}


def blank_evidence_entries(
    report: dict[str, Any], image_gap: str | None, zoom_gap: str | None = None
) -> list[dict[str, Any]]:
    """The evidence entries of ``report`` before any image or second look: every image field null, the gaps given."""
    return [
        {
            **item,
            "bounding_box": None,
            "image": None,
            "frame": None,
            "box_seconds": None,
            "located": None,
            "image_gap": image_gap,
            **ZOOM_ENTRY_FIELDS,
            "zoom_gap": zoom_gap,
        }
        for item in evidence_items(report)
    ]


_REPORT_ITEM_ID_FIELDS = {
    "entity": ("entities", "entity_id"),
    "instrument": ("instruments", "instrument_id"),
    "asset": ("assets", "asset_id"),
}


def apply_zoom_verdict(entry: dict[str, Any], report: dict[str, Any], verdict: ZoomVerdict) -> bool:
    """Record the second look on ``entry`` and apply its correction to the entry and the report payload item.

    A correction is applied only when the model says ``changed`` with confidence at least
    ``ZOOM_CONFIDENCE_THRESHOLD``: the entry's ``item_name`` and ``description`` and the matching report item's
    name and description (an entity keeps its ``type``; only its description changes) are replaced, and the entry
    keeps the previous name as ``name_before`` (and ``description_before``). The item id, label and timestamps are
    never touched. Returns whether a correction was applied.
    """
    entry["zoom_checked"] = True
    entry["zoom_confidence"] = verdict.confidence
    if not verdict.changed:
        return False
    if verdict.confidence < ZOOM_CONFIDENCE_THRESHOLD:
        entry["zoom_gap"] = (
            f"correction to {verdict.name!r} ignored: confidence {verdict.confidence:.2f} is below "
            f"{ZOOM_CONFIDENCE_THRESHOLD}"
        )
        return False
    is_entity = entry["item_type"] == "entity"
    new_name = entry["item_name"] if is_entity else verdict.name
    new_description = verdict.description or entry["description"]
    if new_name == entry["item_name"] and new_description == entry["description"]:
        return False  # the model said changed but repeated the current text
    entry["name_before"] = entry["item_name"]
    entry["description_before"] = entry["description"]
    entry["item_name"] = new_name
    entry["description"] = new_description
    collection, id_field = _REPORT_ITEM_ID_FIELDS[entry["item_type"]]
    for item in report.get(collection) or []:
        if str(item.get(id_field) or "") == entry["item_id"]:
            item["description"] = new_description
            if not is_entity:
                item["name"] = new_name
            break
    return True


def _whole_seconds(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 0
    seconds: float = value
    return max(0, round(seconds))


class CropEvidenceService:
    """Service orchestrating object crop extraction and image upload for one analysis run."""

    def __init__(
        self,
        detector: Any | None = None,
        store: EvidenceStore | None = None,
        namer: Any | None = None,
    ) -> None:
        self.detector = detector if detector is not None else DefaultDetector()
        self.store = store
        # The second look's VLM client: the detector itself when it can name (DefaultDetector does, unbudgeted).
        self.namer = namer if namer is not None else (self.detector if hasattr(self.detector, "zoom_name") else None)

    def is_detector_available(self) -> bool:
        """Check whether the active detector is ready and available."""
        if self.detector is None:
            return False
        if hasattr(self.detector, "is_available"):
            return bool(self.detector.is_available())
        return True

    def crop_item(
        self,
        video_ref: str | Path | np.ndarray,
        timestamp_seconds: int | float,
        label: str,
        detector: Any | None = None,
    ) -> CropResult | None:
        """Locate an evidence item with the configured detector, retrying nearby seconds (the frame alone when not found)."""
        active_detector = detector if detector is not None else self.detector
        return crop_evidence_item(
            video_ref,
            timestamp_seconds,
            label,
            active_detector,
            not_located_fallback=True,
            retry_offsets=LOCATE_RETRY_OFFSETS,
        )

    async def process_incident_report(
        self,
        *,
        video_ref: str | Path | np.ndarray,
        video_id: str,
        report: dict[str, Any],
        video_key: str | None = None,
        batch_id: str | None = None,
        detector: Any | None = None,
        store: EvidenceStore | None = None,
        zoom_names: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Locate every entity, instrument and asset of a report and upload its frame and crop.

        Returns one evidence entry per item (see :func:`evidence_items`) for the revision's
        ``evidence`` JSONB. ``frame`` is the R2 key ``evidence/<video key>/run-<n>/<itemId>-frame.jpg`` of the whole video frame
        (``video_key`` is the video's R2 key; callers without one, such as the prompt experiments, fall back to ``video_id``),
        ``image`` the key of the object crop beside it (``<itemId>.jpg``, what evidence search embeds), ``bounding_box`` the normalised
        crop box in that frame and ``box_seconds`` the second the frame was read at (a retry second when the requested one found
        nothing). ``located`` is true when the detector found the object; when it did not, only ``frame`` is stored, ``image``
        and ``bounding_box`` are null, ``located`` is false and ``image_gap`` says so. When no frame could be produced, ``frame``
        is null as well and ``image_gap`` says why. Never raises for a single item.

        Zoomed second look (``zoom_names``, default :func:`zoom_names_enabled`): each located item's close-up is
        shown to the service's ``namer`` (the grounding VLM) and :func:`apply_zoom_verdict` records the outcome on
        the entry (``zoom_checked``, ``zoom_confidence``, ``name_before`` when corrected, ``zoom_gap`` when not
        checked or ignored) and corrects the matching item of ``report`` **in place**, so the payload the caller
        persists agrees with the evidence. Zoom calls run inside the item's concurrency slot and outside any
        ``CropCallBudget``: ``max_crop_calls`` counts grounding attempts only. A zoom failure never fails the item.
        """
        active_detector = detector if detector is not None else self.detector
        zoom_on = zoom_names_enabled() if zoom_names is None else zoom_names
        namer = self.namer if zoom_on else None
        active_store = store if store is not None else self.store
        folder = video_key or video_id
        batch = batch_id or (await active_store.next_batch_id(folder) if active_store is not None else "run-1")

        if detector is not None:
            detector_ready = bool(detector.is_available()) if hasattr(detector, "is_available") else True
        else:
            detector_ready = self.is_detector_available()
        semaphore = asyncio.Semaphore(EVIDENCE_CROP_CONCURRENCY)

        async def _crop_and_upload(entry: dict[str, Any]) -> None:
            if active_store is None:
                entry["image_gap"] = "no evidence image store is configured (R2 settings missing)"
                return
            if not detector_ready:
                entry["image_gap"] = "no evidence detector is configured (VLM grounding key missing)"
                return
            async with semaphore:
                try:
                    crop = await asyncio.to_thread(
                        self.crop_item, video_ref, entry["timestamp_seconds"], entry["label"], active_detector
                    )
                except CropCallCapReachedError as exc:
                    entry["image_gap"] = f"crop-call cap reached: {exc}"
                    return
                except Exception as exc:
                    logger.warning("Evidence crop failed for %s %s: %s", video_id, entry["item_id"], exc)
                    entry["image_gap"] = f"crop failed: {type(exc).__name__}: {exc}"
                    return
                if crop is None or crop.frame_bytes is None:
                    entry["image_gap"] = (
                        f"no frame produced at {entry['timestamp_seconds']}s (frame unreadable or detector failed)"
                    )
                    return
                frame_key = evidence_frame_key(folder, batch, entry["item_id"])
                key = evidence_key(folder, batch, entry["item_id"])
                try:
                    await active_store.put_image(frame_key, crop.frame_bytes)
                    if crop.image_bytes is not None:
                        await active_store.put_image(key, crop.image_bytes)
                except Exception as exc:
                    logger.warning("Evidence image upload failed for %s: %s", key, exc)
                    entry["image_gap"] = f"image upload failed: {type(exc).__name__}: {exc}"
                    return
                entry["frame"] = frame_key
                entry["box_seconds"] = crop.box_seconds
                entry["located"] = crop.located
                if crop.located and crop.image_bytes is not None:
                    entry["image"] = key
                    entry["bounding_box"] = crop.normalized_box
                    await _zoom_second_look(entry, crop)
                else:
                    entry["image_gap"] = (
                        f"object not located at {entry['timestamp_seconds']}s or within {max(LOCATE_RETRY_OFFSETS)}s either side"
                    )
                    entry["zoom_gap"] = "object not located"

        async def _zoom_second_look(entry: dict[str, Any], crop: CropResult) -> None:
            if not zoom_on:
                entry["zoom_gap"] = f"zoomed second look disabled ({ZOOM_NAMES_ENV})"
                return
            if namer is None or (hasattr(namer, "is_available") and not namer.is_available()):
                entry["zoom_gap"] = "no second-look VLM client is configured (VLM grounding key missing)"
                return
            try:
                if crop.zoom_bytes is None:
                    entry["zoom_gap"] = "no close-up could be cut from the frame"
                    return
                verdict = await asyncio.to_thread(
                    namer.zoom_name,
                    crop.zoom_bytes,
                    item_type=entry["item_type"],
                    name=entry["item_name"],
                    description=entry["description"],
                )
            except Exception as exc:
                logger.warning("Zoomed second look failed for %s %s: %s", video_id, entry["item_id"], exc)
                entry["zoom_gap"] = f"second look failed: {type(exc).__name__}: {exc}"
                return
            if apply_zoom_verdict(entry, report, verdict):
                logger.info(
                    "Zoomed second look renamed %s %s: %r -> %r (confidence %.2f)",
                    video_id,
                    entry["item_id"],
                    entry["name_before"],
                    entry["item_name"],
                    verdict.confidence,
                )

        entries = blank_evidence_entries(report, image_gap=None)
        await asyncio.gather(*(_crop_and_upload(entry) for entry in entries))
        return entries


_default_crop_evidence_service: CropEvidenceService | None = None


def get_crop_evidence_service() -> CropEvidenceService:
    """Retrieve the global CropEvidenceService instance (images go to R2 when R2 is configured)."""
    global _default_crop_evidence_service
    if _default_crop_evidence_service is None:
        _default_crop_evidence_service = CropEvidenceService(store=R2EvidenceStore() if is_r2_configured() else None)
    return _default_crop_evidence_service


def set_crop_evidence_service(service: CropEvidenceService | None) -> None:
    """Set or override the global CropEvidenceService instance (useful for test isolation)."""
    global _default_crop_evidence_service
    _default_crop_evidence_service = service
