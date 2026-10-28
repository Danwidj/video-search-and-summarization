# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Give every existing R2 object a readable name, by copy. Nothing is ever deleted.

    cd supabase/r2 && uv run --no-project --with boto3 python migrate_r2_names.py \
        --env-file ../../.env.local [--sensors-file sensors.json] [--manifest manifest.json] [--apply]

Dry run by default: it lists the bucket, reads the database and prints the plan (old key to new key),
the objects it cannot place, and the names it had to derive. With --apply it, in this order:

1. copies each object to its new key (never over an existing different object) and verifies the copy
   (same size and, when both ETags are plain, the same ETag);
2. for each video whose objects all verified, calls public.apply_r2_rename (migration
   20261028090000_r2_rename.sql, applied first) to point videos.filepath, the evidence images of the
   video's revisions and evidence_crops.image at the new keys, in one transaction;
3. prints, and writes to --manifest, the old keys that are safe to delete. The script has no delete
   call: the old objects stay until a person removes them.

New keys (the layout the console and agent now write):

    uploads/<name>                            the video; <name> is the sensor name from the VST sensor list
                                              (--sensors-file), else upload-YYYYMMDD-HHMMSS.<ext>
    thumbnails/<video key>.webp               next to its video
    evidence/<video key>/run-<N>/<file>       AI crops, N in order of creation
    evidence/<video key>/edit-<N>/<file>      reviewer-uploaded images (old batch folder was a dashed UUID)

Safe to run again: a copy records its source in the object metadata (renamed-from), so a second run
reuses the same new keys, and the database update changes nothing when it is already done. Rows in
model_runs.notes keep the old key (that table is immutable); nothing reads a video from it.

Credentials come from --env-file (R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY, R2_BUCKET,
INCIDENT_SUPABASE_URL, INCIDENT_SUPABASE_SERVICE_ROLE_KEY) and are never printed. Reads the database
through PostgREST, so it runs from the laptop or the VM.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_NAME_LENGTH = 150  # keep in step with incident-console-v2/src/lib/r2/names.ts
FIXTURE_ROOTS = {"anomaly", "normal_videos"}
READABLE_ROOTS = {"uploads", *FIXTURE_ROOTS}
UUID_BATCH = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
RENAMED_FROM = "renamed-from"


# --- Names ----------------------------------------------------------------------------------------
def split_extension(name: str) -> tuple[str, str]:
    match = re.fullmatch(r"(.+?)(\.[A-Za-z0-9]{1,10})", name)
    return (match.group(1), match.group(2)) if match else (name, "")


def fit(stem: str, ext: str, suffix: str = "") -> str:
    return f"{stem[: max(1, MAX_NAME_LENGTH - len(ext) - len(suffix))]}{suffix}{ext}"


def readable_name(original: str) -> str:
    """The console's rule (names.ts inspectUploadName): keep the name, unsafe characters become '_'."""
    name = re.split(r"[\\/]", original)[-1].strip()
    name = re.sub(r"[^\w.()+,-]", "_", name)
    name = re.sub(r"\.{2,}", ".", name)
    if name.startswith("."):
        name = "_" + name[1:]
    name = name or "video"
    stem, ext = split_extension(name)
    return fit(stem, ext) if len(name) > MAX_NAME_LENGTH else name


def with_counter(name: str, counter: int) -> str:
    if counter <= 1:
        return name
    stem, ext = split_extension(name)
    return fit(stem, ext, f"-{counter}")


def first_free(name: str, taken: set[str], prefix: str = "uploads/") -> str:
    for counter in range(1, 1000):
        candidate = with_counter(name, counter)
        if prefix + candidate not in taken:
            return prefix + candidate
    raise SystemExit(f"Too many objects named like {name}")


# --- Plan -----------------------------------------------------------------------------------------
@dataclass
class Move:
    kind: str  # upload | thumbnail | evidence
    old: str
    new: str
    size: int
    video_id: str | None
    note: str = ""
    state: str = "planned"  # planned | copied | verified | failed | already


