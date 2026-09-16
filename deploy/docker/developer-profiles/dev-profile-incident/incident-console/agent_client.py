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

"""HTTP client for vss-agent's upload + AI-trigger API.

Written against the plan's contract (incident-plan-implementation-shared.md
S4-S5). The local ``base_profile_mock`` implements
``POST /api/v1/incidents/{id}/analyze`` for the zero-GPU loop, while the real
``vss-agent`` analyze route and ``POST /api/v1/search`` are still follow-up
work. Every call fails soft: it returns a ``Result`` with ``ok=False`` and a
human-readable ``error`` rather than raising, so the console stays usable when
the agent is absent or a route is missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

import config
from incident_report import (
    IncidentReport,
    extract_message_content,
    parse_incident_report,
)


@dataclass
class Result:
    ok: bool
    data: Any = None
    error: str = ""
    status_code: int | None = None
    # True when the failure is "endpoint not implemented yet" (expected today).
    not_implemented: bool = field(default=False)


class AgentClient:
    def __init__(
        self,
        base_url: str | None = None,
        llm_base_url: str | None = None,
        timeout: float | None = None,
    ):
        # ``None`` means "read from config"; an explicit "" stays empty.
        self.base_url = (config.agent_base_url() if base_url is None else base_url).rstrip("/")
        self.llm_base_url = (config.llm_base_url() if llm_base_url is None else llm_base_url).rstrip("/")
        self.timeout = timeout or config.http_timeout_seconds()

    # -- helpers ------------------------------------------------------- #
    def _post(self, url: str, *, json: dict | None = None, **kwargs: Any) -> Result:
        kwargs.setdefault("timeout", self.timeout)
        try:
            resp = httpx.post(url, json=json, **kwargs)
        except httpx.HTTPError as exc:
            return Result(ok=False, error=f"{type(exc).__name__}: {exc}")
        return self._to_result(url, resp)

    def _get(self, url: str, **kwargs: Any) -> Result:
        try:
            resp = httpx.get(url, timeout=self.timeout, **kwargs)
        except httpx.HTTPError as exc:
            return Result(ok=False, error=f"{type(exc).__name__}: {exc}")
        return self._to_result(url, resp)

    @staticmethod
    def _to_result(url: str, resp: httpx.Response) -> Result:
        if resp.status_code in (404, 405, 501):
            return Result(
                ok=False,
                status_code=resp.status_code,
                not_implemented=True,
                error=(
                    f"{url} returned {resp.status_code} - this endpoint is not "
                    "implemented on the agent yet (follow-up task)."
                ),
            )
        if resp.status_code >= 400:
            return Result(ok=False, status_code=resp.status_code, error=f"HTTP {resp.status_code}: {resp.text[:400]}")
        try:
            return Result(ok=True, data=resp.json(), status_code=resp.status_code)
        except ValueError:
            return Result(ok=True, data=resp.text, status_code=resp.status_code)

    # -- upload (contract exists today) ----------------------------- #
    def request_upload_url(self, filename: str) -> Result:
        """Step 1: ``POST /api/v1/videos {filename}`` -> ``{url}``."""
        return self._post(f"{self.base_url}/api/v1/videos", json={"filename": filename})

    def complete_upload(self, sensor_id: str) -> Result:
        """Step 3: ``POST /api/v1/videos/{sensor_id}/complete``."""
        return self._post(f"{self.base_url}/api/v1/videos/{sensor_id}/complete", json={})

    def upload_video(self, *, filename: str, content: bytes) -> Result:
        """Run the three-step upload contract. Fails soft at every step.

        On success ``data`` is ``{"sensor_id": str, "filepath": str | None,
        "complete": <complete resp>}``. ``filepath`` comes from the chunked
        PUT's ``filePath`` field (part of the real nvstreamer protocol - see
        ``services/ui/packages/common/lib-src/utils/chunkedUpload.ts``'s
        ``filePath?: string``); neither this contract's step 1 nor step 3
        response carries a playable URL, so when the chunk response omits it
        we fall back to asking VST directly for one.
        """
        step1 = self.request_upload_url(filename)
        if not step1.ok:
            return step1
        upload_url = (step1.data or {}).get("url") if isinstance(step1.data, dict) else None
        if not upload_url:
            return Result(ok=False, error=f"agent did not return an upload url: {step1.data!r}")
        try:
            # Field name and the separate `filename` field mirror the real
            # nvstreamer protocol (services/ui/.../chunkedUpload.ts's
            # `formData.append('mediaFile', chunk, fileName)` +
            # `formData.append('filename', fileName)`); this is a single-shot
            # upload (no `nvstreamer-*` chunk headers), which both the real
            # VST endpoint and the mock accept as a one-chunk upload.
            put = httpx.post(
                upload_url,
                files={"mediaFile": (filename, content, "video/mp4")},
                data={"filename": filename},
                timeout=max(self.timeout, 120.0),
            )
            put.raise_for_status()
            body = put.json() if put.headers.get("content-type", "").startswith("application/json") else {}
        except httpx.HTTPError as exc:
            return Result(ok=False, error=f"chunked upload to nvstreamer failed: {exc}")
        except ValueError:
            body = {}
        sensor_id = body.get("sensorId") or body.get("sensor_id")
        if not sensor_id:
            return Result(ok=False, error=f"nvstreamer did not return a sensorId: {body!r}")
        filepath = body.get("filePath") or body.get("filepath")
        # The mock returns an internal filesystem path in filePath. Resolve
        # those through VST so the console receives a browser-playable URL;
        # real absolute URLs and object keys remain untouched.
        if not filepath or (isinstance(filepath, str) and filepath.startswith("/")):
            filepath = self._video_url(sensor_id)
        step3 = self.complete_upload(sensor_id)
        return Result(
            ok=step3.ok,
            data={"sensor_id": sensor_id, "filepath": filepath, "complete": step3.data},
            error=step3.error,
            status_code=step3.status_code,
        )

    def _video_url(self, sensor_id: str) -> str | None:
        """Best-effort fallback: ask VST for a playback URL for this sensor.

        Assumes VST is reachable under the same host as ``base_url`` at
        ``/vst/api`` - true of the local mock (single process) and, per
        ``video_ingest.py``'s haproxy-ingress comment, of the real deployment
        when the console and browser share the same ingress. Not guaranteed
        in general, so failures here are swallowed (``None``) rather than
        failing the whole upload.
        """
        result = self._get(f"{self.base_url}/vst/api/v1/storage/file/{sensor_id}/url")
        if result.ok and isinstance(result.data, dict):
            return result.data.get("videoUrl")
        return None

    # -- AI triggers (real vss-agent routes are follow-up work) ---- #
    def analyze_incident(self, video_id: int, *, reasoning: bool = False) -> Result:
        """``POST /api/v1/incidents/{id}/analyze`` - fails soft if not implemented."""
        # Same floor as upload_video's chunked PUT: the default 15s timeout is
        # too short for a synchronous R2 upload + real VLM inference.
        return self._post(
            f"{self.base_url}/api/v1/incidents/{video_id}/analyze",
            json={"reasoning": reasoning},
            timeout=max(self.timeout, 120.0),
        )

    def search(self, query: str, *, top_k: int = 10) -> Result:
        """``POST /api/v1/search`` - fails soft if not implemented (MVP2)."""
        return self._post(f"{self.base_url}/api/v1/search", json={"query": query, "top_k": top_k})

    # -- direct LLM path (mock server / real NIM) ---------------- #
    def draft_report_via_llm(self, *, prompt: str, model: str = "incident-llm") -> Result:
        """Call an OpenAI-compatible ``/v1/chat/completions`` directly.

        Used for local iteration against ``mock_llm_server.py`` when the agent's
        ``/analyze`` route is not yet available. ``data`` is an
        :class:`IncidentReport` on success.
        """
        if not self.llm_base_url:
            return Result(ok=False, error="INCIDENT_LLM_BASE_URL is not set")
        result = self._post(
            f"{self.llm_base_url}/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "Extract a structured incident report."},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        if not result.ok:
            return result
        report: IncidentReport = parse_incident_report(extract_message_content(result.data or {}))
        return Result(ok=True, data=report, status_code=result.status_code)
