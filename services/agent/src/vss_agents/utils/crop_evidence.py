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
frame, and encoding JPEG quality 85 evidence images persisted via EvidenceStore.
"""

from abc import ABC
from abc import abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
import io
import logging
import math
import os
from pathlib import Path
from typing import Any
from typing import Protocol
from typing import runtime_checkable

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
import numpy as np
from PIL import Image

from vss_agents.utils.optional_cv2 import ensure_codecs

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

    @property
    def image(self) -> bytes:
        return self.image_bytes

    @property
    def box(self) -> list[int]:
        return self.normalized_box

    @property
    def width(self) -> int:
        return self.frame_size[0]

    @property
    def height(self) -> int:
        return self.frame_size[1]


def evidence_key(video_id: str, model_run_id: str, collection: str, item_id: str) -> str:
    """Return the canonical R2 storage key for an evidence crop image.

    Canonical layout: evidence/<videoId>/<modelRunId>/<collection>/<id>.jpg
    Collections are: entities, instruments, assets.
    """
    collection_mapping = {
        "entity": "entities",
        "entities": "entities",
        "instrument": "instruments",
        "instruments": "instruments",
        "asset": "assets",
        "assets": "assets",
    }
    col = collection_mapping.get(collection.lower(), collection)
    return f"evidence/{video_id}/{model_run_id}/{col}/{item_id}.jpg"


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
            return buf.tobytes()

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


class DefaultDetector:
    """Default open-vocabulary detector port adapter.

    Acts as a placeholder swap point until eval PR 119 selects the final
    open-vocabulary detector model (Grounding DINO vs OWLv2 vs Florence-2).
    """

    def __init__(self, model_name: str = "default-open-vocab", min_score: float = 0.2) -> None:
        self.model_name = model_name
        self.min_score = min_score

    def is_available(self) -> bool:
        """Return True if detector weights/service are available in the current environment."""
        return False

    def detect(self, frame: np.ndarray, query: str) -> list[Detection]:  # noqa: ARG002
        # TODO [PR 119]: Plug in selected open-vocabulary detector (Grounding DINO / OWLv2)
        return []


class FakeDetector:
    """In-memory detector fixture for unit testing."""

    def __init__(self, detections: Sequence[Detection] | None = None) -> None:
        self.detections = list(detections) if detections is not None else []

    def is_available(self) -> bool:
        return True

    def detect(self, frame: np.ndarray, query: str) -> list[Detection]:  # noqa: ARG002
        return self.detections


def crop_evidence_item(
    video_ref: str | Path | np.ndarray,
    timestamp_seconds: int | float,
    label: str,
    detector: Any | None = None,
    min_score: float = 0.0,
) -> CropResult | None:
    """Crop an evidence object from a video at the specified timestamp using a detector.

    Args:
        video_ref: Video file path, URL, or pre-extracted BGR numpy frame.
        timestamp_seconds: Seconds from video start where item is prominently visible.
        label: Short search query/label for the detector (e.g. 'crowbar', 'person in hoodie').
        detector: Detector port implementing detect(frame, query) or callable.
        min_score: Minimum confidence score threshold (default 0.0).

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
        return None

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

    if not parsed_detections:
        return None

    best = max(parsed_detections, key=lambda d: d.score)
    if best.score < min_score:
        return None

    box = best.box
    if len(box) != 4:
        return None

    ymin, xmin, ymax, xmax = box
    if ymin >= ymax or xmin >= xmax:
        return None

    c_ymin, c_xmin, c_ymax, c_xmax = apply_box_padding(box, frame_w, frame_h, padding_fraction=0.05)
    if c_ymin >= c_ymax or c_xmin >= c_xmax:
        return None

    crop = frame[c_ymin:c_ymax, c_xmin:c_xmax]
    jpeg_bytes = encode_jpeg(crop, quality=85)
    if not jpeg_bytes:
        return None

    norm_box = normalize_box(c_ymin, c_xmin, c_ymax, c_xmax, frame_w, frame_h)
    return CropResult(
        image_bytes=jpeg_bytes,
        normalized_box=norm_box,
        score=best.score,
        frame_size=(frame_w, frame_h),
    )


class EvidenceStore(ABC):
    """Port for persisting evidence crop images and metadata."""

    @abstractmethod
    async def put_image(self, key: str, image_bytes: bytes, content_type: str = "image/jpeg") -> str:
        """Store image bytes under the given key and return the key or accessible URL."""
        ...

    @abstractmethod
    async def get_image(self, key: str) -> bytes | None:
        """Retrieve stored image bytes by key."""
        ...

    @abstractmethod
    async def record_crop(
        self,
        *,
        incident_id: str,
        model_run_id: str,
        item_type: str,
        item_id: str,
        item_name: str,
        description: str,
        timestamp_seconds: int,
        bounding_box: list[int],
        image_key: str,
        threat_level: int | None = None,
        holder_entity_id: str | None = None,
        embedding: list[float] | None = None,
    ) -> dict[str, Any]:
        """Record crop metadata in the evidence catalog."""
        ...

    @abstractmethod
    async def get_crop(
        self,
        incident_id: str,
        model_run_id: str,
        item_type: str,
        item_id: str,
    ) -> dict[str, Any] | None:
        """Retrieve crop record by composite primary key."""
        ...

    @abstractmethod
    async def list_crops_for_incident(
        self,
        incident_id: str,
        model_run_id: str,
    ) -> list[dict[str, Any]]:
        """List all crops for an incident run."""
        ...


