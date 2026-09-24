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

"""Structured incident-report generation tool for the incident-console ``/analyze`` path.

Thin wrapper over ``video_report_gen``: runs the existing video analysis
report, then extracts a structured :class:`IncidentReport` (incident type,
severity, confidence, persons, ...) from the generated markdown via
``llm.with_structured_output`` (same pattern as
``agents/postprocessing/validators/llm_based_rule_validator.py`` and
``evaluators/report_evaluator/field_evaluators/llm_judge.py``), then persists
the result via ``incident_db.py`` best-effort (a DB outage must never break
report generation - see ``_persist_incident`` below).

Upload-only by design: this tool handles uploaded VST videos (``media_type``
is always ``"video"``). It has no ``media_type``/``start_time``/``end_time``
fields, so the incident profile must never route ``report_agent`` RTSP stream
requests through it - an RTSP request here would silently run as a plain
video report. The incident profile serves uploaded videos only, no RTSP.
"""

import asyncio
from collections.abc import AsyncGenerator
import hashlib
import logging
import re
from typing import Any

from langchain_core.exceptions import LangChainException
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from nat.builder.builder import Builder
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.component_ref import FunctionRef
from nat.data_models.component_ref import LLMRef
from nat.data_models.function import FunctionBaseConfig
from pydantic import BaseModel
from pydantic import Field
from pydantic import ValidationError

from vss_agents.data_models.incident_report import IncidentReport
from vss_agents.tools.video_report_gen import VideoReportGenOutput
from vss_agents.utils import incident_db

logger = logging.getLogger(__name__)

# Default upstream timeout for the extraction LLM call. The NVIDIA free-tier
# remote endpoint caps concurrency at 16 and hangs rather than degrading past
# it, so this must be bounded rather than left to the client default.
DEFAULT_EXTRACTION_TIMEOUT_SECONDS = 60.0

_EXTRACTION_SYSTEM_PROMPT = """You are an incident-analysis assistant. You are given a markdown video
analysis report describing what happens in a surveillance video. Extract a structured incident report
from it.

Rules:
- title is a short factual title summarizing the incident (max 160 characters).
- incident_type must be exactly one of: road accident, burglary, explosion, fighting, animal.
  Pick the closest match; if nothing in the report matches any of these, use "burglary" only if there is
  a clear property-crime element, otherwise pick the single best fit from the list - never invent a new type.
- severity is an integer from 1 (minor) to 5 (critical).
- severity_reason is a concise explanation of why this severity level was selected based on observable risk or harm.
- confidence is a float from 0.0 to 1.0 reflecting how confident you are in incident_type given the report.
- duration_seconds is the duration of the incident in seconds (integer) if observable or stated in the report, else null.
- description is a 1-3 sentence plain-language executive summary of the incident.
- persons should list each distinct person mentioned, with a short physical description and their actions.
- instruments should list objects, tools, weapons, or vehicles actively used in the incident, each with name, description of use, and optional threat_level (1-5, or null if unrated/harmless).
- assets should list property, structures, vehicles, or items affected or targeted in the incident, each with name and description of observable state/damage.
- timeline should be an ordered chronological list of observable events, each with start_seconds (float offset from video start), optional end_seconds (float or null), and description.
- uncertainties should list any ambiguities or aspects that cannot be determined confidently from the report (do not invent unconfirmed details).
- location is the camera/location name if mentioned in the report, else empty string.
Do not fill in incident_start / incident_end - they are derived separately from the report's timestamps.
"""

# Matches the [Xs-Ys] timestamp markers video_report_gen normalizes into the
# markdown content (see video_report_gen.py's _normalize_chunk_timestamps).
_TIMESTAMP_PATTERN = re.compile(
    r"\[\s*(\d+(?:\.\d+)?)(?:s)?\s*-\s*(\d+(?:\.\d+)?)(?:s)?\s*\]",
)