@dataclass
class Plan:
    moves: list[Move] = field(default_factory=list)
    orphans: list[str] = field(
        default_factory=list
    )  # legacy objects no video owns: left alone
    warnings: list[str] = field(default_factory=list)


def is_legacy_upload(key: str) -> bool:
    return key.startswith("uploads/") and "/" in key[len("uploads/") :]


def is_legacy_evidence(key: str) -> bool:
    parts = key.split("/")
    return parts[0] == "evidence" and len(parts) >= 4 and parts[1] not in READABLE_ROOTS


def sensor_names(sensors: list[dict[str, Any]]) -> dict[str, str]:
    return {
        s["sensorId"]: s["name"] for s in sensors if s.get("sensorId") and s.get("name")
    }


def stamp(value: str) -> str:
    return re.sub(r"[^0-9]", "", value.replace("T", " ")[:19]).ljust(14, "0")[:14]


def derived_upload_name(when: str, ext: str) -> str:
    digits = stamp(when)
    return f"upload-{digits[:8]}-{digits[8:14]}{ext}"


def upload_name(
    old: str, video: dict[str, Any] | None, last_modified: str, names: dict[str, str]
) -> tuple[str, str]:
    """The name for a legacy upload and where it came from."""
    _stem, ext = split_extension(old.rsplit("/", 1)[-1])
    sensor = old.split("/")[1]
    candidates = [sensor] + ([video["source"]] if video and video.get("source") else [])
    for candidate in candidates:
        if candidate in names:
            name = names[candidate]
            return readable_name(
                name if name.lower().endswith(ext.lower()) else name + ext
            ), "sensor name"
    when = (video or {}).get("uploaded_datetime") or last_modified
    return derived_upload_name(when, ext), "derived from the upload time"


