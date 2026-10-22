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

"""One-time, idempotent Postgres seed from ``fixtures/data/*.csv``.

Run it by hand once the DSN is configured (see incident-console/README.md):

    uv run python scripts/seed_supabase.py

It upserts one ``videos`` row per incident (natural key: the incident id -
identity rule is 1 video = 1 incident), one shared ``model_runs`` row
(``MR-SEED``), and each incident's model-output ``incidents`` / ``entities`` /
``instruments`` / ``assets`` rows. Re-running replaces the incident and its
evidence rows in place, so row counts do not grow. It never populates
``reports`` or ``queries`` - those stay reserved for a future
report-generation / query-submission workflow, out of scope here. Never
imported by the app and never runs on startup.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402  (loads .env / .env.local before anything reads it)
from db import IncidentDB  # noqa: E402
from scripts.seed_data import MODEL_NAME, MODEL_RUN_ID, MODEL_VERSION, PROMPT_VERSION, seed_rows  # noqa: E402


def seed(database: IncidentDB) -> dict[str, int]:
    """Apply the seed and return the resulting row counts for the seeded set."""
    data = seed_rows()
    counts = {"videos": 0, "model_runs": 0, "incidents": 0, "entities": 0, "instruments": 0, "assets": 0}
    # Known ground-truth gap (see scripts/seed_data.py docstring): entities.csv
    # carries one stray row (RoadAccidents006/E2) with no incidents.csv row of
    # its own. It links to no incident and is excluded here rather than
    # violating the incidents FK.
    incident_ids = {incident["Incident_ID"] for incident in data["Incident"]}

    database.insert_model_run(
        MODEL_RUN_ID, model_name=MODEL_NAME, model_version=MODEL_VERSION, prompt_version=PROMPT_VERSION
    )
    counts["model_runs"] = 1

    for incident in data["Incident"]:
        database.upsert_video(
            incident["Incident_ID"], filepath=incident["Filepath"], duration=incident["Video_Duration"]
        )
        counts["videos"] += 1

    for incident in data["Incident"]:
        incident_id, model_run_id = incident["Incident_ID"], incident["Model_Run_ID"]
        database.insert_incident(
            incident_id,
            model_run_id,
            fields={
                "type": incident["Type"],
                "start_timestamp": incident["Start_Timestamp"],
                "end_timestamp": incident["End_Timestamp"],
                "duration": incident["Duration"],
                "description": incident["Description"],
                "severity_level": incident["Severity"],
                "confidence_score": incident.get("Confidence_Score"),
            },
        )
        counts["incidents"] += 1
        database.clear_incident_evidence(incident_id, model_run_id)

    for entity in data["Entity"]:
        if entity["Incident_ID"] not in incident_ids:
            continue
        database.add_incident_entity(
            entity["Incident_ID"],
            entity["Model_Run_ID"],
            entity_id=entity["ID"],
            type=entity["Type"],
            description=entity["Description"],
        )
        counts["entities"] += 1

    for instrument in data["Instrument"]:
        if instrument["Incident_ID"] not in incident_ids:
            continue
        database.add_incident_instrument(
            instrument["Incident_ID"],
            instrument["Model_Run_ID"],
            instrument_id=instrument["ID"],
            entity_id=instrument["Entity_ID"],
            name=instrument["Name"],
            description=instrument["Description"],
            threat_level=instrument["Threat_Level"],
        )
        counts["instruments"] += 1

    for asset in data["Asset"]:
        if asset["Incident_ID"] not in incident_ids:
            continue
        database.add_incident_asset(
            asset["Incident_ID"],
            asset["Model_Run_ID"],
            asset_id=asset["ID"],
            name=asset["Name"],
            description=asset["Description"],
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
    print("Seed complete:")
    for name, value in counts.items():
        print(f"  {name:12s} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
