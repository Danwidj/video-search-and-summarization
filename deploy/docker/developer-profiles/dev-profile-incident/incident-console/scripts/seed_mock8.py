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

"""One-time, idempotent Postgres seed for the captain's 8-video custom demo set.

This restores a small hand-authored demo set that existed under the old
(pre-multi-model-run) database structure and was lost when that schema was
replaced (see db.py's module docstring). It is a separate, independent seed
from ``scripts/seed_supabase.py`` (the 72-row ground-truth CSV import): the
two datasets never merge, and one never depends on the other. This set is
seeded under its own ``model_run_id`` (``MOCK8``) precisely so the ground-truth
reseed (``MR-SEED``) can never collide with or overwrite it.

The 8 clips are the captain's own R2 uploads under the ``normal_videos/``
prefix in the ``anomaly-detection-dataset`` bucket (verified live via
``list_objects_v2``, distinct from that same prefix's ~1900
``Normal_Videos*_x264.mp4`` objects, which belong to the original dataset and
are not used here). Each incident below is linked to exactly the one clip its
description is written about - see the PR description for the full
incident_id -> R2 key list. All content is fabricated for demo purposes (no
real event occurred), consistent in style (short, objective, lowercase) with
the ground-truth set's descriptions.

Run it by hand once the DSN is configured (see incident-console/README.md):

    uv run python scripts/seed_mock8.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402  (loads .env / .env.local before anything reads it)
from db import IncidentDB  # noqa: E402

MODEL_RUN_ID = "MOCK8"
MODEL_NAME = "captain-demo-set"
MODEL_VERSION = None
PROMPT_VERSION = None

# One entry per captain-uploaded clip. `video_duration` is a rough estimate
# (no ffprobe available in this environment) purely to give the player a
# sane total length; `start`/`end` sit safely inside it.
INCIDENTS = [
    {
        "incident_id": "MOCK-WarehouseSafety01",
        "filename": "warehouse_safety_0001.mp4",
        "type": "warehouse safety",
        "start": "00:00:03",
        "end": "00:00:18",
        "duration": 15,
        "video_duration": 45,
        "description": "a worker crosses the marked forklift lane on foot without making eye contact with the operator.",
        "severity": 3,
        "confidence": 0.81,
        "entities": [
            {"entity_id": "E1", "type": "human", "description": "forklift operator, seated, hands on the controls"},
            {"entity_id": "E2", "type": "human", "description": "pedestrian worker walking through the forklift lane"},
        ],
        "instruments": [
            {
                "instrument_id": "I1",
                "entity_id": "E1",
                "name": "forklift",
                "description": "counterbalance forklift carrying a loaded pallet",
                "threat_level": 3,
            }
        ],
        "assets": [{"asset_id": "A1", "name": "pallet load", "description": "wrapped pallet raised on the forks"}],
    },
    {
        "incident_id": "MOCK-WarehouseSafety02",
        "filename": "warehouse_safety_0002.mp4",
        "type": "warehouse safety",
        "start": "00:00:05",
        "end": "00:00:22",
        "duration": 17,
        "video_duration": 55,
        "description": "a worker climbs open warehouse shelving to reach a top-level box instead of using a ladder.",
        "severity": 2,
        "confidence": 0.74,
        "entities": [{"entity_id": "E1", "type": "human", "description": "warehouse worker in a hi-vis vest"}],
        "instruments": [],
        "assets": [{"asset_id": "A1", "name": "storage rack", "description": "multi-level steel shelving unit"}],
    },
    {
        "incident_id": "MOCK-WarehouseOps01",
        "filename": "warehouse_sample.mp4",
        "type": "warehouse safety",
        "start": "00:00:04",
        "end": "00:00:20",
        "duration": 16,
        "video_duration": 90,
        "description": "a pallet jack is left blocking a marked fire exit aisle during a shift changeover.",
        "severity": 2,
        "confidence": None,
        "entities": [
            {"entity_id": "E1", "type": "human", "description": "warehouse worker walking past the blocked aisle"}
        ],
        "instruments": [],
        "assets": [
            {"asset_id": "A1", "name": "pallet jack", "description": "manual pallet jack left unattended in the aisle"}
        ],
    },
    {
        "incident_id": "MOCK-LadderSafety01",
        "filename": "sample-warehouse-ladder.mp4",
        "type": "warehouse safety",
        "start": "00:00:06",
        "end": "00:00:24",
        "duration": 18,
        "video_duration": 60,
        "description": "a worker stands on the top rung of an extension ladder to reach an overhead shelf, with no spotter present.",
        "severity": 3,
        "confidence": 0.68,
        "entities": [{"entity_id": "E1", "type": "human", "description": "worker on the top rung of the ladder"}],
        "instruments": [
            {
                "instrument_id": "I1",
                "entity_id": None,
                "name": "extension ladder",
                "description": "aluminum extension ladder leaned against open shelving",
                "threat_level": None,
            }
        ],
        "assets": [],
    },
    {
        "incident_id": "MOCK-Conveyor01",
        "filename": "sample-sim-box-conveyor.mp4",
        "type": "equipment",
        "start": "00:00:02",
        "end": "00:00:14",
        "duration": 12,
        "video_duration": 40,
        "description": "a box jams at a conveyor transfer point and a worker reaches into the roller line to clear it while the belt is still moving.",
        "severity": 3,
        "confidence": 0.77,
        "entities": [
            {"entity_id": "E1", "type": "human", "description": "worker reaching into the active conveyor line"}
        ],
        "instruments": [
            {
                "instrument_id": "I1",
                "entity_id": None,
                "name": "conveyor belt",
                "description": "powered roller conveyor, running during the clearance",
                "threat_level": 2,
            }
        ],
        "assets": [
            {"asset_id": "A1", "name": "jammed box", "description": "cardboard box wedged at the transfer point"}
        ],
    },
    {
        "incident_id": "MOCK-Jaywalking01",
        "filename": "sample-sim-jaywalking.mp4",
        "type": "pedestrian",
        "start": "00:00:03",
        "end": "00:00:16",
        "duration": 13,
        "video_duration": 50,
        "description": "a pedestrian crosses mid-block against moving traffic instead of using the marked crosswalk.",
        "severity": 2,
        "confidence": 0.7,
        "entities": [
            {"entity_id": "E1", "type": "human", "description": "pedestrian crossing outside the marked crosswalk"}
        ],
        "instruments": [
            {
                "instrument_id": "I1",
                "entity_id": None,
                "name": "passing vehicle",
                "description": "sedan approaching the crossing point",
                "threat_level": None,
            }
        ],
        "assets": [],
    },
    {
        "incident_id": "MOCK-Traffic01",
        "filename": "sample-sim-traffic.mp4",
        "type": "traffic",
        "start": "00:00:04",
        "end": "00:00:19",
        "duration": 15,
        "video_duration": 45,
        "description": "two vehicles follow each other too closely through a signalized intersection during a yellow-light phase.",
        "severity": 2,
        "confidence": None,
        "entities": [],
        "instruments": [
            {
                "instrument_id": "I1",
                "entity_id": None,
                "name": "lead vehicle",
                "description": "sedan entering the intersection on yellow",
                "threat_level": 3,
            },
            {
                "instrument_id": "I2",
                "entity_id": None,
                "name": "following vehicle",
                "description": "suv tailgating the lead vehicle through the intersection",
                "threat_level": 3,
            },
        ],
        "assets": [],
    },
    {
        "incident_id": "MOCK-BridgeInspection01",
        "filename": "sample-drone-bridge.mp4",
        "type": "structural",
        "start": "00:00:08",
        "end": "00:00:30",
        "duration": 22,
        "video_duration": 120,
        "description": "a drone inspection pass shows a section of exposed rebar and surface cracking on a bridge support pier.",
        "severity": 3,
        "confidence": 0.65,
        "entities": [],
        "instruments": [],
        "assets": [
            {
                "asset_id": "A1",
                "name": "support pier",
                "description": "concrete pier with visible cracking and exposed rebar",
            }
        ],
    },
]


def seed(database: IncidentDB) -> dict[str, int]:
    """Apply the seed and return the resulting row counts for the mock set."""
    counts = {"videos": 0, "model_runs": 0, "incidents": 0, "entities": 0, "instruments": 0, "assets": 0}

    database.insert_model_run(
        MODEL_RUN_ID, model_name=MODEL_NAME, model_version=MODEL_VERSION, prompt_version=PROMPT_VERSION
    )
    counts["model_runs"] = 1

    for incident in INCIDENTS:
        database.upsert_video(
            incident["incident_id"],
            filepath=f"normal_videos/{incident['filename']}",
            duration=incident["video_duration"],
        )
        counts["videos"] += 1

        database.insert_incident(
            incident["incident_id"],
            MODEL_RUN_ID,
            fields={
                "type": incident["type"],
                "start_timestamp": incident["start"],
                "end_timestamp": incident["end"],
                "duration": incident["duration"],
                "description": incident["description"],
                "severity_level": incident["severity"],
                "confidence_score": incident["confidence"],
            },
        )
        counts["incidents"] += 1
        database.clear_incident_evidence(incident["incident_id"], MODEL_RUN_ID)

        for entity in incident["entities"]:
            database.add_incident_entity(
                incident["incident_id"],
                MODEL_RUN_ID,
                entity_id=entity["entity_id"],
                type=entity["type"],
                description=entity["description"],
            )
            counts["entities"] += 1

        for instrument in incident["instruments"]:
            database.add_incident_instrument(
                incident["incident_id"],
                MODEL_RUN_ID,
                instrument_id=instrument["instrument_id"],
                entity_id=instrument["entity_id"],
                name=instrument["name"],
                description=instrument["description"],
                threat_level=instrument["threat_level"],
            )
            counts["instruments"] += 1

        for asset in incident["assets"]:
            database.add_incident_asset(
                incident["incident_id"],
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
            "INCIDENT_DB_DSN is not set. Put the Postgres DSN in incident-console/.env.local (git-ignored) and re-run.",
            file=sys.stderr,
        )
        return 1
    database = IncidentDB.from_dsn(dsn)
    database.init_schema()
    counts = seed(database)
    print("Mock-8 seed complete:")
    for name, value in counts.items():
        print(f"  {name:12s} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