def segment_video(segment: str, videos: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_id = [v for v in videos if v["id"] == segment]
    if by_id:
        return by_id[0]
    clip = [
        v
        for v in videos
        if (name := (v.get("filepath") or "").rsplit("/", 1)[-1]).startswith(
            segment + "_"
        )
        or split_extension(name)[0] == segment
    ]
    return clip[0] if len(clip) == 1 else None


def build_plan(
    objects: dict[str, dict[str, Any]],
    videos: list[dict[str, Any]],
    references: dict[str, str],
    names: dict[str, str],
    done: dict[str, str],
) -> Plan:
    """objects: key -> {size, modified}. references: evidence key -> video id (from the database).
    done: old key -> new key for copies a previous run already made."""
    plan = Plan()
    taken = set(objects) | set(done.values())
    by_id = {v["id"]: v for v in videos}
    new_video_key: dict[
        str, str
    ] = {}  # video id -> the key its video has (or will have)

    # Videos: every legacy upload object, referenced or not.
    legacy = sorted(
        (k for k in objects if is_legacy_upload(k)),
        key=lambda k: (objects[k]["modified"], k),
    )
    owner = {v["filepath"]: v for v in videos if v.get("filepath")}
    for old in legacy:
        video = owner.get(old) or owner.get(done.get(old, ""))
        if old in done:
            new, note = done[old], "already copied"
        else:
            name, source = upload_name(old, video, objects[old]["modified"], names)
            new, note = first_free(name, taken), source
            taken.add(new)
        if not video:
            note += "; no videos row"
        plan.moves.append(
            Move(
                "upload",
                old,
                new,
                objects[old]["size"],
                video["id"] if video else None,
                note,
            )
        )
        if video:
            new_video_key[video["id"]] = new
    for video in videos:  # a video whose filepath is already readable keeps it
        if video["id"] not in new_video_key and video.get("filepath"):
            new_video_key[video["id"]] = video["filepath"]
    old_to_new_video = {m.old: m.new for m in plan.moves if m.kind == "upload"}

    # Thumbnails: next to the renamed video.
    video_of = {m.old: m.video_id for m in plan.moves if m.kind == "upload"}
    for old_key, new_key in old_to_new_video.items():
        thumb = f"thumbnails/{old_key}.webp"
        if thumb in objects:
            new = done.get(thumb) or f"thumbnails/{new_key}.webp"
            if (
                new in objects
                and thumb not in done
                and objects[new]["size"] != objects[thumb]["size"]
            ):
                plan.warnings.append(
                    f"{new} already exists with another size; {thumb} left alone"
                )
                continue
            plan.moves.append(
                Move("thumbnail", thumb, new, objects[thumb]["size"], video_of[old_key])
            )
    known = {m.old for m in plan.moves}
    plan.orphans += sorted(
        k
        for k in objects
        if k.startswith("thumbnails/uploads/")
        and k not in known
        and k.endswith(".webp")
    )

    # Evidence: group the legacy objects of a video by their old batch folder.
    batches: dict[tuple[str, str], list[str]] = {}
    for key in sorted(k for k in objects if is_legacy_evidence(k)):
        segment, batch = key.split("/")[1:3]
        video = by_id.get(references.get(key, "")) or segment_video(segment, videos)
        if video is None or video["id"] not in new_video_key:
            plan.orphans.append(key)
            continue
        batches.setdefault((video["id"], batch), []).append(key)
    folders: dict[
        str, dict[str, int]
    ] = {}  # video id -> {"run": highest N, "edit": highest N}
    for video_id, vkey in new_video_key.items():
        for key in objects:
            match = re.fullmatch(
                re.escape(f"evidence/{vkey}/") + r"(run|edit)-(\d+)/.+", key
            )
            if match:
                top = folders.setdefault(video_id, {})
                top[match.group(1)] = max(
                    top.get(match.group(1), 0), int(match.group(2))
                )
    order = sorted(
        batches.items(),
        key=lambda kv: (min(objects[k]["modified"] for k in kv[1]), kv[0]),
    )
    for (video_id, batch), keys in order:
        vkey = new_video_key[video_id]
        folder = next((done[k].rsplit("/", 1)[0] for k in keys if k in done), None)
        if folder is None:
            kind = "edit" if UUID_BATCH.match(batch) else "run"
            top = folders.setdefault(video_id, {})
            top[kind] = top.get(kind, 0) + 1
            folder = f"evidence/{vkey}/{kind}-{top[kind]}"
        for key in keys:
            new = done.get(key) or f"{folder}/{key.rsplit('/', 1)[-1]}"
            plan.moves.append(
                Move("evidence", key, new, objects[key]["size"], video_id)
            )
    plan.warnings += [
        f"{key} is referenced by the database but not in the bucket"
        for key in sorted(references)
        if key not in objects
    ]
    clashes = [
        k
        for k in {m.new for m in plan.moves}
        if sum(m.new == k for m in plan.moves) > 1
    ]
    if clashes:
        raise SystemExit(
            f"Two objects would get the same new key: {sorted(clashes)[:3]}"
        )
    return plan


# --- R2 -------------------------------------------------------------------------------------------
def not_found(error: Exception) -> bool:
    response = getattr(error, "response", {}) or {}
    return str(response.get("Error", {}).get("Code")) in {
        "404",
        "NoSuchKey",
        "NotFound",
    }


def list_bucket(client: Any, bucket: str) -> dict[str, dict[str, Any]]:
    objects: dict[str, dict[str, Any]] = {}
    token = None
    while True:
        page = client.list_objects_v2(
            Bucket=bucket, **({"ContinuationToken": token} if token else {})
        )
        for item in page.get("Contents", []):
            if not item["Key"].endswith("/"):
                objects[item["Key"]] = {
                    "size": item["Size"],
                    "modified": item["LastModified"].isoformat(),
                }
        if not page.get("IsTruncated"):
            return objects
        token = page["NextContinuationToken"]


def head(client: Any, bucket: str, key: str) -> dict[str, Any] | None:
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except Exception as error:
        if not_found(error):
            return None
        raise


def renamed_from(
    client: Any, bucket: str, objects: dict[str, dict[str, Any]]
) -> dict[str, str]:
    """old key -> new key for every readable object a previous run copied (read from its metadata)."""
    done: dict[str, str] = {}
    for key in objects:
        if key.startswith(("uploads/", "thumbnails/", "evidence/")):
            meta = (head(client, bucket, key) or {}).get("Metadata", {})
            if meta.get(RENAMED_FROM):
                done[meta[RENAMED_FROM]] = key
    return done


def copy_and_verify(client: Any, bucket: str, move: Move) -> None:
    source = head(client, bucket, move.old)
    if source is None:
        move.state, move.note = "failed", "source object is gone"
        return
    target = head(client, bucket, move.new)
    if target is None:
        client.copy_object(
            Bucket=bucket,
            Key=move.new,
            CopySource={"Bucket": bucket, "Key": move.old},
            MetadataDirective="REPLACE",
            Metadata={RENAMED_FROM: move.old},
            ContentType=source.get("ContentType") or "application/octet-stream",
        )
        target = head(client, bucket, move.new)
    elif (target.get("Metadata") or {}).get(RENAMED_FROM) != move.old:
        move.state, move.note = (
            "failed",
            "a different object already has the new key (never overwritten)",
        )
        return
    if target is None or target["ContentLength"] != source["ContentLength"]:
        move.state, move.note = "failed", "size differs after the copy"
        return
    plain = "-" not in source["ETag"] and "-" not in target["ETag"]
    if plain and source["ETag"] != target["ETag"]:
        move.state, move.note = "failed", "ETag differs after the copy"
        return
    move.state = "verified"


# --- Database (PostgREST) -------------------------------------------------------------------------
class Rest:
    def __init__(self, url: str, key: str) -> None:
        self.base = url.rstrip("/") + "/rest/v1/"
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def call(self, path: str, body: Any = None) -> Any:
        request = urllib.request.Request(
            self.base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=self.headers,
            method="GET" if body is None else "POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read() or "null")
        except urllib.error.HTTPError as error:
            raise RuntimeError(
                f"{path.split('?')[0]} failed: HTTP {error.code} {error.read().decode()[:300]}"
            ) from None

    def table(self, name: str, select: str, order: str = "id") -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        while True:
            page = self.call(
                f"{name}?select={select}&order={order}&limit=1000&offset={len(rows)}"
            )
            rows += page
            if len(page) < 1000:
                return rows


def read_database(
    db: Any,
) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    videos = db.table("videos", "id,filepath,source,uploaded_datetime")
    revisions = db.table("report_revisions", "id,video_id,evidence,payload")
    crops = db.table(
        "evidence_crops", "revision_id,image", "revision_id,item_type,item_id"
    )
    owner = {r["id"]: r["video_id"] for r in revisions}
    references: dict[str, str] = {}
    for revision in revisions:
        for item in revision["evidence"] or []:
            if isinstance(item, dict) and item.get("image"):
                references[item["image"]] = revision["video_id"]
    for crop in crops:
        references.setdefault(crop["image"], owner[crop["revision_id"]])
    return videos, references, revisions


def payload_key_warnings(
    revisions: list[dict[str, Any]], moves: list[Move]
) -> list[str]:
    old = [m.old for m in moves]
    return [
        f"report_revisions {r['id']}: payload mentions {key}"
        for r in revisions
        for key in old
        if key in json.dumps(r["payload"])
    ]


def apply_database(db: Any, plan: Plan) -> dict[str, dict[str, Any]]:
    """Point each fully verified video at its new keys. Returns video id -> RPC result."""
    results: dict[str, dict[str, Any]] = {}
    for video_id in sorted({m.video_id for m in plan.moves if m.video_id}):
        moves = [m for m in plan.moves if m.video_id == video_id]
        if any(m.state != "verified" for m in moves):
            plan.warnings.append(
                f"{video_id}: not all objects verified; database left as it is"
            )
            continue
        upload = next((m.new for m in moves if m.kind == "upload"), None)
        key_map = {m.old: m.new for m in moves if m.kind == "evidence"}
        results[video_id] = db.call(
            "rpc/apply_r2_rename",
            {"p_video_id": video_id, "p_filepath": upload, "p_key_map": key_map},
        )
    return results


# --- Output ---------------------------------------------------------------------------------------
def report(
    plan: Plan, applied: bool, results: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    # An old key is safe to delete once its copy is verified and, when a video row points at it,
    # that row has been moved to the new key.
    safe = [
        m.old
        for m in plan.moves
        if m.state == "verified" and (m.video_id is None or m.video_id in results)
    ]
    return {
        "mode": "apply" if applied else "dry-run",
        "moves": [m.__dict__ for m in plan.moves],
        "orphans": plan.orphans,
        "warnings": plan.warnings,
        "database": results,
        "safe_to_delete": sorted(safe),
    }


def print_report(plan: Plan, out: dict[str, Any]) -> None:
    print(f"{out['mode']}: {len(plan.moves)} objects to rename")
    for move in plan.moves:
        print(
            f"  [{move.kind}] {move.old}\n      -> {move.new}   ({move.state}; {move.note or 'ok'})"
        )
    for line in plan.warnings:
        print(f"WARNING {line}")
    if plan.orphans:
        print(f"\nNot renamed, no video row owns them ({len(plan.orphans)}):")
        for key in plan.orphans:
            print(f"  {key}")
    if out["mode"] == "apply":
        print(
            f"\nSafe to delete once you have checked the console ({len(out['safe_to_delete'])} old keys):"
        )
        for key in out["safe_to_delete"]:
            print(f"  {key}")
    else:
        print(
            "\nDry run: nothing was copied or written. Re-run with --apply to copy, verify and update the database."
        )


def read_env(path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in Path(path).read_text().splitlines():
        match = re.match(r"^\s*([A-Z0-9_]+)=(.*)$", line)
        if match:
            env[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    for name in os.environ:
        env.setdefault(name, os.environ[name])
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", required=True)
    parser.add_argument(
        "--sensors-file",
        help="JSON from the VST /vst/api/v1/sensor/list (names for old uploads)",
    )
    parser.add_argument("--manifest", help="write the result here as JSON")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="copy, verify and update the database (default: dry run)",
    )
    args = parser.parse_args(argv)
    env = read_env(args.env_file)
    missing = [
        k
        for k in (
            "R2_ACCOUNT_ID",
            "R2_ACCESS_KEY",
            "R2_SECRET_KEY",
            "R2_BUCKET",
            "INCIDENT_SUPABASE_URL",
            "INCIDENT_SUPABASE_SERVICE_ROLE_KEY",
        )
        if not env.get(k)
    ]
    if missing:
        raise SystemExit(f"Missing in {args.env_file}: {', '.join(missing)}")

    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=env["R2_ACCESS_KEY"],
        aws_secret_access_key=env["R2_SECRET_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )
    bucket = env["R2_BUCKET"]
    db = Rest(env["INCIDENT_SUPABASE_URL"], env["INCIDENT_SUPABASE_SERVICE_ROLE_KEY"])
    names = (
        sensor_names(json.loads(Path(args.sensors_file).read_text()))
        if args.sensors_file
        else {}
    )

    objects = list_bucket(client, bucket)
    videos, references, revisions = read_database(db)
    plan = build_plan(
        objects, videos, references, names, renamed_from(client, bucket, objects)
    )
    plan.warnings += payload_key_warnings(revisions, plan.moves)
    results: dict[str, dict[str, Any]] = {}
    if args.apply:
        try:
            db.call(
                "rpc/apply_r2_rename",
                {"p_video_id": "-", "p_filepath": None, "p_key_map": {}},
            )
        except RuntimeError as error:
            if "Video not found" not in str(error):
                raise SystemExit(
                    f"apply_r2_rename is not usable (apply migration 20261028090000 first): {error}"
                ) from None
        for move in plan.moves:
            copy_and_verify(client, bucket, move)
        results = apply_database(db, plan)
    out = report(plan, args.apply, results)
    print_report(plan, out)
    if args.manifest:
        Path(args.manifest).write_text(json.dumps(out, indent=2, default=str) + "\n")
    return 1 if any(m.state == "failed" for m in plan.moves) else 0


if __name__ == "__main__":
    sys.exit(main())
