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

"""Dashboard evidence: batched fetch equals the per-incident loop, round trips stay constant, cache is safe.

The old ``pages/3_Dashboard.py::_evidence_rows`` (three statements per incident, each on its own
connection) is kept below verbatim as the oracle. Everything runs on the hermetic SQLite fixture;
the SQL itself was also checked against a real PostgreSQL 16 (see the PR description).
"""

from __future__ import annotations

import datetime as dt
import re
from contextlib import contextmanager

import pytest
from sqlalchemy import event, select
from streamlit.testing.v1 import AppTest

import dashboard_data
import db as db_module
from agent_client import Result
from catalog_actions import analyze_and_refresh
from dashboard_data import clear_evidence_cache, evidence_rows, flatten_evidence
from db import IncidentDB
from db_reports import DBReports

TYPES = ("burglary", "road accident", "fighting")
EVIDENCE_SQL = re.compile(r"\bFROM (entities|instruments|assets)\b")


@pytest.fixture(autouse=True)
def cold_cache():
    """``st.cache_data`` is process-wide; never let one test's entries answer another's."""
    clear_evidence_cache()
    yield
    clear_evidence_cache()


# --------------------------------------------------------------------------- #
# Oracle + fixtures
# --------------------------------------------------------------------------- #
def legacy_evidence_rows(db_handle, reports):
    """The Dashboard's former per-incident loop, verbatim (3 statements + 3 connections per incident)."""
    entities: list[dict] = []
    instruments: list[dict] = []
    assets: list[dict] = []
    for report in reports:
        rid, model_run_id = report["id"], report.get("model_run_id")
        for row in db_handle.list_incident_entities(rid, model_run_id):
            entities.append(
                {
                    "Incident_ID": rid,
                    "ID": row.get("entity_id"),
                    "Type": row.get("type"),
                    "Description": row.get("description"),
                }
            )
        for row in db_handle.list_incident_instruments(rid, model_run_id):
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
        for row in db_handle.list_incident_assets(rid, model_run_id):
            assets.append(
                {
                    "Incident_ID": rid,
                    "ID": row.get("asset_id"),
                    "Name": row.get("name"),
                    "Description": row.get("description"),
                }
            )
    return entities, instruments, assets


def seed_incidents(db: IncidentDB, count: int, *, second_run_every: int = 3) -> list[str]:
    """``count`` incidents under run ``MR-A`` with uneven evidence (0-3 entities, 0-2 instruments, ...).

    Every ``second_run_every``-th incident also has a newer run ``MR-B`` whose evidence deliberately
    reuses id ``E1`` (different text) and adds ``E9``, so "all runs of this incident" and "this one
    run" give different answers - the case a batch keyed on ``incident_id`` alone would get wrong.
    Written in one transaction (row-by-row commits make a 36-incident fixture take seconds).
    """
    rows: dict[str, list[dict]] = {
        name: [] for name in ("videos", "incidents", "review_status", "entities", "instruments", "assets")
    }

    def incident(iid, run, severity, confidence, type_):
        rows["incidents"].append(
            {
                "incident_id": iid,
                "model_run_id": run,
                "type": type_,
                "severity_level": severity,
                "confidence_score": confidence,
            }
            | {"start_timestamp": None, "end_timestamp": None, "duration": None, "description": None}
        )
        rows["review_status"].append(
            {"incident_id": iid, "model_run_id": run, "status": "unreviewed"}
            | {"verified_by": None, "verified_at": None, "edited_by": None, "edited_at": None}
        )

    def entity(iid, run, n, type_, text):
        rows["entities"].append(
            {"incident_id": iid, "model_run_id": run, "entity_id": n, "type": type_, "description": text, "image": None}
        )

    def instrument(iid, run, n, name, threat, wielder):
        rows["instruments"].append(
            {"incident_id": iid, "model_run_id": run, "instrument_id": n, "entity_id": wielder, "name": name}
            | {"description": None, "threat_level": threat, "image": None}
        )

    def asset(iid, run, n, name, text):
        rows["assets"].append(
            {"incident_id": iid, "model_run_id": run, "asset_id": n, "name": name, "description": text, "image": None}
        )

    ids = []
    for k in range(count):
        iid = f"Inc{k:03d}"
        ids.append(iid)
        rows["videos"].append(
            {"id": iid, "filepath": f"normal_videos/{iid}.mp4", "uploaded_datetime": dt.datetime(2026, 1, 1)}
            | {"duration": None, "source": None}
        )
        incident(iid, "MR-A", 1 + k % 5, 0.4 + (k % 5) / 10, TYPES[k % 3])
        # Inserted highest id first, so a per-incident id ordering has to come from the query.
        for n in reversed(range(k % 4)):
            entity(iid, "MR-A", f"E{n + 1}", "human", f"{iid} run-A e{n + 1}")
        for n in reversed(range(k % 3)):
            instrument(iid, "MR-A", f"I{n + 1}", f"tool{n}", 1 + n, "E1")
        for n in reversed(range(k % 3)):
            asset(iid, "MR-A", f"A{n + 1}", f"asset{n}", f"{iid} run-A")
        if k % second_run_every == 0:
            incident(iid, "MR-B", 5, 0.9, TYPES[k % 3])
            entity(iid, "MR-B", "E9", "unknown", f"{iid} run-B only")
            entity(iid, "MR-B", "E1", "animal", f"{iid} run-B e1")
            instrument(iid, "MR-B", "I1", "run-B tool", 5, None)
            asset(iid, "MR-B", "A1", "run-B asset", None)

    runs = [
        {"id": "MR-A", "model_name": "vlm-a", "run_datetime": dt.datetime(2026, 1, 1)},
        {"id": "MR-B", "model_name": "vlm-b", "run_datetime": dt.datetime(2026, 2, 1)},
    ]
    with db.engine.begin() as conn:
        conn.execute(
            db_module.model_runs.insert(),
            [r | {"model_version": None, "prompt_version": None, "notes": None} for r in runs],
        )
        for name, batch in rows.items():
            if batch:
                conn.execute(getattr(db_module, name).insert(), batch)
    return ids


