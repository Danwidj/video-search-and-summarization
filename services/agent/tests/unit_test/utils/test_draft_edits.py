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

"""Unit tests for the report editor's proposal tools (no model, no network)."""

from __future__ import annotations

import pytest

from vss_agents.utils import draft_edits
from vss_agents.utils.draft_edits import Call
from vss_agents.utils.draft_edits import DraftSnapshot


def _draft() -> DraftSnapshot:
    return DraftSnapshot.model_validate(
        {
            "incident": {
                "type": "burglary",
                "title": "Shop break-in",
                "start_timestamp": 10,
                "end_timestamp": 60,
                "severity_level": 2,
            },
            "entities": [
                {"key": "entity-0", "type": "human", "first_seen_seconds": 12, "last_seen_seconds": 40},
                {"key": "entity-1", "type": "animal", "first_seen_seconds": 20, "last_seen_seconds": 30},
            ],
            "instruments": [
                {"key": "instrument-0", "holder_key": "entity-0", "name": "crowbar", "threat_level": 3},
                {"key": "instrument-1", "holder_key": None, "name": "bag", "threat_level": 1},
            ],
            "assets": [{"key": "asset-0", "name": "till", "timestamp_seconds": 25}],
        }
    )


def _one(call: dict) -> draft_edits.ProposalResult:
    return draft_edits.propose(_draft(), [Call.model_validate(call)])


def test_valid_incident_fields_are_proposed_without_writing() -> None:
    result = _one({"tool": "set_incident_fields", "args": {"severity_level": 4, "title": "Robbery"}})
    assert result.rejected == []
    assert result.proposals[0].args == {"title": "Robbery", "severity_level": 4}


@pytest.mark.parametrize(
    "args",
    [
        {"severity_level": 6},
        {"type": "shoplifting"},
        {"start_timestamp": 70},
        {"start_timestamp": 50, "end_timestamp": 40},
        {},
    ],
)
def test_bad_incident_fields_are_rejected(args: dict) -> None:
    result = _one({"tool": "set_incident_fields", "args": args})
    assert result.proposals == []
    assert len(result.rejected) == 1


def test_invented_key_is_rejected() -> None:
    result = _one({"tool": "set_timeline_item", "args": {"item_key": "entity-9", "label": "x"}})
    assert result.proposals == []
    assert "entity-9" in result.rejected[0].reason


def test_renumbered_id_is_rejected_because_only_keys_are_accepted() -> None:
    result = _one({"tool": "set_instrument_holder", "args": {"instrument_key": "I1", "holder_key": "E1"}})
    assert result.proposals == []
    assert len(result.rejected) == 1


def test_timeline_seconds_outside_the_incident_are_rejected() -> None:
    result = _one({"tool": "set_timeline_item", "args": {"item_key": "asset-0", "timestamp_seconds": 90}})
    assert result.proposals == []
    assert "within the incident" in result.rejected[0].reason


def test_entity_timestamp_must_sit_inside_its_span() -> None:
    result = _one({"tool": "set_timeline_item", "args": {"item_key": "entity-1", "timestamp_seconds": 35}})
    assert result.proposals == []
    assert "first to last seen" in result.rejected[0].reason


def test_adding_an_instrument_needs_a_threat_level() -> None:
    result = _one({"tool": "upsert_instrument", "args": {"op": "add", "name": "knife"}})
    assert result.proposals == []


def test_threat_level_out_of_range_is_rejected() -> None:
    result = _one({"tool": "upsert_instrument", "args": {"op": "add", "name": "knife", "threat_level": 6}})
    assert result.proposals == []


def test_editing_an_entity_checks_its_merged_span() -> None:
    result = _one({"tool": "upsert_entity", "args": {"op": "edit", "item_key": "entity-1", "last_seen_seconds": 15}})
    assert result.proposals == []
    assert "first seen" in result.rejected[0].reason


def test_add_entity_proposal_has_no_key() -> None:
    result = _one(
        {
            "tool": "upsert_entity",
            "args": {
                "op": "add",
                "name": "person in red jacket",
                "entity_type": "human",
                "first_seen_seconds": 15,
                "last_seen_seconds": 25,
            },
        }
    )
    assert result.rejected == []
    assert "item_key" not in result.proposals[0].args
    assert result.proposals[0].args["name"] == "person in red jacket"


