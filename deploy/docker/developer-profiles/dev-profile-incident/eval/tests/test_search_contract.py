# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Test suite for search-contract-v1 schema, fixtures, and mock backend response validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"
SEARCH_CONTRACT_DIR = CONTRACTS_DIR / "search-contract-v1"
FIXTURES_DIR = SEARCH_CONTRACT_DIR / "fixtures"

REQUEST_SCHEMA = json.loads((SEARCH_CONTRACT_DIR / "search_request.schema.json").read_text(encoding="utf-8"))
RESPONSE_SCHEMA = json.loads((SEARCH_CONTRACT_DIR / "search_response.schema.json").read_text(encoding="utf-8"))

request_validator = Draft202012Validator(REQUEST_SCHEMA)
response_validator = Draft202012Validator(RESPONSE_SCHEMA)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_search_contract_version():
    version_file = SEARCH_CONTRACT_DIR / "VERSION"
    assert version_file.exists()
    assert version_file.read_text(encoding="utf-8").strip() == "search-contract-v1"


def test_valid_request_fixtures():
    valid_dir = FIXTURES_DIR / "valid"
    request_fixtures = [valid_dir / "minimal-request.json", valid_dir / "full-request.json"]
    for path in request_fixtures:
        assert path.exists(), f"Missing fixture {path}"
        data = _load_json(path)
        errors = list(request_validator.iter_errors(data))
        assert not errors, f"Fixture {path.name} failed validation: {errors}"


def test_invalid_request_fixtures():
    invalid_dir = FIXTURES_DIR / "invalid"
    invalid_requests = [
        invalid_dir / "request-missing-query.json",
        invalid_dir / "request-invalid-top-k.json",
        invalid_dir / "request-invalid-item-type.json",
    ]
    for path in invalid_requests:
        assert path.exists(), f"Missing fixture {path}"
        data = _load_json(path)
        errors = list(request_validator.iter_errors(data))
        assert len(errors) > 0, f"Expected {path.name} to fail validation, but it passed."


def test_valid_response_fixtures():
    valid_dir = FIXTURES_DIR / "valid"
    response_fixtures = [valid_dir / "empty-response.json", valid_dir / "full-response.json"]
    for path in response_fixtures:
        assert path.exists(), f"Missing fixture {path}"
        data = _load_json(path)
        errors = list(response_validator.iter_errors(data))
        assert not errors, f"Fixture {path.name} failed validation: {errors}"


def test_invalid_response_fixtures():
    invalid_dir = FIXTURES_DIR / "invalid"
    invalid_responses = [
        invalid_dir / "response-missing-critic.json",
        invalid_dir / "response-invalid-verdict.json",
        invalid_dir / "response-negative-timestamp.json",
    ]
    for path in invalid_responses:
        assert path.exists(), f"Missing fixture {path}"
        data = _load_json(path)
        errors = list(response_validator.iter_errors(data))
        assert len(errors) > 0, f"Expected {path.name} to fail validation, but it passed."


def test_mock_backend_response_validates_against_contract():
    mock_src = Path(__file__).resolve().parents[2] / "mock-backend" / "base_profile_mock" / "src"
    sys.path.insert(0, str(mock_src))

    from base_profile_mock.routers.incident_search import router as search_router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(search_router)
    client = TestClient(app)
    resp = client.post("/api/v1/incidents/search", json={"query": "machete or weapon", "top_k": 5})
    assert resp.status_code == 200
    data = resp.json()

    errors = list(response_validator.iter_errors(data))
    assert not errors, f"Mock search response failed validation against search-contract-v1: {errors}"
    assert data["total_hits"] > 0
    assert data["query"] == "machete or weapon"

    first_hit = data["hits"][0]
    assert "timestamp_seconds" in first_hit["item"]
    assert "label" in first_hit["item"]
    assert "crop_image_url" in first_hit["item"]
    assert "critic" in first_hit
    assert first_hit["critic"]["verdict"] in ("confirmed", "rejected", "unverified")