@contextmanager
def count_sql(db: IncidentDB):
    """Yield ``(statements, checkouts)``; statements are the SQL text of everything executed via SQLAlchemy."""
    statements: list[str] = []
    checkouts: list[int] = []

    def on_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    def on_checkout(dbapi_connection, connection_record, connection_proxy):
        checkouts.append(1)

    for engine in db.engines:
        event.listen(engine, "before_cursor_execute", on_execute)
        event.listen(engine, "checkout", on_checkout)
    try:
        yield statements, checkouts
    finally:
        for engine in db.engines:
            event.remove(engine, "before_cursor_execute", on_execute)
            event.remove(engine, "checkout", on_checkout)


@pytest.fixture
def multi_run_db(incident_db):
    seed_incidents(incident_db, 12)
    return incident_db


def _row_key(row):
    return (row.get("entity_id") or row.get("instrument_id") or row.get("asset_id"), row["model_run_id"])


# --------------------------------------------------------------------------- #
# (a) Equivalence with the per-incident implementation
# --------------------------------------------------------------------------- #
def test_fixture_exercises_the_multi_run_trap(multi_run_db):
    """Guard the guard: a batch keyed on incident_id alone must NOT equal the oracle on this data."""
    reports = DBReports(multi_run_db).list_reports()
    assert {r["model_run_id"] for r in reports} == {"MR-A", "MR-B"}
    ids = [r["id"] for r in reports]
    with multi_run_db.engine.connect() as conn:
        naive_rows = conn.execute(select(db_module.entities).where(db_module.entities.c.incident_id.in_(ids))).all()
    naive = {(r._mapping["incident_id"], r._mapping["entity_id"], r._mapping["model_run_id"]) for r in naive_rows}
    correct = {
        (r["id"], e["entity_id"], e["model_run_id"])
        for r in reports
        for e in multi_run_db.list_incident_entities(r["id"], r["model_run_id"])
    }
    assert naive > correct  # extra rows: the other run's evidence


def test_evidence_rows_equal_the_per_incident_loop_on_multi_run_data(multi_run_db):
    reports = DBReports(multi_run_db).list_reports()
    assert evidence_rows(multi_run_db, reports) == legacy_evidence_rows(multi_run_db, reports)


def test_evidence_rows_follow_reports_order_and_id_order(multi_run_db):
    reports = list(reversed(DBReports(multi_run_db).list_reports()))
    got = evidence_rows(multi_run_db, reports)
    assert got == legacy_evidence_rows(multi_run_db, reports)
    ids_in_output = [row["Incident_ID"] for row in got[0]]
    assert ids_in_output == sorted(ids_in_output, key=[r["id"] for r in reports].index)
    per_incident = {}
    for row in got[0]:
        per_incident.setdefault(row["Incident_ID"], []).append(row["ID"])
    assert all(ids == sorted(ids) for ids in per_incident.values())


