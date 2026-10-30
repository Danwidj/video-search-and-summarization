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

Produces tightly framed object crops from video frames at VLM timestamp_seconds
using an open-vocabulary detector port, applying 5% margin padding clamped to the
frame, and encoding JPEG quality 85 evidence images persisted via EvidenceStore (R2 in production).
The crops become the evidence entries of the AI revision the analysis run writes; the console builds
the searchable ``evidence_crops`` rows from a revision's evidence when it is made official.
"""

from abc import ABC
from abc import abstractmethod
import asyncio
import base64
from collections.abc import Iterable
from collections.abc import Sequence
from dataclasses import dataclass
import io
import json
import logging
import math
import os
from pathlib import Path
import re
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
from vss_agents.utils.r2 import get_r2_key_prefix
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
    """Cropped evidence image and spatial grounding metadata."""

    image_bytes: bytes
    normalized_box: list[int]  # [ymin, xmin, ymax, xmax] normalized 0-1000
    score: float
    frame_size: tuple[int, int]  # (width, height)


def evidence_key(video_key: str, batch_id: str, item_id: str) -> str:
    """Return the R2 key for one evidence crop image: ``evidence/<video key>/<batchId>/<itemId>.jpg``.

    ``video_key`` is the video's own R2 key (``uploads/clip.mp4``), so the path reads like the video.
    ``batch_id`` is ``run-<n>``, one per analysis run of that video (:meth:`EvidenceStore.next_batch_id`),
    so a key is never reused and an image a revision references is never overwritten. Item ids
    (``E1``, ``I1``, ``A1``) are unique across the three collections, so no collection folder is needed.
    """
    return f"evidence/{video_key}/{batch_id}/{item_id}.jpg"


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

    def is_available(self) -> bool:
        """Return True if the remote VLM endpoint is configured with credentials."""
        return bool(self.api_key)

    def _chat_url(self) -> str:
        root = self.base_url[: -len("/v1")] if self.base_url.endswith("/v1") else self.base_url
        return f"{root}/v1/chat/completions"

    def _request_box(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST the grounding request, retrying rate limits, server errors and unparseable replies."""
        for attempt in range(1, GROUNDING_MAX_ATTEMPTS + 1):
            resp = httpx.post(
                self._chat_url(),
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout_seconds,
            )
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


def _whole_frame_result(frame: np.ndarray) -> CropResult | None:
    """Whole-frame crop (box [0, 0, 1000, 1000], score 0.0 marking low confidence)."""
    frame_h, frame_w = frame.shape[:2]
    jpeg_bytes = encode_jpeg(frame, quality=85)
    if not jpeg_bytes:
        return None
    return CropResult(
        image_bytes=jpeg_bytes, normalized_box=[0, 0, 1000, 1000], score=0.0, frame_size=(frame_w, frame_h)
    )


