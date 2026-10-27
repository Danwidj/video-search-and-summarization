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

"""Dataset fetch, verification and manifest (hermetic: a fake S3 client, no R2), plus the ``_demo`` resolution."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import dataset_manifest as dm  # noqa: E402
import eval_fetch_videos  # noqa: E402
import eval_refresh_split_keys  # noqa: E402
from eval_video_resolution import (  # noqa: E402
    ResolutionError,
    build_basename_index,
    resolve_filename,
)

EVAL_DIR = Path(__file__).resolve().parents[1]
_MODIFIED = dt.datetime(2026, 10, 27, 3, 0, tzinfo=dt.UTC)


def _box(box_type: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), box_type) + body


def _mp4(seconds: int, salt: bytes = b"") -> bytes:
    mvhd = _box(b"mvhd", bytes(4) + bytes(8) + struct.pack(">II", 1000, seconds * 1000) + bytes(80))
    return _box(b"ftyp", b"isom" + bytes(4)) + _box(b"mdat", salt + bytes(32)) + _box(b"moov", mvhd)


class _Body:
    def __init__(self, data: bytes):
        self._stream = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


class _Paginator:
    def __init__(self, client):
        self.client = client

    def paginate(self, *, Bucket, Prefix):  # noqa: N803 - boto3 keyword names
        contents = [
            {"Key": key, "Size": len(data), "ETag": self.client.etags.get(key, f'"{hashlib.md5(data).hexdigest()}"'),
             "LastModified": _MODIFIED}
            for key, data in sorted(self.client.objects.items()) if key.startswith(Prefix)
        ]
        yield {"Contents": contents[:3]}
        yield {"Contents": contents[3:]}


class FakeS3:
    """Lists and serves ``objects``; ``failures`` makes a key's first N reads raise; ``serve`` overrides served bytes."""

    def __init__(self, objects: dict[str, bytes], *, etags=None, failures=None, serve=None):
        self.objects, self.etags = objects, etags or {}
        self.failures, self.serve = dict(failures or {}), serve or {}
        self.gets: list[str] = []
        self.writes: list[str] = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return _Paginator(self)

    def get_object(self, *, Bucket, Key):  # noqa: N803
        self.gets.append(Key)
        if self.failures.get(Key, 0) > 0:
            self.failures[Key] -= 1
            raise ConnectionError("connection reset")
        return {"Body": _Body(self.serve.get(Key, self.objects[Key]))}

    def __getattr__(self, name):  # put_object, delete_object, copy_object ... must never be called
        if name.startswith(("put", "delete", "copy", "upload")):
            self.writes.append(name)
        raise AttributeError(name)


DATASET = {
    "anomaly/demo/": b"",
    "anomaly/demo/Assault018_x264_demo.mp4": _mp4(12, b"a18"),
    "anomaly/assault/Assault007_x264.mp4": _mp4(30, b"a07"),
    "anomaly/burglary/Burglary004_x264.mp4": _mp4(45, b"b04"),
    "anomaly/shooting/Shooting001_x264.mp4": _mp4(5, b"s01"),
    "anomaly/burglary/notes.txt": b"not a video",
    "anomaly/explosion/Empty_x264.mp4": b"",
    "normal_videos/Normal001_x264.mp4": _mp4(9, b"n01"),
}


def _splits(tmp_path: Path, few_shot=("Assault018_x264.mp4",), evaluation=("Assault007_x264.mp4", "Burglary004_x264.mp4")):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "split_mixed.json").write_text(json.dumps({
        "category": "Mixed", "seed": 42, "few_shot_demo_videos": list(few_shot), "evaluation_videos": list(evaluation),
    }))
    return tmp_path


def _fetch(client, tmp_path, **kwargs):
    return eval_fetch_videos.fetch(
        client, "bucket", videos_dir=tmp_path / "eval_data" / "videos",
        reproducibility_dir=kwargs.pop("reproducibility_dir", None) or _splits(tmp_path / "repro"),
        sleep=kwargs.pop("sleep", lambda s: None), log=lambda line: None, **kwargs,
    )


# --- selection and naming --------------------------------------------------------------


