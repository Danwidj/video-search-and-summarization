# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the targeted timestamp backfill script (scripts/backfill_official_timestamps.py)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.backfill_official_timestamps import (
    BackfillOptions,
    BackfillRunner,
    EvidenceCropRecord,
    EvidenceItem,
    FakeCropClient,
    FakeTextEmbedder,
    FakeVLMClient,
    FileReportSource,
    GroundingResult,
    InMemoryEvidenceStore,
    InMemoryReportSource,
    LiveEvidenceStore,
    OfficialReport,
    RemoteVLMClient,
    dump_evidence_records,
    load_evidence_records,
    parse_args,
    parse_grounding_reply,
)


def _sample_official_reports() -> list[OfficialReport]:
    return [
        OfficialReport(
            video_id="Animal003",
            model_run_id="mr_official_01",
            video_filepath="videos/Animal003.mp4",
            incident_data={
                "incident_id": "Animal003",
                "type": "animal attack",
                "start_timestamp": 5,
                "end_timestamp": 25,
                "description": "Dog attacks child in front yard",
            },
            items=[
                EvidenceItem(
                    item_type="entity",
                    item_id="E1",
                    description="Child in yellow shirt playing on lawn",
                    name="human",
                ),
                EvidenceItem(
                    item_type="entity",
                    item_id="E2",
                    description="Medium-sized brown dog rushing toward fence",
                    name="animal",
                ),
                EvidenceItem(
                    item_type="instrument",
                    item_id="I1",
                    description="Stick picked up by bystander to fend off animal",
                    name="wooden stick",
                    threat_level=2,
                    holder_entity_id="E1",
                ),
            ],
        ),
        OfficialReport(
            video_id="Burglary004",
            model_run_id="mr_official_02",
            video_filepath="videos/Burglary004.mp4",
            incident_data={
                "incident_id": "Burglary004",
                "type": "burglary",
                "start_timestamp": 10,
                "end_timestamp": 45,
                "description": "Vehicle drives into storefront ATM vestibule",
            },
            items=[
                EvidenceItem(
                    item_type="asset",
                    item_id="A1",
                    description="Front glass doors of ATM enclosure",
                    name="glass entrance",
                ),
                EvidenceItem(
                    item_type="instrument",
                    item_id="I1",
                    description="Heavy metal crowbar used to pry cash box",
                    name="crowbar",
                    threat_level=4,
                ),
            ],
        ),
    ]


