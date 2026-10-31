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

"""``POST /api/v1/incidents/charts`` - draws the figures it is given with ``chart_generator``.

The incident console reads its figures from the database and sends them here, so nothing in
this route chooses or computes a number. The image goes to the agent's object store and the
response names its key, which ``GET /static/{key}`` serves.

The tool is called directly because NAT's generic ``front_end.endpoints`` route cannot serve it:
that route checks the result with ``isinstance(result, list[ChartGenExecOutput])``, which Python
refuses, after the tool has already drawn.

Status codes: 200 with the tool's outputs, 422 for a request that does not validate, 501 when the
profile does not configure ``chart_generator``, 500 when the tool fails.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
from nat.builder.framework_enum import LLMFrameworkEnum

from vss_agents.tools.chart_generator import ChartGeneratorInput
from vss_agents.tools.chart_generator import ChartGenExecOutput

if TYPE_CHECKING:
    from nat.builder.workflow_builder import WorkflowBuilder

logger = logging.getLogger(__name__)


def create_incident_charts_router(builder: WorkflowBuilder) -> APIRouter:
    """Build the ``POST /api/v1/incidents/charts`` router."""
    router = APIRouter()

    @router.post("/api/v1/incidents/charts", response_model=list[ChartGenExecOutput])
    async def draw_charts(body: ChartGeneratorInput) -> list[ChartGenExecOutput]:
        try:
            tool = await builder.get_tool("chart_generator", wrapper_type=LLMFrameworkEnum.LANGCHAIN)
        except Exception as exc:
            logger.error("chart_generator tool is not configured: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=501, detail="chart_generator tool is not configured on this profile"
            ) from exc
        try:
            result: list[ChartGenExecOutput] = await tool.ainvoke(body.model_dump())
        except Exception as exc:
            logger.error("chart_generator failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail="The chart could not be drawn") from exc
        return result

    return router


def register_incident_charts_routes(app: FastAPI, builder: WorkflowBuilder) -> None:
    """Register ``POST /api/v1/incidents/charts``.

    The route is always mounted. Profiles that don't configure the ``chart_generator`` tool get a
    501 at request time (the tool is resolved per request), so unconditional registration is safe.
    """
    try:
        app.include_router(create_incident_charts_router(builder))
        logger.info("Registered POST /api/v1/incidents/charts")
    except Exception as exc:
        logger.error("Failed to register incident charts route: %s", exc, exc_info=True)
        raise
