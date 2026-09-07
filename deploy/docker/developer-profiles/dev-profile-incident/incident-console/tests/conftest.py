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

"""Hermetic fixtures - no live Postgres / agent / GPU."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db import IncidentDB  # noqa: E402


@pytest.fixture
def incident_db(tmp_path) -> IncidentDB:
    handle = IncidentDB.from_dsn(f"sqlite:///{tmp_path / 'incidents.db'}")
    handle.init_schema()
    return handle


@pytest.fixture(autouse=True)
def no_live_r2(monkeypatch):
    """App tests never use developer credentials or make live storage requests."""
    monkeypatch.setattr("r2_videos.configured", lambda: False)