def _seconds_to_mmss(seconds: float) -> str:
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def _derive_video_id(sensor_id: str) -> str:
    """Map ``sensor_id`` to a stable id that fits ``videos.id`` (``String(20)``).

    Mirrors the incident-console's own
    ``catalog_actions.derive_video_id()`` exactly (same hash, same prefix,
    same truncation) so a video uploaded through the console and later
    analyzed via a caller that never passes an explicit ``incident_id``
    (e.g. a chat-driven ``report_agent`` invocation) still resolves to the
    same row on repeated calls. Cannot import that module directly - the
    console and the agent are separate deployable apps.
    """
    return "v" + hashlib.sha256(sensor_id.encode("utf-8")).hexdigest()[:19]


def _timestamp_span(content: str | None) -> tuple[float, float] | None:
    """Return the (min start, max end) seconds across every ``[Xs-Ys]`` marker, or ``None`` if there are none."""
    if not content:
        return None
    matches = list(_TIMESTAMP_PATTERN.finditer(content))
    if not matches:
        return None
    return min(float(m.group(1)) for m in matches), max(float(m.group(2)) for m in matches)


def _derive_incident_bounds(content: str | None) -> tuple[str, str, bool]:
    """Derive (incident_start, incident_end, confirmed) from timestamped chunks in ``content``.

    Takes the min start / max end across every ``[Xs-Ys]`` marker in the
    generated report. Falls back to ``("0:00", "0:00", False)`` when no
    timestamps are present.
    """
    span = _timestamp_span(content)
    if span is None:
        return "0:00", "0:00", False
    return _seconds_to_mmss(span[0]), _seconds_to_mmss(span[1]), True


class IncidentReportGenConfig(FunctionBaseConfig, name="incident_report_gen"):
    """Config for the structured incident-report extraction tool.

    Upload-only: the incident profile serves uploaded videos, not RTSP
    streams, so there is deliberately no stream configuration here.
    """

    video_report_tool: FunctionRef = Field(
        default="video_report_gen",
        description="Name of the video_report_gen tool to generate the underlying video analysis report.",
    )
    llm_name: LLMRef = Field(
        ...,
        description="LLM used to extract a structured IncidentReport from the generated report markdown.",
    )
    extraction_timeout_seconds: float = Field(
        default=DEFAULT_EXTRACTION_TIMEOUT_SECONDS,
        gt=0,
        description="Upstream timeout for the structured-extraction LLM call.",
    )
    model_run_id: str = Field(
        default="incident_report_gen",
        description="model_runs.id this tool's incident writes are recorded under in the incident DB.",
    )
    model_name: str = Field(
        default="incident_report_gen",
        description="model_runs.model_name recorded alongside model_run_id.",
    )


class IncidentReportGenOutput(VideoReportGenOutput):
    """``video_report_gen``'s output plus the extracted structured report."""

    structured_report: IncidentReport = Field(default_factory=IncidentReport)


async def _extract_structured_report(
    llm: Any,  # Untyped: the NAT builder returns untyped LangChain wrappers at this boundary.
    content: str,
    timeout_seconds: float,
) -> IncidentReport:
    """Run ``llm.with_structured_output(IncidentReport)`` over the report markdown, bounded by a timeout."""
    structured_llm = llm.with_structured_output(IncidentReport)
    messages = [
        SystemMessage(content=_EXTRACTION_SYSTEM_PROMPT),
        HumanMessage(content=f"Video analysis report:\n\n{content}"),
    ]
    try:
        result = await asyncio.wait_for(structured_llm.ainvoke(messages), timeout=timeout_seconds)
        return IncidentReport.model_validate(result)
    except TimeoutError:
        logger.warning("incident_report_gen: extraction LLM call timed out after %ss", timeout_seconds)
        return IncidentReport()
    except (
        OutputParserException,
        LangChainException,
        ValidationError,
    ) as e:
        logger.warning("incident_report_gen: extraction LLM call failed: %s", e)
        return IncidentReport()


