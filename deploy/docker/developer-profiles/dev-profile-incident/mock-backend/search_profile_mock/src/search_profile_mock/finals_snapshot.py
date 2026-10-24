# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The finals snapshot of base_profile_mock, loaded from the sibling package rather than copied.

base_profile_mock/src/base_profile_mock/finals_snapshot.py (and the JSON beside it) is the one
copy of the finals AI revisions, so both mocks answer about the same clips. The module is loaded
by path because importing base_profile_mock would pull in its Supabase and boto3 dependencies,
which this offline mock does not need; finals_snapshot.py itself uses only the standard library.
Refresh the snapshot in base_profile_mock (see its README).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

_BASE_SNAPSHOT = (
    Path(__file__).resolve().parents[3] / "base_profile_mock" / "src" / "base_profile_mock" / "finals_snapshot.py"
)
_NAME = "_base_profile_mock_finals_snapshot"


def _load():
    if _NAME in sys.modules:
        return sys.modules[_NAME]
    spec = importlib.util.spec_from_file_location(_NAME, _BASE_SNAPSHOT)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load the finals snapshot from {_BASE_SNAPSHOT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_NAME] = module
    spec.loader.exec_module(module)
    return module


_snapshot = _load()
EVIDENCE_IMAGE_ROUTE = _snapshot.EVIDENCE_IMAGE_ROUTE
evidence_hits = _snapshot.evidence_hits
match_score = _snapshot.match_score
query_tokens = _snapshot.query_tokens
revision_hits = _snapshot.revision_hits
