"""VST storage surface: chunked upload ingestion + timeline/size/url lookups.

All upload entrypoints (multipart POST used by the UI's chunked uploader,
and the legacy PUT-per-chunk variants) converge on one internal chunk
handler reading the nvstreamer-* headers, per
services/ui/packages/common/lib-src/utils/chunkedUpload.ts.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import os
from pathlib import PurePosixPath
from typing import Any
import uuid

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.responses import Response

from base_profile_mock.state import AppState
from base_profile_mock.state import Stream
from base_profile_mock.state import UploadInProgress
from base_profile_mock.state import get_state

router = APIRouter(prefix="/vst/api/v1")

_CATEGORIES = (
    ("road_accidents", "road accident"),
    ("fighting", "fighting"),
    ("animal_attacks", "animal"),
    ("burglary", "burglary"),
    ("explosion", "explosion"),
)


def _r2_upload(stream: Stream, sensor_id: str) -> str:
    """Upload a completed mock stream and return its durable R2 object key."""
    import boto3
    from botocore.config import Config

    required = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY", "R2_SECRET_KEY", "R2_BUCKET")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"R2 storage is not configured; missing {', '.join(missing)}")
    incident_id = "v" + hashlib.sha256(sensor_id.encode("utf-8")).hexdigest()[:19]
    folder, _ = _CATEGORIES[hashlib.sha256(incident_id.encode("utf-8")).digest()[0] % len(_CATEGORIES)]
    filename = PurePosixPath(stream.filename or f"{incident_id}.mp4").name
    key = f"anomaly/{folder}/{filename}"
    client = boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY"],
        aws_secret_access_key=os.environ["R2_SECRET_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4", connect_timeout=10, read_timeout=30, retries={"max_attempts": 2}),
    )
    client.put_object(Bucket=os.environ["R2_BUCKET"], Key=key, Body=stream.content, ContentType="video/mp4")
    return key


async def _process_chunk(
    state: AppState,
    headers: Any,
    body_bytes: bytes,
    filename_hint: str | None = None,
) -> dict[str, Any]:
    identifier = headers.get("nvstreamer-identifier")
    file_name = headers.get("nvstreamer-file-name") or filename_hint or "upload.bin"
    total_chunks = int(headers.get("nvstreamer-total-chunks") or 1)
    is_last = (headers.get("nvstreamer-is-last-chunk") or "true").lower() == "true"

    if identifier is None:
        # No chunk headers at all: treat as a single-shot, one-chunk upload.
        identifier = str(uuid.uuid4())
        total_chunks = 1
        is_last = True

    now = _dt.datetime.now(tz=_dt.UTC).isoformat()

    async with state.lock:
        upload = state.uploads.get(identifier)
        if upload is None:
            sensor_id = state.derive_sensor_id(identifier)
            upload = UploadInProgress(
                identifier=identifier,
                filename=file_name,
                total_chunks=total_chunks,
                sensor_id=sensor_id,
            )
            state.uploads[identifier] = upload

        upload.chunks_received += 1
        upload.bytes_received += len(body_bytes)
        if file_name:
            upload.filename = file_name
        sensor_id = upload.sensor_id

        if is_last:
            stream = Stream(
                stream_id=sensor_id,
                name=upload.filename,
                filename=upload.filename,
                bytes_total=upload.bytes_received,
                content=body_bytes,
            )
            state.streams[sensor_id] = stream
            # R2 is the durable video store. Keep the in-memory copy for the
            # mock VST endpoints, but return the R2 key to the console so it
            # can commit filepath before automatic analysis starts.
            try:
                file_path = await asyncio.to_thread(_r2_upload, stream, sensor_id)
            except Exception as exc:
                raise HTTPException(status_code=503, detail=f"R2 upload failed: {exc}") from exc
        else:
            file_path = f"/data/videos/{upload.filename}"

        return {
            "id": sensor_id,
            "filename": upload.filename,
            "bytes": upload.bytes_received,
            "streamId": sensor_id,
            "sensorId": sensor_id,
            "filePath": file_path,
            "timestamp": now,
            "created_at": now,
        }


@router.post("/storage/file")
async def upload_file_multipart(
    request: Request,
    state: AppState = Depends(get_state),
) -> JSONResponse:
    form = await request.form()
    media_file = form.get("mediaFile")
    filename_hint = form.get("filename")
    body_bytes = b""
    # Starlette may return its base UploadFile class even though the route
    # imports FastAPI's compatibility subclass, so use the upload protocol.
    if media_file is not None and hasattr(media_file, "read"):
        body_bytes = await media_file.read()
        filename_hint = filename_hint or media_file.filename

    result = await _process_chunk(state, request.headers, body_bytes, str(filename_hint) if filename_hint else None)
    return JSONResponse(result)


@router.put("/storage/file/{filename}")
async def upload_file_put(
    filename: str,
    request: Request,
    state: AppState = Depends(get_state),
) -> JSONResponse:
    body_bytes = await request.body()
    result = await _process_chunk(state, request.headers, body_bytes, filename)
    return JSONResponse(result)


@router.put("/storage/file/{filename}/{timestamp}")
async def upload_file_put_legacy(
    filename: str,
    timestamp: str,
    request: Request,
    state: AppState = Depends(get_state),
) -> JSONResponse:
    body_bytes = await request.body()
    result = await _process_chunk(state, request.headers, body_bytes, filename)
    result["timestamp"] = timestamp
    return JSONResponse(result)


@router.get("/storage/timelines")
async def get_all_timelines(state: AppState = Depends(get_state)) -> dict[str, Any]:
    async with state.lock:
        return {
            stream_id: [{"startTime": stream.created_at, "endTime": stream.created_at + 1}]
            for stream_id, stream in state.streams.items()
        }


@router.get("/storage/{stream_id}/timelines")
async def get_stream_timelines(stream_id: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    async with state.lock:
        stream = state.streams.get(stream_id)
    if stream is None:
        return {stream_id: []}
    return {stream_id: [{"startTime": stream.created_at, "endTime": stream.created_at + 1}]}


@router.get("/storage/file/{filename}")
async def get_uploaded_file(filename: str, state: AppState = Depends(get_state)) -> Response:
    """Serve the bytes captured by the mock upload for browser playback."""
    async with state.lock:
        stream = next((item for item in state.streams.values() if item.filename == filename), None)
    if stream is None:
        return Response(status_code=404, content=b"video not found")
    return Response(content=stream.content, media_type="video/mp4", headers={"Accept-Ranges": "bytes"})


@router.get("/storage/file/{sensor_id}/url")
async def get_file_url(sensor_id: str, request: Request, state: AppState = Depends(get_state)) -> dict[str, Any]:
    async with state.lock:
        stream = state.streams.get(sensor_id)
    base = str(request.base_url).rstrip("/")
    filename = stream.filename if stream else f"{sensor_id}.mp4"
    return {"videoUrl": f"{base}/vst/api/v1/storage/file/{filename}"}


@router.get("/storage/size")
async def get_storage_size(timelines: bool = False, state: AppState = Depends(get_state)) -> dict[str, Any]:
    async with state.lock:
        total_bytes = sum(s.bytes_total for s in state.streams.values())
        result: dict[str, Any] = {"totalBytes": total_bytes, "totalSize": total_bytes}
        if timelines:
            result["timelines"] = {
                stream_id: [{"startTime": stream.created_at, "endTime": stream.created_at + 1}]
                for stream_id, stream in state.streams.items()
            }
    return result