@pytest.mark.parametrize(
    "shape",
    ["latest", "every_run", "no_run_filter", "mixed", "none_and_pinned", "unknown", "duplicates", "empty"],
)
def test_batch_matches_per_pair_calls(multi_run_db, shape):
    latest = [(r["id"], r["model_run_id"]) for r in DBReports(multi_run_db).list_reports()]
    every_run = sorted({(r["incident_id"], r["model_run_id"]) for r in multi_run_db.list_incidents()})
    pairs = {
        "latest": latest,
        "every_run": every_run,
        "no_run_filter": [(iid, None) for iid, _ in latest],
        "mixed": [(iid, None) if n % 2 else (iid, run) for n, (iid, run) in enumerate(latest)],
        # The same incident asked for as "all runs" and as each single run, in one call.
        "none_and_pinned": [*[(iid, None) for iid, _ in every_run], *every_run],
        "unknown": [("NoSuchIncident", None), ("NoSuchIncident", "MR-A"), (latest[0][0], "MR-NOPE")],
        "duplicates": [*latest, *latest[:3]],
        "empty": [],
    }[shape]
    batch = multi_run_db.list_evidence_batch(pairs)
    per_pair = {
        "entities": multi_run_db.list_incident_entities,
        "instruments": multi_run_db.list_incident_instruments,
        "assets": multi_run_db.list_incident_assets,
    }
    assert set(batch) == set(per_pair)
    for table, fetch_one in per_pair.items():
        assert set(batch[table]) == set(pairs)
        for pair in pairs:
            want, got = fetch_one(*pair), batch[table][pair]
            if pair[1] is None:  # rows of several runs sharing an id are unordered in the per-incident query
                want, got = sorted(want, key=_row_key), sorted(got, key=_row_key)
            assert got == want, (table, pair)


def test_no_run_filter_keeps_every_runs_rows(multi_run_db):
    iid = "Inc003"  # runs MR-A (E1-E3) and MR-B (E1, E9): both have an E1
    both = multi_run_db.list_evidence_batch([(iid, None)])["entities"][(iid, None)]
    only_a = multi_run_db.list_evidence_batch([(iid, "MR-A")])["entities"][(iid, "MR-A")]
    only_b = multi_run_db.list_evidence_batch([(iid, "MR-B")])["entities"][(iid, "MR-B")]
    assert {r["model_run_id"] for r in both} == {"MR-A", "MR-B"}
    assert {r["model_run_id"] for r in only_a} == {"MR-A"}
    assert {r["model_run_id"] for r in only_b} == {"MR-B"}
    assert len(both) == len(only_a) + len(only_b)


def test_batch_entries_do_not_share_rows_or_lists(multi_run_db):
    """Like the per-incident methods, each pair gets its own rows: editing one entry must not leak into another."""
    iid = "Inc003"
    batch = multi_run_db.list_evidence_batch([(iid, None), (iid, "MR-A"), (iid, "MR-B")])["entities"]
    batch[(iid, "MR-A")][0]["description"] = "edited in place"
    batch[(iid, "MR-B")].clear()
    every_run = batch[(iid, None)]
    assert all(row["description"] != "edited in place" for row in every_run)
    assert {row["model_run_id"] for row in every_run} == {"MR-A", "MR-B"}


def test_reports_without_a_run_id_fall_back_to_all_runs_like_the_loop(multi_run_db):
    reports = [{**r, "model_run_id": None} for r in DBReports(multi_run_db).list_reports()]
    got, want = evidence_rows(multi_run_db, reports), legacy_evidence_rows(multi_run_db, reports)
    for a, b in zip(got, want, strict=True):  # ties across runs are unordered in the loop's query
        assert sorted(a, key=lambda r: (r["Incident_ID"], r["ID"], str(r["Description"]))) == sorted(
            b, key=lambda r: (r["Incident_ID"], r["ID"], str(r["Description"]))
        )


def _pinned_pairs(db: IncidentDB) -> list[tuple[str, str]]:
    return [(r["id"], r["model_run_id"]) for r in DBReports(db).list_reports()]


def test_batch_statements_return_only_the_requested_runs_rows(multi_run_db, monkeypatch):
    """Judge over-fetching by the rows the statements return: the per-pair Python filter would hide it in the result."""
    pairs = _pinned_pairs(multi_run_db)
    fetched: list[dict] = []
    to_dict = db_module._row_to_dict

    def recording(row):
        values = to_dict(row)
        fetched.append(values)
        return values

    monkeypatch.setattr(db_module, "_row_to_dict", recording)
    batch = multi_run_db.list_evidence_batch(pairs)

    kept = sum(len(rows) for table in batch.values() for rows in table.values())
    assert fetched
    assert {(row["incident_id"], row["model_run_id"]) for row in fetched} <= set(pairs)
    assert len(fetched) == kept  # nothing transferred only to be thrown away