def _derive_entity_id(incident_id: str, idx: int) -> str:
    """Deterministic ``entities.entity_id`` (``String(20)``) for the ``idx``-th person.

    ``incident_id`` (up to 20 chars) plus a raw ``-person-N`` suffix can
    exceed the column, so hash the pair instead of concatenating.
    """
    return "e" + hashlib.sha256(f"{incident_id}:{idx}".encode()).hexdigest()[:19]


def _derive_instrument_id(incident_id: str, idx: int) -> str:
    """Deterministic ``instruments.instrument_id`` (``String(20)``) for the ``idx``-th instrument."""
    return "i" + hashlib.sha256(f"{incident_id}:{idx}".encode()).hexdigest()[:19]


def _derive_asset_id(incident_id: str, idx: int) -> str:
    """Deterministic ``assets.asset_id`` (``String(20)``) for the ``idx``-th asset."""
    return "a" + hashlib.sha256(f"{incident_id}:{idx}".encode()).hexdigest()[:19]


async def _persist_incident(
    *,
    incident_id: str,
    sensor_id: str,
    report: IncidentReport,
    incident_start: str,
    incident_end: str,
    filepath: str | None,
    model_run_id: str,
    model_name: str,
) -> None:
    """Best-effort persistence to the incident DB. Never raises - a DB outage must not break generation."""
    try:
        if not incident_db.is_configured():
            return
        db = await incident_db.get_db()
        if db is None:
            return
        await db.upsert_video(incident_id, filepath=filepath, source=sensor_id)
        await db.insert_model_run(model_run_id, model_name=model_name)
        await db.insert_incident(
            incident_id,
            model_run_id,
            fields={
                "type": report.incident_type,
                "start_timestamp": incident_start,
                "end_timestamp": incident_end,
                "duration": report.duration_seconds,
                "description": report.description,
                "severity_level": report.severity,
                "confidence_score": report.confidence,
            },
        )
        # Delete-then-insert, mirroring insert_incident above: entity ids are
        # deterministic per (incident, person index), so a second Analyze on
        # the same video/model-run would otherwise PK-violate on every insert
        # (swallowed per-entity below) and keep the stale person list.
        await db.delete_incident_entities(incident_id, model_run_id)
        for idx, person in enumerate(report.persons):
            try:
                await db.add_incident_entity(
                    incident_id,
                    model_run_id,
                    entity_id=_derive_entity_id(incident_id, idx),
                    type="person",
                    description=f"{person.description} {person.actions}".strip(),
                )
            except Exception as e:
                logger.warning("incident_report_gen: failed to persist entity %d for %s: %s", idx, incident_id, e)

        await db.delete_incident_instruments(incident_id, model_run_id)
        for idx, inst in enumerate(report.instruments):
            try:
                await db.add_incident_instrument(
                    incident_id,
                    model_run_id,
                    instrument_id=_derive_instrument_id(incident_id, idx),
                    name=inst.name,
                    description=inst.description,
                    threat_level=inst.threat_level,
                )
            except Exception as e:
                logger.warning("incident_report_gen: failed to persist instrument %d for %s: %s", idx, incident_id, e)

        await db.delete_incident_assets(incident_id, model_run_id)
        for idx, asset in enumerate(report.assets):
            try:
                await db.add_incident_asset(
                    incident_id,
                    model_run_id,
                    asset_id=_derive_asset_id(incident_id, idx),
                    name=asset.name,
                    description=asset.description,
                )
            except Exception as e:
                logger.warning("incident_report_gen: failed to persist asset %d for %s: %s", idx, incident_id, e)
    except Exception as e:
        logger.warning("incident_report_gen: failed to persist incident for %s: %s", incident_id, e)