def test_adding_an_entity_needs_a_name() -> None:
    result = _one(
        {
            "tool": "upsert_entity",
            "args": {"op": "add", "entity_type": "human", "first_seen_seconds": 15, "last_seen_seconds": 25},
        }
    )
    assert result.proposals == []
    assert "name" in result.rejected[0].reason


def test_holder_must_be_an_entity_and_null_means_nobody() -> None:
    ok = _one({"tool": "set_instrument_holder", "args": {"instrument_key": "instrument-1", "holder_key": "entity-1"}})
    nobody = _one({"tool": "set_instrument_holder", "args": {"instrument_key": "instrument-0", "holder_key": None}})
    wrong = _one({"tool": "set_instrument_holder", "args": {"instrument_key": "instrument-0", "holder_key": "asset-0"}})
    assert ok.rejected == []
    assert nobody.rejected == []
    assert wrong.proposals == []


def test_an_instrument_can_name_its_holder_when_added_or_edited() -> None:
    add = _one(
        {
            "tool": "upsert_instrument",
            "args": {"op": "add", "name": "knife", "threat_level": 4, "holder_key": "entity-1"},
        }
    )
    edit = _one(
        {"tool": "upsert_instrument", "args": {"op": "edit", "item_key": "instrument-1", "holder_key": "entity-0"}}
    )
    assert add.rejected == []
    assert add.proposals[0].args["holder_key"] == "entity-1"
    assert add.proposals[0].summary == "Add instrument knife, held by entity-1"
    assert edit.rejected == []
    assert edit.proposals[0].args == {"op": "edit", "item_key": "instrument-1", "holder_key": "entity-0"}


def test_an_upserted_instrument_holder_must_be_an_existing_entity() -> None:
    invented = _one(
        {
            "tool": "upsert_instrument",
            "args": {"op": "add", "name": "knife", "threat_level": 4, "holder_key": "entity-9"},
        }
    )
    not_an_entity = _one(
        {
            "tool": "upsert_instrument",
            "args": {"op": "add", "name": "knife", "threat_level": 4, "holder_key": "asset-0"},
        }
    )
    assert invented.proposals == []
    assert "entity-9" in invented.rejected[0].reason
    assert not_an_entity.proposals == []


def test_deleting_an_entity_reports_the_instruments_it_takes_with_it() -> None:
    result = _one({"tool": "delete_item", "args": {"item_key": "entity-0"}})
    assert result.rejected == []
    assert result.proposals[0].also_removes == ["instrument-0"]


def test_unknown_tool_is_rejected() -> None:
    result = _one({"tool": "publish_report", "args": {}})
    assert result.proposals == []
    assert "publish_report" in result.rejected[0].reason


def test_extra_argument_is_rejected() -> None:
    result = _one({"tool": "delete_item", "args": {"item_key": "asset-0", "confirm": True}})
    assert result.proposals == []


def test_duplicate_draft_keys_are_refused() -> None:
    with pytest.raises(ValueError, match="unique"):
        DraftSnapshot.model_validate(
            {
                "incident": {},
                "assets": [{"key": "dup"}, {"key": "dup"}],
            }
        )


def test_reviewer_labels_are_optional_and_kept_on_each_item() -> None:
    labelled = DraftSnapshot.model_validate(
        {
            "incident": {},
            "entities": [{"key": "entity-0", "reviewer_label": "E1", "reviewer_name": "person in purple"}],
            "instruments": [{"key": "instrument-0", "reviewer_label": "I1", "reviewer_name": "crowbar"}],
            "assets": [{"key": "asset-0", "reviewer_label": "A1", "reviewer_name": "till"}],
        }
    )
    assert labelled.entities[0].reviewer_label == "E1"
    assert labelled.instruments[0].reviewer_name == "crowbar"
    assert labelled.assets[0].reviewer_label == "A1"
    unlabelled = _draft()
    assert unlabelled.entities[0].reviewer_label == ""
    assert unlabelled.assets[0].reviewer_name == ""