@pytest.fixture
def reversed_scans(multi_run_db):
    """SQLite returns a SELECT with no ORDER BY in reverse of its natural order, so a missing one shows up."""
    event.listen(multi_run_db.engine, "connect", lambda conn, _: conn.execute("PRAGMA reverse_unordered_selects=ON"))
    multi_run_db.engine.dispose()  # pooled connections were opened without the pragma
    return multi_run_db


def test_unordered_selects_come_back_out_of_id_order_here(reversed_scans):
    """Guard the guard: the ordering test below can only fail if an unordered SELECT differs from the ordered one."""
    for table, id_column in ((db_module.entities, "entity_id"), (db_module.instruments, "instrument_id")):
        columns = (table.c.incident_id, table.c.model_run_id, table.c[id_column])
        with reversed_scans.engine.connect() as conn:
            unordered = conn.execute(select(*columns)).all()
            ordered = conn.execute(select(*columns).order_by(table.c.incident_id, table.c[id_column])).all()
        assert sorted(unordered) == sorted(ordered)
        assert unordered != ordered


def test_batch_rows_come_back_in_the_per_incident_order(reversed_scans):
    every_run = sorted({(r["incident_id"], r["model_run_id"]) for r in reversed_scans.list_incidents()})
    batch = reversed_scans.list_evidence_batch(every_run)
    per_pair = {
        "entities": reversed_scans.list_incident_entities,
        "instruments": reversed_scans.list_incident_instruments,
        "assets": reversed_scans.list_incident_assets,
    }
    for table, fetch_one in per_pair.items():
        assert any(len(batch[table][pair]) > 1 for pair in every_run), table  # ordering is observable
        for pair in every_run:
            assert batch[table][pair] == fetch_one(*pair), (table, pair)


def test_batch_orders_by_the_tables_id_column_in_the_sql(multi_run_db):
    """Extra guard beside the ordering test above, for what SQLite cannot show.

    A partial ORDER BY such as ``ORDER BY incident_id`` still returns the right order on SQLite (rows
    come back in primary-key order even under ``reverse_unordered_selects``) but leaves the per-incident
    order to chance on PostgreSQL, so require each statement to order by its table's id column.
    """
    pairs = _pinned_pairs(multi_run_db)
    with count_sql(multi_run_db) as (statements, _):
        multi_run_db.list_evidence_batch(pairs)
    for statement, id_column in zip(statements, ("entity_id", "instrument_id", "asset_id"), strict=True):
        assert id_column in " ".join(statement.split()).split(" ORDER BY ", 1)[1]


def test_flatten_is_strict_about_missing_pairs():
    with pytest.raises(KeyError):
        flatten_evidence([{"id": "X", "model_run_id": "MR-A"}], {"entities": {}, "instruments": {}, "assets": {}})


# --------------------------------------------------------------------------- #
# (b) Round trips do not grow with the incident count
# --------------------------------------------------------------------------- #
def _round_trips(db: IncidentDB, fetch) -> tuple[int, int]:
    """``(statements, connection checkouts)`` one call to ``fetch`` costs."""
    with count_sql(db) as (statements, checkouts):
        fetch()
    return len(statements), len(checkouts)


def _fetch_costs(db: IncidentDB) -> dict[str, tuple[int, int]]:
    reports = DBReports(db).list_reports()
    pairs = [(r["id"], r["model_run_id"]) for r in reports]
    costs = {"incidents": (len(reports), 0)}
    costs["batch"] = _round_trips(db, lambda: db.list_evidence_batch(pairs))
    clear_evidence_cache()
    costs["evidence_rows"] = _round_trips(db, lambda: evidence_rows(db, reports))
    costs["loop"] = _round_trips(db, lambda: legacy_evidence_rows(db, reports))
    return costs


