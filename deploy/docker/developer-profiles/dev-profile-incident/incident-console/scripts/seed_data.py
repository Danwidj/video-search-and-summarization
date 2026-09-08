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

"""The 8 fabricated incidents for the Supabase seed.

One incident per video clip the captain uploaded to the R2 bucket under
``normal_videos/``. The video/incident correspondence is loose and thematic
(captain's decision - no exact tally required); the link itself is a fixed
stored FK, set once by ``seed_supabase.py`` and never recomputed.

Everything here is fabricated -> ``is_synthetic = true`` throughout. Timestamps
are ``HH:MM:SS`` offsets inside each clip, kept between 0:02 and 0:25 so they
land inside even the shortest (25 s) clip. Descriptions follow the merged CSV
set's style: short, objective, lowercase. Threat levels follow the same rubric:
firearm/IED-class 5, blade 4, bat/pipe/vehicle 3, tool/bottle 2, bag/trolley 1;
road vehicles left blank where that fits.

``r2_key`` is the natural key: re-running the importer upserts on it.
"""

from __future__ import annotations

MODEL_VERSION = "mock-seed-v1"

# Probed clip lengths (seconds), stored on the videos row where known.
CLIP_DURATIONS = {
    "normal_videos/warehouse_safety_0001.mp4": 25,
    "normal_videos/warehouse_safety_0002.mp4": 30,
    "normal_videos/warehouse_sample.mp4": 210,
    "normal_videos/sample-warehouse-ladder.mp4": 135,
    "normal_videos/sample-sim-box-conveyor.mp4": 81,
    "normal_videos/sample-sim-jaywalking.mp4": 88,
    "normal_videos/sample-sim-traffic.mp4": 130,
    "normal_videos/sample-drone-bridge.mp4": 180,
}

