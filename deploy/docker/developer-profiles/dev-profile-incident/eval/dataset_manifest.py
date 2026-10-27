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

"""The evaluation video set: which R2 objects it holds, how a local copy is verified, and its manifest.

``scripts/eval_fetch_videos.py`` uses these helpers to download the dataset clips
(``anomaly/<folder>/<file>``, every folder except ``shooting/``) into the
gitignored ``eval_data/videos/<folder>/<file>`` and to write the tracked manifest
``eval_reproducibility/dataset-manifest-v1.json``. Everything here is pure or
works on local files, so the tests need no network.

Integrity rules for one clip:
- the local size equals R2's ``Size``;
- the local MD5 equals the ``ETag`` when the ETag is a plain MD5 (single-part
  upload); for a multipart ETag (``<md5>-<parts>``) the ETag is recomputed from the
  local file for every whole-MiB part size that gives that many parts, and must match
  one of them (an ETag no candidate reproduces is a problem);
- the SHA-256 is recorded, and is what later runs verify against;
- the MP4 ``mvhd`` duration is read from the local file (``video_duration``); an
  unreadable header is a finding, never a guess.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath

from video_duration import mp4_duration_seconds

MANIFEST_VERSION = "dataset-manifest-v1"
DATASET_PREFIX = "anomaly/"
EXCLUDED_FOLDERS = frozenset({"shooting"})
VIDEO_EXTENSIONS = (".mp4",)
_PLAIN_MD5_ETAG = re.compile(r"^[0-9a-f]{32}$")
_CHUNK = 1024 * 1024


DEMO_SUFFIX = "_demo"


def canonical_basename(name: str) -> str:
    """``name`` without a ``_demo`` suffix before its extension (``A_x264_demo.mp4`` -> ``A_x264.mp4``).

    The only filename alias the evaluation allows: R2's ``anomaly/demo/`` folder holds
    presentation-demo copies of dataset clips renamed this way and otherwise unchanged
    (sizes identical). Ground truth and split manifests name the plain file.
    """
    stem, dot, extension = name.rpartition(".")
    if dot and stem.endswith(DEMO_SUFFIX):
        return f"{stem[: -len(DEMO_SUFFIX)]}.{extension}"
    return name


canonical_filename = canonical_basename


def incident_id_for(filename: str) -> str:
    """Incident id from a dataset filename: everything before the first ``_`` (``Assault018_x264.mp4`` -> ``Assault018``)."""
    return PurePosixPath(filename).name.split("_", 1)[0]


def select_dataset_objects(objects: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split an R2 listing (``Key``/``Size``/``ETag``/``LastModified`` dicts) into dataset clips and skipped objects.

    A dataset clip is ``anomaly/<folder>/<file>.mp4`` with a non-zero size, outside the
    excluded folders. Everything else under the prefix is returned as skipped, with a reason.
    """
    selected, skipped = [], []
    for obj in objects:
        key = obj["Key"]
        if not key.startswith(DATASET_PREFIX):
            continue
        parts = key[len(DATASET_PREFIX):].split("/")
        if len(parts) != 2 or not parts[0]:
            reason = "folder marker" if key.endswith("/") else "not in a dataset folder"
        elif parts[0] in EXCLUDED_FOLDERS:
            reason = f"excluded folder {parts[0]}/"
        elif not parts[1]:
            reason = "folder marker"
        elif not parts[1].lower().endswith(VIDEO_EXTENSIONS):
            reason = "not an .mp4 file"
        elif int(obj.get("Size") or 0) == 0:
            reason = "zero-byte object"
        else:
            selected.append(obj)
            continue
        skipped.append({"key": key, "size_bytes": int(obj.get("Size") or 0), "reason": reason})
    return sorted(selected, key=lambda o: o["Key"]), sorted(skipped, key=lambda s: s["key"])


def local_path_for(videos_dir: Path, key: str) -> Path:
    """``videos_dir/<folder>/<original basename>`` - the R2 filename is kept exactly."""
    folder, basename = key[len(DATASET_PREFIX):].split("/")
    return videos_dir / folder / basename


def plain_etag_md5(etag: str | None) -> str | None:
    """The MD5 an ETag carries, or ``None`` for a multipart or missing ETag."""
    value = (etag or "").strip('"').lower()
    return value if _PLAIN_MD5_ETAG.match(value) else None


def _multipart_parts(etag: str | None) -> tuple[str, int] | None:
    value = (etag or "").strip('"').lower()
    match = re.match(r"^([0-9a-f]{32})-(\d+)$", value)
    return (match.group(1), int(match.group(2))) if match else None


