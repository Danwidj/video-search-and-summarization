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

"""``POST /api/v1/incidents/link-evidence`` - stateless cross-video evidence linker.

Each camera's analysis numbers its own items (E1, I1, A1 ...), so the same person or object seen by two
cameras appears under two ids.  Given the per-camera reports of one report version, the endpoint asks one
text-only LLM call (temperature 0 from the shared RP1 settings) which items are the same real-world entity,
instrument or asset across *different* videos, and returns them as ``evidence_groups``:

``[{id: "G1", kind: "entity"|"instrument"|"asset", label, members: [{video, itemId}], source: "ai", reason?}]``

Rules enforced here, whatever the model says: a group has two or more members, all of one kind, at most one
per video; each ``(video, itemId)`` is in at most one group; members must exist in the request; ids are
renumbered ``G1, G2 ...``.  A group that breaks a rule is dropped.  Model failure or unusable output gives an
empty list (HTTP 200), because linking is an enhancement the caller never lets block a report build.

The endpoint is **stateless**: it writes nothing and never alters the per-video payloads or their ids.

Status codes:
- 422  body validation failed (empty ``videos`` list, payload not contract-valid).
- 503  RP1 endpoint or API key not configured on this agent.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from typing import Literal

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
import httpx
from pydantic import BaseModel
from pydantic import Field

from vss_agents import incident_contract
from vss_agents.api.incident_synthesize import VideoAnalysisInput  # noqa: TC001

logger = logging.getLogger(__name__)

Kind = Literal["entity", "instrument", "asset"]

# Contract list name -> (group kind, id field).
_KINDS: dict[str, tuple[Kind, str]] = {
    "entities": ("entity", "entity_id"),
    "instruments": ("instrument", "instrument_id"),
    "assets": ("asset", "asset_id"),
}

_MAX_LABEL_CHARS = 120
_MAX_REASON_CHARS = 300

_LINK_PROMPT_TEMPLATE = """\
You match items across security cameras. Several cameras recorded the same scene. Each camera numbered its own
items (E = person or animal, I = instrument held or used, A = asset or object), so the same real-world person or
object appears under different ids in different cameras.

Below is each camera's list of items, text only.

CAMERAS:
{cameras}

Group the items that are the SAME real-world person, instrument or asset seen by different cameras.
Rules:
- Link only when the descriptions clearly agree (clothing colour and type, build, object kind, colour, position, what it
  is doing). Do not link on role or location alone. When unsure, leave the items unlinked.
- A group holds items of one kind only (all E, all I or all A) and at most ONE item per camera.
- Never put two items of the same camera in one group, and never use an item in two groups.
- Names of small objects at low resolution can be wrong; weigh colour, size and position over the name.
- Use the ids exactly as given.

Return ONLY a JSON object, no markdown fences or extra text:
{{"groups": [{{"kind": "entity" | "instrument" | "asset", "label": "short neutral name for the shared item",
"members": [{{"video": "<camera name>", "itemId": "<id in that camera>"}}], "reason": "one short sentence"}}]}}
Use {{"groups": []}} when nothing is the same across cameras."""


class LinkEvidenceRequest(BaseModel):
    """Body for ``POST /api/v1/incidents/link-evidence``."""

    videos: list[VideoAnalysisInput] = Field(..., min_length=1, description="The per-camera reports of one version.")


class EvidenceGroupMember(BaseModel):
    video: str
    itemId: str  # noqa: N815 - the stored version payload spells it camelCase.


class EvidenceGroup(BaseModel):
    id: str
    kind: Kind
    label: str
    members: list[EvidenceGroupMember]
    source: Literal["ai"] = "ai"
    reason: str | None = None


class LinkEvidenceResponse(BaseModel):
    """Response for ``POST /api/v1/incidents/link-evidence``."""

    evidence_groups: list[EvidenceGroup] = Field(description="Cross-video groups; empty when none or on failure.")


def _text(value: Any, limit: int) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _items(video: VideoAnalysisInput) -> dict[str, dict[str, dict[str, Any]]]:
    """The camera's items by kind then id; later duplicates of an id are ignored."""
    found: dict[str, dict[str, dict[str, Any]]] = {kind: {} for kind, _ in _KINDS.values()}
    for list_name, (kind, id_field) in _KINDS.items():
        for item in video.payload.get(list_name) or []:
            item_id = item.get(id_field)
            if isinstance(item_id, str) and item_id not in found[kind]:
                found[kind][item_id] = item
    return found


