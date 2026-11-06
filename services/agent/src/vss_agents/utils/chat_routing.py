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

"""Which route a question about one report takes in ``routed`` chat mode. Pure: no model, no input but the question.

- **deterministic:** a question that asks only for a kind of report field is composed by code
  (:func:`vss_agents.utils.report_answers.compose`), with no model call.
- **report_llm:** anything that names something, reasons, leans on the conversation or points at one moment goes to the
  chat model, which reads the report only.

A question never reaches the video from here. The router only says whether a check of the video may be *offered*:
always when the question asks for one or disputes the report, never for a motive (footage cannot show it), and
otherwise only when the answer turns out to lack a visible detail. The reviewer's confirmation runs it.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from vss_agents.utils import report_answers

Route = Literal["deterministic", "report_llm"]
VideoOffer = Literal["always", "if_missing", "never"]

_ASKS_FOR_VIDEO = re.compile(
    r"\b(?:check|verify|look at|inspect|review|watch|re-?watch|re-?analy[sz]e)\b.*\b(?:video|footage|clip|recording)\b"
    r"|\b(?:video|footage|clip|recording)\b.*\b(?:show|shows|showed|actually)\b"
)
_DISPUTES_REPORT = re.compile(
    r"\bactually\b|\breally\b|\bare you sure\b|\bdouble.?check\b|\bmisidentif"
    r"|\b(?:is|was) (?:that|this|it|the report) (?:right|correct|true|accurate)\b"
    r"|\breport\b.*\b(?:wrong|mistaken|incorrect|inaccurate)\b"
)
_ABOUT_THE_REPORT = re.compile(r"\b(?:classif|rated|rating|severity|label|marked|called|reported)")
_MOTIVE = re.compile(r"^\s*why\b|\bmotive\b|\bintent(?:ion)?s?\b|\bwhat made\b")


@dataclass(frozen=True)
class Decision:
    route: Route
    reason: str
    video: VideoOffer


def decide(question: str, view: report_answers.ReportView) -> Decision:
    """The route of one question about one report version, and whether a video check may be offered."""
    q = question.lower()
    if _ASKS_FOR_VIDEO.search(q):
        return Decision("report_llm", "asks_for_video", "always")
    if _DISPUTES_REPORT.search(q):
        return Decision("report_llm", "disputes_report", "always")
    if _MOTIVE.search(q) and not _ABOUT_THE_REPORT.search(q):
        return Decision("report_llm", "motive", "never")
    if report_answers.is_plain(question, view):
        return Decision("deterministic", "report_field", "if_missing")
    return Decision("report_llm", "needs_reading", "if_missing")