class IncidentReportGenInput(BaseModel):
    """Input for the incident_report_gen tool.

    Upload-only: there are deliberately no ``media_type``/``start_time``/
    ``end_time`` fields (cf. ``VideoReportGenInput``) - the incident profile
    serves uploaded videos, not RTSP streams.
    """

    sensor_id: str | list[str] = Field(
        ...,
        description=(
            "VST sensor ID (filename) of the uploaded video to analyze. A list batches multiple videos "
            "into one report_agent call (matching video_report_gen's contract); that case is passed "
            "straight through to video_report_gen with no structured incident extraction or persistence, "
            "since incident semantics (single incident_type/severity/persons) only make sense per-video."
        ),
    )
    incident_id: str | None = Field(
        default=None,
        description=(
            "incident-console videos.id/incidents.incident_id (String(20)) to persist under. Passed "
            "explicitly by the console's /analyze route, which already knows the row's derived id. When "
            "omitted (e.g. a chat-driven report_agent call with no console record), one is derived from "
            "sensor_id the same way the console derives it, so repeated calls for the same video resolve "
            "to the same row."
        ),
    )
    model_run_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        description="Optional model_runs.id to persist under. When omitted, defaults to config.model_run_id.",
    )
    user_query: str = Field(
        default="Generate a detailed incident report of the video.",
        description="The analysis request passed through to video_report_gen.",
    )
    vlm_reasoning: bool | None = Field(default=None, description="Enable VLM reasoning mode for video analysis.")
    prompt_override: str | None = Field(
        default=None,
        description="Optional override for user_query (kept separate so callers can pass both explicitly).",
    )


@register_function(config_type=IncidentReportGenConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def incident_report_gen(config: IncidentReportGenConfig, builder: Builder) -> AsyncGenerator[FunctionInfo]:
    """Generate a video report via ``video_report_gen`` and extract a structured :class:`IncidentReport`."""

    video_report_tool = await builder.get_tool(config.video_report_tool, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
    llm = await builder.get_llm(config.llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

    async def _incident_report_gen(tool_input: IncidentReportGenInput) -> IncidentReportGenOutput:
        user_query = tool_input.prompt_override or tool_input.user_query
        video_report_input: dict = {
            "sensor_id": tool_input.sensor_id,
            "user_query": user_query,
            "media_type": "video",
        }
        if tool_input.vlm_reasoning is not None:
            video_report_input["vlm_reasoning"] = tool_input.vlm_reasoning

        report_result: VideoReportGenOutput = await video_report_tool.ainvoke(video_report_input)

        if isinstance(tool_input.sensor_id, list):
            # Multi-video report_agent requests carry no single incident semantics
            # (one incident_type/severity/persons doesn't apply across videos) -
            # pass straight through to video_report_gen, unchanged from dev-profile-base.
            return IncidentReportGenOutput(**report_result.model_dump())

        content = report_result.content or ""
        structured_report = await _extract_structured_report(llm, content, config.extraction_timeout_seconds)

        span = _timestamp_span(content)
        incident_start, incident_end, confirmed = _derive_incident_bounds(content)
        structured_report.incident_start = incident_start
        structured_report.incident_end = incident_end
        structured_report.incident_start_confirmed = confirmed
        if structured_report.duration_seconds is None and span is not None:
            structured_report.duration_seconds = max(0, round(span[1] - span[0]))

        incident_id = tool_input.incident_id or _derive_video_id(tool_input.sensor_id)
        model_run_id = tool_input.model_run_id or config.model_run_id
        await _persist_incident(
            incident_id=incident_id,
            sensor_id=tool_input.sensor_id,
            report=structured_report,
            incident_start=incident_start,
            incident_end=incident_end,
            filepath=report_result.video_url,
            model_run_id=model_run_id,
            model_name=config.model_name,
        )

        return IncidentReportGenOutput(
            **report_result.model_dump(),
            structured_report=structured_report,
        )

    yield FunctionInfo.create(
        single_fn=_incident_report_gen,
        description=(
            "Generate an incident analysis report for an uploaded video and extract a structured "
            "IncidentReport (incident_type, severity, confidence, persons, description, location, etc.). "
            "Persists the result to the incident DB when configured (best-effort, fails soft)."
        ),
        input_schema=IncidentReportGenInput,
        single_output_schema=IncidentReportGenOutput,
    )
