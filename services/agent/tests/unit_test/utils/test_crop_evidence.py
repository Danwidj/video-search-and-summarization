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

"""Unit tests for crop_evidence utility and CropEvidenceService (MVP2 VM Step 3)."""

from collections.abc import Generator
from pathlib import Path
import tempfile

import cv2
import numpy as np
import pytest

from vss_agents.utils.crop_evidence import CropEvidenceService
from vss_agents.utils.crop_evidence import CropResult
from vss_agents.utils.crop_evidence import DefaultDetector
from vss_agents.utils.crop_evidence import Detection
from vss_agents.utils.crop_evidence import FakeDetector
from vss_agents.utils.crop_evidence import InMemoryEvidenceStore
from vss_agents.utils.crop_evidence import R2EvidenceStore
from vss_agents.utils.crop_evidence import SupabaseEvidenceStore
from vss_agents.utils.crop_evidence import apply_box_padding
from vss_agents.utils.crop_evidence import crop_evidence_item
from vss_agents.utils.crop_evidence import encode_jpeg
from vss_agents.utils.crop_evidence import evidence_key
from vss_agents.utils.crop_evidence import extract_frame
from vss_agents.utils.crop_evidence import get_crop_evidence_service
from vss_agents.utils.crop_evidence import normalize_box
from vss_agents.utils.crop_evidence import set_crop_evidence_service


