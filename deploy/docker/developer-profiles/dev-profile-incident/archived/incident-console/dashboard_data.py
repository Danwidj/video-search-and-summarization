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

"""Linked-evidence data path for the Analytics Dashboard.

The dashboard needs every listed incident's entities / instruments / assets.
It used to fetch them one incident at a time (three statements, each on its own
connection checkout, per incident), which made the page's load time grow with
the incident count and with the round-trip time to Postgres. Now:

- ``IncidentDB.list_evidence_batch`` fetches all of them in three statements on
  one connection, whatever the incident count. It matches ``(incident_id,
  model_run_id)`` pairs, not incident ids, so an incident with several model
  runs never mixes runs.
- ``_fetch_evidence`` wraps that in a short-TTL ``st.cache_data``. Streamlit
  reruns the whole script on every widget click, and the dashboard filters
  in-memory, so the rerun should not hit the database again.

Only the evidence is cached. ``DBReports.list_reports()`` is still read fresh on
every run, so a reviewer's edit or verify shows on the dashboard immediately -
including edits made in another reviewer's console. Evidence rows change only when
an analysis rewrites them: the cache key holds the ``(incident_id, model_run_id)``
pairs, so a new incident or a new run misses by itself, and
``analyze_and_refresh`` in ``catalog_actions`` calls ``clear_evidence_cache`` after
the agent's analyze call. The TTL is the backstop for writers this process cannot
see (the agent analyzing on its own, a seed script, another console) - the
worst case is evidence up to ``EVIDENCE_CACHE_TTL_SECONDS`` old.
"""

from __future__ import annotations

import streamlit as st

from db import IncidentDB

EVIDENCE_CACHE_TTL_SECONDS = 30

Pair = tuple[str, str | None]
EvidenceBatch = dict[str, dict[Pair, list[dict]]]


def _pair_sort_key(pair: Pair) -> tuple[str, bool, str]:
    incident_id, model_run_id = pair
    return incident_id, model_run_id is not None, model_run_id or ""


@st.cache_data(ttl=EVIDENCE_CACHE_TTL_SECONDS, max_entries=16, show_spinner=False)
def _fetch_evidence(_handle: IncidentDB, scope: str, pairs: tuple[Pair, ...]) -> EvidenceBatch:
    # ``_handle`` is excluded from the cache key (underscore prefix), so ``scope``
    # stands in for it: two databases never share an entry.
    return _handle.list_evidence_batch(pairs)


def clear_evidence_cache() -> None:
    """Drop every cached evidence batch (this process). Call after anything rewrites evidence rows."""
    _fetch_evidence.clear()


def flatten_evidence(reports: list[dict], evidence: EvidenceBatch) -> tuple[list[dict], list[dict], list[dict]]:
    """Flatten batched DB evidence into ``dashboard_view``'s entity / instrument / asset row shapes.

    Rows follow ``reports`` order and, within a report, the DB's id order - the same
    output the former per-incident loop produced.
    """
    entities: list[dict] = []
    instruments: list[dict] = []
    assets: list[dict] = []
    for report in reports:
        rid = report["id"]
        pair = (rid, report.get("model_run_id"))
        for row in evidence["entities"][pair]:
            entities.append(
                {
                    "Incident_ID": rid,
                    "ID": row.get("entity_id"),
                    "Type": row.get("type"),
                    "Description": row.get("description"),
                }
            )
        for row in evidence["instruments"][pair]:
            instruments.append(
                {
                    "Incident_ID": rid,
                    "ID": row.get("instrument_id"),
                    "Entity_ID": row.get("entity_id"),
                    "Name": row.get("name"),
                    "Description": row.get("description"),
                    "Threat_Level": row.get("threat_level"),
                }
            )
        for row in evidence["assets"][pair]:
            assets.append(
                {
                    "Incident_ID": rid,
                    "ID": row.get("asset_id"),
                    "Name": row.get("name"),
                    "Description": row.get("description"),
                }
            )
    return entities, instruments, assets


def evidence_rows(handle: IncidentDB, reports: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Dashboard-shaped ``(entities, instruments, assets)`` for ``reports``, from the cached batch fetch."""
    # Sorted so the key does not depend on the order the incident list happens to come back in.
    pairs = tuple(sorted({(r["id"], r.get("model_run_id")) for r in reports}, key=_pair_sort_key))
    # ``str(url)`` masks the password, so no credential ever reaches the cache key.
    return flatten_evidence(reports, _fetch_evidence(handle, str(handle.engine.url), pairs))
