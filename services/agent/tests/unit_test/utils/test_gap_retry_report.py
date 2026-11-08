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

"""The chat's gap retry of one existing report: the extracted stage, its caps, the item selection and the jobs."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import numpy as np
import pytest

from vss_agents.utils import crop_evidence
from vss_agents.utils import gap_retry_jobs
from vss_agents.utils.crop_evidence import CropEvidenceService
from vss_agents.utils.crop_evidence import CropResult
from vss_agents.utils.crop_evidence import Detection
from vss_agents.utils.crop_evidence import FakeZoomNamer
from vss_agents.utils.crop_evidence import GapRetryOutcome
from vss_agents.utils.crop_evidence import retry_gap_crops

FRAME = np.full((80, 120, 3), 128, dtype=np.uint8)
GAP_BOX = Detection(box=[200, 200, 600, 600], score=0.9, label="crowbar")
NOT_LOCATED = "object not located at 1s or within 6s either side"


class QueryLog:
    """A detector that answers from ``by_query`` and records every query it is asked."""

    def __init__(self, by_query: dict[str, list[Detection]] | None = None, error: Exception | None = None) -> None:
        self.by_query = by_query or {}
        self.error = error
        self.queries: list[str] = []

    def is_available(self) -> bool:
        return True

    def detect(self, frame: np.ndarray, query: str) -> list[Detection]:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return self.by_query.get(query, [])


def entry(
    item_id: str, *, image: str | None = None, image_gap: str | None = NOT_LOCATED, name: str = "crowbar"
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "item_type": "asset",
        "item_name": name,
        "label": name,
        "description": "Heavy metal tool. Painted red.",
        "timestamp_seconds": 1,
        "image": image,
        "image_gap": image_gap,
    }


def semaphore() -> asyncio.Semaphore:
    return asyncio.Semaphore(4)


@pytest.mark.asyncio
async def test_a_confirmed_box_is_found_and_says_its_second() -> None:
    detector = QueryLog({"crowbar": [GAP_BOX]})
    outcomes = await retry_gap_crops(
        [(entry("A1"), None)],
        video_ref=FRAME,
        video_id="v",
        detector=detector,
        checker=FakeZoomNamer(),
        stop_at=None,
        semaphore=semaphore(),
    )
    found = outcomes["A1"].found
    assert found is not None and found.located
    assert found.box_seconds == 4  # the first offset tried after the requested second
    assert outcomes["A1"].reason is None


@pytest.mark.asyncio
async def test_a_box_the_model_refuses_gives_the_reason() -> None:
    checker = FakeZoomNamer(box_checks={"crowbar": {"match": False, "confidence": 0.9, "seen": "shelf"}})
    outcomes = await retry_gap_crops(
        [(entry("A1"), None)],
        video_ref=FRAME,
        video_id="v",
        detector=QueryLog({"crowbar": [GAP_BOX]}),
        checker=checker,
        stop_at=None,
        semaphore=semaphore(),
    )
    assert outcomes["A1"].found is None
    assert outcomes["A1"].reason is not None
    assert outcomes["A1"].reason.startswith("the video model did not confirm a box at")


@pytest.mark.asyncio
async def test_an_item_the_detector_never_finds_says_no_box_was_found() -> None:
    outcomes = await retry_gap_crops(
        [(entry("A1"), None)],
        video_ref=FRAME,
        video_id="v",
        detector=QueryLog(),
        checker=FakeZoomNamer(),
        stop_at=None,
        semaphore=semaphore(),
    )
    assert outcomes["A1"].found is None
    assert outcomes["A1"].reason == crop_evidence.NO_BOX_REASON


@pytest.mark.asyncio
async def test_a_spent_time_limit_gives_no_detector_call_and_a_time_reason() -> None:
    detector = QueryLog({"crowbar": [GAP_BOX]})
    outcomes = await retry_gap_crops(
        [(entry("A1"), None)],
        video_ref=FRAME,
        video_id="v",
        detector=detector,
        checker=FakeZoomNamer(),
        stop_at=time.monotonic() - 1,
        semaphore=semaphore(),
    )
    assert detector.queries == []
    assert outcomes["A1"].reason == crop_evidence.TIME_REASON


@pytest.mark.asyncio
async def test_a_failing_detector_ends_only_its_item() -> None:
    outcomes = await retry_gap_crops(
        [(entry("A1"), None), (entry("A2"), "detector failed at 1s (ReadTimeout)")],
        video_ref=FRAME,
        video_id="v",
        detector=QueryLog({"crowbar": [GAP_BOX]}, error=RuntimeError("boom")),
        checker=FakeZoomNamer(),
        stop_at=None,
        semaphore=semaphore(),
    )
    assert set(outcomes) == {"A1", "A2"}
    assert all(outcome.found is None for outcome in outcomes.values())
    assert all(outcome.reason is not None for outcome in outcomes.values())


@pytest.mark.asyncio
async def test_the_call_budget_refusal_is_a_reason_for_its_item(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crop_evidence, "REPORT_GAP_RETRY_MAX_CALLS", 1)
    service = CropEvidenceService(detector=QueryLog({"crowbar": [GAP_BOX]}), namer=FakeZoomNamer())
    outcomes = await service.retry_report_gaps(
        video_ref=FRAME,
        video_id="v",
        pending=[(entry("A1"), None), (entry("A2"), None)],
        deadline=time.monotonic() + 60,
    )
    # One call for the whole request: whichever item takes it finds the box, and the other is refused with the cap reason.
    assert sum(outcome.found is not None for outcome in outcomes.values()) == 1
    assert [outcome.reason for outcome in outcomes.values() if outcome.found is None] == [crop_evidence.CALL_CAP_REASON]


@pytest.mark.asyncio
async def test_the_service_retries_every_pending_item_with_its_model_check() -> None:
    checker = FakeZoomNamer()
    service = CropEvidenceService(detector=QueryLog({"crowbar": [GAP_BOX]}), namer=checker)
    outcomes = await service.retry_report_gaps(
        video_ref=FRAME,
        video_id="v",
        pending=[(entry("A1"), None), (entry("A2"), "detector failed at 1s (ReadTimeout)")],
        deadline=time.monotonic() + 60,
    )
    assert all(outcome.found is not None for outcome in outcomes.values())
    assert len(checker.checks) == 2  # one model check per found box, the same check the analysis makes


@pytest.mark.asyncio
async def test_without_a_detector_or_a_model_check_nothing_is_looked_for() -> None:
    no_model = CropEvidenceService(detector=QueryLog({"crowbar": [GAP_BOX]}), namer=None)
    outcomes = await no_model.retry_report_gaps(
        video_ref=FRAME, video_id="v", pending=[(entry("A1"), None)], deadline=time.monotonic() + 60
    )
    assert outcomes["A1"].found is None
    assert outcomes["A1"].reason == "the video model check is not configured"


@pytest.mark.asyncio
async def test_without_a_detector_nothing_is_looked_for() -> None:
    service = CropEvidenceService(detector=QueryLog(), namer=FakeZoomNamer())
    service.detector = None
    outcomes = await service.retry_report_gaps(
        video_ref=FRAME, video_id="v", pending=[(entry("A1"), None)], deadline=time.monotonic() + 60
    )
    assert outcomes["A1"].reason == "the box detector is not configured"


@pytest.mark.parametrize(
    ("image_gap", "gap"),
    [
        (None, None),
        (NOT_LOCATED, None),
        ("detector failed at 1s (ReadTimeout)", "detector failed at 1s (ReadTimeout)"),
        (
            "no usable box within 2s either side: too small to judge",
            "no usable box within 2s either side: too small to judge",
        ),
    ],
)
def test_a_stored_gap_is_the_first_look_gap_a_retry_reads(image_gap: str | None, gap: str | None) -> None:
    assert crop_evidence.stored_gap_for_retry({"image_gap": image_gap}) == gap


def test_the_selection_takes_every_item_with_no_box_and_says_why_for_the_others() -> None:
    evidence = [
        entry("A1"),
        entry("A2", image="evidence/v/run-1/A2.jpg", image_gap=None),
        entry("A3", image_gap="no frame produced at 1s"),
    ]
    selection = gap_retry_jobs.select(evidence, None)
    assert [item["item_id"] for item, _ in selection.pending] == ["A1"]
    assert "A3" in selection.refused and "A2" not in selection.refused


def test_a_named_item_with_a_box_is_refused_and_a_missing_one_is_an_error() -> None:
    evidence = [entry("A1"), entry("A2", image="evidence/v/run-1/A2.jpg", image_gap=None)]
    selection = gap_retry_jobs.select(evidence, "A2")
    assert selection.pending == []
    assert selection.refused == {"A2": "it already has a box"}
    with pytest.raises(ValueError, match="there is no item A9 in this report"):
        gap_retry_jobs.select(evidence, "A9")


async def _wait_done(job: gap_retry_jobs.GapRetryJob) -> None:
    for _ in range(200):
        if job.done:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the job did not finish")


@pytest.mark.asyncio
async def test_a_job_lists_every_item_pending_then_its_outcome() -> None:
    jobs = gap_retry_jobs.GapRetryJobs()
    selection = gap_retry_jobs.select([entry("A1"), entry("A2", image="x", image_gap=None)], None)
    found = CropResult(
        image_bytes=None, normalized_box=[100, 200, 300, 400], score=1.0, frame_size=(120, 80), box_seconds=4.0
    )

    async def runner(deadline: float) -> dict[str, GapRetryOutcome]:
        await asyncio.sleep(0)
        return {"A1": GapRetryOutcome(found)}

    job = jobs.start(video_id="v", revision_id=7, selection=selection, runner=runner, wall_seconds=60)
    assert not job.done
    assert jobs.active("v") is job
    assert [item.status for item in job.items] == [gap_retry_jobs.ITEM_PENDING]

    await _wait_done(job)
    assert jobs.active("v") is None
    [item] = job.items
    assert item.status == gap_retry_jobs.ITEM_FOUND
    assert item.seconds == 4.0
    assert item.box == [100, 200, 300, 400]


@pytest.mark.asyncio
async def test_an_item_without_an_outcome_or_a_runner_failure_is_not_found_or_not_retried() -> None:
    jobs = gap_retry_jobs.GapRetryJobs()
    selection = gap_retry_jobs.select([entry("A1"), entry("A2")], None)

    async def silent(deadline: float) -> dict[str, GapRetryOutcome]:
        return {}

    job = jobs.start(video_id="v", revision_id=None, selection=selection, runner=silent, wall_seconds=60)
    await _wait_done(job)
    assert [item.status for item in job.items] == [gap_retry_jobs.ITEM_NOT_FOUND] * 2
    assert all(item.reason == crop_evidence.TIME_REASON for item in job.items)

    async def broken(deadline: float) -> dict[str, GapRetryOutcome]:
        raise RuntimeError("model down")

    job = jobs.start(video_id="v", revision_id=None, selection=selection, runner=broken, wall_seconds=60)
    await _wait_done(job)
    assert [item.status for item in job.items] == [gap_retry_jobs.ITEM_NOT_RETRIED] * 2
    assert all(item.reason == "the retry failed" for item in job.items)


@pytest.mark.asyncio
async def test_a_refused_item_is_listed_with_its_reason_and_the_registry_keeps_a_few_jobs() -> None:
    jobs = gap_retry_jobs.GapRetryJobs()
    selection = gap_retry_jobs.select([entry("A1", image="x", image_gap=None)], "A1")

    async def nothing(deadline: float) -> dict[str, GapRetryOutcome]:
        return {}

    job = jobs.start(video_id="v", revision_id=None, selection=selection, runner=nothing, wall_seconds=60)
    await _wait_done(job)
    [item] = job.items
    assert item.status == gap_retry_jobs.ITEM_NOT_RETRIED
    assert item.reason == "it already has a box"

    for _ in range(gap_retry_jobs.JOBS_KEPT + 3):
        later = jobs.start(video_id="v", revision_id=None, selection=selection, runner=nothing, wall_seconds=60)
        await _wait_done(later)
    assert jobs.get(job.job_id) is None  # the oldest job is the first one dropped
    assert jobs.get(later.job_id) is later
