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

"""Incident extraction for the incident-console ``/analyze`` path, on the shared incident contract.

Runs the same two calls as ``incident-console-v2`` (gateway mode) and the ``eval/`` benchmark
(see ``.docs/prompt-contract-plan.md`` in the incident profile):

1. **P1** - the video as a signed R2 URL first, then the contract extraction prompt, with the
   contract JSON Schema enforced through ``response_format`` and the fixed settings from
   ``p1_request.json``. The response is parsed strictly (``incident_contract.parse_report``);
   a violation raises :class:`IncidentExtractionError` and nothing is persisted.
2. **RP1** - a text-only prose report from the validated P1 JSON (``rp1_request.json``). A
   failed RP1 never discards a valid P1 report; the error is returned instead.

The validated report is persisted best-effort through ``incident_db`` (``incidents``,
``entities``, ``instruments``, ``assets`` - contract ids ``E1``/``I1``/``A1``). The ``videos``
row belongs to the console, which owns the durable R2 key, so this tool never writes it.
"""

from collections.abc import AsyncGenerator
import logging
import os
from typing import Any

import httpx
from nat.builder.builder import Builder
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig
from pydantic import BaseModel
from pydantic import Field

from vss_agents import incident_contract
from vss_agents.incident_contract import IncidentExtractionError
from vss_agents.utils import incident_db

logger = logging.getLogger(__name__)

# P1 with 64 frames or a reasoning model can take minutes; matches the console and gateway.
DEFAULT_REQUEST_TIMEOUT_SECONDS = 300.0


class IncidentReportGenConfig(FunctionBaseConfig, name="incident_report_gen"):
    """Endpoints and identity for the contract P1/RP1 calls.

    The P1/RP1 prompts, schema and request settings are not configured here: they come
    from the vendored incident contract, identical to eval and the console.
    """

    vlm_base_url: str = Field(..., description="OpenAI-compatible base URL for P1 (no trailing /v1).")
    vlm_model_name: str = Field(..., description="VLM that runs P1 on the video.")
    rp1_base_url: str = Field(..., description="OpenAI-compatible base URL for RP1 (no trailing /v1).")
    api_key_env: str = Field(
        default="OPENAI_API_KEY", description="Environment variable holding the bearer key for both endpoints."
    )
    request_timeout_seconds: float = Field(default=DEFAULT_REQUEST_TIMEOUT_SECONDS, gt=0)
    model_run_id: str = Field(
        default="incident_report_gen",
        description="model_runs.id used when the caller does not pass one.",
    )


class IncidentReportGenInput(BaseModel):
    incident_id: str = Field(..., min_length=1, max_length=20, description="Console videos.id / incidents.incident_id.")
    video_url: str = Field(
        ..., min_length=1, description="Signed R2 URL of the uploaded video, created by the console."
    )
    model_run_id: str | None = Field(default=None, min_length=1, max_length=20)


class IncidentReportGenOutput(BaseModel):
    """What ``POST /api/v1/incidents/{id}/analyze`` returns to the console."""

    report: dict[str, Any] = Field(description="Validated contract report with derived fields (incident.duration).")
    report_text: str | None = None
    report_text_error: str | None = None
    model: str
    contract_version: str
    raw_output: str


def _chat_completions_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/v1/chat/completions"


def p1_request_body(model: str, video_url: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "video_url", "video_url": {"url": video_url}},
                    {"type": "text", "text": incident_contract.extraction_prompt()},
                ],
            }
        ],
        "stream": False,
        **incident_contract.p1_request(),
        "response_format": incident_contract.response_format(),
    }


def rp1_request_body(report: dict[str, Any]) -> dict[str, Any]:
    settings = incident_contract.rp1_request()
    model = settings.pop("model")
    return {
        "model": model,
        "messages": [{"role": "user", "content": incident_contract.report_prompt(report)}],
        "stream": False,
        **settings,
    }


def _message_content(body: Any) -> tuple[str, str | None]:
    """``(content, finish_reason)`` of the first choice; a non-completion body is an error."""
    if not isinstance(body, dict) or not body.get("choices"):
        raise ValueError(f"no completion in response body: {str(body)[:300]}")
    choice = body["choices"][0]
    return (choice.get("message") or {}).get("content") or "", choice.get("finish_reason")


async def run_p1(
    client: httpx.AsyncClient, config: IncidentReportGenConfig, video_url: str
) -> tuple[dict[str, Any], str]:
    """One P1 call parsed strictly. Returns ``(report, raw_content)``."""
    response = await client.post(
        _chat_completions_url(config.vlm_base_url), json=p1_request_body(config.vlm_model_name, video_url)
    )
    if response.status_code >= 400:
        raise RuntimeError(f"P1 call returned HTTP {response.status_code}: {response.text[:500]}")
    content, finish_reason = _message_content(response.json())
    if not content and finish_reason == "length":
        raise IncidentExtractionError("the VLM ran out of tokens before returning the report (finish_reason=length)")
    return incident_contract.parse_report(content), content