def multipart_etag_matches(path: Path, etag: str | None) -> bool | None:
    """Whether a multipart ETag is reproduced from the local file; ``None`` if the ETag is not multipart.

    S3-style multipart ETags are ``md5(md5(part1) + ... + md5(partN))-N``. The part size is not
    recorded, so every whole-MiB size giving exactly N parts is tried.
    """
    parsed = _multipart_parts(etag)
    if parsed is None:
        return None
    expected, parts = parsed
    size = path.stat().st_size
    mib = 1024 * 1024
    smallest = max(1, -(-size // parts) // mib)
    for part_mib in range(smallest, smallest + 64):
        part_size = part_mib * mib
        if -(-size // part_size) != parts:
            if -(-size // part_size) < parts:
                break
            continue
        digests = []
        with path.open("rb") as handle:
            for chunk in iter(lambda h=handle, n=part_size: h.read(n), b""):
                digests.append(hashlib.md5(chunk).digest())  # noqa: S324 - reproduces R2's ETag
        if hashlib.md5(b"".join(digests)).hexdigest() == expected:  # noqa: S324
            return True
    return False


def file_digests(path: Path) -> tuple[str, str]:
    """``(md5, sha256)`` hex digests of a local file, streamed."""
    md5, sha256 = hashlib.md5(), hashlib.sha256()  # noqa: S324 - MD5 only to compare with R2's ETag
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            md5.update(chunk)
            sha256.update(chunk)
    return md5.hexdigest(), sha256.hexdigest()


def local_duration_seconds(path: Path) -> float | None:
    """MP4 ``mvhd`` duration of a local file, or ``None`` when the header cannot be read."""
    size = path.stat().st_size
    with path.open("rb") as handle:
        def read_range(offset: int, length: int) -> bytes:
            handle.seek(offset)
            return handle.read(length)

        return mp4_duration_seconds(read_range, size)


def verify_local_copy(path: Path, obj: dict) -> dict:
    """Check one downloaded file against its R2 listing entry; returns the manifest fields and any problems."""
    problems = []
    size = path.stat().st_size if path.exists() else None
    if size is None:
        return {"problems": ["missing local file"]}
    if size != int(obj["Size"]):
        problems.append(f"size {size} != R2 size {obj['Size']}")
    md5, sha256 = file_digests(path)
    expected_md5 = plain_etag_md5(obj.get("ETag"))
    if expected_md5 is not None and md5 != expected_md5:
        problems.append("MD5 does not match the R2 ETag")
    multipart = multipart_etag_matches(path, obj.get("ETag")) if expected_md5 is None else None
    if multipart is False:
        problems.append("multipart ETag not reproduced from the local file")
    duration = local_duration_seconds(path)
    return {
        "size_bytes": size,
        "md5": md5,
        "sha256": sha256,
        "etag_md5_checked": expected_md5 is not None or bool(multipart),
        "etag_kind": "single-part" if expected_md5 is not None else ("multipart" if multipart is not None else "unknown"),
        "duration_seconds": round(duration, 3) if duration is not None else None,
        "problems": problems,
    }


def manifest_entry(obj: dict, verified: dict, *, videos_dir: Path, relative_to: Path) -> dict:
    key = obj["Key"]
    folder, basename = key[len(DATASET_PREFIX):].split("/")
    filename = canonical_filename(basename)
    last_modified = obj.get("LastModified")
    return {
        "incident_id": incident_id_for(filename),
        "filename": filename,
        "r2_key": key,
        "r2_folder": folder,
        "demo": folder == "demo",
        "r2_size_bytes": int(obj["Size"]),
        "r2_etag": (obj.get("ETag") or "").strip('"'),
        "r2_last_modified": last_modified.isoformat() if hasattr(last_modified, "isoformat") else last_modified,
        "local_path": str(local_path_for(videos_dir, key).relative_to(relative_to)),
        **{k: verified.get(k) for k in ("size_bytes", "md5", "sha256", "etag_kind", "etag_md5_checked", "duration_seconds")},
        "problems": verified.get("problems", []),
    }


def integrity_findings(entries: list[dict], split_filenames: dict[str, str] | None = None) -> dict:
    """Dataset-level findings: failed clips, duplicate content, unreadable durations, split coverage.

    ``split_filenames`` maps each split-manifest filename to its split (``dev``/``test`` or
    ``few_shot``/``evaluation``), so every split video must be exactly one clip and every clip
    a split video.
    """
    by_sha: dict[str, list[str]] = {}
    by_incident: dict[str, list[str]] = {}
    for entry in entries:
        if entry.get("sha256"):
            by_sha.setdefault(entry["sha256"], []).append(entry["r2_key"])
        by_incident.setdefault(entry["incident_id"], []).append(entry["r2_key"])
    findings = {
        "clips_with_problems": {e["r2_key"]: e["problems"] for e in entries if e["problems"]},
        "duplicate_content": [keys for keys in by_sha.values() if len(keys) > 1],
        "duplicate_incident_ids": {i: keys for i, keys in by_incident.items() if len(keys) > 1},
        "unreadable_duration": [e["r2_key"] for e in entries if e.get("sha256") and e.get("duration_seconds") is None],
    }
    if split_filenames is not None:
        clip_filenames = {e["filename"] for e in entries}
        findings["split_videos_missing_from_dataset"] = sorted(set(split_filenames) - clip_filenames)
        findings["dataset_clips_not_in_any_split"] = sorted(clip_filenames - set(split_filenames))
    return findings


def findings_ok(findings: dict) -> bool:
    return not any(findings.values())


def build_manifest(entries: list[dict], skipped: list[dict], findings: dict, *, bucket: str, generated_at: str) -> dict:
    sizes = [e["r2_size_bytes"] for e in entries]
    durations = [e["duration_seconds"] for e in entries if e.get("duration_seconds") is not None]
    by_folder: dict[str, int] = {}
    for entry in entries:
        by_folder[entry["r2_folder"]] = by_folder.get(entry["r2_folder"], 0) + 1
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "generated_at": generated_at,
        "source": {"bucket": bucket, "prefix": DATASET_PREFIX, "excluded_folders": sorted(EXCLUDED_FOLDERS)},
        "summary": {
            "clips": len(entries),
            "total_bytes": sum(sizes),
            "clips_by_r2_folder": dict(sorted(by_folder.items())),
            "duration_seconds": {
                "readable": len(durations),
                "total": round(sum(durations), 3),
                "min": min(durations) if durations else None,
                "max": max(durations) if durations else None,
            },
        },
        "integrity": {"ok": findings_ok(findings), **findings},
        "skipped_objects": skipped,
        "clips": sorted(entries, key=lambda e: e["filename"]),
    }
    manifest["clips_sha256"] = hashlib.sha256(
        "\n".join(f"{e['filename']} {e['sha256']}" for e in manifest["clips"]).encode()
    ).hexdigest()
    return manifest