def test_batched_fetch_statement_count_is_independent_of_incident_count(tmp_path):
    costs = {}
    for n in (5, 36):
        db = IncidentDB.from_dsn(f"sqlite:///{tmp_path / f'n{n}.db'}")
        db.init_schema()
        seed_incidents(db, n)
        costs[n] = _fetch_costs(db)
        assert costs[n]["incidents"][0] == n
    # Constant: three statements (one per table) on one connection, however many incidents.
    assert costs[5]["batch"] == costs[36]["batch"] == (3, 1)
    assert costs[5]["evidence_rows"] == costs[36]["evidence_rows"] == (3, 1)
    # The regression this guards against: the loop is 3 statements and 3 connections per incident.
    assert costs[5]["loop"] == (15, 15)
    assert costs[36]["loop"] == (108, 108)


def test_batch_with_no_pairs_touches_no_database(multi_run_db):
    with count_sql(multi_run_db) as (statements, checkouts):
        assert multi_run_db.list_evidence_batch([])["entities"] == {}
    assert not statements
    assert not checkouts


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #
def test_second_fetch_within_the_ttl_runs_no_statements(multi_run_db):
    reports = DBReports(multi_run_db).list_reports()
    first = evidence_rows(multi_run_db, reports)
    with count_sql(multi_run_db) as (statements, checkouts):
        again = evidence_rows(multi_run_db, reports)
    assert again == first
    assert not statements
    assert not checkouts


def test_ttl_is_short():
    # The TTL is the only backstop for writers this process cannot see; keep it to seconds.
    assert 0 < dashboard_data.EVIDENCE_CACHE_TTL_SECONDS <= 60


def test_cache_key_ignores_report_order(multi_run_db):
    reports = DBReports(multi_run_db).list_reports()
    evidence_rows(multi_run_db, reports)
    with count_sql(multi_run_db) as (statements, _):
        evidence_rows(multi_run_db, list(reversed(reports)))
    assert not statements


def test_clear_evidence_cache_forces_a_refetch(multi_run_db):
    reports = DBReports(multi_run_db).list_reports()
    before = evidence_rows(multi_run_db, reports)
    iid, run = reports[1]["id"], reports[1]["model_run_id"]
    multi_run_db.add_incident_entity(iid, run, entity_id="E7", type="human", description="added later")

    assert evidence_rows(multi_run_db, reports) == before  # served from cache: still the old rows
    clear_evidence_cache()
    after = evidence_rows(multi_run_db, reports)
    assert after != before
    assert any(row["ID"] == "E7" for row in after[0])


def test_a_new_model_run_misses_the_cache_without_any_invalidation(multi_run_db):
    """The key holds the (incident_id, model_run_id) pairs, so a newer run is picked up by itself."""
    reports = DBReports(multi_run_db).list_reports()
    evidence_rows(multi_run_db, reports)
    iid = "Inc001"  # only has MR-A so far
    multi_run_db.insert_model_run("MR-C", model_name="vlm-c", run_datetime=dt.datetime(2026, 3, 1))
    multi_run_db.insert_incident(iid, "MR-C", fields={"type": "burglary", "severity_level": 2})
    multi_run_db.add_incident_entity(iid, "MR-C", entity_id="E1", type="human", description="run C")

    fresh_reports = DBReports(multi_run_db).list_reports()
    assert next(r for r in fresh_reports if r["id"] == iid)["model_run_id"] == "MR-C"
    rows = evidence_rows(multi_run_db, fresh_reports)
    assert [r["Description"] for r in rows[0] if r["Incident_ID"] == iid] == ["run C"]
    assert rows == legacy_evidence_rows(multi_run_db, fresh_reports)


def test_databases_never_share_cache_entries(tmp_path):
    """Same incident ids and run ids in two databases: each must see only its own rows."""
    dbs = []
    for name in ("one", "two"):
        db = IncidentDB.from_dsn(f"sqlite:///{tmp_path / (name + '.db')}")
        db.init_schema()
        db.insert_model_run("MR-A", model_name="m")
        db.upsert_video("Inc000", filepath="normal_videos/Inc000.mp4")
        db.insert_incident("Inc000", "MR-A", fields={"type": "burglary", "severity_level": 3})
        db.add_incident_entity("Inc000", "MR-A", entity_id="E1", type="human", description=f"only in {name}")
        dbs.append(db)
    seen = []
    for db in dbs:
        entities_, _, _ = evidence_rows(db, DBReports(db).list_reports())
        seen.append([e["Description"] for e in entities_])
    assert seen == [["only in one"], ["only in two"]]


