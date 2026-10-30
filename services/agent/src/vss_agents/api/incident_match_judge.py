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

"""``POST /api/v1/incidents/match-judge`` - stateless match scoring endpoint.

Given a new video's analysis payload and a list of candidate incidents, returns per candidate
a score (0-1) and plain-language reasons. Touches no database and writes nothing.

Scoring rules (place and event type dominate):
- Event type match:  0.45 (hard fail if mismatch → 0.0)
- Location match:    0.40 (partial credit for partial location overlap)
- Time overlap:      0.15 bonus (only when both sides supply recorded times that overlap)

A type mismatch returns score 0.0 immediately; no other factors are considered.
Location matching is token-based (case-insensitive word overlap / Jaccard).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter
from fastapi import FastAPI
from pydantic import BaseModel
from pydantic import Field

logger = logging.getLogger(__name__)

# Weight constants
_WEIGHT_TYPE = 0.45
_WEIGHT_LOCATION = 0.40
_WEIGHT_TIME = 0.15


def _tokenise(text: str) -> set[str]:
    """Lower-case word tokens from a string; empty set for None/empty."""
    return set(re.findall(r"[a-z0-9]+", text.lower())) if text else set()


def _location_score(new_location: str | None, candidate_location: str | None) -> tuple[float, str, StructuredReason]:
    """Jaccard similarity on word tokens; returns (score, reason, structured reason)."""
    new_tokens = _tokenise(new_location or "")
    cand_tokens = _tokenise(candidate_location or "")
    if not new_tokens or not cand_tokens:
        return (
            0.5,
            "location not available for one or both sides - neutral",
            StructuredReason(kind="place_unknown", label="Place unknown", detail="No location on one or both sides"),
        )
    intersection = len(new_tokens & cand_tokens)
    union = len(new_tokens | cand_tokens)
    jaccard = intersection / union if union > 0 else 0.0
    detail = f"{new_location} / {candidate_location}"
    if jaccard >= 0.8:
        reason = f"locations match closely ({new_location!r} vs {candidate_location!r})"
        structured = StructuredReason(kind="same_place", label="Same place", detail=detail)
    elif jaccard >= 0.4:
        reason = f"locations partially overlap ({new_location!r} vs {candidate_location!r})"
        structured = StructuredReason(kind="similar_place", label="Similar place", detail=detail)
    elif jaccard > 0:
        reason = f"locations share only a few terms ({new_location!r} vs {candidate_location!r})"
        structured = StructuredReason(kind="different_place", label="Different place", detail=detail)
    else:
        reason = f"locations do not overlap ({new_location!r} vs {candidate_location!r})"
        structured = StructuredReason(kind="different_place", label="Different place", detail=detail)
    return jaccard, reason, structured


def _time_overlap_bonus(
    new_start: int | None,
    new_end: int | None,
    candidate_recorded_at_start: int | None,
    candidate_recorded_at_end: int | None,
) -> tuple[float, str | None, StructuredReason | None]:
    """Soft time-overlap bonus; returns (bonus, reason_or_None, structured_reason_or_None)."""
    if None in (new_start, new_end, candidate_recorded_at_start, candidate_recorded_at_end):
        return 0.0, None, None
    # Overlap check: [s1, e1] overlaps [s2, e2] iff s1 <= e2 and s2 <= e1
    if new_start <= candidate_recorded_at_end and candidate_recorded_at_start <= new_end:  # type: ignore[operator]
        return (
            1.0,
            "recorded times overlap",
            StructuredReason(kind="time_overlap", label="Time overlap", detail="Recorded times overlap"),
        )
    return (
        0.0,
        "recorded times do not overlap",
        StructuredReason(kind="time_apart", label="Different time", detail="Recorded times do not overlap"),
    )


def judge_candidate(
    new_incident_type: str,
    new_location: str | None,
    new_recorded_start: int | None,
    new_recorded_end: int | None,
    candidate: CandidateIncident,
) -> CandidateJudgement:
    """Score one candidate against the new video's analysis."""
    reasons: list[str] = []
    structured: list[StructuredReason] = []

    # Event type - dominant; mismatch short-circuits to 0
    candidate_type = (candidate.overview or {}).get("type", "")
    if candidate_type != new_incident_type:
        return CandidateJudgement(
            incident_id=candidate.incident_id,
            score=0.0,
            reasons=[f"event type mismatch: new video is {new_incident_type!r}, candidate is {candidate_type!r}"],
            structured_reasons=[
                StructuredReason(
                    kind="different_event_type",
                    label="Different event type",
                    detail=f"{new_incident_type} / {candidate_type}",
                )
            ],
        )
    reasons.append(f"event types match ({new_incident_type!r})")
    structured.append(StructuredReason(kind="same_event_type", label="Same event type", detail=new_incident_type))

    # Location
    candidate_location = (candidate.overview or {}).get("location")
    loc_score, loc_reason, loc_structured = _location_score(new_location, candidate_location)
    reasons.append(loc_reason)
    structured.append(loc_structured)

    # Time bonus
    time_bonus, time_reason, time_structured = _time_overlap_bonus(
        new_recorded_start,
        new_recorded_end,
        candidate.recorded_at_start,
        candidate.recorded_at_end,
    )
    if time_reason:
        reasons.append(time_reason)
    if time_structured:
        structured.append(time_structured)

    score = round(_WEIGHT_TYPE + _WEIGHT_LOCATION * loc_score + _WEIGHT_TIME * time_bonus, 4)
    return CandidateJudgement(
        incident_id=candidate.incident_id, score=score, reasons=reasons, structured_reasons=structured
    )


