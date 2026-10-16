# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Test suite for start.sh launcher, argument handling, and always-on search route."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest

INCIDENT_PROFILE_DIR = Path(__file__).resolve().parents[2]
START_SH_PATH = INCIDENT_PROFILE_DIR / "start.sh"


def test_start_script_exists_and_executable():
    assert START_SH_PATH.is_file(), f"start.sh not found at {START_SH_PATH}"
    assert os.access(START_SH_PATH, os.X_OK), "start.sh is not executable"


def test_start_script_rejects_search_flag():
    """Verify that there is no opt-in --search flag; search is always on and --search is rejected."""
    res = subprocess.run(
        [str(START_SH_PATH), "--search"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 1
    assert "unknown argument '--search'" in res.stderr
    assert "Usage: ./start.sh [--mode local|vm]" in res.stderr


def test_start_script_rejects_unknown_argument():
    res = subprocess.run(
        [str(START_SH_PATH), "--unknown-flag"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 1
    assert "unknown argument '--unknown-flag'" in res.stderr
    assert "Usage: ./start.sh [--mode local|vm]" in res.stderr


def test_start_script_rejects_invalid_mode():
    res = subprocess.run(
        [str(START_SH_PATH), "--mode", "invalid-mode"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 1
    assert "VSS_START_MODE must be 'vm' or 'local'" in res.stderr


def test_start_script_refuses_to_run_on_kwanz_ws(tmp_path: Path):
    """start.sh must refuse to run directly on the VM (kwanz-ws)."""
    fake_bin_dir = tmp_path / "bin"
    fake_bin_dir.mkdir()
    fake_hostname = fake_bin_dir / "hostname"
    fake_hostname.write_text("#!/bin/sh\necho kwanz-ws\n")
    fake_hostname.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin_dir}:{env.get('PATH', '')}"

    res = subprocess.run(
        [str(START_SH_PATH)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert res.returncode == 1
    assert "run this from your laptop, not on kwanz-ws" in res.stderr


def test_start_script_shellcheck():
    """Verify start.sh passes shellcheck without warnings or syntax errors."""
    shellcheck_bin = shutil.which("shellcheck")
    if not shellcheck_bin:
        pytest.skip("shellcheck binary not installed on PATH")

    res = subprocess.run(
        [shellcheck_bin, "-x", str(START_SH_PATH)],
        cwd=str(INCIDENT_PROFILE_DIR),
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"shellcheck failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"


def test_start_script_always_mounts_search_route():
    """Verify that start.sh documents and wires always-on search route with no conditional gate."""
    content = START_SH_PATH.read_text(encoding="utf-8")
    assert "SEARCH_ROUTE" in content
    assert "/api/v1/incidents/search" in content
    assert "always-on" in content
    assert "NO opt-in" in content or "no opt-in" in content
    assert "ENABLE_SEARCH" not in content


def test_local_search_route_launches_under_5_seconds():
    """Acceptance check: base_profile_mock search route responds in under 5 seconds."""
    import sys
    mock_src = INCIDENT_PROFILE_DIR / "mock-backend" / "base_profile_mock" / "src"
    if str(mock_src) not in sys.path:
        sys.path.insert(0, str(mock_src))

    from base_profile_mock.routers.incident_search import router as search_router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    t0 = time.perf_counter()
    app = FastAPI()
    app.include_router(search_router)
    client = TestClient(app)
    response = client.post(
        "/api/v1/incidents/search",
        json={"query": "crowbar used in burglary", "top_k": 3},
    )
    elapsed = time.perf_counter() - t0

    assert response.status_code == 200
    assert elapsed < 5.0, f"Expected search launch response in <5s, took {elapsed:.2f}s"
    data = response.json()
    assert data["total_hits"] > 0
    assert "critic" in data["hits"][0]