def test_selection_keeps_dataset_clips_and_reports_everything_else():
    listing = [{"Key": k, "Size": len(v), "ETag": '"x"', "LastModified": _MODIFIED} for k, v in DATASET.items()]
    selected, skipped = dm.select_dataset_objects(listing)
    assert [o["Key"] for o in selected] == [
        "anomaly/assault/Assault007_x264.mp4", "anomaly/burglary/Burglary004_x264.mp4",
        "anomaly/demo/Assault018_x264_demo.mp4",
    ]
    assert {s["key"]: s["reason"] for s in skipped} == {
        "anomaly/demo/": "folder marker",
        "anomaly/shooting/Shooting001_x264.mp4": "excluded folder shooting/",
        "anomaly/burglary/notes.txt": "not an .mp4 file",
        "anomaly/explosion/Empty_x264.mp4": "zero-byte object",
    }


@pytest.mark.parametrize(("name", "canonical"), [
    ("Assault018_x264_demo.mp4", "Assault018_x264.mp4"),
    ("Assault018_x264.mp4", "Assault018_x264.mp4"),
    ("demo_file_3.mp4", "demo_file_3.mp4"),
    ("RoadAccidents039_x264_demo.MP4", "RoadAccidents039_x264.MP4"),
])
def test_canonical_basename(name, canonical):
    assert dm.canonical_basename(name) == canonical


def test_incident_id_and_local_path_keep_the_original_filename(tmp_path):
    assert dm.incident_id_for("RoadAccidents039_x264.mp4") == "RoadAccidents039"
    assert dm.local_path_for(tmp_path, "anomaly/demo/Assault018_x264_demo.mp4") == (
        tmp_path / "demo" / "Assault018_x264_demo.mp4"
    )


def test_plain_and_multipart_etags():
    assert dm.plain_etag_md5('"0123456789abcdef0123456789ABCDEF"') == "0123456789abcdef0123456789abcdef"
    assert dm.plain_etag_md5('"0123456789abcdef0123456789abcdef-4"') is None
    assert dm.plain_etag_md5(None) is None


# --- _demo resolution ------------------------------------------------------------------


def test_demo_clip_resolves_from_the_ground_truth_filename_and_its_own_name():
    index = build_basename_index(["anomaly/demo/Assault018_x264_demo.mp4", "anomaly/assault/Assault007_x264.mp4"])
    assert resolve_filename("Assault018_x264.mp4", index) == "anomaly/demo/Assault018_x264_demo.mp4"
    assert resolve_filename("Assault018_x264_demo.mp4", index) == "anomaly/demo/Assault018_x264_demo.mp4"
    assert resolve_filename("Assault007_x264.mp4", index) == "anomaly/assault/Assault007_x264.mp4"


def test_a_plain_clip_and_its_demo_copy_are_ambiguous():
    index = build_basename_index(["anomaly/demo/Assault018_x264_demo.mp4", "anomaly/assault/Assault018_x264.mp4"])
    with pytest.raises(ResolutionError, match="ambiguous"):
        resolve_filename("Assault018_x264.mp4", index)


# --- fetch, resume, retry, integrity ----------------------------------------------------


def test_fetch_downloads_verifies_and_builds_the_manifest(tmp_path):
    client = FakeS3(DATASET)
    manifest = _fetch(client, tmp_path)
    assert manifest["integrity"]["ok"] is True
    assert manifest["summary"]["clips"] == 3
    assert manifest["summary"]["clips_by_r2_folder"] == {"assault": 1, "burglary": 1, "demo": 1}
    demo = next(c for c in manifest["clips"] if c["demo"])
    assert demo["filename"] == "Assault018_x264.mp4" and demo["incident_id"] == "Assault018"
    assert demo["local_path"] == "eval_data/videos/demo/Assault018_x264_demo.mp4"
    assert demo["sha256"] == hashlib.sha256(DATASET["anomaly/demo/Assault018_x264_demo.mp4"]).hexdigest()
    assert demo["etag_md5_checked"] is True and demo["duration_seconds"] == 12.0
    assert (tmp_path / demo["local_path"]).read_bytes() == DATASET["anomaly/demo/Assault018_x264_demo.mp4"]
    assert not list((tmp_path / "eval_data").rglob("*.part"))
    assert "anomaly/shooting/Shooting001_x264.mp4" not in client.gets
    assert client.writes == []


def test_rerun_resumes_without_downloading_verified_clips(tmp_path):
    _fetch(FakeS3(DATASET), tmp_path)
    client = FakeS3(DATASET)
    manifest = _fetch(client, tmp_path)
    assert client.gets == [] and manifest["integrity"]["ok"] is True


