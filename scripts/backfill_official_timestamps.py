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

"""Targeted timestamp and detector label backfill over existing official incident reports.

For each official report (videos.selected_model_run_id is not null), for each
entity, instrument, and asset item, this script sends the video (or clip window)
plus the item's existing description to the remote VLM to obtain timestamp_seconds and
a concise detector label (incident-contract-v3 fields), crops the item out of the video
frame at that second (bounding box also from the remote VLM), uploads the crop to
Cloudflare R2, embeds the item description with the remote embedding endpoint and upserts
the evidence_crops row in Supabase. Needs the R2_*, INCIDENT_SUPABASE_*, VLM
(VLM_GATEWAY_API_KEY or OPENAI_API_KEY, VLM_BASE_URL) and embedding (NVIDIA_API_KEY) settings.

- Crucial invariants:
- Never changes the report's text, IDs, severity, or human edits.
- Idempotent and resumable: skips items already present in the EvidenceStore or pre-loaded from --output-file (JSON lines format).
- Bounded concurrency and batch size flags.
- Safe dry-run mode (--dry-run) that inspects records and prints the plan without calls.
- Per-item failure isolation: errors on individual items are logged without aborting the batch.
- Emits a comprehensive summary at the end.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc  # type: ignore[attr-defined]
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable

# Add workspace search paths for module imports
REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_SRC = REPO_ROOT / "services" / "agent" / "src"
PROFILE_DIR = (
    REPO_ROOT / "deploy" / "docker" / "developer-profiles" / "dev-profile-incident"
)

for path in (REPO_ROOT, AGENT_SRC, PROFILE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

logger = logging.getLogger("backfill_official_timestamps")

DEFAULT_VLM_MODEL = os.getenv("VLM_NAME") or "nvidia/cosmos-3-nano-reasoner"
DEFAULT_DETECTOR = "vlm"
GROUNDING_MAX_ATTEMPTS = 4
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

ITEM_TYPE_TO_COLLECTION = {
    "entity": "entities",
    "instrument": "instruments",
    "asset": "assets",
}


# =============================================================================
# Domain Models
# =============================================================================


@dataclass
class EvidenceItem:
    """An individual entity, instrument, or asset item from an official report."""

    item_type: str  # 'entity', 'instrument', 'asset'
    item_id: str  # e.g. 'E1', 'I1', 'A1'
    description: str
    name: str = ""
    threat_level: int | None = None
    holder_entity_id: str | None = None
    existing_timestamp: int | None = None
    existing_label: str | None = None

    @property
    def collection(self) -> str:
        return ITEM_TYPE_TO_COLLECTION.get(self.item_type, f"{self.item_type}s")


@dataclass
class OfficialReport:
    """An official report associated with a video (videos.selected_model_run_id)."""

    video_id: str
    model_run_id: str
    video_filepath: str
    incident_data: dict[str, Any]
    items: list[EvidenceItem]


@dataclass
class GroundingResult:
    """Output from the VLM targeted grounding pass."""

    timestamp_seconds: int
    label: str


@dataclass
class CropResult:
    """Output from the open-vocabulary detector crop service."""

    bounding_box: list[int]  # [ymin, xmin, ymax, xmax] normalised 0-1000
    image_key: str
    confidence: float | None = None
    image_bytes: bytes | None = None


@dataclass
class EvidenceCropRecord:
    """Persisted record in evidence_crops (unified MVP2 schema)."""

    incident_id: str
    model_run_id: str
    item_type: str
    item_id: str
    item_name: str
    description: str
    timestamp_seconds: int
    label: str
    bounding_box: list[int]
    image: str
    threat_level: int | None = None
    holder_entity_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    embedding: list[float] | None = None


@dataclass
class ItemFailure:
    """Record of a failed item backfill."""

    video_id: str
    model_run_id: str
    item_type: str
    item_id: str
    error: str


@dataclass
class BackfillOptions:
    """Configuration options for the backfill run."""

    batch_size: int | None = None
    concurrency: int = 4
    dry_run: bool = False
    video_id: str | None = None
    model: str = DEFAULT_VLM_MODEL
    detector: str = DEFAULT_DETECTOR
    input_file: Path | None = None
    output_file: Path | None = None
    verbose: bool = False


@dataclass
class BackfillSummary:
    """Summary metrics of the backfill execution."""

    total_videos: int = 0
    total_items: int = 0
    entities_count: int = 0
    instruments_count: int = 0
    assets_count: int = 0
    skipped_count: int = 0
    processed_count: int = 0
    failed_count: int = 0
    failures: list[ItemFailure] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# =============================================================================
# Ports (Interfaces)
# =============================================================================


@runtime_checkable
class VideoReportSource(Protocol):
    """Port for fetching official incident reports from database or fixture."""

    async def get_official_reports(self) -> list[OfficialReport]: ...


@runtime_checkable
class VLMClient(Protocol):
    """Port for sending video + item description to VLM for timestamp and label."""

    async def ground_item(
        self,
        video_ref: str,
        item: EvidenceItem,
        *,
        clip_window: tuple[int, int] | None = None,
        incident_context: dict[str, Any] | None = None,
    ) -> GroundingResult: ...


@runtime_checkable
class CropClient(Protocol):
    """Port for obtaining bounding box crops and evidence storage keys."""

    async def crop_item(
        self,
        video_ref: str,
        timestamp_seconds: int,
        label: str,
        *,
        video_id: str,
        model_run_id: str,
        collection: str,
        item_id: str,
        detector: str = DEFAULT_DETECTOR,
    ) -> CropResult: ...

    def get_evidence_key(
        self,
        video_id: str,
        model_run_id: str,
        collection: str,
        item_id: str,
    ) -> str: ...


@runtime_checkable
class TextEmbedder(Protocol):
    """Port for embedding an evidence description into the evidence_crops vector."""

    async def embed(self, text: str) -> list[float]: ...


@runtime_checkable
class EvidenceStore(Protocol):
    """Port for checking existing evidence crops and persisting new ones."""

    async def has_crop(
        self,
        incident_id: str,
        model_run_id: str,
        item_type: str,
        item_id: str,
    ) -> bool: ...

    async def save_crop(self, record: EvidenceCropRecord) -> None: ...

    async def list_crops(
        self,
        incident_id: str | None = None,
        model_run_id: str | None = None,
    ) -> list[EvidenceCropRecord]: ...


# =============================================================================
# Adapters & Implementations
# =============================================================================


class InMemoryReportSource:
    """In-memory report source adapter for unit testing and fixtures."""

    def __init__(self, reports: list[OfficialReport] | None = None):
        self.reports = reports or []

    async def get_official_reports(self) -> list[OfficialReport]:
        return list(self.reports)


class FileReportSource:
    """Loads official reports from a JSON fixture file."""

    def __init__(self, file_path: Path):
        self.file_path = file_path

    async def get_official_reports(self) -> list[OfficialReport]:
        if not self.file_path.exists():
            raise FileNotFoundError(f"Fixture file not found: {self.file_path}")
        raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        reports: list[OfficialReport] = []
        for entry in raw:
            items: list[EvidenceItem] = []
            for item_raw in entry.get("items", []):
                items.append(
                    EvidenceItem(
                        item_type=item_raw["item_type"],
                        item_id=item_raw["item_id"],
                        description=item_raw["description"],
                        name=item_raw.get("name", ""),
                        threat_level=item_raw.get("threat_level"),
                        holder_entity_id=item_raw.get("holder_entity_id"),
                        existing_timestamp=item_raw.get("timestamp_seconds"),
                        existing_label=item_raw.get("label"),
                    )
                )
            reports.append(
                OfficialReport(
                    video_id=entry["video_id"],
                    model_run_id=entry["model_run_id"],
                    video_filepath=entry.get(
                        "video_filepath", f"videos/{entry['video_id']}.mp4"
                    ),
                    incident_data=entry.get("incident_data", {}),
                    items=items,
                )
            )
        return reports


class SupabaseReportSource:
    """Fetches official reports from live/mock Supabase PostgREST client."""

    def __init__(self, incident_db: Any):
        self.db = incident_db

    async def get_official_reports(self) -> list[OfficialReport]:
        # Query videos where selected_model_run_id is not null
        result = (
            await self.db.client.table("videos")
            .select("id,filepath,selected_model_run_id")
            .not_.is_("selected_model_run_id", "null")
            .execute()
        )
        videos = result.data or []
        reports: list[OfficialReport] = []

        for video in videos:
            video_id = video["id"]
            model_run_id = video["selected_model_run_id"]
            if not model_run_id:
                continue

            incident = await self.db.get_incident(video_id, model_run_id)
            if not incident:
                continue

            entities = await self.db.list_incident_entities(video_id, model_run_id)
            instruments = await self.db.list_incident_instruments(
                video_id, model_run_id
            )
            assets = await self.db.list_incident_assets(video_id, model_run_id)

            items: list[EvidenceItem] = []
            for e in entities:
                items.append(
                    EvidenceItem(
                        item_type="entity",
                        item_id=e["entity_id"],
                        description=e.get("description", ""),
                        name=e.get("type", "entity"),
                        existing_timestamp=e.get("timestamp_seconds"),
                        existing_label=e.get("label"),
                    )
                )
            for i in instruments:
                items.append(
                    EvidenceItem(
                        item_type="instrument",
                        item_id=i["instrument_id"],
                        description=i.get("description", ""),
                        name=i.get("name", "instrument"),
                        threat_level=i.get("threat_level"),
                        holder_entity_id=i.get("entity_id"),
                        existing_timestamp=i.get("timestamp_seconds"),
                        existing_label=i.get("label"),
                    )
                )
            for a in assets:
                items.append(
                    EvidenceItem(
                        item_type="asset",
                        item_id=a["asset_id"],
                        description=a.get("description", ""),
                        name=a.get("name", "asset"),
                        existing_timestamp=a.get("timestamp_seconds"),
                        existing_label=a.get("label"),
                    )
                )

            reports.append(
                OfficialReport(
                    video_id=video_id,
                    model_run_id=model_run_id,
                    video_filepath=video.get("filepath", f"videos/{video_id}.mp4"),
                    incident_data=incident,
                    items=items,
                )
            )

        return reports


class FakeVLMClient:
    """In-memory fake VLM client for testing and dry runs."""

    def __init__(
        self,
        responses: dict[tuple[str, str], GroundingResult] | None = None,
        default_result: GroundingResult | None = None,
        failure_keys: set[tuple[str, str]] | None = None,
    ):
        self.responses = responses or {}
        self.default_result = default_result or GroundingResult(
            timestamp_seconds=10, label="target object"
        )
        self.failure_keys = failure_keys or set()
        self.call_log: list[dict[str, Any]] = []

    async def ground_item(
        self,
        video_ref: str,
        item: EvidenceItem,
        *,
        clip_window: tuple[int, int] | None = None,
        incident_context: dict[str, Any] | None = None,
    ) -> GroundingResult:
        key = (item.item_type, item.item_id)
        self.call_log.append(
            {
                "video_ref": video_ref,
                "item_type": item.item_type,
                "item_id": item.item_id,
                "description": item.description,
                "clip_window": clip_window,
            }
        )
        if key in self.failure_keys:
            raise RuntimeError(
                f"VLM grounding simulated failure for {item.item_type} {item.item_id}"
            )
        return self.responses.get(key, self.default_result)


class RemoteVLMClient:
    """Async VLM client calling Brev Switchyard or vlm-gateway chat completions endpoint."""

    GROUNDING_SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "timestamp_seconds": {
                "type": "integer",
                "minimum": 0,
                "description": "Seconds from video start where the item is most clearly visible.",
            },
            "label": {
                "type": "string",
                "description": "Short label for detector search (e.g. 'crowbar', 'machete', 'person in dark hoodie').",
            },
        },
        "required": ["timestamp_seconds", "label"],
    }

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str = "nvidia/cosmos-3-nano-reasoner",
        timeout: float = 240.0,
    ):
        root = (
            base_url
            or os.getenv("VLM_GATEWAY_BASE_URL")
            or os.getenv("VLM_BASE_URL")
            or "https://switchyard-13doh4lsz.brevlab.com"
        ).rstrip("/")
        self.base_url = root if root.endswith("/v1") else f"{root}/v1"
        self.api_key = (
            api_key
            or os.getenv("VLM_GATEWAY_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )
        self.model = model
        self.timeout = timeout

    async def ground_item(
        self,
        video_ref: str,
        item: EvidenceItem,
        *,
        clip_window: tuple[int, int] | None = None,
        incident_context: dict[str, Any] | None = None,
    ) -> GroundingResult:
        import httpx
        from vss_agents.utils.crop_evidence import parse_json_object
        from vss_agents.utils.r2 import resolve_r2_url

        if not self.api_key:
            raise ValueError("VLM_GATEWAY_API_KEY or OPENAI_API_KEY is not configured")

        item_label_name = item.name or item.item_type
        prompt = (
            f"You are an expert video grounding assistant. Locate the exact whole second where the following "
            f"item from an official incident report is most clearly and prominently visible in the video, "
            f"and provide a short, specific 1-4 word detector label for object detection.\n\n"
            f"Item Details:\n"
            f"- Category: {item.item_type}\n"
            f"- ID: {item.item_id}\n"
            f"- Name: {item_label_name}\n"
            f"- Description: {item.description}\n"
        )
        if clip_window:
            prompt += f"- Temporal Search Window: between {clip_window[0]}s and {clip_window[1]}s\n"

        content = [
            {"type": "video_url", "video_url": {"url": resolve_r2_url(video_ref)}},
            {"type": "text", "text": prompt},
        ]
        messages = [{"role": "user", "content": content}]

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 1024,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "evidence_item_grounding",
                    "schema": self.GROUNDING_SCHEMA,
                    "strict": True,
                },
            },
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        parsed: dict[str, Any] = {}
        for attempt in range(1, GROUNDING_MAX_ATTEMPTS + 1):
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
            last_attempt = attempt == GROUNDING_MAX_ATTEMPTS
            if resp.status_code in RETRYABLE_STATUS_CODES and not last_attempt:
                await asyncio.sleep(
                    float(resp.headers.get("retry-after") or 2.0 * attempt)
                )
                continue
            resp.raise_for_status()
            choices = resp.json().get("choices", [])
            if not choices:
                raise ValueError(f"No choices returned from VLM: {resp.json()}")
            try:
                parsed = parse_json_object(choices[0]["message"]["content"])
                break
            except ValueError:
                if last_attempt:
                    raise
                logger.warning(
                    "Unparseable grounding reply (attempt %d); retrying", attempt
                )

        ts = int(parsed["timestamp_seconds"])
        label = str(parsed["label"]).strip()
        if ts < 0 or not label:
            raise ValueError(
                f"Invalid grounding fields returned: ts={ts}, label={label}"
            )

        return GroundingResult(timestamp_seconds=ts, label=label)


class FakeCropClient:
    """In-memory fake crop client for tests and dry runs."""

    def __init__(self, default_box: list[int] | None = None):
        self.default_box = default_box or [120, 240, 680, 780]
        self.crop_calls: list[dict[str, Any]] = []

    def get_evidence_key(
        self,
        video_id: str,
        model_run_id: str,
        collection: str,
        item_id: str,
    ) -> str:
        return f"evidence/{video_id}/{model_run_id}/{collection}/{item_id}.jpg"

    async def crop_item(
        self,
        video_ref: str,
        timestamp_seconds: int,
        label: str,
        *,
        video_id: str,
        model_run_id: str,
        collection: str,
        item_id: str,
        detector: str = "grounding_dino",
    ) -> CropResult:
        key = self.get_evidence_key(video_id, model_run_id, collection, item_id)
        self.crop_calls.append(
            {
                "video_ref": video_ref,
                "timestamp_seconds": timestamp_seconds,
                "label": label,
                "video_id": video_id,
                "model_run_id": model_run_id,
                "collection": collection,
                "item_id": item_id,
                "detector": detector,
                "image_key": key,
            }
        )
        return CropResult(
            bounding_box=list(self.default_box),
            image_key=key,
            confidence=0.95,
        )


class LiveCropClient:
    """Production crop adapter: remote VLM bounding box on the video frame, crop uploaded to R2."""

    def __init__(self, detector: Any | None = None, image_store: Any | None = None):
        from vss_agents.utils.crop_evidence import DefaultDetector, R2EvidenceStore

        self.detector = detector if detector is not None else DefaultDetector()
        self.image_store = image_store if image_store is not None else R2EvidenceStore()

    def get_evidence_key(
        self,
        video_id: str,
        model_run_id: str,
        collection: str,
        item_id: str,
    ) -> str:
        from vss_agents.utils.crop_evidence import evidence_key

        return evidence_key(video_id, model_run_id, collection, item_id)

    async def crop_item(
        self,
        video_ref: str,
        timestamp_seconds: int,
        label: str,
        *,
        video_id: str,
        model_run_id: str,
        collection: str,
        item_id: str,
        detector: str = DEFAULT_DETECTOR,
    ) -> CropResult:
        from vss_agents.utils.crop_evidence import crop_evidence_item
        from vss_agents.utils.r2 import resolve_r2_url

        crop = await asyncio.to_thread(
            crop_evidence_item,
            resolve_r2_url(video_ref),
            timestamp_seconds,
            label,
            self.detector,
        )
        if crop is None:
            raise ValueError(f"No crop found for {label!r} at {timestamp_seconds}s")
        key = self.get_evidence_key(video_id, model_run_id, collection, item_id)
        await self.image_store.put_image(key, crop.image_bytes)
        return CropResult(
            bounding_box=crop.normalized_box, image_key=key, confidence=crop.score
        )


class RemoteTextEmbedderAdapter:
    """Embeds evidence descriptions as passages with the remote embedding endpoint."""

    def __init__(self, embedder: Any | None = None):
        from vss_agents.utils.embeddings import RemoteTextEmbedder

        self.embedder = embedder if embedder is not None else RemoteTextEmbedder()

    async def embed(self, text: str) -> list[float]:
        return await self.embedder.embed_passage(text)


class FakeTextEmbedder:
    """In-memory fake embedder for tests and dry runs."""

    def __init__(self, vector: list[float] | None = None):
        self.vector = vector or [0.0] * 1024
        self.texts: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.texts.append(text)
        return list(self.vector)


class InMemoryEvidenceStore:
    """In-memory evidence crop storage for testing and dry runs."""

    def __init__(self, initial_records: list[EvidenceCropRecord] | None = None):
        self.records: dict[tuple[str, str, str, str], EvidenceCropRecord] = {}
        if initial_records:
            for rec in initial_records:
                key = (rec.incident_id, rec.model_run_id, rec.item_type, rec.item_id)
                self.records[key] = rec

    async def has_crop(
        self,
        incident_id: str,
        model_run_id: str,
        item_type: str,
        item_id: str,
    ) -> bool:
        return (incident_id, model_run_id, item_type, item_id) in self.records

    async def save_crop(self, record: EvidenceCropRecord) -> None:
        key = (
            record.incident_id,
            record.model_run_id,
            record.item_type,
            record.item_id,
        )
        self.records[key] = record

    async def list_crops(
        self,
        incident_id: str | None = None,
        model_run_id: str | None = None,
    ) -> list[EvidenceCropRecord]:
        items = list(self.records.values())
        if incident_id is not None:
            items = [r for r in items if r.incident_id == incident_id]
        if model_run_id is not None:
            items = [r for r in items if r.model_run_id == model_run_id]
        return items


class LiveEvidenceStore:
    """Production persistence: evidence_crops rows (with embeddings) upserted into Supabase.

    Records already known locally (for example resumed from --output-file) count as present
    without a database lookup.
    """

    def __init__(
        self,
        crops: Any | None = None,
        initial_records: list[EvidenceCropRecord] | None = None,
    ):
        if crops is None:
            from vss_agents.utils.crop_evidence import SupabaseEvidenceStore

            crops = SupabaseEvidenceStore()
        self.crops = crops
        self.local = InMemoryEvidenceStore(initial_records)

    async def has_crop(
        self,
        incident_id: str,
        model_run_id: str,
        item_type: str,
        item_id: str,
    ) -> bool:
        if await self.local.has_crop(incident_id, model_run_id, item_type, item_id):
            return True
        return (
            await self.crops.get_crop(incident_id, model_run_id, item_type, item_id)
            is not None
        )

    async def save_crop(self, record: EvidenceCropRecord) -> None:
        await self.crops.record_crop(
            incident_id=record.incident_id,
            model_run_id=record.model_run_id,
            item_type=record.item_type,
            item_id=record.item_id,
            item_name=record.item_name,
            description=record.description,
            timestamp_seconds=record.timestamp_seconds,
            bounding_box=record.bounding_box,
            image_key=record.image,
            threat_level=record.threat_level,
            holder_entity_id=record.holder_entity_id,
            embedding=record.embedding,
        )
        await self.local.save_crop(record)

    async def list_crops(
        self,
        incident_id: str | None = None,
        model_run_id: str | None = None,
    ) -> list[EvidenceCropRecord]:
        return await self.local.list_crops(incident_id, model_run_id)


# =============================================================================
# Core Backfill Orchestrator
# =============================================================================


class BackfillRunner:
    """Orchestrates the targeted timestamp backfill pass."""

    def __init__(
        self,
        report_source: VideoReportSource,
        vlm_client: VLMClient,
        crop_client: CropClient,
        evidence_store: EvidenceStore,
        embedder: TextEmbedder | None = None,
    ):
        self.report_source = report_source
        self.vlm_client = vlm_client
        self.crop_client = crop_client
        self.evidence_store = evidence_store
        self.embedder = embedder

    async def run(self, options: BackfillOptions) -> BackfillSummary:
        start_time = time.monotonic()
        summary = BackfillSummary(dry_run=options.dry_run)

        reports = await self.report_source.get_official_reports()
        if options.video_id:
            reports = [r for r in reports if r.video_id == options.video_id]

        summary.total_videos = len(reports)

        # Plan inspection
        tasks_to_process: list[tuple[OfficialReport, EvidenceItem]] = []
        for report in reports:
            for item in report.items:
                summary.total_items += 1
                if item.item_type == "entity":
                    summary.entities_count += 1
                elif item.item_type == "instrument":
                    summary.instruments_count += 1
                elif item.item_type == "asset":
                    summary.assets_count += 1

                already_exists = await self.evidence_store.has_crop(
                    report.video_id,
                    report.model_run_id,
                    item.item_type,
                    item.item_id,
                )
                if already_exists:
                    summary.skipped_count += 1
                    logger.debug(
                        "Skipping %s/%s/%s (already backfilled)",
                        report.video_id,
                        item.item_type,
                        item.item_id,
                    )
                else:
                    tasks_to_process.append((report, item))

        if options.dry_run:
            summary.elapsed_seconds = time.monotonic() - start_time
            self._print_plan(reports, tasks_to_process, summary, options)
            return summary

        # Apply batch size limit if specified
        if options.batch_size is not None and options.batch_size > 0:
            tasks_to_process = tasks_to_process[: options.batch_size]

        semaphore = asyncio.Semaphore(max(1, options.concurrency))

        async def _process_task(report: OfficialReport, item: EvidenceItem) -> None:
            async with semaphore:
                try:
                    # 1. Targeted grounding pass via VLM
                    grounding = await self.vlm_client.ground_item(
                        video_ref=report.video_filepath,
                        item=item,
                        incident_context=report.incident_data,
                    )

                    # 2. Open-vocabulary detector crop pass
                    crop_result = await self.crop_client.crop_item(
                        video_ref=report.video_filepath,
                        timestamp_seconds=grounding.timestamp_seconds,
                        label=grounding.label,
                        video_id=report.video_id,
                        model_run_id=report.model_run_id,
                        collection=item.collection,
                        item_id=item.item_id,
                        detector=options.detector,
                    )

                    # 3. Embed the item text for pgvector search
                    item_name = item.name or grounding.label
                    embedding = (
                        await self.embedder.embed(f"{item_name}: {item.description}")
                        if self.embedder
                        else None
                    )

                    # 4. Persist into evidence_crops via store
                    record = EvidenceCropRecord(
                        incident_id=report.video_id,
                        model_run_id=report.model_run_id,
                        item_type=item.item_type,
                        item_id=item.item_id,
                        item_name=item_name,
                        description=item.description,
                        threat_level=item.threat_level,
                        holder_entity_id=item.holder_entity_id,
                        timestamp_seconds=grounding.timestamp_seconds,
                        label=grounding.label,
                        bounding_box=crop_result.bounding_box,
                        image=crop_result.image_key,
                        embedding=embedding,
                    )
                    await self.evidence_store.save_crop(record)
                    summary.processed_count += 1
                    logger.info(
                        "Successfully backfilled %s/%s/%s: ts=%ds, label=%r, box=%s",
                        report.video_id,
                        item.item_type,
                        item.item_id,
                        grounding.timestamp_seconds,
                        grounding.label,
                        crop_result.bounding_box,
                    )

                except Exception as exc:  # noqa: BLE001 - isolate per-item errors without aborting batch
                    summary.failed_count += 1
                    failure = ItemFailure(
                        video_id=report.video_id,
                        model_run_id=report.model_run_id,
                        item_type=item.item_type,
                        item_id=item.item_id,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    summary.failures.append(failure)
                    logger.error(
                        "Failed backfilling %s/%s/%s: %s",
                        report.video_id,
                        item.item_type,
                        item.item_id,
                        exc,
                    )

        # Process all tasks with concurrency
        if tasks_to_process:
            await asyncio.gather(
                *[_process_task(rep, itm) for rep, itm in tasks_to_process]
            )

        summary.elapsed_seconds = time.monotonic() - start_time
        self._print_summary(summary)
        return summary

    def _print_plan(
        self,
        reports: list[OfficialReport],
        tasks_to_process: list[tuple[OfficialReport, EvidenceItem]],
        summary: BackfillSummary,
        options: BackfillOptions,
    ) -> None:
        print("\n=== Official Report Timestamp Backfill Plan (DRY RUN) ===")
        print(f"Videos inspected: {summary.total_videos}")
        print(
            f"Total evidence items: {summary.total_items} "
            f"({summary.entities_count} entities, {summary.instruments_count} instruments, {summary.assets_count} assets)"
        )
        print(f"Already backfilled (will skip): {summary.skipped_count}")
        print(f"Pending backfill: {len(tasks_to_process)}")
        if options.batch_size is not None and options.batch_size > 0:
            print(
                f"Batch size limit: {options.batch_size} "
                f"(will process up to {min(len(tasks_to_process), options.batch_size)} items)"
            )
        print(f"Concurrency: {options.concurrency}")
        print(f"VLM Model: {options.model}")
        print(f"Detector: {options.detector}")

        print("\nPlanned Items:")
        for rep, itm in tasks_to_process:
            desc_snippet = (
                (itm.description[:60] + "...")
                if len(itm.description) > 60
                else itm.description
            )
            print(
                f"  - [{rep.video_id} / {rep.model_run_id}] {itm.item_type.upper()} {itm.item_id}: {desc_snippet}"
            )

        print("\n(DRY RUN completed: no VLM or storage calls made)\n")

    def _print_summary(self, summary: BackfillSummary) -> None:
        print("\n=== Official Report Timestamp Backfill Summary ===")
        print(f"Videos inspected: {summary.total_videos}")
        print(
            f"Total items inspected: {summary.total_items} "
            f"({summary.entities_count} entities, {summary.instruments_count} instruments, {summary.assets_count} assets)"
        )
        print(f"Items skipped (already present): {summary.skipped_count}")
        print(f"Items processed successfully: {summary.processed_count}")
        print(f"Items failed: {summary.failed_count}")
        print(f"Elapsed time: {summary.elapsed_seconds:.2f}s")

        if summary.failures:
            print("\nFailures:")
            for f in summary.failures:
                print(f"  - [{f.video_id}] {f.item_type} {f.item_id}: {f.error}")
        print("===================================================\n")


# =============================================================================
# CLI Interface
# =============================================================================


def _positive_int(val: str) -> int:
    try:
        ival = int(val)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid integer: {val!r}") from exc
    if ival < 1:
        raise argparse.ArgumentTypeError(f"batch-size must be >= 1, got {ival}")
    return ival


def load_evidence_records(path: Path) -> list[EvidenceCropRecord]:
    records: list[EvidenceCropRecord] = []
    if not path.exists():
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            records.append(EvidenceCropRecord(**data))
    return records


def dump_evidence_records(records: list[EvidenceCropRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(asdict(rec)) + "\n" for rec in records)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill timestamps and detector labels for existing official incident reports."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect plan and items without making VLM or database writes.",
    )
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=None,
        help="Maximum number of items to process in this run (must be >= 1).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Maximum concurrent VLM and crop requests (default: 4).",
    )
    parser.add_argument(
        "--video-id",
        type=str,
        default=None,
        help="Filter backfill to a single specific video ID.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_VLM_MODEL,
        help=f"VLM model identifier for grounding (default: $VLM_NAME or {DEFAULT_VLM_MODEL}).",
    )
    parser.add_argument(
        "--detector",
        type=str,
        default=DEFAULT_DETECTOR,
        help="Open-vocabulary detector identifier (default: vlm, the remote VLM bounding box).",
    )
    parser.add_argument(
        "--input-file",
        type=Path,
        default=None,
        help="Optional JSON fixture file to read official reports from (zero-DB mode).",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help="Path to JSON lines file for saving and resuming evidence crop records.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable detailed debug logging.",
    )
    return parser.parse_args(argv)


async def async_main(args: argparse.Namespace) -> int:
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s [%(levelname)s] %(message)s"
    )

    options = BackfillOptions(
        batch_size=args.batch_size,
        concurrency=args.concurrency,
        dry_run=args.dry_run,
        video_id=args.video_id,
        model=args.model,
        detector=args.detector,
        input_file=args.input_file,
        output_file=args.output_file,
        verbose=args.verbose,
    )

    # Resolve report source
    if options.input_file:
        report_source: VideoReportSource = FileReportSource(options.input_file)
    else:
        # Check if Supabase is available
        try:
            from vss_agents.utils.incident_db import get_db, is_configured

            if is_configured():
                db = await get_db()
                if db:
                    report_source = SupabaseReportSource(db)
                else:
                    report_source = InMemoryReportSource([])
            else:
                logger.warning(
                    "Supabase credentials not configured; using empty InMemoryReportSource."
                )
                report_source = InMemoryReportSource([])
        except ImportError:
            logger.warning(
                "vss_agents.utils.incident_db not available; using empty InMemoryReportSource."
            )
            report_source = InMemoryReportSource([])

    # Resolve VLM client, crop client, embedder and store (dry runs use fakes and make no calls)
    initial_records: list[EvidenceCropRecord] = []
    if options.output_file and options.output_file.exists():
        initial_records = load_evidence_records(options.output_file)
        logger.info(
            "Loaded %d existing evidence records from %s",
            len(initial_records),
            options.output_file,
        )

    vlm_client: VLMClient
    crop_client: CropClient
    embedder: TextEmbedder | None
    evidence_store: EvidenceStore
    if options.dry_run:
        vlm_client = FakeVLMClient()
        crop_client = FakeCropClient()
        embedder = None
        evidence_store = (
            LiveEvidenceStore(initial_records=initial_records)
            if isinstance(report_source, SupabaseReportSource)
            else InMemoryEvidenceStore(initial_records)
        )
    else:
        if (
            not isinstance(report_source, SupabaseReportSource)
            and not options.input_file
        ):
            logger.error(
                "Supabase credentials are required for a live run (use --dry-run to plan)"
            )
            return 2
        remote_vlm = RemoteVLMClient(model=options.model)
        if not remote_vlm.api_key:
            logger.error(
                "VLM_GATEWAY_API_KEY or OPENAI_API_KEY must be set for a live run (use --dry-run to plan)"
            )
            return 2
        vlm_client = remote_vlm
        crop_client = LiveCropClient()
        embedder = RemoteTextEmbedderAdapter()
        evidence_store = LiveEvidenceStore(initial_records=initial_records)

    runner = BackfillRunner(
        report_source=report_source,
        vlm_client=vlm_client,
        crop_client=crop_client,
        evidence_store=evidence_store,
        embedder=embedder,
    )

    summary = await runner.run(options)

    if options.output_file and not options.dry_run:
        records = await evidence_store.list_crops()
        dump_evidence_records(records, options.output_file)
        logger.info(
            "Wrote %d evidence records to %s", len(records), options.output_file
        )

    return 0 if summary.failed_count == 0 else 1


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(async_main(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