class InMemoryEvidenceStore(EvidenceStore):
    """In-memory adapter for hermetic unit testing and zero-cloud environments."""

    def __init__(self) -> None:
        self.images: dict[str, bytes] = {}
        self.crops: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    async def put_image(self, key: str, image_bytes: bytes, content_type: str = "image/jpeg") -> str:  # noqa: ARG002
        self.images[key] = image_bytes
        return key

    async def get_image(self, key: str) -> bytes | None:
        return self.images.get(key)

    async def record_crop(
        self,
        *,
        incident_id: str,
        model_run_id: str,
        item_type: str,
        item_id: str,
        item_name: str,
        description: str,
        timestamp_seconds: int,
        bounding_box: list[int],
        image_key: str,
        threat_level: int | None = None,
        holder_entity_id: str | None = None,
        embedding: list[float] | None = None,
    ) -> dict[str, Any]:
        record = {
            "incident_id": incident_id,
            "model_run_id": model_run_id,
            "item_type": item_type,
            "item_id": item_id,
            "item_name": item_name,
            "description": description,
            "timestamp_seconds": timestamp_seconds,
            "bounding_box": bounding_box,
            "image": image_key,
            "threat_level": threat_level,
            "holder_entity_id": holder_entity_id,
            "embedding": embedding,
        }
        self.crops[(incident_id, model_run_id, item_type, item_id)] = record
        return record

    async def get_crop(
        self,
        incident_id: str,
        model_run_id: str,
        item_type: str,
        item_id: str,
    ) -> dict[str, Any] | None:
        return self.crops.get((incident_id, model_run_id, item_type, item_id))

    async def list_crops_for_incident(
        self,
        incident_id: str,
        model_run_id: str,
    ) -> list[dict[str, Any]]:
        return [
            v for (inc_id, run_id, _, _), v in self.crops.items() if inc_id == incident_id and run_id == model_run_id
        ]


