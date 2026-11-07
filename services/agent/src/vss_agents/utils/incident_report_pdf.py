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

"""Render an incident report Markdown to a PDF in the VSS look.

The pipeline is the one VSS uses for its own reports (``video_report_gen._convert_markdown_to_pdf``): Markdown to
HTML with the ``tables`` and ``fenced_code`` extensions, a fixed stylesheet around it, then ``xhtml2pdf``. Images are
fetched here, on the server, and embedded as data URIs, so the PDF never depends on a URL the PDF renderer would fetch
itself. A URL is never logged: failures name the image's position in the report, not its address.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from html import escape
import io
import logging
import re

import httpx
import markdown as markdown_lib
from xhtml2pdf import pisa

logger = logging.getLogger(__name__)

# httpx logs every request URL at INFO and httpcore logs the host at DEBUG. The image URLs are signed, so their
# query strings must never reach the logs: these loggers stay at WARNING while this module is loaded.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_TIMEOUT_SECONDS = 15.0
_IMAGE_PATTERN = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)\s]+)\)")

# The report stylesheet: A4 portrait with 15 mm margins and 11 pt type, the console's primary green as the accent with a thin
# rule under each section heading, and a running header and footer on every page (page X of Y from xhtml2pdf's counters).
ACCENT = "#174f3b"
VSS_STYLESHEET = """
body { font-family: Helvetica, Arial, sans-serif; font-size: 11pt; color: #12211b; line-height: 1.4; }
h1 { font-size: 18pt; margin: 0 0 10px; }
h2 { font-size: 13pt; margin: 16px 0 6px; padding-bottom: 3px; border-bottom: 0.75pt solid ACCENT; }
h3 { font-size: 11.5pt; font-weight: bold; margin: 12px 0 4px; }
p { text-align: left; margin: 0 0 8px; }
table { width: 100%; border-collapse: collapse; margin: 4px 0 10px; }
th, td { border: 0.4pt solid #b8c2bc; padding: 4px 6px; vertical-align: top; text-align: left; }
th { background-color: #eef3ef; }
img { width: 60mm; }
em { color: #5b6761; }
""".replace("ACCENT", ACCENT)
PAGE_SETUP = """
@page {
  size: a4 portrait;
  margin: 22mm 15mm 18mm 15mm;
  @frame header { -pdf-frame-content: header; top: 6mm; margin-left: 15mm; margin-right: 15mm; height: 8mm; }
  @frame footer { -pdf-frame-content: footer; bottom: 6mm; margin-left: 15mm; margin-right: 15mm; height: 8mm; }
}
"""


@dataclass(frozen=True)
class ImageRef:
    alt: str
    url: str


def image_refs(markdown_text: str) -> list[ImageRef]:
    """Every image in the Markdown, in order, with its alt text."""
    return [
        ImageRef(alt=match.group("alt"), url=match.group("url")) for match in _IMAGE_PATTERN.finditer(markdown_text)
    ]


async def fetch_image(client: httpx.AsyncClient, url: str) -> bytes | None:
    """The image's bytes, or ``None`` when it cannot be fetched or is too large. The URL is never logged."""
    try:
        async with client.stream("GET", url, timeout=IMAGE_TIMEOUT_SECONDS) as response:
            if response.status_code != 200:
                return None
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
    except httpx.HTTPError:
        return None


def _data_uri(content: bytes) -> str:
    mime = "image/png" if content.startswith(b"\x89PNG") else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"


def markdown_to_html(markdown_text: str, images: dict[str, bytes | None]) -> str:
    """The report's HTML body. An image that was not fetched becomes a plain note, so the PDF still builds."""

    def swap(match: re.Match[str]) -> str:
        url = match.group("url")
        alt = match.group("alt")
        content = images.get(url)
        if content is None:
            return f"*Snapshot unavailable{': ' + alt if alt else ''}.*"
        return f"![{alt}]({_data_uri(content)})"

    body = _IMAGE_PATTERN.sub(swap, markdown_text)
    return markdown_lib.markdown(body, extensions=["tables", "fenced_code"])


def html_document(body: str, running_header: str, footer: str) -> str:
    header = escape(running_header, quote=False)
    foot = escape(footer, quote=False)
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<style>{PAGE_SETUP}{VSS_STYLESHEET}</style></head><body>"
        f'<div id="header" style="font-size:8pt;color:{ACCENT};">{header}</div>'
        f'<div id="footer" style="font-size:8pt;color:#5b6761;">{foot} &middot; page <pdf:pagenumber /> of <pdf:pagecount /></div>'
        f"{body}</body></html>"
    )


def html_to_pdf(html: str) -> bytes:
    output = io.BytesIO()
    status = pisa.CreatePDF(html, dest=output, encoding="utf-8")
    if status.err:
        raise PdfRenderError(f"the PDF renderer reported {status.err} error(s)")
    return output.getvalue()


class PdfRenderError(Exception):
    """The Markdown could not be turned into a PDF."""


async def build_pdf(
    markdown_text: str, running_header: str, footer: str, client: httpx.AsyncClient
) -> tuple[bytes, int]:
    """The PDF for a report, and how many of its images could not be fetched."""
    refs = image_refs(markdown_text)
    fetched: dict[str, bytes | None] = {}
    for ref in refs:
        if ref.url not in fetched:
            fetched[ref.url] = await fetch_image(client, ref.url)
    missing = sum(1 for ref in refs if fetched.get(ref.url) is None)
    html = html_document(markdown_to_html(markdown_text, fetched), running_header, footer)
    return html_to_pdf(html), missing


def escape_text(value: str) -> str:
    return escape(value, quote=False)