def crop_evidence_item(
    video_ref: str | Path | np.ndarray,
    timestamp_seconds: int | float,
    label: str,
    detector: Any | None = None,
    min_score: float = 0.0,
    whole_frame_fallback: bool = False,
) -> CropResult | None:
    """Crop an evidence object from a video at the specified timestamp using a detector.

    Args:
        video_ref: Video file path, URL, or pre-extracted BGR numpy frame.
        timestamp_seconds: Seconds from video start where item is prominently visible.
        label: Short search query/label for the detector (e.g. 'crowbar', 'person in hoodie').
        detector: Detector port implementing detect(frame, query) or callable.
        min_score: Minimum confidence score threshold (default 0.0).
        whole_frame_fallback: When the detector yields no usable box, return the whole frame
            (box [0, 0, 1000, 1000], score 0.0) instead of None. A missing frame still returns None.

    Returns:
        CropResult or None when nothing is found or detector is unavailable.
    """
    if detector is None:
        return None

    if hasattr(detector, "is_available") and not detector.is_available():
        return None

    frame: np.ndarray | None = (
        video_ref if isinstance(video_ref, np.ndarray) else extract_frame(video_ref, timestamp_seconds)
    )

    if frame is None or frame.size == 0:
        return None

    frame_h, frame_w = frame.shape[:2]
    if frame_h <= 0 or frame_w <= 0:
        return None

    try:
        if hasattr(detector, "detect"):
            raw_detections = detector.detect(frame, label)
        elif callable(detector):
            raw_detections = detector(frame, label)
        else:
            return None
    except Exception as exc:
        logger.warning("Detector execution failed for query '%s': %s", label, exc)
        return None

    if not raw_detections:
        return _whole_frame_result(frame) if whole_frame_fallback else None

    parsed_detections: list[Detection] = []
    for d in raw_detections:
        if isinstance(d, Detection):
            parsed_detections.append(d)
        elif isinstance(d, dict):
            box = d.get("box") or d.get("bounding_box") or [0, 0, 0, 0]
            score = float(d.get("score", 0.0))
            lbl = str(d.get("label", label))
            parsed_detections.append(Detection(box=list(box), score=score, label=lbl))
        elif hasattr(d, "box") and hasattr(d, "score"):
            parsed_detections.append(Detection(box=list(d.box), score=float(d.score), label=getattr(d, "label", label)))

    fallback = _whole_frame_result(frame) if whole_frame_fallback else None

    if not parsed_detections:
        return fallback

    best = max(parsed_detections, key=lambda d: d.score)
    if best.score < min_score:
        return fallback

    box = best.box
    if len(box) != 4:
        return fallback

    ymin, xmin, ymax, xmax = box
    if ymin >= ymax or xmin >= xmax:
        return fallback

    c_ymin, c_xmin, c_ymax, c_xmax = apply_box_padding(box, frame_w, frame_h, padding_fraction=0.05)
    if c_ymin >= c_ymax or c_xmin >= c_xmax:
        return fallback

    crop = frame[c_ymin:c_ymax, c_xmin:c_xmax]
    jpeg_bytes = encode_jpeg(crop, quality=85)
    if not jpeg_bytes:
        return fallback

    norm_box = normalize_box(c_ymin, c_xmin, c_ymax, c_xmax, frame_w, frame_h)
    return CropResult(
        image_bytes=jpeg_bytes,
        normalized_box=norm_box,
        score=best.score,
        frame_size=(frame_w, frame_h),
    )


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
    """Cloudflare R2 adapter for evidence crop images (the production store).

    ``R2_KEY_PREFIX`` is prepended to every R2 request so all objects land
    under the configured prefix (e.g. ``mvp3/``).  The logical keys returned
    to callers and stored in the database stay prefix-free.
    """

    def __init__(self, bucket: str | None = None, client: Any = None) -> None:
        self.bucket = bucket or os.getenv("R2_BUCKET", "")
        self._client = client

    def _get_client(self) -> Any:
        return self._client if self._client is not None else get_r2_client()

    def _r2_key(self, logical_key: str) -> str:
        """Apply the R2 key prefix to a logical (DB) key."""
        return get_r2_key_prefix() + logical_key.lstrip("/")

    async def put_image(self, key: str, image_bytes: bytes, content_type: str = "image/jpeg") -> str:
        # IfNoneMatch="*" makes R2 refuse (412) a key that exists, so a stored crop is never overwritten.
        await asyncio.to_thread(
            self._get_client().put_object,
            Bucket=self.bucket,
            Key=self._r2_key(key),
            Body=image_bytes,
            ContentType=content_type,
            IfNoneMatch="*",
        )
        return key  # return the prefix-free key so the DB stores a portable reference

    async def next_batch_id(self, video_key: str) -> str:
        def _list_batches() -> list[str]:
            logical_prefix = f"evidence/{video_key}/"
            r2_prefix = self._r2_key(logical_prefix)
            batches: list[str] = []
            for page in (
                self._get_client()
                .get_paginator("list_objects_v2")
                .paginate(Bucket=self.bucket, Prefix=r2_prefix, Delimiter="/")
            ):
                batches.extend(
                    str(entry["Prefix"])[len(r2_prefix) :].rstrip("/") for entry in page.get("CommonPrefixes", [])
                )
            return batches

        return next_run_batch_id(await asyncio.to_thread(_list_batches))

    async def get_image(self, key: str) -> bytes | None:
        try:
            obj = await asyncio.to_thread(self._get_client().get_object, Bucket=self.bucket, Key=self._r2_key(key))
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
    ) -> None:
        self.detector = detector if detector is not None else DefaultDetector()
        self.store = store

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
        """Crop an evidence item using the configured detector (whole frame when no box is found)."""
        active_detector = detector if detector is not None else self.detector
        return crop_evidence_item(video_ref, timestamp_seconds, label, active_detector, whole_frame_fallback=True)

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
    ) -> list[dict[str, Any]]:
        """Crop every entity, instrument and asset of a report and upload each image.

        Returns one evidence entry per item (see :func:`evidence_items`) for the revision's
        ``evidence`` JSONB. ``image`` is the R2 key ``evidence/<video key>/run-<n>/<itemId>.jpg`` (``video_key`` is the video's
        R2 key; callers without one, such as the prompt experiments, fall back to ``video_id``)
        and ``bounding_box`` the normalised crop box; when no image could be produced ``image`` and
        ``bounding_box`` are null and ``image_gap`` says why. Never raises for a single item.
        """
        active_detector = detector if detector is not None else self.detector
        active_store = store if store is not None else self.store
        folder = video_key or video_id
        items = evidence_items(report)
        batch = batch_id or (await active_store.next_batch_id(folder) if active_store is not None else "run-1")

        detector_ready = detector is not None or self.is_detector_available()
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
                except Exception as exc:
                    logger.warning("Evidence crop failed for %s %s: %s", video_id, entry["item_id"], exc)
                    entry["image_gap"] = f"crop failed: {type(exc).__name__}: {exc}"
                    return
                if crop is None:
                    entry["image_gap"] = (
                        f"no crop produced at {entry['timestamp_seconds']}s (frame unreadable or detector failed)"
                    )
                    return
                key = evidence_key(folder, batch, entry["item_id"])
                try:
                    await active_store.put_image(key, crop.image_bytes)
                except Exception as exc:
                    logger.warning("Evidence image upload failed for %s: %s", key, exc)
                    entry["image_gap"] = f"image upload failed: {type(exc).__name__}: {exc}"
                    return
                entry["image"] = key
                entry["bounding_box"] = crop.normalized_box

        entries = [{**item, "bounding_box": None, "image": None, "image_gap": None} for item in items]
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