def _camera_text(video: VideoAnalysisInput) -> str:
    lines = [f"Camera: {video.video_name}"]
    incident = video.payload.get("incident") or {}
    if incident.get("description"):
        lines.append(f"Scene: {_text(incident['description'], 400)}")
    for list_name, (_, id_field) in _KINDS.items():
        for item in video.payload.get(list_name) or []:
            parts = [f"{item.get(id_field)}"]
            for key in ("type", "name", "label"):
                if item.get(key):
                    parts.append(f"{key}={_text(item[key], 80)}")
            if item.get("entity_id") and list_name == "instruments":
                parts.append(f"held_by={item['entity_id']}")
            if item.get("first_seen_seconds") is not None:
                parts.append(f"seen={item['first_seen_seconds']}s-{item.get('last_seen_seconds')}s")
            elif item.get("timestamp_seconds") is not None:
                parts.append(f"at={item['timestamp_seconds']}s")
            parts.append(f"description: {_text(item.get('description'), 300)}")
            lines.append("- " + "; ".join(parts))
    return "\n".join(lines)


def _parse_json_object(content: str) -> dict[str, Any]:
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", content.strip(), re.DOTALL)
    parsed = json.loads(fenced.group(1) if fenced else content)
    if not isinstance(parsed, dict):
        raise ValueError("Link LLM returned a non-object")
    return parsed


def validate_groups(raw: Any, videos: list[VideoAnalysisInput]) -> list[EvidenceGroup]:
    """The model's groups that obey the rules, renumbered G1, G2 ...; anything else is dropped."""
    if not isinstance(raw, list):
        return []
    known = {video.video_name: _items(video) for video in videos}
    used: set[tuple[str, str]] = set()
    groups: list[EvidenceGroup] = []
    for candidate in raw:
        if not isinstance(candidate, dict):
            continue
        kind = candidate.get("kind")
        label = _text(candidate.get("label"), _MAX_LABEL_CHARS)
        members_raw = candidate.get("members")
        if kind not in ("entity", "instrument", "asset") or not label or not isinstance(members_raw, list):
            continue
        members: list[tuple[str, str]] = []
        for member in members_raw:
            if not isinstance(member, dict):
                members = []
                break
            video, item_id = member.get("video"), member.get("itemId")
            if not isinstance(video, str) or not isinstance(item_id, str):
                members = []
                break
            members.append((video, item_id.strip()))
        cameras = {video for video, _ in members}
        if (
            len(members) < 2
            or len(cameras) != len(members)  # two items of one video
            or len(set(members)) != len(members)
            or any(item_id not in known.get(video, {}).get(kind, {}) for video, item_id in members)
            or any(member in used for member in members)
        ):
            continue
        used.update(members)
        reason = _text(candidate.get("reason"), _MAX_REASON_CHARS) or None
        groups.append(
            EvidenceGroup(
                id=f"G{len(groups) + 1}",
                kind=kind,
                label=label,
                members=[EvidenceGroupMember(video=video, itemId=item_id) for video, item_id in members],
                reason=reason,
            )
        )
    return groups


async def _link_via_llm(
    videos: list[VideoAnalysisInput],
    rp1_base_url: str,
    api_key: str,
    timeout: float,
) -> list[EvidenceGroup]:
    """One text-only LLM call; raises on transport, HTTP or JSON failure."""
    prompt = _LINK_PROMPT_TEMPLATE.format(cameras="\n\n".join(_camera_text(video) for video in videos))
    rp1_settings = incident_contract.rp1_request()
    model = rp1_settings.pop("model")
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False, **rp1_settings}
    url = f"{rp1_base_url.rstrip('/')}/v1/chat/completions"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=body, headers={"Authorization": f"Bearer {api_key}"})
    if response.status_code >= 400:
        raise ValueError(f"Link LLM returned HTTP {response.status_code}: {response.text[:300]}")
    choices = response.json().get("choices") or []
    content = ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
    if not content:
        raise ValueError("Link LLM returned no content")
    return validate_groups(_parse_json_object(content).get("groups"), videos)


def create_incident_link_evidence_router(
    rp1_base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = 60.0,
) -> APIRouter:
    """Build the ``POST /api/v1/incidents/link-evidence`` router."""
    router = APIRouter()

    @router.post(
        "/api/v1/incidents/link-evidence",
        summary="Link the same entity, instrument or asset across the videos of one report version (stateless)",
        tags=["Incident Link Evidence"],
    )
    async def link_evidence(body: LinkEvidenceRequest) -> LinkEvidenceResponse:
        if len({video.video_name for video in body.videos}) < 2:
            return LinkEvidenceResponse(evidence_groups=[])
        if not rp1_base_url or not api_key:
            raise HTTPException(status_code=503, detail="No RP1 endpoint or API key configured for evidence linking")
        try:
            groups = await _link_via_llm(body.videos, rp1_base_url, api_key, timeout)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
            logger.warning("Evidence linking failed, returning no groups: %s", exc)
            groups = []
        return LinkEvidenceResponse(evidence_groups=groups)

    return router


def register_incident_link_evidence_routes(
    app: FastAPI,
    rp1_base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = 60.0,
) -> None:
    """Register ``POST /api/v1/incidents/link-evidence``."""
    app.include_router(
        create_incident_link_evidence_router(rp1_base_url=rp1_base_url, api_key=api_key, timeout=timeout)
    )
    logger.info("Registered POST /api/v1/incidents/link-evidence")
