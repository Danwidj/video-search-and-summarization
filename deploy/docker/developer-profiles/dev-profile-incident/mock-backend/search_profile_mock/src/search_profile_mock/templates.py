"""Canned/templated text generation - no LLM/VLM call, ever.

Only `vss-agent` itself calls the real LLM/VLM; the UI never does. Mocking
vss-agent's own logic therefore means replacing that generation step with
simple keyword-based intent classification and canned or templated text, not
building a separate inference mock.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import uuid

from search_profile_mock.state import Stream

# Copied verbatim from
# deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml
# (hitl_vlm_prompt_template, ~lines 114-129).
HITL_VLM_PROMPT_TEMPLATE = """**VLM Prompt for Report Generation**

**OPTIONS:**

• Press Submit (empty) → Approve and generate report

• Type a new prompt directly or paste current prompt and edit it manually

• Type `/generate <description>` → AI creates a prompt based on your description

• Type `/refine <instructions>` → AI modifies the current prompt

• Type `/cancel` → Cancel report generation

Enter your choice or press Submit to keep current value:"""

CANCEL_KEYWORD = "/cancel"

REPORT_KEYWORDS = ("report", "summarize", "summarise", "summary")
VIDEO_LIST_KEYWORDS = ("list", "videos", "streams", "catalog", "what videos", "available")
# Search-profile chat intent (agent-mode search via the chat sidebar). Checked
# after report/video_list so base intents keep their exact behavior.
SEARCH_KEYWORDS = ("search for", "find ", "locate", "show me", "where is", "look for", "retrieve")


def classify_intent(message: str) -> str:
    """Very small keyword classifier standing in for the real agent's routing."""
    lowered = message.lower()
    if any(kw in lowered for kw in REPORT_KEYWORDS):
        return "report"
    if any(kw in lowered for kw in VIDEO_LIST_KEYWORDS):
        return "video_list"
    if any(kw in lowered for kw in SEARCH_KEYWORDS):
        return "search"
    return "generic"


def build_generic_answer(message: str, streams: dict[str, Stream]) -> str:
    lowered = message.lower()
    for stream in streams.values():
        if stream.filename.lower() in lowered or stream.name.lower() in lowered:
            return (
                f"I looked at **{stream.filename}** and did not find any notable events. "
                "This is a canned answer from the search-profile mock backend - no real VLM "
                "inference was performed."
            )
    return (
        "No notable events found. This is a canned answer from the search-profile mock "
        "backend - no real VLM inference was performed."
    )


def build_video_list_answer(streams: dict[str, Stream]) -> str:
    if not streams:
        return "No videos have been uploaded yet."
    lines = ["Here are the videos currently available:", ""]
    for stream in streams.values():
        lines.append(f"- **{stream.filename}** (stream id `{stream.stream_id}`)")
    return "\n".join(lines)


def build_report_markdown(streams: dict[str, Stream], conversation_id: str) -> str:
    now = _dt.datetime.now(tz=_dt.UTC)
    video_lines = "\n".join(f"- {s.filename} (`{s.stream_id}`)" for s in streams.values()) or "- (no videos uploaded)"
    return f"""# Incident Report (mock)

Generated: {now.isoformat()}
Conversation: {conversation_id}

## Summary

This report was fabricated by the search-profile mock backend for local UI
development. No real VLM inference was performed.

## Videos considered

{video_lines}

## Findings

No notable events were detected in the mock analysis.
"""


def report_filename(now: _dt.datetime | None = None) -> str:
    now = now or _dt.datetime.now(tz=_dt.UTC)
    suffix = uuid.uuid4().hex[:8]
    return f"agent_report_{now.strftime('%Y%m%d_%H%M%S')}_{suffix}.md"


# ---------------------------------------------------------------------------
# Search-profile additions: canned visual-search / analytics surfaces.
#
# Shapes mirror what the search-tab UI consumes:
# - `POST /api/v1/search` request/response in
#   services/ui/packages/nv-metropolis-bp-vss-ui/search/lib-src/hooks/useSearch.ts
#   (response `{data: [...]}` with video_name/similarity/screenshot_url/
#   description/start_time/end_time/sensor_id/object_ids/critic_result).
# - `GET /frames` response handling in `hooks/useSearchByImage.ts` (array, or
#   `{frames: [...]}`, or a single frame object; objects carry id/objectId +
#   bbox in leftX/topY/rightX/bottomY or left/top/right/bottom form).
# Scores, boxes, and ids are deterministic hashes, not real inference output.
# ---------------------------------------------------------------------------