def test_a_corrupted_local_copy_is_downloaded_again(tmp_path):
    _fetch(FakeS3(DATASET), tmp_path)
    local = tmp_path / "eval_data/videos/assault/Assault007_x264.mp4"
    local.write_bytes(bytes(len(local.read_bytes())))  # same size, wrong content
    client = FakeS3(DATASET)
    manifest = _fetch(client, tmp_path)
    assert client.gets == ["anomaly/assault/Assault007_x264.mp4"] and manifest["integrity"]["ok"] is True
    assert local.read_bytes() == DATASET["anomaly/assault/Assault007_x264.mp4"]


def test_transfer_errors_are_retried_with_backoff(tmp_path):
    sleeps = []
    client = FakeS3(DATASET, failures={"anomaly/assault/Assault007_x264.mp4": 2})
    manifest = _fetch(client, tmp_path, sleep=sleeps.append)
    assert manifest["integrity"]["ok"] is True and sleeps == [1, 2]
    entry = next(c for c in manifest["clips"] if c["incident_id"] == "Assault007")
    assert entry["problems"] == []


def test_content_that_never_matches_its_etag_is_a_finding_and_leaves_no_file(tmp_path):
    key = "anomaly/burglary/Burglary004_x264.mp4"
    tampered = bytearray(DATASET[key])
    tampered[-1] ^= 0xFF
    client = FakeS3(DATASET, serve={key: bytes(tampered)})
    manifest = _fetch(client, tmp_path)
    assert manifest["integrity"]["ok"] is False
    assert manifest["integrity"]["clips_with_problems"][key] == ["MD5 does not match the R2 ETag"]
    assert client.gets.count(key) == eval_fetch_videos.MAX_ATTEMPTS
    assert not (tmp_path / "eval_data/videos/burglary/Burglary004_x264.mp4").exists()
    assert not list((tmp_path / "eval_data").rglob("*.part"))


def _multipart_etag(data: bytes, part_size: int) -> str:
    parts = [data[i:i + part_size] for i in range(0, len(data), part_size)]
    return f'"{hashlib.md5(b"".join(hashlib.md5(p).digest() for p in parts)).hexdigest()}-{len(parts)}"'


def test_a_multipart_etag_is_reproduced_from_the_local_file(tmp_path):
    key = "anomaly/assault/Assault007_x264.mp4"
    big = _mp4(30, b"big" + bytes(3 * 1024 * 1024))  # > 2 MiB, so 1 MiB parts give 4 parts
    objects = {**DATASET, key: big}
    manifest = _fetch(FakeS3(objects, etags={key: _multipart_etag(big, 1024 * 1024)}), tmp_path)
    entry = next(c for c in manifest["clips"] if c["r2_key"] == key)
    assert entry["etag_kind"] == "multipart" and entry["etag_md5_checked"] is True
    assert entry["problems"] == [] and manifest["integrity"]["ok"] is True


def test_a_multipart_etag_that_no_part_size_reproduces_is_a_problem(tmp_path):
    key = "anomaly/assault/Assault007_x264.mp4"
    manifest = _fetch(FakeS3(DATASET, etags={key: '"0123456789abcdef0123456789abcdef-1"'}), tmp_path)
    assert manifest["integrity"]["clips_with_problems"][key] == ["multipart ETag not reproduced from the local file"]


def test_duplicates_unreadable_headers_and_split_coverage_are_findings(tmp_path):
    objects = {
        "anomaly/assault/Assault007_x264.mp4": _mp4(30, b"same"),
        "anomaly/demo/Assault009_x264_demo.mp4": _mp4(30, b"same"),
        "anomaly/burglary/Burglary004_x264.mp4": b"\x00" * 64,  # no MP4 header
    }
    splits = _splits(tmp_path / "repro", few_shot=("Assault007_x264.mp4",), evaluation=("Missing001_x264.mp4",))
    manifest = _fetch(FakeS3(objects), tmp_path, reproducibility_dir=splits)
    integrity = manifest["integrity"]
    assert integrity["ok"] is False
    assert integrity["duplicate_content"] == [["anomaly/assault/Assault007_x264.mp4",
                                               "anomaly/demo/Assault009_x264_demo.mp4"]]
    assert integrity["unreadable_duration"] == ["anomaly/burglary/Burglary004_x264.mp4"]
    assert integrity["split_videos_missing_from_dataset"] == ["Missing001_x264.mp4"]
    assert integrity["dataset_clips_not_in_any_split"] == ["Assault009_x264.mp4", "Burglary004_x264.mp4"]


