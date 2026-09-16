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
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
import asyncio
import logging
import re

from langchain_core.exceptions import LangChainException, OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from nat.builder.builder import Builder
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.component_ref import FunctionRef, LLMRef
from nat.data_models.function import FunctionBaseConfig
from pydantic import BaseModel, Field

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
- incident_type must be exactly one of: road accident, burglary, explosion, fighting, animal.
  Pick the closest match; if nothing in the report matches any of these, use "burglary" only if there is
  a clear property-crime element, otherwise pick the single best fit from the list - never invent a new type.
- severity is an integer from 1 (minor) to 5 (critical).
- confidence is a float from 0.0 to 1.0 reflecting how confident you are in incident_type given the report.
- persons should list each distinct person mentioned, with a short physical description and their actions.
- description is a 1-3 sentence summary of the incident.
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


def _derive_incident_bounds(content: str | None) -> tuple[str, str, bool]:
    """Derive (incident_start, incident_end, confirmed) from timestamped chunks in ``content``.

    Takes the min start / max end across every ``[Xs-Ys]`` marker in the
    generated report. Falls back to ``("0:00", "0:00", False)`` when no
    timestamps are present.
    """
    if not content:
        return "0:00", "0:00", False
    matches = list(_TIMESTAMP_PATTERN.finditer(content))
    if not matches:
        return "0:00", "0:00", False
    starts = [float(m.group(1)) for m in matches]
    ends = [float(m.group(2)) for m in matches]
    return _seconds_to_mmss(min(starts)), _seconds_to_mmss(max(ends)), True


class IncidentReportGenConfig(FunctionBaseConfig, name="incident_report_gen"):
    """Config for the structured incident-report extraction tool."""

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
    llm,  # noqa: ANN001 - langchain BaseChatModel, kept loose to match sibling tools
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
    except (OutputParserException, LangChainException) as e:
        logger.warning("incident_report_gen: extraction LLM call failed: %s", e)
        return IncidentReport()


async def _persist_incident(
    *,
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
        await db.upsert_video(sensor_id, filepath=filepath, source="vss_agent")
        await db.insert_model_run(model_run_id, model_name=model_name)
        await db.insert_incident(
            sensor_id,
            model_run_id,
            fields={
                "type": report.incident_type,
                "start_timestamp": incident_start,
                "end_timestamp": incident_end,
                "description": report.description,
                "severity_level": report.severity,
                "confidence_score": report.confidence,
            },
        )
        for idx, person in enumerate(report.persons):
            try:
                await db.add_incident_entity(
                    sensor_id,
                    model_run_id,
                    entity_id=f"{sensor_id}-person-{idx}",
                    type="person",
                    description=f"{person.description} {person.actions}".strip(),
                )
            except Exception as e:  # noqa: BLE001 - one bad entity write must not drop the rest
                logger.warning("incident_report_gen: failed to persist entity %d for %s: %s", idx, sensor_id, e)
    except Exception as e:  # noqa: BLE001 - fail-soft by design, see module docstring
        logger.warning("incident_report_gen: failed to persist incident for %s: %s", sensor_id, e)


class IncidentReportGenInput(BaseModel):
    """Input for the incident_report_gen tool."""

    sensor_id: str = Field(..., description="VST sensor ID (filename) of the uploaded video to analyze.")
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

        content = report_result.content or ""
        structured_report = await _extract_structured_report(llm, content, config.extraction_timeout_seconds)

        incident_start, incident_end, confirmed = _derive_incident_bounds(content)
        structured_report.incident_start = incident_start
        structured_report.incident_end = incident_end
        structured_report.incident_start_confirmed = confirmed

        await _persist_incident(
            sensor_id=tool_input.sensor_id,
            report=structured_report,
            incident_start=incident_start,
            incident_end=incident_end,
            filepath=report_result.video_url,
            model_run_id=config.model_run_id,
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
            "IncidentReport (incident_type, severity, confidence, persons, description, location). "
            "Persists the result to the incident DB when configured (best-effort, fails soft)."
        ),
        input_schema=IncidentReportGenInput,
        single_output_schema=IncidentReportGenOutput,
    )
