# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""C3 amendment A1: a reply Python's JSON parser refuses with a plain ValueError is an invalid output, not a crash."""

from evalv2.tasks.incident_objects import v1


def test_a_runaway_integer_is_invalid_json_not_a_crash():
    content = '{"incident": {"end_timestamp": ' + "7" * 13698 + "}}"
    policy = v1.evaluate_policy(content, 30.0)
    assert policy["core_ok"] is False and policy["full_contract_ok"] is False
    assert [v["code"] for v in policy["core"]] == ["INVALID_JSON"]
    assert policy["report"] is None


def test_ordinary_replies_are_unchanged():
    from contract import evaluate_policy as original
    for content in ("", "not json", '{"incident": {}}'):
        assert v1.evaluate_policy(content, 30.0) == original(content, 30.0)
