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

"""One-time, idempotent Postgres seed for the Tier 1 GT-evaluation demo.

Seeds ``gt_*`` rows for 5 real, video-backed incidents drawn from
``fixtures/data/*.csv`` (the same ground-truth-quality CSV content
``scripts/seed_data.py`` imports under ``MR-SEED``), plus one deterministically
perturbed ``incidents``/``entities``/``instruments``/``assets`` row set under a
dedicated ``MR-EVAL-DEMO`` model run - so the GT evaluation section on the
report-detail page (``eval_gt.run_evaluation``) has something meaningful to
score without needing a live VLM pass or the real mock-backend
``/analyze`` route.

Never run on startup; run it by hand once ``INCIDENT_DB_DSN`` is configured
(see incident-console/README.md)::

    uv run python scripts/seed_gt_demo.py

Each incident below is deliberately built to exercise one of the scenarios the
Tier 1 evaluation spec calls out, so a single click through the 5 seeded
incidents' "Run GT Evaluation" sections demonstrates every code path:

- ``Burglary001`` - reworded-but-equivalent description + a start timestamp
  inside tolerance + a correct (matching) severity: everything passes.
- ``Burglary002`` - a start timestamp shifted well outside tolerance.
- ``Burglary003`` - a semantically-similar-but-differently-worded entity
  description, matched by the embedding endpoint despite the wording.
- ``Burglary004`` - a fabricated extra model entity with no GT counterpart
  (false positive).
- ``Burglary007`` - the model output omits the GT asset entirely
  (false negative).

GT content (types, descriptions, entities/instruments/assets) is taken
verbatim or lightly restructured from the real CSV rows; severity levels are
not present for these burglary rows in the CSV, so a fixed demo value is
assigned per incident (documented inline) purely to give the severity
comparison something to score.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402  (loads .env / .env.local before anything reads it)
from db import IncidentDB  # noqa: E402

MODEL_RUN_ID = "MR-EVAL-DEMO"
MODEL_NAME = "eval-demo-perturbed"
MODEL_VERSION = None
PROMPT_VERSION = None


def _r2_key(filename: str) -> str:
    return f"anomaly/burglary/{filename}"


# Each entry pairs one real CSV-backed GT incident with a deterministically
# perturbed model-output incident under MODEL_RUN_ID.
INCIDENTS = [
    {
        # Scenario: reworded-but-equivalent description, timestamp within
        # tolerance (start off by 3s; config.EVAL_TIMESTAMP_TOLERANCE_SECONDS
        # defaults to 5s), correct/matching severity.
        "incident_id": "Burglary001",
        "filename": "Burglary001_x264.mp4",
        "video_duration": 130,
        "gt": {
            "type": "burglary",
            "start": "00:00:08",
            "end": "00:01:57",
            "duration": 109,
            "description": (
                "a van/suv crashed into the shop, 2 men came out of the vehicle to shift the atm "
                "from the store to their vehicle and drove off"
            ),
            "severity": 3,
            "entities": [
                {"entity_id": "GE1", "type": "human", "description": "a person in purple hoodie"},
                {"entity_id": "GE2", "type": "human", "description": "a person in black shirt, blue jeans"},
            ],
            "instruments": [],
            "assets": [{"asset_id": "GA1", "name": "atm", "description": "atm was carried away by the entities"}],
        },
        "model": {
            "type": "burglary",
            "start": "00:00:11",  # +3s, inside the default 5s tolerance
            "end": "00:01:57",
            "duration": 109,
            "description": (
                "a van or suv crashed into the shop and two men came out of the vehicle to move the atm "
                "from the store into their vehicle before driving off"
            ),
            "severity": 3,
            "confidence": 0.8,
            "entities": [
                {"entity_id": "E1", "type": "human", "description": "a person wearing a purple hoodie"},
                {"entity_id": "E2", "type": "human", "description": "individual in a black shirt and blue jeans"},
            ],
            "instruments": [],
            "assets": [{"asset_id": "A1", "name": "atm", "description": "the atm was carried away by the men"}],
        },
    },
    {
        # Scenario: start timestamp shifted well outside tolerance (+20s).
        "incident_id": "Burglary002",
        "filename": "Burglary002_x264.mp4",
        "video_duration": 110,
        "gt": {
            "type": "burglary",
            "start": "00:00:04",
            "end": "00:01:37",
            "duration": 93,
            "description": "a guy sneaked into the building, took items from the fridge and left",
            "severity": 2,
            "entities": [
                {
                    "entity_id": "GE1",
                    "type": "human",
                    "description": "a guy wearing white clothes, with a shirt covering his head",
                }
            ],
            "instruments": [],
            "assets": [{"asset_id": "GA1", "name": "fridge", "description": "items were stolen from the fridge"}],
        },
        "model": {
            "type": "burglary",
            "start": "00:00:24",  # +20s, well outside the default 5s tolerance
            "end": "00:01:37",
            "duration": 93,
            "description": "a man entered the building quietly, removed items from the fridge, then left",
            "severity": 2,
            "confidence": 0.75,
            "entities": [
                {
                    "entity_id": "E1",
                    "type": "human",
                    "description": "man wearing white clothes with a shirt covering his head",
                }
            ],
            "instruments": [],
            "assets": [{"asset_id": "A1", "name": "fridge", "description": "items were stolen from the fridge"}],
        },
    },
    {
        # Scenario: semantically similar entity description matched despite
        # very different wording.
        "incident_id": "Burglary003",
        "filename": "Burglary003_x264.mp4",
        "video_duration": 60,
        "gt": {
            "type": "burglary",
            "start": "00:00:00",
            "end": "00:00:39",
            "duration": 39,
            "description": "a guy taking items from a container with a crowbar in his hand",
            "severity": 2,
            "entities": [
                {"entity_id": "GE1", "type": "human", "description": "a bearded guy wearing a long sleeved top"}
            ],
            "instruments": [{"instrument_id": "GI1", "name": "crowbar", "description": "average sized crowbar"}],
            "assets": [{"asset_id": "GA1", "name": "boxes", "description": "small rectangular boxes"}],
        },
        "model": {
            "type": "burglary",
            "start": "00:00:00",
            "end": "00:00:39",
            "duration": 39,
            "description": "a man pries open a storage container and removes items using a metal bar",
            "severity": 2,
            "confidence": 0.7,
            "entities": [
                # Reworded from GE1's "bearded guy wearing a long sleeved top" -
                # a single synonym swap ("guy" -> "man"), matched via embedding
                # cosine similarity rather than exact string overlap.
                {"entity_id": "E1", "type": "human", "description": "a bearded man wearing a long sleeved top"}
            ],
            "instruments": [{"instrument_id": "I1", "name": "crowbar", "description": "medium sized crowbar"}],
            "assets": [{"asset_id": "A1", "name": "boxes", "description": "small rectangular cardboard boxes"}],
        },
    },
    {
        # Scenario: one fabricated extra model entity with no GT counterpart
        # (false positive).
        "incident_id": "Burglary004",
        "filename": "Burglary004_x264.mp4",
        "video_duration": 90,
        "gt": {
            "type": "burglary",
            "start": "00:00:03",
            "end": "00:00:56",
            "duration": 53,
            "description": (
                "an suv crashed into the store, 3 men came out of the suv to carry an atm back to "
                "their vehicle and drove off"
            ),
            "severity": 3,
            "entities": [
                {
                    "entity_id": "GE1",
                    "type": "human",
                    "description": "a guy wearing black jacket with long pants and orange beanie",
                },
                {"entity_id": "GE2", "type": "human", "description": "a guy wearing grey hoodie and sweatpants"},
                {"entity_id": "GE3", "type": "human", "description": "a guy wearing grey hoodie and black pants"},
            ],
            "instruments": [{"instrument_id": "GI1", "name": "suv", "description": "green suv, 6 seater"}],
            "assets": [{"asset_id": "GA1", "name": "atm", "description": "atm was carried away by the entities"}],
        },
        "model": {
            "type": "burglary",
            "start": "00:00:03",
            "end": "00:00:56",
            "duration": 53,
            "description": "an suv struck the storefront and three men carried an atm to the vehicle before leaving",
            "severity": 3,
            "confidence": 0.72,
            "entities": [
                {
                    "entity_id": "E1",
                    "type": "human",
                    "description": "man in a black jacket, long pants and orange beanie",
                },
                {"entity_id": "E2", "type": "human", "description": "man in a grey hoodie and sweatpants"},
                {"entity_id": "E3", "type": "human", "description": "man in a grey hoodie and black pants"},
                # Fabricated: no GT counterpart at all -> unmatched model row (FP).
                {"entity_id": "E4", "type": "human", "description": "a bystander filming the scene on a phone"},
            ],
            "instruments": [{"instrument_id": "I1", "name": "suv", "description": "green 6 seater suv"}],
            "assets": [{"asset_id": "A1", "name": "atm", "description": "the atm was carried away by the men"}],
        },
    },
    {
        # Scenario: the model output omits a GT asset entirely (false negative).
        "incident_id": "Burglary007",
        "filename": "Burglary007_x264.mp4",
        "video_duration": 55,
        "gt": {
            "type": "burglary",
            "start": "00:00:00",
            "end": "00:00:34",
            "duration": 34,
            "description": (
                "2 entities standing outside the store, while a truck was used to break the door, 1 entity "
                "used a rope to attach an atm within the store to the truck. the truck then pulled the atm "
                "away while the 2 entities ran away"
            ),
            "severity": 3,
            "entities": [
                {"entity_id": "GE1", "type": "human", "description": "a guy wearing white top and blue jeans"},
                {"entity_id": "GE2", "type": "human", "description": "a guy wearing black top and black pants"},
            ],
            "instruments": [
                {"instrument_id": "GI1", "name": "crowbar", "description": "average sized crowbar"},
                {"instrument_id": "GI2", "name": "truck", "description": "white truck"},
                {"instrument_id": "GI3", "name": "rope", "description": "thick rope attached to truck"},
            ],
            "assets": [{"asset_id": "GA1", "name": "atm", "description": "atm was towed away by the truck"}],
        },
        "model": {
            "type": "burglary",
            "start": "00:00:00",
            "end": "00:00:34",
            "duration": 34,
            "description": (
                "two people wait outside while a truck breaks the door open; one attaches a rope from the "
                "truck to the atm inside, and the truck pulls it away as the two run off"
            ),
            "severity": 3,
            "confidence": 0.69,
            "entities": [
                {"entity_id": "E1", "type": "human", "description": "man in a white top and blue jeans"},
                {"entity_id": "E2", "type": "human", "description": "man in a black top and black pants"},
            ],
            "instruments": [
                {"instrument_id": "I1", "name": "truck", "description": "white pickup truck"},
                {"instrument_id": "I2", "name": "rope", "description": "thick rope attached to the truck"},
            ],
            # No asset row at all - the model never reports the atm (FN).
            "assets": [],
        },
    },
]


def seed(database: IncidentDB) -> dict[str, int]:
    """Apply the seed and return the resulting row counts."""
    counts = {
        "videos": 0,
        "model_runs": 0,
        "gt_incidents": 0,
        "gt_entities": 0,
        "gt_instruments": 0,
        "gt_assets": 0,
        "incidents": 0,
        "entities": 0,
        "instruments": 0,
        "assets": 0,
    }

    database.insert_model_run(
        MODEL_RUN_ID, model_name=MODEL_NAME, model_version=MODEL_VERSION, prompt_version=PROMPT_VERSION
    )
    counts["model_runs"] = 1

    for incident in INCIDENTS:
        incident_id = incident["incident_id"]
        gt, model = incident["gt"], incident["model"]

        database.upsert_video(incident_id, filepath=_r2_key(incident["filename"]), duration=incident["video_duration"])
        counts["videos"] += 1

        database.insert_gt_incident(
            incident_id,
            fields={
                "type": gt["type"],
                "start_timestamp": gt["start"],
                "end_timestamp": gt["end"],
                "duration": gt["duration"],
                "description": gt["description"],
                "severity_level": gt["severity"],
                "labelled_by": "seed_gt_demo.py",
            },
        )
        counts["gt_incidents"] += 1
        for entity in gt["entities"]:
            database.add_gt_entity(
                incident_id, entity_id=entity["entity_id"], type=entity["type"], description=entity["description"]
            )
            counts["gt_entities"] += 1
        for instrument in gt["instruments"]:
            database.add_gt_instrument(
                incident_id,
                instrument_id=instrument["instrument_id"],
                name=instrument["name"],
                description=instrument["description"],
            )
            counts["gt_instruments"] += 1
        for asset in gt["assets"]:
            database.add_gt_asset(
                incident_id, asset_id=asset["asset_id"], name=asset["name"], description=asset["description"]
            )
            counts["gt_assets"] += 1

        database.insert_incident(
            incident_id,
            MODEL_RUN_ID,
            fields={
                "type": model["type"],
                "start_timestamp": model["start"],
                "end_timestamp": model["end"],
                "duration": model["duration"],
                "description": model["description"],
                "severity_level": model["severity"],
                "confidence_score": model["confidence"],
            },
        )
        counts["incidents"] += 1
        database.clear_incident_evidence(incident_id, MODEL_RUN_ID)
        for entity in model["entities"]:
            database.add_incident_entity(
                incident_id,
                MODEL_RUN_ID,
                entity_id=entity["entity_id"],
                type=entity["type"],
                description=entity["description"],
            )
            counts["entities"] += 1
        for instrument in model["instruments"]:
            database.add_incident_instrument(
                incident_id,
                MODEL_RUN_ID,
                instrument_id=instrument["instrument_id"],
                name=instrument["name"],
                description=instrument["description"],
            )
            counts["instruments"] += 1
        for asset in model["assets"]:
            database.add_incident_asset(
                incident_id,
                MODEL_RUN_ID,
                asset_id=asset["asset_id"],
                name=asset["name"],
                description=asset["description"],
            )
            counts["assets"] += 1

    return counts


def main() -> int:
    dsn = config.incident_db_dsn()
    if not dsn:
        print(
            "INCIDENT_DB_DSN is not set. Put the DSN in incident-console/.env.local (git-ignored) and re-run.",
            file=sys.stderr,
        )
        return 1
    database = IncidentDB.from_dsn(dsn)
    database.init_schema()
    counts = seed(database)
    print("GT evaluation demo seed complete:")
    for name, value in counts.items():
        print(f"  {name:14s} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