def _deterministic_score(seed: str) -> float:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    fraction = int(digest[:8], 16) / 0xFFFFFFFF
    return round(0.55 + fraction * 0.44, 2)


def _object_ids_for(stream_id: str, count: int = 2) -> list[str]:
    digest = hashlib.sha256(stream_id.encode()).hexdigest()
    return [f"obj-{digest[i * 8 : i * 8 + 8]}" for i in range(count)]


def build_search_results(
    streams: dict[str, Stream],
    query: str,
    top_k: int = 10,
    base_url: str = "http://localhost:7778",
    min_similarity: float = 0.0,
    video_sources: list[str] | None = None,
    now: _dt.datetime | None = None,
) -> list[dict]:
    """Canned `{data: [...]}` items for `POST /api/v1/search` and siblings."""
    now = now or _dt.datetime.now(tz=_dt.UTC)
    candidates = list(streams.values())
    if video_sources:
        wanted = set(video_sources)
        candidates = [s for s in candidates if s.stream_id in wanted or s.name in wanted or s.filename in wanted]
    items = []
    for index, stream in enumerate(candidates):
        score = _deterministic_score(f"{query}:{stream.stream_id}")
        if score < min_similarity:
            continue
        start = now - _dt.timedelta(minutes=5 * (index + 1))
        end = start + _dt.timedelta(seconds=30)
        picture = (
            f"{base_url.rstrip('/')}/vst/api/v1/replay/stream/{stream.stream_id}/picture?startTime={start.isoformat()}"
        )
        items.append(
            {
                "video_name": stream.filename,
                "similarity": score,
                "screenshot_url": picture,
                "description": (
                    f"Mock match for query '{query}' in **{stream.filename}**. "
                    "Fabricated by the search-profile mock backend - no real "
                    "embedding or perception inference was performed."
                ),
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "sensor_id": stream.stream_id,
                "object_ids": _object_ids_for(stream.stream_id),
                "critic_result": {"result": "unverified", "criteria_met": {}},
            }
        )
    items.sort(key=lambda item: item["similarity"], reverse=True)
    return items[: max(0, top_k)]


def build_agent_mode_search_answer(
    streams: dict[str, Stream],
    query: str,
    top_k: int = 10,
    base_url: str = "http://localhost:7778",
) -> str:
    """Chat-sidebar answer carrying a Search-API-shaped JSON block.

    The search tab's agent mode forwards the query to chat and parses the
    answer with `utils/agentResponseParser.ts`, which extracts a
    ```json {"data": [...]}``` block. This returns that shape as text.
    """
    payload = {"data": build_search_results(streams, query, top_k=top_k, base_url=base_url)}
    if not payload["data"]:
        return "No matching clips found in the mock index. Upload a video first, then search again."
    return (
        f"Found {len(payload['data'])} mock match(es) for '{query}' "
        "(fabricated - no real inference):\n\n```json\n"
        f"{json.dumps(payload, indent=2)}\n```"
    )


def build_frames_response(sensor_name: str, timestamp: str) -> dict:
    """Canned `GET /video-analytics-api/frames` payload with bbox objects."""
    digest = hashlib.sha256(f"{sensor_name}:{timestamp}".encode()).hexdigest()
    object_types = ("Person", "Vehicle")
    objects = []
    for i in range(2):
        seed = int(digest[i * 8 : i * 8 + 8], 16)
        left = round(0.05 + (seed % 70) / 100, 3)
        top = round(0.05 + ((seed >> 8) % 70) / 100, 3)
        objects.append(
            {
                "id": f"obj-{digest[i * 8 : i * 8 + 8]}",
                "type": object_types[i % len(object_types)],
                "bbox": {
                    "leftX": left,
                    "topY": top,
                    "rightX": round(min(0.98, left + 0.15), 3),
                    "bottomY": round(min(0.98, top + 0.25), 3),
                },
            }
        )
    return {"frames": [{"timestamp": timestamp, "metadata": {"objects": objects}}]}


def build_kibana_dashboards() -> dict:
    """Canned `GET /kibana/api/saved_objects/_find` payload for the dashboard tab."""
    return {
        "saved_objects": [
            {
                "id": "mock-search-overview",
                "type": "dashboard",
                "attributes": {
                    "title": "VSS Search Overview (mock)",
                    "description": "Placeholder dashboard served by the search-profile mock backend.",
                },
            }
        ],
        "total": 1,
        "per_page": 20,
        "page": 1,
    }