class TestBackfillOfficialTimestamps(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.reports = _sample_official_reports()
        self.report_source = InMemoryReportSource(self.reports)
        self.vlm_client = FakeVLMClient(
            responses={
                ("entity", "E1"): GroundingResult(
                    timestamp_seconds=6, label="child in yellow"
                ),
                ("entity", "E2"): GroundingResult(
                    timestamp_seconds=12, label="brown dog"
                ),
                ("instrument", "I1"): GroundingResult(
                    timestamp_seconds=18, label="stick"
                ),
                ("asset", "A1"): GroundingResult(
                    timestamp_seconds=15, label="glass doors"
                ),
            },
            default_result=GroundingResult(timestamp_seconds=22, label="crowbar tool"),
        )
        self.crop_client = FakeCropClient(default_box=[100, 150, 700, 850])
        self.evidence_store = InMemoryEvidenceStore()
        self.runner = BackfillRunner(
            report_source=self.report_source,
            vlm_client=self.vlm_client,
            crop_client=self.crop_client,
            evidence_store=self.evidence_store,
        )

    async def test_dry_run_makes_no_mutating_calls(self) -> None:
        options = BackfillOptions(dry_run=True)
        summary = await self.runner.run(options)

        self.assertTrue(summary.dry_run)
        self.assertEqual(summary.total_videos, 2)
        self.assertEqual(summary.total_items, 5)
        self.assertEqual(summary.entities_count, 2)
        self.assertEqual(summary.instruments_count, 2)
        self.assertEqual(summary.assets_count, 1)
        self.assertEqual(summary.skipped_count, 0)
        self.assertEqual(summary.processed_count, 0)
        self.assertEqual(summary.failed_count, 0)

        # Ensure no VLM or crop calls occurred
        self.assertEqual(len(self.vlm_client.call_log), 0)
        self.assertEqual(len(self.crop_client.crop_calls), 0)
        # Ensure evidence store is empty
        stored = await self.evidence_store.list_crops()
        self.assertEqual(len(stored), 0)

    async def test_full_backfill_execution(self) -> None:
        options = BackfillOptions(dry_run=False, concurrency=2)
        summary = await self.runner.run(options)

        self.assertFalse(summary.dry_run)
        self.assertEqual(summary.total_videos, 2)
        self.assertEqual(summary.total_items, 5)
        self.assertEqual(summary.processed_count, 5)
        self.assertEqual(summary.skipped_count, 0)
        self.assertEqual(summary.failed_count, 0)

        # Check evidence store contents
        stored = await self.evidence_store.list_crops()
        self.assertEqual(len(stored), 5)

        # Verify key mapping and fields for Animal003 E2
        e2_crop = next(
            r for r in stored if r.incident_id == "Animal003" and r.item_id == "E2"
        )
        self.assertEqual(e2_crop.timestamp_seconds, 12)
        self.assertEqual(e2_crop.label, "brown dog")
        self.assertEqual(e2_crop.bounding_box, [100, 150, 700, 850])
        self.assertEqual(
            e2_crop.image, "evidence/Animal003/mr_official_01/entities/E2.jpg"
        )
        self.assertEqual(
            e2_crop.description, "Medium-sized brown dog rushing toward fence"
        )

        # Verify instrument I1 fields
        i1_crop = next(
            r for r in stored if r.incident_id == "Animal003" and r.item_id == "I1"
        )
        self.assertEqual(i1_crop.threat_level, 2)
        self.assertEqual(i1_crop.holder_entity_id, "E1")
        self.assertEqual(
            i1_crop.image, "evidence/Animal003/mr_official_01/instruments/I1.jpg"
        )

    async def test_idempotent_and_resumable(self) -> None:
        # Pre-seed one record into evidence_store
        pre_existing = EvidenceCropRecord(
            incident_id="Animal003",
            model_run_id="mr_official_01",
            item_type="entity",
            item_id="E1",
            item_name="child",
            description="Child in yellow shirt playing on lawn",
            timestamp_seconds=6,
            label="child in yellow",
            bounding_box=[100, 100, 500, 500],
            image="evidence/Animal003/mr_official_01/entities/E1.jpg",
        )
        await self.evidence_store.save_crop(pre_existing)

        # Run backfill: E1 should be skipped, other 4 processed
        summary = await self.runner.run(BackfillOptions(dry_run=False))
        self.assertEqual(summary.skipped_count, 1)
        self.assertEqual(summary.processed_count, 4)
        self.assertEqual(summary.failed_count, 0)
        self.assertEqual(len(self.vlm_client.call_log), 4)

        # Re-running the backfill should skip all 5 items
        self.vlm_client.call_log.clear()
        rerun_summary = await self.runner.run(BackfillOptions(dry_run=False))
        self.assertEqual(rerun_summary.skipped_count, 5)
        self.assertEqual(rerun_summary.processed_count, 0)
        self.assertEqual(len(self.vlm_client.call_log), 0)

    async def test_batch_size_flag(self) -> None:
        options = BackfillOptions(dry_run=False, batch_size=2)
        summary = await self.runner.run(options)

        self.assertEqual(summary.processed_count, 2)
        self.assertEqual(len(await self.evidence_store.list_crops()), 2)
        self.assertEqual(len(self.vlm_client.call_log), 2)

    async def test_single_video_filter(self) -> None:
        options = BackfillOptions(dry_run=False, video_id="Burglary004")
        summary = await self.runner.run(options)

        self.assertEqual(summary.total_videos, 1)
        self.assertEqual(summary.total_items, 2)
        self.assertEqual(summary.processed_count, 2)
        stored = await self.evidence_store.list_crops()
        self.assertEqual(len(stored), 2)
        self.assertTrue(all(r.incident_id == "Burglary004" for r in stored))

    async def test_per_item_failure_isolation(self) -> None:
        # Cause E2 to fail in the VLM
        failing_vlm = FakeVLMClient(failure_keys={("entity", "E2")})
        runner = BackfillRunner(
            report_source=self.report_source,
            vlm_client=failing_vlm,
            crop_client=self.crop_client,
            evidence_store=self.evidence_store,
        )

        summary = await runner.run(BackfillOptions(dry_run=False))

        # E2 failed, but remaining 4 items succeeded without aborting the batch
        self.assertEqual(summary.failed_count, 1)
        self.assertEqual(summary.processed_count, 4)
        self.assertEqual(len(summary.failures), 1)

        failure = summary.failures[0]
        self.assertEqual(failure.video_id, "Animal003")
        self.assertEqual(failure.item_id, "E2")
        self.assertIn("simulated failure", failure.error)

        stored = await self.evidence_store.list_crops()
        self.assertEqual(len(stored), 4)

    async def test_official_report_immutability(self) -> None:
        original_desc = self.reports[0].items[0].description
        original_id = self.reports[0].items[0].item_id

        await self.runner.run(BackfillOptions(dry_run=False))

        # The source report objects must not be modified
        self.assertEqual(self.reports[0].items[0].description, original_desc)
        self.assertEqual(self.reports[0].items[0].item_id, original_id)

    async def test_file_report_source(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            data = [
                {
                    "video_id": "RoadAccidents001",
                    "model_run_id": "MR_OFFICIAL_99",
                    "video_filepath": "videos/RoadAccidents001.mp4",
                    "incident_data": {"type": "road accident"},
                    "items": [
                        {
                            "item_type": "asset",
                            "item_id": "A1",
                            "name": "sedan",
                            "description": "Blue four-door sedan",
                        }
                    ],
                }
            ]
            json.dump(data, f)
            temp_path = Path(f.name)

        try:
            source = FileReportSource(temp_path)
            reports = await source.get_official_reports()
            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0].video_id, "RoadAccidents001")
            self.assertEqual(len(reports[0].items), 1)
            self.assertEqual(reports[0].items[0].name, "sedan")
        finally:
            temp_path.unlink()

    def test_cli_parse_args(self) -> None:
        args = parse_args(
            [
                "--dry-run",
                "--batch-size",
                "10",
                "--concurrency",
                "8",
                "--video-id",
                "Animal003",
                "--output-file",
                "crops.jsonl",
            ]
        )
        self.assertTrue(args.dry_run)
        self.assertEqual(args.batch_size, 10)
        self.assertEqual(args.concurrency, 8)
        self.assertEqual(args.video_id, "Animal003")
        self.assertEqual(args.output_file, Path("crops.jsonl"))

    def test_cli_parse_args_rejects_non_positive_batch_size(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--batch-size", "0"])
        with self.assertRaises(SystemExit):
            parse_args(["--batch-size", "-3"])

    async def test_output_file_json_lines_persistence_and_resumption(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            temp_path = Path(f.name)

        try:
            # Phase 1: Process initial batch of 2 items
            batch1_store = InMemoryEvidenceStore()
            batch1_runner = BackfillRunner(
                report_source=self.report_source,
                vlm_client=self.vlm_client,
                crop_client=self.crop_client,
                evidence_store=batch1_store,
            )
            summary1 = await batch1_runner.run(BackfillOptions(batch_size=2))
            self.assertEqual(summary1.processed_count, 2)
            self.assertEqual(summary1.skipped_count, 0)

            crops1 = await batch1_store.list_crops()
            self.assertEqual(len(crops1), 2)
            dump_evidence_records(crops1, temp_path)

            # Assert observable JSON lines file contents
            lines = [
                line.strip()
                for line in temp_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(lines), 2)
            loaded_data = [json.loads(line) for line in lines]
            self.assertEqual({d["item_id"] for d in loaded_data}, {"E1", "E2"})

            # Phase 2: Rerun loading from file; pre-existing 2 are skipped, remaining 3 are processed
            resumed_records = load_evidence_records(temp_path)
            self.assertEqual(len(resumed_records), 2)
            batch2_store = InMemoryEvidenceStore(resumed_records)
            batch2_runner = BackfillRunner(
                report_source=self.report_source,
                vlm_client=self.vlm_client,
                crop_client=self.crop_client,
                evidence_store=batch2_store,
            )
            summary2 = await batch2_runner.run(BackfillOptions())
            self.assertEqual(summary2.skipped_count, 2)
            self.assertEqual(summary2.processed_count, 3)

            crops2 = await batch2_store.list_crops()
            self.assertEqual(len(crops2), 5)
            dump_evidence_records(crops2, temp_path)

            # Phase 3: Rerun with all 5 items completed; all 5 are skipped, 0 processed
            all_records = load_evidence_records(temp_path)
            self.assertEqual(len(all_records), 5)
            batch3_store = InMemoryEvidenceStore(all_records)
            batch3_runner = BackfillRunner(
                report_source=self.report_source,
                vlm_client=self.vlm_client,
                crop_client=self.crop_client,
                evidence_store=batch3_store,
            )
            summary3 = await batch3_runner.run(BackfillOptions())
            self.assertEqual(summary3.skipped_count, 5)
            self.assertEqual(summary3.processed_count, 0)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    async def test_embeds_item_text_into_saved_records(self) -> None:
        embedder = FakeTextEmbedder(vector=[0.25] * 4)
        runner = BackfillRunner(
            report_source=self.report_source,
            vlm_client=self.vlm_client,
            crop_client=self.crop_client,
            evidence_store=self.evidence_store,
            embedder=embedder,
        )
        summary = await runner.run(BackfillOptions(concurrency=1))

        self.assertEqual(summary.processed_count, 5)
        stored = await self.evidence_store.list_crops()
        self.assertTrue(all(r.embedding == [0.25] * 4 for r in stored))
        self.assertIn("human: Child in yellow shirt playing on lawn", embedder.texts)

    async def test_embedding_failure_is_isolated_per_item(self) -> None:
        embedder = FakeTextEmbedder()
        embedder.embed = AsyncMock(side_effect=RuntimeError("embedding endpoint down"))  # type: ignore[method-assign]
        runner = BackfillRunner(
            report_source=self.report_source,
            vlm_client=self.vlm_client,
            crop_client=self.crop_client,
            evidence_store=self.evidence_store,
            embedder=embedder,
        )
        summary = await runner.run(BackfillOptions())

        self.assertEqual(summary.failed_count, 5)
        self.assertEqual(await self.evidence_store.list_crops(), [])

    async def test_live_store_upserts_rows_and_skips_known_items(self) -> None:
        crops = MagicMock()
        crops.get_crop = AsyncMock(return_value=None)
        crops.record_crop = AsyncMock(return_value={})
        store = LiveEvidenceStore(crops=crops)
        runner = BackfillRunner(
            report_source=self.report_source,
            vlm_client=self.vlm_client,
            crop_client=self.crop_client,
            evidence_store=store,
            embedder=FakeTextEmbedder(vector=[0.5] * 4),
        )

        summary = await runner.run(BackfillOptions())

        self.assertEqual(summary.processed_count, 5)
        self.assertEqual(crops.record_crop.await_count, 5)
        kwargs = crops.record_crop.await_args_list[0].kwargs
        self.assertEqual(kwargs["embedding"], [0.5] * 4)
        self.assertTrue(kwargs["image_key"].startswith("evidence/"))
        # Items saved in this run are skipped without another database lookup.
        lookups = crops.get_crop.await_count
        self.assertTrue(
            await store.has_crop("Animal003", "mr_official_01", "entity", "E1")
        )
        self.assertEqual(crops.get_crop.await_count, lookups)
        # Unknown items fall back to the database.
        crops.get_crop.return_value = {"item_id": "X"}
        self.assertTrue(
            await store.has_crop("Animal003", "mr_official_01", "entity", "X9")
        )


class ParseGroundingReplyTests(unittest.TestCase):
    def test_complete_json(self) -> None:
        self.assertEqual(
            parse_grounding_reply('{"timestamp_seconds": 7, "label": "fireball"}'),
            {"timestamp_seconds": 7, "label": "fireball"},
        )

    def test_truncated_json_recovers_both_fields(self) -> None:
        reply = '{"timestamp_seconds": 12, "label": "person in \\"hoodie\\"", "reasoning": "the su'
        self.assertEqual(
            parse_grounding_reply(reply),
            {"timestamp_seconds": 12, "label": 'person in "hoodie"'},
        )

    def test_truncated_json_missing_label_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_grounding_reply('{"timestamp_seconds": 12, "lab')

    def test_runaway_digit_run_is_recovered_by_regex(self) -> None:
        reply = (
            '{"timestamp_seconds": ' + "9" * 400 + ', "label": "x", "reasoning": "tr'
        )
        self.assertGreater(parse_grounding_reply(reply)["timestamp_seconds"], 10**300)


class GroundItemTimestampBoundsTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversized_timestamp_is_rejected_not_overflowed(self) -> None:
        client = RemoteVLMClient(model="m")
        client.api_key = "k"
        reply = (
            '{"timestamp_seconds": ' + "9" * 400 + ', "label": "x", "reasoning": "tr'
        )
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"choices": [{"message": {"content": reply}}]}
        with (
            patch("httpx.AsyncClient.post", AsyncMock(return_value=resp)),
            self.assertRaisesRegex(ValueError, "Invalid grounding fields"),
        ):
            await client.ground_item(
                video_ref="v.mp4",
                item=EvidenceItem(item_type="entity", item_id="E1", description="d"),
                incident_context={},
            )


if __name__ == "__main__":
    unittest.main()
