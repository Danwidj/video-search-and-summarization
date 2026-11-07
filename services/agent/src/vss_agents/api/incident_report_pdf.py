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

"""``POST /api/v1/incidents/report-pdf`` - a report's Markdown rendered to a PDF in the VSS look.

The console builds the Markdown from the version the reviewer chose and posts it here. The agent fetches each image
itself, on the server, and returns the PDF. It stores nothing: the report is not changed and no file is kept.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Response
import httpx
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic.alias_generators import to_camel

from vss_agents.utils import incident_report_pdf

logger = logging.getLogger(__name__)

MAX_MARKDOWN_CHARS = 200_000
MAX_IMAGES = 80


class ReportPdfRequest(BaseModel):
    """The report's Markdown and the text of its running header and footer (camelCase on the wire)."""

    model_config = ConfigDict(extra="forbid", alias_generator=to_camel, populate_by_name=True)

    markdown: str = Field(..., min_length=1, max_length=MAX_MARKDOWN_CHARS)
    running_header: str = Field(default="Incident report", max_length=300)
    footer: str = Field(default="", max_length=300)


def create_incident_report_pdf_router() -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/v1/incidents/report-pdf",
        response_class=Response,
        responses={200: {"content": {"application/pdf": {}}}},
        summary="A report's Markdown rendered to a PDF in the VSS look (nothing is stored)",
        tags=["Incident Report"],
    )
    async def render_report_pdf(body: ReportPdfRequest) -> Response:
        if len(incident_report_pdf.image_refs(body.markdown)) > MAX_IMAGES:
            raise HTTPException(status_code=422, detail=f"A report has at most {MAX_IMAGES} images")
        async with httpx.AsyncClient(follow_redirects=False) as client:
            try:
                pdf, missing = await incident_report_pdf.build_pdf(
                    body.markdown, body.running_header, body.footer, client
                )
            except incident_report_pdf.PdfRenderError as exc:
                logger.error("Report PDF failed: %s", exc)
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        logger.info("Rendered a report PDF (%d bytes, %d image(s) unavailable)", len(pdf), missing)
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"X-Missing-Images": str(missing), "Cache-Control": "no-store"},
        )

    return router


def register_incident_report_pdf_routes(app: FastAPI) -> None:
    """Register ``POST /api/v1/incidents/report-pdf`` onto the FastAPI app."""
    app.include_router(create_incident_report_pdf_router())
    logger.info("Registered POST /api/v1/incidents/report-pdf")
