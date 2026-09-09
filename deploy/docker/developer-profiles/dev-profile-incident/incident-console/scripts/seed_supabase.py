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

"""One-time, idempotent Supabase seed for the 8 mock incidents.

Run it by hand once the DSN is configured (see incident-console/README.md):

    uv run python scripts/seed_supabase.py

It upserts 8 ``videos`` rows (natural key: ``r2_key``), one ``incident_reports``
row per clip (natural key: that video's id), and each incident's fabricated
entities / instruments / assets. Re-running replaces the evidence rows and
updates the incident in place, so row counts do not grow. It is never imported
by the app and never runs on startup.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402  (loads .env / .env.local before anything reads it)
from db import IncidentDB  # noqa: E402
from scripts.seed_data import (  # noqa: E402
    CLIP_DURATIONS,
    INCIDENTS,
    MODEL_VERSION,
    duration_sec_for,
    filename_for,
)

_EDITABLE = (
    "incident_type",
    "severity",
    "confidence",
    "incident_start",
    "incident_end",
    "incident_start_confirmed",
    "description",
    "duration_sec",
    "model_version",
)


def seed(database: IncidentDB) -> dict[str, int]:
    """Apply the seed and return the resulting row counts for the seeded set."""
    counts = {"videos": 0, "reports": 0, "entities": 0, "instruments": 0, "assets": 0}
    for incident in INCIDENTS:
        r2_key = incident["r2_key"]
        video_id = database.upsert_video_by_r2_key(
            r2_key=r2_key,
            filename=filename_for(r2_key),
            status="analyzed",
            duration_sec=CLIP_DURATIONS.get(r2_key),
        )
        counts["videos"] += 1

        report = {
            "incident_type": incident["incident_type"],
            "severity": incident["severity"],
            "confidence": incident["confidence"],
            "incident_start": incident["incident_start"],
            "incident_end": incident["incident_end"],
            "incident_start_confirmed": True,
            "description": incident["description"],
            "duration_sec": duration_sec_for(incident),
            "model_version": MODEL_VERSION,
            "status": "unreviewed",
        }
        existing = database.get_report_by_video_id(video_id)
        if existing:
            report_id = int(existing["id"])
            database.update_report(
                report_id,
                fields={k: report[k] for k in _EDITABLE},
                edited_by="seed-importer",
            )
        else:
            report_id = database.insert_report(video_id=video_id, report=report)
        counts["reports"] += 1

        database.clear_incident_evidence(report_id)
        for entity in incident["entities"]:
            database.add_incident_entity(
                report_id,
                entity_id=entity["entity_id"],
                type=entity["type"],
                description=entity["description"],
            )
            counts["entities"] += 1
        for instrument in incident["instruments"]:
            database.add_incident_instrument(
                report_id,
                instrument_id=instrument["instrument_id"],
                entity_id=instrument.get("entity_id"),
                name=instrument["name"],
                description=instrument["description"],
                threat_level=instrument.get("threat_level"),
            )
            counts["instruments"] += 1
        for asset in incident["assets"]:
            database.add_incident_asset(
                report_id,
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
            "INCIDENT_DB_DSN is not set. Put the Supabase DSN in incident-console/.env.local (git-ignored) and re-run.",
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