INCIDENTS: list[dict] = [
    {
        "r2_key": "normal_videos/warehouse_safety_0001.mp4",
        "incident_type": "warehouse safety",
        "severity": 2,
        "confidence": 0.62,
        "incident_start": "00:00:04",
        "incident_end": "00:00:19",
        "description": (
            "a warehouse operator lifts a heavy carton from floor level with a rounded "
            "back and straight legs beside occupied pallet racking."
        ),
        "entities": [
            {"local_id": "E1", "type": "human", "description": "operator in a hi-vis vest and hard hat"},
        ],
        "instruments": [
            {
                "local_id": "I1",
                "entity_local_id": "E1",
                "name": "cardboard carton",
                "description": "oversized taped carton lifted two-handed",
                "threat_level": 1,
            },
        ],
        "assets": [
            {
                "local_id": "A1",
                "name": "pallet racking bay",
                "description": "loaded selective racking directly behind the lift",
            },
        ],
    },
    {
        "r2_key": "normal_videos/warehouse_safety_0002.mp4",
        "incident_type": "warehouse safety",
        "severity": 3,
        "confidence": None,
        "incident_start": "00:00:05",
        "incident_end": "00:00:22",
        "description": (
            "a worker on foot walks the length of a marked forklift lane without stopping "
            "at the pedestrian gate or checking for traffic."
        ),
        "entities": [
            {"local_id": "E1", "type": "human", "description": "worker on foot in the vehicle lane"},
            {"local_id": "E2", "type": "human", "description": "forklift operator approaching from the cross aisle"},
        ],
        "instruments": [
            {
                "local_id": "I1",
                "entity_local_id": "E2",
                "name": "counterbalance forklift",
                "description": "laden forklift sharing the aisle",
                "threat_level": 3,
            },
        ],
        "assets": [
            {
                "local_id": "A1",
                "name": "forklift traffic lane",
                "description": "yellow-taped shared pedestrian and vehicle lane",
            },
        ],
    },
    {
        "r2_key": "normal_videos/warehouse_sample.mp4",
        "incident_type": "equipment",
        "severity": 3,
        "confidence": 0.81,
        "incident_start": "00:00:08",
        "incident_end": "00:00:24",
        "description": (
            "a pallet stacked well above the safe load line leans against shelf uprights "
            "while a forklift manoeuvres beneath it."
        ),
        "entities": [
            {"local_id": "E1", "type": "human", "description": "forklift operator in the cab"},
        ],
        "instruments": [
            {
                "local_id": "I1",
                "entity_local_id": "E1",
                "name": "reach forklift",
                "description": "reach truck working under the leaning load",
                "threat_level": 3,
            },
            {
                "local_id": "I2",
                "entity_local_id": None,
                "name": "shrink-wrapped pallet load",
                "description": "overheight pallet with an unstable top tier",
                "threat_level": 1,
            },
        ],
        "assets": [
            {
                "local_id": "A1",
                "name": "storage shelving upright",
                "description": "rack upright taking the sideways load",
            },
            {"local_id": "A2", "name": "overloaded pallet", "description": "pallet stacked past the painted fill line"},
        ],
    },
    {
        "r2_key": "normal_videos/sample-warehouse-ladder.mp4",
        "incident_type": "warehouse safety",
        "severity": 4,
        "confidence": 0.55,
        "incident_start": "00:00:06",
        "incident_end": "00:00:20",
        "description": (
            "a worker stands on the top rung of an a-frame step ladder and overreaches to "
            "a high shelf with no spotter present."
        ),
        "entities": [
            {"local_id": "E1", "type": "human", "description": "worker balanced on the ladder top rung"},
        ],
        "instruments": [
            {
                "local_id": "I1",
                "entity_local_id": "E1",
                "name": "a-frame step ladder",
                "description": "lightweight ladder used above its top safe step",
                "threat_level": 2,
            },
        ],
        "assets": [
            {
                "local_id": "A1",
                "name": "upper storage shelf",
                "description": "out-of-reach shelf the worker is stretching for",
            },
        ],
    },
    {
        "r2_key": "normal_videos/sample-sim-box-conveyor.mp4",
        "incident_type": "equipment",
        "severity": 2,
        "confidence": 0.72,
        "incident_start": "00:00:03",
        "incident_end": "00:00:18",
        "description": (
            "a carton jams at a powered roller transfer and product backs up while the "
            "conveyor keeps running unattended."
        ),
        "entities": [
            {"local_id": "E1", "type": "human", "description": "line operator returning to the jam"},
            {"local_id": "E2", "type": "unknown", "description": "figure partly out of frame near the guard"},
        ],
        "instruments": [],
        "assets": [
            {
                "local_id": "A1",
                "name": "powered roller conveyor",
                "description": "driven roller line still running during the jam",
            },
            {"local_id": "A2", "name": "jammed carton", "description": "carton wedged across the transfer point"},
        ],
    },
    {
        "r2_key": "normal_videos/sample-sim-jaywalking.mp4",
        "incident_type": "pedestrian",
        "severity": 3,
        "confidence": 0.66,
        "incident_start": "00:00:05",
        "incident_end": "00:00:21",
        "description": (
            "a pedestrian crosses mid-block outside the marked crossing as vehicles approach in both directions."
        ),
        "entities": [
            {"local_id": "E1", "type": "human", "description": "pedestrian crossing mid-block"},
        ],
        "instruments": [
            {
                "local_id": "I1",
                "entity_local_id": None,
                "name": "approaching car",
                "description": "car closing on the crossing point",
                "threat_level": None,
            },
        ],
        "assets": [
            {"local_id": "A1", "name": "through road", "description": "two-way road with no crossing at that point"},
        ],
    },
    {
        "r2_key": "normal_videos/sample-sim-traffic.mp4",
        "incident_type": "traffic",
        "severity": 3,
        "confidence": None,
        "incident_start": "00:00:07",
        "incident_end": "00:00:23",
        "description": (
            "two vehicles brake hard and stop short of each other at an uncontrolled junction; no contact is seen."
        ),
        "entities": [
            {"local_id": "E1", "type": "human", "description": "driver of the lead vehicle"},
            {"local_id": "E2", "type": "human", "description": "driver of the second vehicle"},
        ],
        "instruments": [
            {
                "local_id": "I1",
                "entity_local_id": "E1",
                "name": "sedan",
                "description": "lead car braking into the junction",
                "threat_level": None,
            },
            {
                "local_id": "I2",
                "entity_local_id": "E2",
                "name": "delivery van",
                "description": "van braking hard behind the sedan",
                "threat_level": 3,
            },
        ],
        "assets": [
            {
                "local_id": "A1",
                "name": "uncontrolled junction",
                "description": "unsignalled crossroads with no give-way markings",
            },
        ],
    },
    {
        "r2_key": "normal_videos/sample-drone-bridge.mp4",
        "incident_type": "structural",
        "severity": 4,
        "confidence": 0.88,
        "incident_start": "00:00:10",
        "incident_end": "00:00:25",
        "description": (
            "a drone pass under a bridge span shows concrete spalling and exposed corroded "
            "reinforcement along a girder soffit."
        ),
        "entities": [
            {"local_id": "E1", "type": "unknown", "description": "no people present in the inspection pass"},
        ],
        "instruments": [],
        "assets": [
            {
                "local_id": "A1",
                "name": "bridge girder soffit",
                "description": "underside of the span with visible spalling",
            },
            {
                "local_id": "A2",
                "name": "exposed reinforcement bar",
                "description": "corroded rebar showing through lost cover concrete",
            },
        ],
    },
]


def _seconds(hhmmss: str) -> int:
    h, m, s = (int(p) for p in hhmmss.split(":"))
    return h * 3600 + m * 60 + s


def filename_for(r2_key: str) -> str:
    return r2_key.rsplit("/", 1)[-1]


def duration_sec_for(incident: dict) -> int:
    return _seconds(incident["incident_end"]) - _seconds(incident["incident_start"])
