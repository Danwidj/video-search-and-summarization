# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for migration 20261030090000_incidents_core.sql (P1.1).

Run by the hermetic harness (test_baseline.py discovers and invokes this file).
Connects to the shared pgserver via the PGSERVER_URI environment variable.
"""

from __future__ import annotations

import os
import sys

import psycopg
from psycopg import errors

PGSERVER_URI = os.environ["PGSERVER_URI"]
PASSED: list[str] = []


def test(name):
    def wrap(fn):
        fn()
        PASSED.append(name)
        print("ok  ", name)
    return wrap


def one(conn, sql, params=None):
    return conn.execute(sql, params).fetchone()


def refused(conn, sql, params=None, kind=errors.Error, contains=""):
    with conn.transaction(force_rollback=True):
        try:
            conn.execute(sql, params)
        except kind as exc:
            assert contains in str(exc), (contains, str(exc))
            return str(exc)
    raise AssertionError(f"no error from: {sql}")


conn = psycopg.connect(PGSERVER_URI, autocommit=True)
conn.execute("SET ROLE service_role")

# --- schema checks -----------------------------------------------------------------------

@test("p1.1: incidents table has id, official_revision_id, official_since, created_at")
def _():
    cols = {r[0]: r[1] for r in conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'incidents'").fetchall()}
    assert "id" in cols and cols["id"] == "bigint", cols
    assert "official_revision_id" in cols and cols["official_revision_id"] == "bigint", cols
    assert "official_since" in cols, cols
    assert "created_at" in cols, cols


@test("p1.1: videos has incident_id NOT NULL and recorded_at, lacks official_revision_id and official_since")
def _():
    cols = {r[0]: r[1] for r in conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'videos'").fetchall()}
    assert "incident_id" in cols and cols["incident_id"] == "bigint", cols
    assert "recorded_at" in cols, cols
    assert "official_revision_id" not in cols, cols
    assert "official_since" not in cols, cols
    # incident_id must be NOT NULL
    nullable = one(conn,
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='videos' AND column_name='incident_id'")[0]
    assert nullable == "NO", nullable


@test("p1.1: videos.id and model_runs.id are TEXT (unrestricted length)")
def _():
    vid_type = one(conn, "SELECT data_type FROM information_schema.columns "
                   "WHERE table_schema='public' AND table_name='videos' AND column_name='id'")[0]
    run_type = one(conn, "SELECT data_type FROM information_schema.columns "
                   "WHERE table_schema='public' AND table_name='model_runs' AND column_name='id'")[0]
    rr_vid_type = one(conn, "SELECT data_type FROM information_schema.columns "
                      "WHERE table_schema='public' AND table_name='report_revisions' AND column_name='video_id'")[0]
    rr_run_type = one(conn, "SELECT data_type FROM information_schema.columns "
                      "WHERE table_schema='public' AND table_name='report_revisions' AND column_name='model_run_id'")[0]
    assert vid_type == "text", vid_type
    assert run_type == "text", run_type
    assert rr_vid_type == "text", rr_vid_type
    assert rr_run_type == "text", rr_run_type


@test("p1.1: model_runs.id accepts readable text longer than 20 characters")
def _():
    long_id = "front-door.mp4@2026-10-30T09:00:00Z"
    with conn.transaction(force_rollback=True):
        conn.execute("INSERT INTO public.model_runs (id, model_name, notes) VALUES (%s, 'test', NULL)", (long_id,))
        stored = one(conn, "SELECT id FROM public.model_runs WHERE id = %s", (long_id,))[0]
        assert stored == long_id, stored


@test("p1.1: videos.id accepts real file names longer than 20 characters")
def _():
    long_name = "front-entrance-camera-left-angle.mp4"
    with conn.transaction(force_rollback=True):
        (inc_id,) = conn.execute("INSERT INTO public.incidents DEFAULT VALUES RETURNING id").fetchone()
        conn.execute(
            "INSERT INTO public.videos (id, filepath, source, incident_id) VALUES (%s, %s, 'cam', %s)",
            (long_name, f"uploads/{long_name}", inc_id))
        stored = one(conn, "SELECT id FROM public.videos WHERE id = %s", (long_name,))[0]
        assert stored == long_name, stored


# --- FK chain and cascade checks ---------------------------------------------------------

@test("p1.1: incident → video → revision chain is referentially valid")
def _():
    with conn.transaction(force_rollback=True):
        (inc_id,) = conn.execute("INSERT INTO public.incidents DEFAULT VALUES RETURNING id").fetchone()
        conn.execute(
            "INSERT INTO public.videos (id, filepath, source, incident_id) VALUES ('chain-test.mp4', 'uploads/chain.mp4', 'cam', %s)",
            (inc_id,))
        conn.execute(
            "INSERT INTO public.model_runs (id, model_name, notes) VALUES ('chain-test.mp4@2026-01-01T00:00:00Z', 'model', NULL)")
        rev_id = one(conn, """
            INSERT INTO public.report_revisions (video_id, revision_no, kind, model_run_id, payload, evidence,
                incident_type, severity_level, start_seconds, end_seconds)
            VALUES ('chain-test.mp4', 1, 'ai', 'chain-test.mp4@2026-01-01T00:00:00Z',
                    '{"incident":{"type":"assault"}}', '[]', 'assault', 3, 0, 5)
            RETURNING id""")[0]
        # Wire official_revision_id on the incident
        conn.execute("UPDATE public.incidents SET official_revision_id = %s WHERE id = %s", (rev_id, inc_id))
        assert one(conn, "SELECT official_revision_id FROM public.incidents WHERE id = %s", (inc_id,))[0] == rev_id


@test("p1.1: deleting an incident cascades to its videos (and their revisions)")
def _():
    with conn.transaction(force_rollback=True):
        (inc_id,) = conn.execute("INSERT INTO public.incidents DEFAULT VALUES RETURNING id").fetchone()
        conn.execute(
            "INSERT INTO public.videos (id, incident_id, source) VALUES ('cascade-test.mp4', %s, 'cam')", (inc_id,))
        conn.execute(
            "INSERT INTO public.model_runs (id, model_name) VALUES ('cascade-test.mp4@now', 'model')")
        conn.execute("""
            INSERT INTO public.report_revisions (video_id, revision_no, kind, model_run_id, payload, evidence,
                incident_type, severity_level, start_seconds, end_seconds)
            VALUES ('cascade-test.mp4', 1, 'ai', 'cascade-test.mp4@now',
                    '{"incident":{"type":"assault"}}', '[]', 'assault', 3, 0, 5)""")
        assert one(conn, "SELECT count(*) FROM public.videos WHERE id = 'cascade-test.mp4'")[0] == 1
        conn.execute("DELETE FROM public.incidents WHERE id = %s", (inc_id,))
        assert one(conn, "SELECT count(*) FROM public.videos WHERE id = 'cascade-test.mp4'")[0] == 0
        assert one(conn, "SELECT count(*) FROM public.report_revisions WHERE video_id = 'cascade-test.mp4'")[0] == 0


@test("p1.1: video without incident_id is refused")
def _():
    refused(conn, "INSERT INTO public.videos (id, source) VALUES ('no-incident.mp4', 'cam')",
            kind=errors.NotNullViolation)


# --- security ----------------------------------------------------------------------------

@test("p1.1: incidents table is inaccessible to anon and authenticated")
def _():
    conn.execute("RESET ROLE")
    for role in ("anon", "authenticated"):
        assert not one(conn, "SELECT has_table_privilege(%s, 'public.incidents', 'SELECT')", (role,))[0], role
        assert not one(conn, "SELECT has_table_privilege(%s, 'public.incidents', 'INSERT')", (role,))[0], role
    assert one(conn, "SELECT has_table_privilege('service_role', 'public.incidents', 'SELECT')")[0]
    conn.execute("SET ROLE service_role")


conn.execute("RESET ROLE")
conn.close()

print(f"\n{len(PASSED)} passed")
sys.exit(0)