@pytest.fixture
def tiny_video_path() -> Generator[Path]:
    """Generate a tiny 20-frame (2-second at 10fps) video fixture."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
        video_path = Path(temp_file.name)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    fps = 10.0
    width, height = 120, 80
    writer = cv2.VideoWriter(str(video_path), fourcc, fps, (width, height))

    # Frame 0-9: blue background with white rectangle in center
    for _ in range(10):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:, :] = (255, 0, 0)  # Blue
        frame[20:60, 30:90] = (255, 255, 255)  # White box
        writer.write(frame)

    # Frame 10-19: green background with red rectangle in center
    for _ in range(10):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:, :] = (0, 255, 0)  # Green
        frame[10:50, 40:80] = (0, 0, 255)  # Red box
        writer.write(frame)

    writer.release()

    try:
        yield video_path
    finally:
        if video_path.exists():
            video_path.unlink()


class TestEvidenceKey:
    """Test canonical evidence key layout generation."""

    def test_canonical_key_format(self) -> None:
        key = evidence_key("Explosion001", "MR001", "entities", "E1")
        assert key == "evidence/Explosion001/MR001/entities/E1.jpg"

    def test_singular_collection_normalization(self) -> None:
        assert evidence_key("Burglary004", "run1", "entity", "E2") == "evidence/Burglary004/run1/entities/E2.jpg"
        assert evidence_key("Burglary004", "run1", "instrument", "I1") == "evidence/Burglary004/run1/instruments/I1.jpg"
        assert evidence_key("Burglary004", "run1", "asset", "A3") == "evidence/Burglary004/run1/assets/A3.jpg"

    def test_plural_collections(self) -> None:
        assert (
            evidence_key("Assault007", "MR002", "instruments", "I2") == "evidence/Assault007/MR002/instruments/I2.jpg"
        )
        assert evidence_key("Assault007", "MR002", "assets", "A1") == "evidence/Assault007/MR002/assets/A1.jpg"


class TestBoxPaddingAndNormalization:
    """Test 5% padding clamping and coordinate normalization."""

    def test_padding_calculation(self) -> None:
        # Box [100, 200, 300, 400] on 1000x1000 frame -> bw=200, bh=200.
        # 5% padding = 10 px margin.
        c_ymin, c_xmin, c_ymax, c_xmax = apply_box_padding([100, 200, 300, 400], frame_w=1000, frame_h=1000)
        assert (c_ymin, c_xmin, c_ymax, c_xmax) == (90, 190, 310, 410)

    def test_clamping_to_frame_boundaries(self) -> None:
        # Box at origin [0, 0, 100, 100] -> left/top clamped to 0.
        c_ymin, c_xmin, c_ymax, c_xmax = apply_box_padding([0, 0, 100, 100], frame_w=1000, frame_h=1000)
        assert c_ymin == 0
        assert c_xmin == 0
        assert c_ymax == 105
        assert c_xmax == 105

        # Box at bottom right [900, 900, 1000, 1000] -> bottom/right clamped to frame max.
        c_ymin, c_xmin, c_ymax, c_xmax = apply_box_padding([900, 900, 1000, 1000], frame_w=1000, frame_h=1000)
        assert c_ymin == 895
        assert c_xmin == 895
        assert c_ymax == 1000
        assert c_xmax == 1000

    def test_normalize_box(self) -> None:
        norm = normalize_box(c_ymin=50, c_xmin=100, c_ymax=150, c_xmax=300, frame_w=1000, frame_h=500)
        assert norm == [100, 100, 300, 300]

    def test_apply_box_padding_invalid_dimensions(self) -> None:
        with pytest.raises(ValueError, match="Expected 4 bounding box coordinates"):
            apply_box_padding([10, 20], frame_w=100, frame_h=100)


class TestFrameExtractionAndEncoding:
    """Test video frame extraction and JPEG encoding."""

    def test_extract_frame_valid(self, tiny_video_path: Path) -> None:
        frame_t0 = extract_frame(tiny_video_path, timestamp_seconds=0)
        assert frame_t0 is not None
        assert frame_t0.shape == (80, 120, 3)
        # Blue background at t=0
        assert frame_t0[0, 0, 0] > 200

        frame_t1 = extract_frame(tiny_video_path, timestamp_seconds=1)
        assert frame_t1 is not None
        assert frame_t1.shape == (80, 120, 3)
        # Green background at t=1
        assert frame_t1[0, 0, 1] > 200

    def test_extract_frame_nonexistent_file(self) -> None:
        frame = extract_frame("/path/does/not/exist.mp4", timestamp_seconds=0)
        assert frame is None

    def test_encode_jpeg_quality(self) -> None:
        sample_img = np.zeros((50, 50, 3), dtype=np.uint8)
        jpeg_bytes = encode_jpeg(sample_img, quality=85)
        assert jpeg_bytes is not None
        assert len(jpeg_bytes) > 0
        # Valid JPEG header
        assert jpeg_bytes[:2] == b"\xff\xd8"


class TestCropEvidenceItem:
    """Test crop_evidence_item standalone function."""

    def test_crop_with_fake_detector(self, tiny_video_path: Path) -> None:
        detector = FakeDetector(
            detections=[
                Detection(box=[250, 250, 750, 750], score=0.92, label="person"),
            ]
        )
        result = crop_evidence_item(
            video_ref=tiny_video_path,
            timestamp_seconds=0,
            label="person",
            detector=detector,
        )
        assert isinstance(result, CropResult)
        assert result.score == 0.92
        assert result.frame_size == (120, 80)
        assert len(result.normalized_box) == 4
        assert result.image_bytes[:2] == b"\xff\xd8"

    def test_crop_picks_best_box(self, tiny_video_path: Path) -> None:
        detector = FakeDetector(
            detections=[
                Detection(box=[100, 100, 200, 200], score=0.40, label="crowbar"),
                Detection(box=[200, 200, 600, 600], score=0.88, label="crowbar"),
                Detection(box=[150, 150, 300, 300], score=0.65, label="crowbar"),
            ]
        )
        result = crop_evidence_item(
            video_ref=tiny_video_path,
            timestamp_seconds=1,
            label="crowbar",
            detector=detector,
        )
        assert result is not None
        assert result.score == 0.88

    def test_crop_returns_none_when_no_detections(self, tiny_video_path: Path) -> None:
        detector = FakeDetector(detections=[])
        result = crop_evidence_item(
            video_ref=tiny_video_path,
            timestamp_seconds=0,
            label="unknown",
            detector=detector,
        )
        assert result is None

    def test_crop_returns_none_when_detector_unavailable(self, tiny_video_path: Path) -> None:
        detector = DefaultDetector()
        assert not detector.is_available()
        result = crop_evidence_item(
            video_ref=tiny_video_path,
            timestamp_seconds=0,
            label="person",
            detector=detector,
        )
        assert result is None

    def test_crop_returns_none_when_detector_is_none(self, tiny_video_path: Path) -> None:
        result = crop_evidence_item(
            video_ref=tiny_video_path,
            timestamp_seconds=0,
            label="person",
            detector=None,
        )
        assert result is None

    def test_crop_returns_none_for_invalid_bounding_box(self, tiny_video_path: Path) -> None:
        detector = FakeDetector(detections=[Detection(box=[500, 500, 200, 200], score=0.9, label="person")])
        result = crop_evidence_item(
            video_ref=tiny_video_path,
            timestamp_seconds=0,
            label="person",
            detector=detector,
        )
        assert result is None


class TestEvidenceStoreAdapters:
    """Test EvidenceStore port and in-memory adapter."""

    @pytest.mark.asyncio
    async def test_in_memory_store_put_and_get(self) -> None:
        store = InMemoryEvidenceStore()
        key = "evidence/Video1/Run1/entities/E1.jpg"
        data = b"\xff\xd8\xff\xe0test_image"

        stored_key = await store.put_image(key, data)
        assert stored_key == key

        retrieved = await store.get_image(key)
        assert retrieved == data

        non_existent = await store.get_image("evidence/missing.jpg")
        assert non_existent is None

    @pytest.mark.asyncio
    async def test_in_memory_store_crop_metadata(self) -> None:
        store = InMemoryEvidenceStore()
        record = await store.record_crop(
            incident_id="Vid001",
            model_run_id="Run001",
            item_type="instrument",
            item_id="I1",
            item_name="crowbar",
            description="Used to pry open lockbox",
            timestamp_seconds=12,
            bounding_box=[100, 200, 300, 400],
            image_key="evidence/Vid001/Run001/instruments/I1.jpg",
            threat_level=4,
            holder_entity_id="E1",
        )
        assert record["item_name"] == "crowbar"
        assert record["threat_level"] == 4

        fetched = await store.get_crop("Vid001", "Run001", "instrument", "I1")
        assert fetched == record

        all_crops = await store.list_crops_for_incident("Vid001", "Run001")
        assert len(all_crops) == 1
        assert all_crops[0]["item_id"] == "I1"

    @pytest.mark.asyncio
    async def test_r2_and_supabase_adapters_raise_not_implemented(self) -> None:
        r2_store = R2EvidenceStore()
        with pytest.raises(NotImplementedError, match="owned by PR 120"):
            await r2_store.put_image("key", b"data")

        supabase_store = SupabaseEvidenceStore()
        with pytest.raises(NotImplementedError, match="owned by PR 120"):
            await supabase_store.record_crop(
                incident_id="v1",
                model_run_id="m1",
                item_type="entity",
                item_id="E1",
                item_name="person",
                description="desc",
                timestamp_seconds=5,
                bounding_box=[0, 0, 100, 100],
                image_key="key",
            )


class TestCropEvidenceService:
    """Test CropEvidenceService report processing."""

    @pytest.mark.asyncio
    async def test_process_incident_report_crops_all_items(self, tiny_video_path: Path) -> None:
        detector = FakeDetector(
            detections=[
                Detection(box=[200, 200, 600, 600], score=0.95, label="person"),
            ]
        )
        store = InMemoryEvidenceStore()
        service = CropEvidenceService(detector=detector, store=store)

        report = {
            "incident": {"title": "Burglary", "type": "burglary"},
            "entities": [
                {
                    "entity_id": "E1",
                    "type": "human",
                    "description": "Suspect in hoodie",
                    "timestamp_seconds": 0,
                    "label": "person",
                }
            ],
            "instruments": [
                {
                    "instrument_id": "I1",
                    "entity_id": "E1",
                    "name": "crowbar",
                    "description": "Heavy metal tool",
                    "threat_level": 3,
                    "timestamp_seconds": 1,
                    "label": "crowbar",
                }
            ],
            "assets": [
                {
                    "asset_id": "A1",
                    "name": "cash register",
                    "description": "Store register",
                    "timestamp_seconds": 1,
                    "label": "cash register",
                }
            ],
        }

        results = await service.process_incident_report(
            video_ref=tiny_video_path,
            incident_id="Burglary001",
            model_run_id="MR001",
            report=report,
        )

        assert len(results) == 3
        # Verify images stored in InMemoryEvidenceStore
        e1_key = evidence_key("Burglary001", "MR001", "entities", "E1")
        i1_key = evidence_key("Burglary001", "MR001", "instruments", "I1")
        a1_key = evidence_key("Burglary001", "MR001", "assets", "A1")

        assert (await store.get_image(e1_key)) is not None
        assert (await store.get_image(i1_key)) is not None
        assert (await store.get_image(a1_key)) is not None

        # Verify crop records
        crop_records = await store.list_crops_for_incident("Burglary001", "MR001")
        assert len(crop_records) == 3
        types = {c["item_type"] for c in crop_records}
        assert types == {"entity", "instrument", "asset"}

    @pytest.mark.asyncio
    async def test_process_incident_report_gracefully_degrades_when_detector_unavailable(
        self, tiny_video_path: Path
    ) -> None:
        service = CropEvidenceService(detector=DefaultDetector())
        assert not service.is_detector_available()

        report = {
            "entities": [{"entity_id": "E1", "type": "human", "timestamp_seconds": 0, "label": "person"}],
            "instruments": [],
            "assets": [],
        }

        results = await service.process_incident_report(
            video_ref=tiny_video_path,
            incident_id="Vid1",
            model_run_id="Run1",
            report=report,
        )
        assert results == []

    def test_global_service_get_and_set(self) -> None:
        orig = get_crop_evidence_service()
        custom = CropEvidenceService(detector=FakeDetector())
        set_crop_evidence_service(custom)
        assert get_crop_evidence_service() is custom
        set_crop_evidence_service(orig)
