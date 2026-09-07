"""Canned/templated text generation - no LLM/VLM call, ever.

Only `vss-agent` itself calls the real LLM/VLM; the UI never does. Mocking
vss-agent's own logic therefore means replacing that generation step with
simple keyword-based intent classification and canned or templated text, not
building a separate inference mock.
"""

from __future__ import annotations

import datetime as _dt
import uuid

from base_profile_mock.state import Stream

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


def classify_intent(message: str) -> str:
    """Very small keyword classifier standing in for the real agent's routing."""
    lowered = message.lower()
    if any(kw in lowered for kw in REPORT_KEYWORDS):
        return "report"
    if any(kw in lowered for kw in VIDEO_LIST_KEYWORDS):
        return "video_list"
    return "generic"


def build_generic_answer(message: str, streams: dict[str, Stream]) -> str:
    lowered = message.lower()
    for stream in streams.values():
        if stream.filename.lower() in lowered or stream.name.lower() in lowered:
            return (
                f"I looked at **{stream.filename}** and did not find any notable events. "
                "This is a canned answer from the base-profile mock backend - no real VLM "
                "inference was performed."
            )
    return (
        "No notable events found. This is a canned answer from the base-profile mock "
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

This report was fabricated by the base-profile mock backend for local UI
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