class R2EvidenceStore(EvidenceStore):
    """Cloudflare R2 adapter for evidence crop images.

    TODO [PR 120]: Cloudflare R2 evidence crop storage management and presigned
    URL generation owned by PR 120 (MVP2 data and search layer).
    """

    def __init__(self, bucket: str | None = None, account_id: str | None = None) -> None:
        self.bucket = bucket or os.getenv("R2_BUCKET", "")
        self.account_id = account_id or os.getenv("R2_ACCOUNT_ID", "")

    async def put_image(self, key: str, image_bytes: bytes, content_type: str = "image/jpeg") -> str:
        # TODO [PR 120]: Implement boto3/aioboto3 PutObject to R2
        raise NotImplementedError("R2EvidenceStore.put_image owned by PR 120")

    async def get_image(self, key: str) -> bytes | None:
        # TODO [PR 120]: Implement boto3/aioboto3 GetObject from R2
        raise NotImplementedError("R2EvidenceStore.get_image owned by PR 120")

    async def record_crop(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("R2EvidenceStore only manages object storage; metadata is owned by PR 120")

    async def get_crop(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        raise NotImplementedError("R2EvidenceStore only manages object storage")

    async def list_crops_for_incident(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise NotImplementedError("R2EvidenceStore only manages object storage")


class SupabaseEvidenceStore(EvidenceStore):
    """Supabase PostgREST adapter for evidence_crops table.

    TODO [PR 120]: Supabase evidence_crops table migration and PostgREST persistence
    adapter owned by PR 120 (MVP2 data and search layer).
    """

    def __init__(self, client: Any = None) -> None:
        self.client = client

    async def put_image(self, key: str, image_bytes: bytes, content_type: str = "image/jpeg") -> str:
        raise NotImplementedError("SupabaseEvidenceStore only manages database rows; images belong in R2")

    async def get_image(self, key: str) -> bytes | None:
        raise NotImplementedError("SupabaseEvidenceStore only manages database rows")

    async def record_crop(
        self,
        *,
        incident_id: str,
        model_run_id: str,
        item_type: str,
        item_id: str,
        item_name: str,
        description: str,
        timestamp_seconds: int,
        bounding_box: list[int],
        image_key: str,
        threat_level: int | None = None,
        holder_entity_id: str | None = None,
        embedding: list[float] | None = None,
    ) -> dict[str, Any]:
        # TODO [PR 120]: Insert row into evidence_crops via PostgREST service_role client
        raise NotImplementedError("SupabaseEvidenceStore.record_crop owned by PR 120")

    async def get_crop(
        self,
        incident_id: str,
        model_run_id: str,
        item_type: str,
        item_id: str,
    ) -> dict[str, Any] | None:
        # TODO [PR 120]: Select row from evidence_crops via PostgREST
        raise NotImplementedError("SupabaseEvidenceStore.get_crop owned by PR 120")

    async def list_crops_for_incident(
        self,
        incident_id: str,
        model_run_id: str,
    ) -> list[dict[str, Any]]:
        # TODO [PR 120]: Select rows from evidence_crops where incident_id and model_run_id
        raise NotImplementedError("SupabaseEvidenceStore.list_crops_for_incident owned by PR 120")


class CropEvidenceService:
    """Service orchestrating object crop extraction and persistence."""

    def __init__(
        self,
        detector: Any | None = None,
        store: EvidenceStore | None = None,
    ) -> None:
        self.detector = detector if detector is not None else DefaultDetector()
        self.store = store if store is not None else InMemoryEvidenceStore()

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
        """Crop an evidence item using the configured detector."""
        active_detector = detector if detector is not None else self.detector
        return crop_evidence_item(video_ref, timestamp_seconds, label, active_detector)

    async def process_incident_report(
        self,
        *,
        video_ref: str | Path | np.ndarray,
        incident_id: str,
        model_run_id: str,
        report: dict[str, Any],
        detector: Any | None = None,
        store: EvidenceStore | None = None,
    ) -> list[CropResult]:
        """Crop all entities, instruments, and assets from an incident-contract-v3 report."""
        active_detector = detector if detector is not None else self.detector
        active_store = store if store is not None else self.store

        if not self.is_detector_available() and detector is None:
            return []

        results: list[CropResult] = []

        # 1. Process entities
        for entity in report.get("entities", []):
            label = entity.get("label") or entity.get("description") or entity.get("type", "entity")
            ts = entity.get("timestamp_seconds", 0)
            entity_id = entity.get("entity_id", "E1")
            crop = self.crop_item(video_ref, ts, label, detector=active_detector)
            if crop is not None:
                results.append(crop)
                key = evidence_key(incident_id, model_run_id, "entities", entity_id)
                await active_store.put_image(key, crop.image_bytes)
                await active_store.record_crop(
                    incident_id=incident_id,
                    model_run_id=model_run_id,
                    item_type="entity",
                    item_id=entity_id,
                    item_name=entity.get("type", "entity"),
                    description=entity.get("description", ""),
                    timestamp_seconds=ts,
                    bounding_box=crop.normalized_box,
                    image_key=key,
                )

        # 2. Process instruments
        for instrument in report.get("instruments", []):
            label = instrument.get("label") or instrument.get("name", "instrument")
            ts = instrument.get("timestamp_seconds", 0)
            instrument_id = instrument.get("instrument_id", "I1")
            crop = self.crop_item(video_ref, ts, label, detector=active_detector)
            if crop is not None:
                results.append(crop)
                key = evidence_key(incident_id, model_run_id, "instruments", instrument_id)
                await active_store.put_image(key, crop.image_bytes)
                await active_store.record_crop(
                    incident_id=incident_id,
                    model_run_id=model_run_id,
                    item_type="instrument",
                    item_id=instrument_id,
                    item_name=instrument.get("name", "instrument"),
                    description=instrument.get("description", ""),
                    timestamp_seconds=ts,
                    bounding_box=crop.normalized_box,
                    image_key=key,
                    threat_level=instrument.get("threat_level"),
                    holder_entity_id=instrument.get("entity_id"),
                )

        # 3. Process assets
        for asset in report.get("assets", []):
            label = asset.get("label") or asset.get("name", "asset")
            ts = asset.get("timestamp_seconds", 0)
            asset_id = asset.get("asset_id", "A1")
            crop = self.crop_item(video_ref, ts, label, detector=active_detector)
            if crop is not None:
                results.append(crop)
                key = evidence_key(incident_id, model_run_id, "assets", asset_id)
                await active_store.put_image(key, crop.image_bytes)
                await active_store.record_crop(
                    incident_id=incident_id,
                    model_run_id=model_run_id,
                    item_type="asset",
                    item_id=asset_id,
                    item_name=asset.get("name", "asset"),
                    description=asset.get("description", ""),
                    timestamp_seconds=ts,
                    bounding_box=crop.normalized_box,
                    image_key=key,
                )

        return results


_default_crop_evidence_service: CropEvidenceService | None = None


def get_crop_evidence_service() -> CropEvidenceService:
    """Retrieve the global CropEvidenceService instance."""
    global _default_crop_evidence_service
    if _default_crop_evidence_service is None:
        _default_crop_evidence_service = CropEvidenceService()
    return _default_crop_evidence_service


def set_crop_evidence_service(service: CropEvidenceService | None) -> None:
    """Set or override the global CropEvidenceService instance (useful for test isolation)."""
    global _default_crop_evidence_service
    _default_crop_evidence_service = service
