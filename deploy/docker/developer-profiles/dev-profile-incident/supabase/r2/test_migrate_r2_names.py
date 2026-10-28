# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for migrate_r2_names.py: an in-memory bucket and database, no network.

cd supabase/r2 && uv run --no-project --with boto3 --with pytest pytest -q
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

import migrate_r2_names as m

T0 = dt.datetime(2026, 10, 22, 12, 0, tzinfo=dt.UTC)
SENSORS = [{"sensorId": "sensor-uuid-1", "name": "Animal001_x264"}]
UP1 = "uploads/sensor-uuid-1/aaaa.mp4"
UP2 = "uploads/sensor-xyz/bbbb.mp4"
RUN = "6078175c-9b25-4d35-92f6-cc7862142529"


class FakeS3:
    def __init__(self, objects: dict[str, tuple[bytes, dict[str, str]]]) -> None:
        self.objects = objects
        self.calls: list[str] = []

    def list_objects_v2(
        self, Bucket: str, ContinuationToken: str | None = None
    ) -> dict[str, Any]:
        keys = sorted(self.objects)
        return {
            "Contents": [
                {
                    "Key": k,
                    "Size": len(self.objects[k][0]),
                    "LastModified": T0 + dt.timedelta(minutes=i),
                }
                for i, k in enumerate(keys)
            ],
            "IsTruncated": False,
        }

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        body, meta = self.objects[Key]
        return {
            "ContentLength": len(body),
            "ETag": f'"{hash(body) & 0xFFFF:x}"',
            "Metadata": meta,
            "ContentType": "x",
        }

    def copy_object(
        self,
        Bucket: str,
        Key: str,
        CopySource: dict[str, str],
        Metadata: dict[str, str],
        **_: Any,
    ) -> None:
        self.calls.append("copy")
        self.objects[Key] = (self.objects[CopySource["Key"]][0], dict(Metadata))

    def delete_object(self, **_: Any) -> None:  # the script must never call this
        raise AssertionError("delete_object called")


class FakeDb:
    def __init__(self) -> None:
        self.rpcs: list[dict[str, Any]] = []

    def call(self, path: str, body: Any = None) -> Any:
        assert path == "rpc/apply_r2_rename"
        self.rpcs.append(body)
        return {"videoId": body["p_video_id"]}


def world() -> tuple[
    dict[str, dict[str, Any]], FakeS3, list[dict[str, Any]], dict[str, str]
]:
    ev_old = f"evidence/v1/{RUN}/asset-3.jpg"
    bucket = {
        UP1: b"video-one",
        UP2: b"video-two-xx",
        f"thumbnails/{UP1}.webp": b"thumb",
        "evidence/v1/5ef1ea1963c242309a8dd8024455cfbd/E1.jpg": b"e1",
        "evidence/v1/5ef1ea1963c242309a8dd8024455cfbd/assets/A1.jpg": b"a1",
        ev_old: b"edit",
        "evidence/gone/abcdef/E1.jpg": b"orphan",
        "uploads/Already.mp4": b"keep",
        "anomaly/demo/x.mp4": b"fixture",
    }
    s3 = FakeS3({k: (v, {}) for k, v in bucket.items()})
    videos = [
        {
            "id": "v1",
            "filepath": UP1,
            "source": "sensor-uuid-1",
            "uploaded_datetime": "2026-10-22T12:16:29.468",
        },
        {
            "id": "v2",
            "filepath": UP2,
            "source": "sensor-xyz",
            "uploaded_datetime": "2026-10-23T01:02:03",
        },
    ]
    refs = {"evidence/v1/5ef1ea1963c242309a8dd8024455cfbd/E1.jpg": "v1"}
    return m.list_bucket(s3, "b"), s3, videos, refs


def plan_of(objects, videos, refs, done=None):
    return m.build_plan(objects, videos, refs, m.sensor_names(SENSORS), done or {})


def test_readable_name_keeps_the_original_and_replaces_unsafe_characters() -> None:
    assert m.readable_name("My clip (1).mp4") == "My_clip_(1).mp4"
    assert m.readable_name("../etc/pass wd.mp4") == "pass_wd.mp4"
    assert m.readable_name(".hidden.mp4") == "_hidden.mp4"
    assert len(m.readable_name("a" * 300 + ".mp4")) == m.MAX_NAME_LENGTH
    assert m.readable_name("a" * 300 + ".mp4").endswith(".mp4")
    assert m.with_counter("clip.mp4", 3) == "clip-3.mp4"


