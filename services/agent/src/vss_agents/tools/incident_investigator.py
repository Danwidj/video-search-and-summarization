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

"""Read-only tools for the incident investigator agent (``POST /api/v1/incidents/{video_id}/investigate``).

The agent chooses among tools declared under ``functions:`` in the agent config. These two read the stored report
of the video the request is about. The video is bound by the route (``utils/agent_loop``), never an argument the model
fills in, so the model cannot ask about another video. Both go through :func:`agent_loop.run_guarded_tool`, which keeps
the step log and the step budget. Neither writes anything.
"""

from collections.abc import AsyncGenerator
import json
import logging
from typing import Any

from nat.builder.builder import Builder
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig
from pydantic import BaseModel

from vss_agents.utils import agent_loop
from vss_agents.utils import incident_db

logger = logging.getLogger(__name__)

REPORT_CHARS = 8000


class NoArguments(BaseModel):
    """These tools take nothing from the model: the video comes from the request."""


def _database(db: incident_db.IncidentDB | None) -> incident_db.IncidentDB:
    if db is None:
        # Not a ValueError: a database that is down is not something the model can fix, so the run stops.
        raise RuntimeError("the incident database is not configured or unreachable")
    return db


async def read_report(video_id: str) -> str:
    """The video's official report, else its newest one, as JSON text cut at ``REPORT_CHARS``."""
    db = _database(await incident_db.get_db())
    video = await db.get_video(video_id)
    if video is None:
        raise ValueError(f"there is no video {video_id}")
    official = video.get("official_revision_id")
    revision = await db.get_revision(int(official)) if official is not None else None
    which = "official"
    if revision is None:
        revisions = await db.list_revisions(video_id)
        revision = revisions[-1] if revisions else None
        which = "newest, not official"
    if revision is None:
        raise ValueError(f"video {video_id} has no report yet")
    text = json.dumps(revision.get("payload") or {}, ensure_ascii=False)
    if len(text) > REPORT_CHARS:
        text = text[:REPORT_CHARS] + " ...[report cut]"
    return f"Report of {video_id}, version {revision.get('revision_no')} ({which}): {text}"


async def list_versions(video_id: str) -> str:
    """Each saved version of the report: number, who made it (ai or human) and whether it is the official one."""
    db = _database(await incident_db.get_db())
    video = await db.get_video(video_id)
    if video is None:
        raise ValueError(f"there is no video {video_id}")
    official = video.get("official_revision_id")
    revisions = await db.list_revisions(video_id)
    if not revisions:
        raise ValueError(f"video {video_id} has no report yet")
    rows: list[dict[str, Any]] = [
        {
            "version": revision.get("revision_no"),
            "made_by": revision.get("kind"),
            "official": official is not None and revision.get("id") == official,
            "saved_at": revision.get("created_at"),
        }
        for revision in revisions
    ]
    return json.dumps(rows, ensure_ascii=False)


class IncidentReadReportConfig(FunctionBaseConfig, name="incident_read_report"):
    pass


class IncidentListVersionsConfig(FunctionBaseConfig, name="incident_list_versions"):
    pass


@register_function(config_type=IncidentReadReportConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def incident_read_report(
    config: IncidentReadReportConfig,  # noqa: ARG001
    builder: Builder,  # noqa: ARG001
) -> AsyncGenerator[FunctionInfo]:
    async def run(arguments: NoArguments) -> str:  # noqa: ARG001
        return await agent_loop.run_guarded_tool(
            "incident_read_report", {}, lambda: read_report(agent_loop.current().video_id)
        )

    yield FunctionInfo.create(
        single_fn=run,
        description=(
            "Read the stored report of this video: the incident, its people, objects and places, and the timeline. "
            "Takes no arguments. Use it first for any question the report may answer."
        ),
        input_schema=NoArguments,
        single_output_schema=str,
    )


@register_function(config_type=IncidentListVersionsConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def incident_list_versions(
    config: IncidentListVersionsConfig,  # noqa: ARG001
    builder: Builder,  # noqa: ARG001
) -> AsyncGenerator[FunctionInfo]:
    async def run(arguments: NoArguments) -> str:  # noqa: ARG001
        return await agent_loop.run_guarded_tool(
            "incident_list_versions", {}, lambda: list_versions(agent_loop.current().video_id)
        )

    yield FunctionInfo.create(
        single_fn=run,
        description=(
            "List the saved versions of this video's report: version number, whether an AI or a person made it, "
            "which one is official, and when it was saved. Takes no arguments. Use it for questions about "
            "versions, edits or the official report."
        ),
        input_schema=NoArguments,
        single_output_schema=str,
    )
