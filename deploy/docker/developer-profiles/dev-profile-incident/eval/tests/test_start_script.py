# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Test suite for start.sh launcher, argument handling, and always-on search route."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

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
    assert "Usage: ./start.sh [--mode mock|vm]" in res.stderr


def test_start_script_rejects_unknown_argument():
    res = subprocess.run(
        [str(START_SH_PATH), "--unknown-flag"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 1
    assert "unknown argument '--unknown-flag'" in res.stderr
    assert "Usage: ./start.sh [--mode mock|vm]" in res.stderr


def test_start_script_rejects_invalid_mode():
    res = subprocess.run(
        [str(START_SH_PATH), "--mode", "invalid-mode"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 1
    assert "VSS_START_MODE must be 'vm' or 'mock'" in res.stderr


def _run_on_fake_vm(tmp_path: Path, args: list[str], extra_env: dict[str, str] | None = None):
    """Run start.sh with `hostname` faked to kwanz-ws so it exits at the laptop guard, after mode validation."""
    fake_bin_dir = tmp_path / "bin"
    fake_bin_dir.mkdir()
    fake_hostname = fake_bin_dir / "hostname"
    fake_hostname.write_text("#!/bin/sh\necho kwanz-ws\n")
    fake_hostname.chmod(0o755)

    env = os.environ.copy()
    env.pop("VSS_START_MODE", None)
    env["PATH"] = f"{fake_bin_dir}:{env.get('PATH', '')}"
    env.update(extra_env or {})

    return subprocess.run(
        [str(START_SH_PATH), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.mark.parametrize(
    ("args", "extra_env"),
    [(["--mode", "mock"], None), (["--mode=mock"], None), (["--mode", "vm"], None), ([], {"VSS_START_MODE": "mock"})],
)
def test_start_script_accepts_canonical_modes(tmp_path: Path, args: list[str], extra_env: dict[str, str] | None):
    res = _run_on_fake_vm(tmp_path, args, extra_env)
    assert res.returncode == 1
    assert "must be 'vm' or 'mock'" not in res.stderr
    assert "deprecated" not in res.stderr
    assert "run this from your laptop, not on kwanz-ws" in res.stderr


@pytest.mark.parametrize(("args", "extra_env"), [(["--mode", "local"], None), ([], {"VSS_START_MODE": "local"})])
def test_start_script_local_is_deprecated_alias_for_mock(
    tmp_path: Path, args: list[str], extra_env: dict[str, str] | None
):
    res = _run_on_fake_vm(tmp_path, args, extra_env)
    assert res.returncode == 1
    assert "mode 'local' is deprecated; use 'mock'" in res.stderr
    assert "must be 'vm' or 'mock'" not in res.stderr
    assert "run this from your laptop, not on kwanz-ws" in res.stderr


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
    assert res.returncode == 0, (
        f"shellcheck failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"
    )


@pytest.mark.parametrize("name", ["test-vm-preflight.sh", "test-vm-ensure-docker.sh"])
def test_vm_helper_scripts_hermetic_tests(name: str):
    """The VM-side failure classification and Docker step have their own fake-ssh/fake-docker tests."""
    res = subprocess.run(
        ["bash", str(INCIDENT_PROFILE_DIR / ".scripts" / name)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert res.returncode == 0, f"{name} failed:\n{res.stdout}\n{res.stderr}"


def test_start_script_always_mounts_search_route(mock_search_router):
    """Verify that the search route is mounted unconditionally and responds with expected status codes."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(mock_search_router)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/incidents/search",
        json={"query": "crowbar used in burglary", "top_k": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_hits"] > 0
    assert "hits" in data
    assert "critic" in data["hits"][0]

    invalid_resp = client.post("/api/v1/incidents/search", json={})
    assert invalid_resp.status_code == 422

    get_resp = client.get("/api/v1/incidents/search")
    assert get_resp.status_code == 405


def test_local_search_route_launches_under_5_seconds(mock_search_router):
    """Acceptance check: base_profile_mock search route responds in under 5 seconds."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    t0 = time.perf_counter()
    app = FastAPI()
    app.include_router(mock_search_router)
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

