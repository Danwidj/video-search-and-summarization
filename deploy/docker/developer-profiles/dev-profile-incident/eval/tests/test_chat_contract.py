# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Test suite for chat-contract-v1 schema, fixtures, and mock backend response validation."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"
CHAT_CONTRACT_DIR = CONTRACTS_DIR / "chat-contract-v1"
FIXTURES_DIR = CHAT_CONTRACT_DIR / "fixtures"

REQUEST_SCHEMA = json.loads(
    (CHAT_CONTRACT_DIR / "chat_request.schema.json").read_text(encoding="utf-8")
)
RESPONSE_SCHEMA = json.loads(
    (CHAT_CONTRACT_DIR / "chat_response.schema.json").read_text(encoding="utf-8")
)

request_validator = Draft202012Validator(REQUEST_SCHEMA)
response_validator = Draft202012Validator(RESPONSE_SCHEMA)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_chat_contract_version():
    version_file = CHAT_CONTRACT_DIR / "VERSION"
    assert version_file.exists()
    assert version_file.read_text(encoding="utf-8").strip() == "chat-contract-v1"


def test_valid_request_fixtures():
    valid_dir = FIXTURES_DIR / "valid"
    request_fixtures = [
        valid_dir / "minimal-request.json",
        valid_dir / "full-request.json",
    ]
    for path in request_fixtures:
        assert path.exists(), f"Missing fixture {path}"
        data = _load_json(path)
        errors = list(request_validator.iter_errors(data))
        assert not errors, f"Fixture {path.name} failed validation: {errors}"


def test_invalid_request_fixtures():
    invalid_dir = FIXTURES_DIR / "invalid"
    invalid_requests = [
        invalid_dir / "request-missing-messages.json",
        invalid_dir / "request-empty-messages.json",
        invalid_dir / "request-invalid-scope.json",
    ]
    for path in invalid_requests:
        assert path.exists(), f"Missing fixture {path}"
        data = _load_json(path)
        errors = list(request_validator.iter_errors(data))
        assert len(errors) > 0, (
            f"Expected {path.name} to fail validation, but it passed."
        )


def test_valid_response_fixtures():
    valid_dir = FIXTURES_DIR / "valid"
    response_fixtures = [
        valid_dir / "empty-response.json",
        valid_dir / "full-response.json",
    ]
    for path in response_fixtures:
        assert path.exists(), f"Missing fixture {path}"
        data = _load_json(path)
        errors = list(response_validator.iter_errors(data))
        assert not errors, f"Fixture {path.name} failed validation: {errors}"


def test_invalid_response_fixtures():
    invalid_dir = FIXTURES_DIR / "invalid"
    invalid_responses = [
        invalid_dir / "response-missing-session.json",
        invalid_dir / "response-invalid-role.json",
        invalid_dir / "response-invalid-citation.json",
    ]
    for path in invalid_responses:
        assert path.exists(), f"Missing fixture {path}"
        data = _load_json(path)
        errors = list(response_validator.iter_errors(data))
        assert len(errors) > 0, (
            f"Expected {path.name} to fail validation, but it passed."
        )