def test_verify_only_rehashes_local_copies(tmp_path):
    manifest = _fetch(FakeS3(DATASET), tmp_path)
    assert eval_fetch_videos.verify_only(manifest, eval_dir=tmp_path) == []
    (tmp_path / "eval_data/videos/assault/Assault007_x264.mp4").write_bytes(b"changed")
    (tmp_path / "eval_data/videos/burglary/Burglary004_x264.mp4").unlink()
    problems = eval_fetch_videos.verify_only(manifest, eval_dir=tmp_path)
    assert problems == ["eval_data/videos/assault/Assault007_x264.mp4: SHA-256 differs from the manifest",
                        "eval_data/videos/burglary/Burglary004_x264.mp4: missing"]


def test_manifest_hash_depends_only_on_filenames_and_content(tmp_path):
    first = _fetch(FakeS3(DATASET), tmp_path / "one")
    second = _fetch(FakeS3(DATASET), tmp_path / "two")
    assert first["clips_sha256"] == second["clips_sha256"]


# --- split-manifest key refresh -----------------------------------------------------------


def test_refresh_updates_stale_keys_and_keeps_membership():
    manifest = {
        "category": "Assault", "seed": 42,
        "few_shot_demo_videos": ["Assault030_x264.mp4"], "evaluation_videos": ["Assault018_x264.mp4", "Assault007_x264.mp4"],
        "few_shot_demo_videos_r2_keys": {"Assault030_x264.mp4": "anomaly/assault/Assault030_x264.mp4"},
        "evaluation_videos_r2_keys": {"Assault018_x264.mp4": "anomaly/assault/Assault018_x264.mp4",
                                      "Assault007_x264.mp4": "anomaly/assault/Assault007_x264.mp4"},
    }
    index = build_basename_index(["anomaly/demo/Assault030_x264_demo.mp4", "anomaly/demo/Assault018_x264_demo.mp4",
                                  "anomaly/assault/Assault007_x264.mp4"])
    refreshed, changes = eval_refresh_split_keys.refresh_keys(manifest, index, refreshed_at="2026-10-27T00:00:00+00:00")
    assert refreshed["evaluation_videos"] == manifest["evaluation_videos"]
    assert refreshed["few_shot_demo_videos"] == manifest["few_shot_demo_videos"]
    assert refreshed["evaluation_videos_r2_keys"]["Assault018_x264.mp4"] == "anomaly/demo/Assault018_x264_demo.mp4"
    assert [c["filename"] for c in changes] == ["Assault030_x264.mp4", "Assault018_x264.mp4"]
    assert refreshed["r2_keys_refreshed_at"] == "2026-10-27T00:00:00+00:00"
    assert manifest["evaluation_videos_r2_keys"]["Assault018_x264.mp4"] == "anomaly/assault/Assault018_x264.mp4"


def test_refresh_refuses_an_unresolvable_filename():
    manifest = {"few_shot_demo_videos": [], "evaluation_videos": ["Gone001_x264.mp4"]}
    with pytest.raises(ResolutionError):
        eval_refresh_split_keys.refresh_keys(manifest, build_basename_index([]), refreshed_at="t")


# --- the tracked manifests agree with each other ------------------------------------------


def _tracked_dataset_manifest() -> dict:
    path = EVAL_DIR / "eval_reproducibility" / "dataset-manifest-v1.json"
    if not path.exists():
        pytest.skip("dataset manifest not generated yet")
    return json.loads(path.read_text())


def test_tracked_dataset_manifest_is_complete_and_clean():
    manifest = _tracked_dataset_manifest()
    assert manifest["manifest_version"] == "dataset-manifest-v1"
    assert manifest["integrity"]["ok"] is True
    assert manifest["summary"]["clips"] == len(manifest["clips"]) == 80
    assert "shooting" not in manifest["summary"]["clips_by_r2_folder"]
    assert len({c["incident_id"] for c in manifest["clips"]}) == 80
    assert all(len(c["sha256"]) == 64 and c["problems"] == [] for c in manifest["clips"])
    assert manifest["clips_sha256"] == hashlib.sha256(
        "\n".join(f"{c['filename']} {c['sha256']}" for c in manifest["clips"]).encode()
    ).hexdigest()


def test_tracked_split_manifests_point_at_the_dataset_manifest_keys():
    keys = {c["filename"]: c["r2_key"] for c in _tracked_dataset_manifest()["clips"]}
    seen = []
    for path in sorted((EVAL_DIR / "eval_reproducibility").glob("split_*.json")):
        split = json.loads(path.read_text())
        for field in ("few_shot_demo_videos", "evaluation_videos"):
            for filename in split[field]:
                assert split[f"{field}_r2_keys"][filename] == keys[filename], (path.name, filename)
                seen.append(filename)
    assert sorted(seen) == sorted(keys) and len(seen) == 80