def test_plan_gives_every_legacy_object_a_readable_key_without_ids() -> None:
    objects, _s3, videos, refs = world()
    plan = plan_of(objects, videos, refs)
    new = {mv.old: mv.new for mv in plan.moves}
    assert new[UP1] == "uploads/Animal001_x264.mp4"
    assert new[UP2] == "uploads/upload-20261023-010203.mp4"
    assert new[f"thumbnails/{UP1}.webp"] == "thumbnails/uploads/Animal001_x264.mp4.webp"
    assert (
        new["evidence/v1/5ef1ea1963c242309a8dd8024455cfbd/E1.jpg"]
        == "evidence/uploads/Animal001_x264.mp4/run-1/E1.jpg"
    )
    assert (
        new["evidence/v1/5ef1ea1963c242309a8dd8024455cfbd/assets/A1.jpg"]
        == "evidence/uploads/Animal001_x264.mp4/run-1/A1.jpg"
    )
    assert (
        new[f"evidence/v1/{RUN}/asset-3.jpg"]
        == "evidence/uploads/Animal001_x264.mp4/edit-1/asset-3.jpg"
    )
    assert plan.orphans == ["evidence/gone/abcdef/E1.jpg"]
    assert "uploads/Already.mp4" not in new and "anomaly/demo/x.mp4" not in new


def test_a_name_that_is_taken_gets_a_counter_and_nothing_is_reused() -> None:
    objects, _s3, videos, refs = world()
    objects["uploads/Animal001_x264.mp4"] = {"size": 1, "modified": T0.isoformat()}
    plan = plan_of(objects, videos, refs)
    assert {mv.old: mv.new for mv in plan.moves}[UP1] == "uploads/Animal001_x264-2.mp4"
    assert len({mv.new for mv in plan.moves}) == len(plan.moves)


def test_apply_copies_verifies_updates_the_database_and_never_deletes() -> None:
    objects, s3, videos, refs = world()
    plan = plan_of(objects, videos, refs)
    for mv in plan.moves:
        m.copy_and_verify(s3, "b", mv)
    assert {mv.state for mv in plan.moves} == {"verified"}
    db = FakeDb()
    results = m.apply_database(db, plan)
    assert sorted(results) == ["v1", "v2"]
    first = next(r for r in db.rpcs if r["p_video_id"] == "v1")
    assert first["p_filepath"] == "uploads/Animal001_x264.mp4"
    assert first["p_key_map"][
        "evidence/v1/5ef1ea1963c242309a8dd8024455cfbd/E1.jpg"
    ] == ("evidence/uploads/Animal001_x264.mp4/run-1/E1.jpg")
    out = m.report(plan, True, results)
    assert (
        UP1 in out["safe_to_delete"]
        and "evidence/gone/abcdef/E1.jpg" not in out["safe_to_delete"]
    )
    assert s3.objects[UP1][0] == s3.objects["uploads/Animal001_x264.mp4"][0], (
        "the old object is untouched"
    )
    assert s3.objects["uploads/Animal001_x264.mp4"][1] == {m.RENAMED_FROM: UP1}


def test_a_second_run_reuses_the_same_keys_and_copies_nothing_again() -> None:
    objects, s3, videos, refs = world()
    for mv in plan_of(objects, videos, refs).moves:
        m.copy_and_verify(s3, "b", mv)
    copies = s3.calls.count("copy")
    again_objects = m.list_bucket(s3, "b")
    done = m.renamed_from(s3, "b", again_objects)
    videos = [
        {**v, "filepath": done.get(v["filepath"], v["filepath"])} for v in videos
    ]  # the database was updated
    plan = plan_of(again_objects, videos, refs, done)
    assert {mv.old: mv.new for mv in plan.moves}[UP1] == "uploads/Animal001_x264.mp4"
    for mv in plan.moves:
        m.copy_and_verify(s3, "b", mv)
    assert s3.calls.count("copy") == copies
    assert {mv.state for mv in plan.moves} == {"verified"}


def test_a_different_object_at_the_new_key_is_never_overwritten() -> None:
    objects, s3, videos, refs = world()
    plan = plan_of(objects, videos, refs)
    target = next(mv for mv in plan.moves if mv.old == UP1)
    s3.objects[target.new] = (b"someone else's", {})
    m.copy_and_verify(s3, "b", target)
    assert target.state == "failed" and s3.objects[target.new][0] == b"someone else's"


def test_a_video_with_a_failed_copy_keeps_its_database_rows() -> None:
    objects, s3, videos, refs = world()
    plan = plan_of(objects, videos, refs)
    for mv in plan.moves:
        m.copy_and_verify(s3, "b", mv)
    next(
        mv for mv in plan.moves if mv.video_id == "v1" and mv.kind == "evidence"
    ).state = "failed"
    db = FakeDb()
    assert sorted(m.apply_database(db, plan)) == ["v2"]
    assert any("not all objects verified" in w for w in plan.warnings)


def test_payload_keys_are_reported() -> None:
    objects, _s3, videos, refs = world()
    plan = plan_of(objects, videos, refs)
    warnings = m.payload_key_warnings([{"id": 7, "payload": {"x": UP1}}], plan.moves)
    assert warnings == [f"report_revisions 7: payload mentions {UP1}"]


def test_script_has_no_delete_call() -> None:
    assert "delete_object" not in Path(m.__file__).read_text()
    with pytest.raises(AssertionError):
        FakeS3({}).delete_object()