class CandidateIncident(BaseModel):
    """One candidate incident to score against."""

    incident_id: int = Field(..., description="Incident id from the database.")
    overview: dict[str, Any] | None = Field(
        default=None,
        description="The incident's overview block (same fields as the contract's incident block).",
    )
    video_names: list[str] = Field(default_factory=list, description="Names of videos that belong to this incident.")
    recorded_at_start: int | None = Field(
        default=None,
        description="Unix epoch seconds of the earliest recorded time among the incident's videos (optional).",
    )
    recorded_at_end: int | None = Field(
        default=None,
        description="Unix epoch seconds of the latest recorded time among the incident's videos (optional).",
    )


class MatchJudgeRequest(BaseModel):
    """Body for ``POST /api/v1/incidents/match-judge``."""

    analysis: dict[str, Any] = Field(
        ...,
        description=(
            "The new video's contract-valid analysis payload (incident-contract-v4, the payload field from "
            "video_analyses). Must contain at least analysis.incident.type and analysis.incident.location."
        ),
    )
    recorded_at_start: int | None = Field(
        default=None,
        description="Unix epoch seconds at which the new video's recording started (optional).",
    )
    recorded_at_end: int | None = Field(
        default=None,
        description="Unix epoch seconds at which the new video's recording ended (optional).",
    )
    candidates: list[CandidateIncident] = Field(..., min_length=1, description="Candidate incidents to score.")


class StructuredReason(BaseModel):
    """One comparison outcome, ready to render as a chip. Derived from the same comparison as ``reasons``."""

    kind: str = Field(
        ...,
        description=(
            "same_event_type, different_event_type, same_place, similar_place, different_place, place_unknown, "
            "time_overlap or time_apart."
        ),
    )
    label: str = Field(..., description="Short chip text, e.g. 'Same place'.")
    detail: str = Field(..., description="The compared values or a one-line explanation.")


class CandidateJudgement(BaseModel):
    """Score and reasons for one candidate."""

    incident_id: int
    score: float = Field(ge=0.0, le=1.0)
    reasons: list[str]
    structured_reasons: list[StructuredReason] = Field(
        default_factory=list,
        description="The same comparison as ``reasons`` as {kind, label, detail} entries. Additive; ``reasons`` is unchanged.",
    )


class MatchJudgeResponse(BaseModel):
    """Scores for every submitted candidate."""

    judgements: list[CandidateJudgement]


def create_incident_match_judge_router() -> APIRouter:
    """Build the ``POST /api/v1/incidents/match-judge`` router."""
    router = APIRouter()

    @router.post(
        "/api/v1/incidents/match-judge",
        summary="Score candidate incidents against a new video's analysis",
        tags=["Incident Match Judge"],
        response_model=MatchJudgeResponse,
    )
    async def match_judge(body: MatchJudgeRequest) -> MatchJudgeResponse:
        incident_block = (body.analysis or {}).get("incident", {})
        new_type: str = incident_block.get("type", "")
        new_location: str | None = incident_block.get("location")

        judgements = [
            judge_candidate(
                new_incident_type=new_type,
                new_location=new_location,
                new_recorded_start=body.recorded_at_start,
                new_recorded_end=body.recorded_at_end,
                candidate=candidate,
            )
            for candidate in body.candidates
        ]
        return MatchJudgeResponse(judgements=judgements)

    return router


def register_incident_match_judge_routes(app: FastAPI) -> None:
    """Register ``POST /api/v1/incidents/match-judge``."""
    try:
        app.include_router(create_incident_match_judge_router())
        logger.info("Registered POST /api/v1/incidents/match-judge")
    except Exception as exc:
        logger.error("Failed to register incident match-judge route: %s", exc, exc_info=True)
        raise