# --------------------------------------------------------------------------- #
# Invalidation at the write paths
# --------------------------------------------------------------------------- #
class _AnalyzingAgent:
    """Stands in for vss-agent: analysis rewrites the incident's evidence in *another process*."""

    def __init__(self, db: IncidentDB, iid: str, run: str, *, result: Result | None = None, raises: bool = False):
        self.db, self.iid, self.run, self.result, self.raises = db, iid, run, result or Result(ok=True), raises

    def analyze_incident(self, video_id):
        self.db.clear_incident_evidence(self.iid, self.run)
        self.db.add_incident_entity(self.iid, self.run, entity_id="E1", type="human", description="re-analysed")
        if self.raises:
            raise RuntimeError("agent exploded")
        return self.result


@pytest.mark.parametrize(
    ("result", "raises"),
    [(Result(ok=True), False), (Result(ok=False, error="boom"), False), (None, True)],
    ids=["success", "failed-call", "raised"],
)
def test_analyze_and_refresh_makes_new_evidence_visible(multi_run_db, result, raises):
    reports = DBReports(multi_run_db).list_reports()
    iid, run = reports[2]["id"], reports[2]["model_run_id"]
    stale = evidence_rows(multi_run_db, reports)  # warm the cache

    agent = _AnalyzingAgent(multi_run_db, iid, run, result=result, raises=raises)
    if raises:
        with pytest.raises(RuntimeError):
            analyze_and_refresh(agent, iid)
    else:
        assert analyze_and_refresh(agent, iid) is agent.result

    fresh = evidence_rows(multi_run_db, reports)
    assert fresh != stale
    assert fresh == legacy_evidence_rows(multi_run_db, reports)
    assert [r["Description"] for r in fresh[0] if r["Incident_ID"] == iid] == ["re-analysed"]


def test_reviewer_edits_and_verify_show_immediately_without_touching_the_evidence_cache(multi_run_db):
    """Reports are read fresh every run; only evidence is cached, and reviewers never change evidence."""
    handle = DBReports(multi_run_db)
    reports = handle.list_reports()
    warm = evidence_rows(multi_run_db, reports)
    target = reports[0]["id"]

    handle.update_report(target, fields={"severity": 2, "description": "edited by a reviewer"}, edited_by="dana")
    handle.set_review_status(target, status="verified", reviewed_by="dana")

    after = handle.list_reports()
    row = next(r for r in after if r["id"] == target)
    assert (row["severity"], row["description"], row["status"]) == (2, "edited by a reviewer", "verified")
    with count_sql(multi_run_db) as (statements, _):
        assert evidence_rows(multi_run_db, after) == warm  # still cached, and still correct
    assert not statements


# --------------------------------------------------------------------------- #
# The page: a widget click must not touch the database for evidence again
# --------------------------------------------------------------------------- #
@pytest.fixture
def dashboard_env(monkeypatch):
    def use(db: IncidentDB) -> None:
        monkeypatch.setattr("config.incident_db_dsn", lambda: str(db.engine.url))
        monkeypatch.setattr("db.is_configured", lambda: True)
        monkeypatch.setattr("db.get_db", lambda: db)

    return use


def test_widget_clicks_on_the_dashboard_do_not_refetch_evidence(incident_db, dashboard_env):
    """The reported bug: every filter click re-ran the per-incident loop. Now a rerun costs no evidence SQL."""
    seed_incidents(incident_db, 12)
    dashboard_env(incident_db)
    clear_evidence_cache()

    app = AppTest.from_file("../pages/3_Dashboard.py", default_timeout=30)
    with count_sql(incident_db) as (first_run, _):
        app.run()
    assert not app.exception
    assert len([s for s in first_run if EVIDENCE_SQL.search(s)]) == 3  # one per table, whatever the count

    with count_sql(incident_db) as (second_run, _):
        app.select_slider[0].set_value((2, 5)).run()  # a filter click reruns the whole script
    assert not app.exception
    assert [s for s in second_run if EVIDENCE_SQL.search(s)] == []


def test_dashboard_page_statement_count_does_not_grow_with_incident_count(tmp_path, dashboard_env):
    """Whole page, cold cache: 5 incidents and 36 incidents cost the same number of statements."""
    totals = {}
    for n in (5, 36):
        db = IncidentDB.from_dsn(f"sqlite:///{tmp_path / f'page{n}.db'}")
        db.init_schema()
        seed_incidents(db, n)
        dashboard_env(db)
        clear_evidence_cache()
        app = AppTest.from_file("../pages/3_Dashboard.py", default_timeout=30)
        with count_sql(db) as (statements, checkouts):
            app.run()
        assert not app.exception
        assert app.metric[0].value == str(n)  # every seeded incident is on the page
        totals[n] = (len(statements), len(checkouts))
    assert totals[5] == totals[36]