async def run_rp1(
    client: httpx.AsyncClient, config: IncidentReportGenConfig, report: dict[str, Any]
) -> tuple[str | None, str | None]:
    """One RP1 call. Never raises: returns ``(report_text, error)``."""
    try:
        response = await client.post(_chat_completions_url(config.rp1_base_url), json=rp1_request_body(report))
        if response.status_code >= 400:
            return None, f"RP1 call returned HTTP {response.status_code}: {response.text[:300]}"
        content, _ = _message_content(response.json())
        text = content.strip()
        return (text, None) if text else (None, "RP1 returned no final content")
    except Exception as exc:  # A prose-report failure must not discard a valid P1 report.
        return None, f"{type(exc).__name__}: {exc}"


async def persist_report(*, incident_id: str, model_run_id: str, model_name: str, report: dict[str, Any]) -> None:
    """Best-effort persistence of a validated report. Never raises - a DB outage must not break analysis."""
    try:
        if not incident_db.is_configured():
            return
        db = await incident_db.get_db()
        if db is None:
            return
        incident = report["incident"]
        await db.insert_model_run(
            model_run_id, model_name=model_name, prompt_version=incident_contract.contract_version()
        )
        await db.insert_incident(
            incident_id,
            model_run_id,
            fields={
                "type": incident["type"],
                # Bare seconds, like eval and the console; readers accept both this and M:SS.
                "start_timestamp": str(incident["start_timestamp"]),
                "end_timestamp": str(incident["end_timestamp"]),
                "duration": incident["duration"],
                "description": incident["description"],
                "severity_level": incident["severity_level"],
                "confidence_score": incident["confidence_score"],
            },
        )
        # insert_incident's delete cascades to evidence rows; delete explicitly too so a
        # partial earlier write can never leave stale rows behind.
        await db.delete_incident_entities(incident_id, model_run_id)
        await db.delete_incident_instruments(incident_id, model_run_id)
        await db.delete_incident_assets(incident_id, model_run_id)
        for entity in report["entities"]:
            await db.add_incident_entity(
                incident_id,
                model_run_id,
                entity_id=entity["entity_id"],
                type=entity["type"],
                description=entity["description"],
            )
        for instrument in report["instruments"]:
            await db.add_incident_instrument(
                incident_id,
                model_run_id,
                instrument_id=instrument["instrument_id"],
                entity_id=instrument["entity_id"],
                name=instrument["name"],
                description=instrument["description"],
                threat_level=instrument["threat_level"],
            )
        for asset in report["assets"]:
            await db.add_incident_asset(
                incident_id,
                model_run_id,
                asset_id=asset["asset_id"],
                name=asset["name"],
                description=asset["description"],
            )
    except Exception as exc:
        logger.warning("incident_report_gen: failed to persist incident %s: %s", incident_id, exc)


@register_function(config_type=IncidentReportGenConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def incident_report_gen(config: IncidentReportGenConfig, builder: Builder) -> AsyncGenerator[FunctionInfo]:  # noqa: ARG001
    """Contract P1 -> RP1 over one uploaded video, persisted best-effort."""

    async def _incident_report_gen(tool_input: IncidentReportGenInput) -> IncidentReportGenOutput:
        api_key = os.environ.get(config.api_key_env, "")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        async with httpx.AsyncClient(timeout=config.request_timeout_seconds, headers=headers) as client:
            try:
                report, raw_output = await run_p1(client, config, tool_input.video_url)
            except httpx.TimeoutException as exc:
                raise TimeoutError(f"P1 call timed out after {config.request_timeout_seconds}s") from exc
            report_text, report_text_error = await run_rp1(client, config, report)

        await persist_report(
            incident_id=tool_input.incident_id,
            model_run_id=tool_input.model_run_id or config.model_run_id,
            model_name=config.vlm_model_name,
            report=report,
        )
        return IncidentReportGenOutput(
            report=report,
            report_text=report_text,
            report_text_error=report_text_error,
            model=config.vlm_model_name,
            contract_version=incident_contract.contract_version(),
            raw_output=raw_output,
        )

    yield FunctionInfo.create(
        single_fn=_incident_report_gen,
        description=(
            "Extract a structured incident report (incident-contract) from an uploaded video given its signed URL, "
            "then write a prose report. Persists to the incident DB when configured (best-effort)."
        ),
        input_schema=IncidentReportGenInput,
        single_output_schema=IncidentReportGenOutput,
    )
