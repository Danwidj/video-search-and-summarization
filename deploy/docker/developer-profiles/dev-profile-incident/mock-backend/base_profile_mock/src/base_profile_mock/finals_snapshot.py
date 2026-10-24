# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Mock search and chat content built from a snapshot of the finals database.

finals_snapshot.json copies the AI revisions the finals database holds, so the mock's
search, chat and Find evidence answer about clips that are really indexed there.
The snapshot is static: refresh it with the query in this package's README.
"""

from __future__ import annotations

from functools import cache
import json
from pathlib import Path
from typing import Any

_SNAPSHOT_PATH = Path(__file__).with_name("finals_snapshot.json")


@cache
def _revisions() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))["revisions"])


def query_tokens(query: str) -> list[str]:
    return [tok for tok in query.lower().replace("?", " ").replace(",", " ").split() if len(tok) > 2]


def match_score(tokens: list[str], text: str) -> float:
    """Share of query tokens found in text; with no usable tokens every text matches."""
    if not tokens:
        return 1.0
    lowered = text.lower()
    found = sum(1 for tok in tokens if tok in lowered or (len(tok) > 3 and tok.rstrip("s") in lowered))
    return round(found / len(tokens), 2)


def evidence_hits() -> list[dict[str, Any]]:
    """One evidence hit per finals item, shaped like search-contract-v1 hits (without a score)."""
    hits: list[dict[str, Any]] = []
    for rev in _revisions():
        video_id = rev["video_id"]
        model_run_id = rev["model_run_id"]
        inc = rev["incident"]
        incident = {
            "incident_id": video_id,
            "model_run_id": model_run_id,
            "incident_type": inc["incident_type"],
            "severity_level": inc["severity_level"],
            "title": inc["title"],
            "description": inc["description"],
            "playback_url": f"https://pub-r2.example.com/videos/{video_id}.mp4",
            "incident_window": [float(inc["start_seconds"]), float(inc["end_seconds"])],
        }
        for item in rev["items"]:
            crop_url = f"https://pub-r2.example.com/evidence/{video_id}/{model_run_id}/{item['item_type']}/{item['item_id']}.jpg"
            hits.append(
                {
                    "item": {**item, "crop_image_url": crop_url, "bounding_box": None},
                    "incident": incident,
                    "critic": {
                        "verdict": "confirmed",
                        "confidence": 0.9,
                        "rationale": "Mock critic verdict: no crop was reviewed.",
                    },
                }
            )
    return hits


def revision_hits() -> list[dict[str, Any]]:
    """One saved-revision hit per finals AI revision, shaped like the agent's RevisionSearchHit."""
    hits: list[dict[str, Any]] = []
    for rev in _revisions():
        inc = rev["incident"]
        hits.append(
            {
                "revision_id": rev["revision_id"],
                "video_id": rev["video_id"],
                "revision_no": rev["revision_no"],
                "kind": "ai",
                "model_run_id": rev["model_run_id"],
                "title": inc["title"],
                "description": inc["description"],
                "incident_type": inc["incident_type"],
                "severity_level": inc["severity_level"],
                "start_seconds": inc["start_seconds"],
                "end_seconds": inc["end_seconds"],
            }
        )
    return hits
