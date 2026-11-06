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
"""Times in a model's answer belong to the event they stand beside. Stored and hand-made replies only: no model call."""

from typing import Any

import pytest

from vss_agents.utils import chat_attribution as ca
from vss_agents.utils import grounded_chat
from vss_agents.utils import report_answers as ra

FIRE = {
    "incident": {"type": "explosion", "start_timestamp": 6, "end_timestamp": 91},
    "entities": [],
    "instruments": [],
    "assets": [{"asset_id": "A1", "name": "pickup truck", "label": "white pickup truck", "timestamp_seconds": 2}],
    "timeline": [
        {
            "start_seconds": 2,
            "end_seconds": 6,
            "description": "A white pickup truck enters the frame and drives into the lot.",
        },
        {
            "start_seconds": 6,
            "end_seconds": 11,
            "description": "The truck suddenly erupts in flames and people run away.",
        },
        {
            "start_seconds": 11,
            "end_seconds": 72,
            "description": "The fire continues to burn intensely as bystanders watch.",
        },
        {"start_seconds": 72, "end_seconds": 91, "description": "A large explosion occurs, sending debris flying."},
    ],
}
FALL = {
    "incident": {"type": "assault", "start_timestamp": 1, "end_timestamp": 15},
    "entities": [
        {
            "entity_id": "E1",
            "type": "human",
            "label": "man in light shirt",
            "description": "",
            "timestamp_seconds": 1,
            "last_seen_seconds": 10,
        },
        {"entity_id": "E2", "type": "animal", "label": "black dog", "description": "", "timestamp_seconds": 2},
    ],
    "instruments": [],
    "assets": [
        {"asset_id": "A1", "name": "bench", "label": "wooden bench", "description": "", "timestamp_seconds": 12}
    ],
    "timeline": [
        {"start_seconds": 1, "end_seconds": 3, "description": "A black dog runs in and jumps on the man."},
        {
            "start_seconds": 3,
            "end_seconds": 5,
            "description": "The man falls to the ground as the dog continues to attack him.",
        },
        {
            "start_seconds": 5,
            "end_seconds": 7,
            "description": "The man struggles to get up while the dog remains nearby.",
        },
        {
            "start_seconds": 7,
            "end_seconds": 10,
            "description": "The man manages to stand up and walks away from the dog.",
        },
    ],
}


def _check(report: dict[str, Any], answer: str, **reply: Any) -> grounded_chat.RoutedAnswer:
    context = grounded_chat.routed_context(report, [])
    view = ra.report_view(report, [])
    full = {
        "answer": answer,
        "interpretation": "",
        "not_established": "",
        "citations": [],
        "insufficient_evidence": False,
        "video_could_answer": False,
        **reply,
    }
    return grounded_chat.check_routed(full, context, view, question="What happened?")


def test_the_end_of_an_event_given_as_the_moment_it_happened_is_not_linked():
    """Explosion041: the explosion event runs 1:12 to 1:31, and the answer said it exploded at 1:31."""
    answer = _check(FIRE, "The fire grew, and the vehicle exploded at 1:31.")
    assert answer.unknown_times == ("1:31",)


def test_the_stored_explosion041_reply_stays_unlinked_under_not_established():
    reply = "The report shows the fire intensifying and the vehicle exploding at 1:31, with no record of firefighting."
    answer = _check(
        FIRE, "The report does not mention any firefighters.", not_established=reply, insufficient_evidence=True
    )
    assert "1:31" in answer.unknown_times


def test_the_start_of_the_event_is_linked():
    assert _check(FIRE, "The vehicle exploded at 1:12.").unknown_times == ()


@pytest.mark.parametrize("words", ["by", "until", "till", "up to"])
def test_the_end_of_an_event_is_linked_when_the_text_says_it_is_an_end(words: str):
    assert _check(FALL, f"The man struggled to get up {words} 0:07.").unknown_times == ()


def test_a_range_must_match_the_events_it_describes():
    assert _check(FIRE, "The truck erupted in flames (0:06–0:11).").unknown_times == ()
    assert set(_check(FIRE, "The truck erupted in flames (0:06–0:30).").unknown_times) == {"0:06", "0:30"}


def test_a_range_over_two_described_events_is_linked():
    assert _check(FALL, "The dog jumped on him and he fell to the ground (0:01–0:05).").unknown_times == ()


def test_a_real_time_beside_the_wrong_event_is_not_linked():
    assert _check(FALL, "The man fell to the ground at 0:07.").unknown_times == ("0:07",)


def test_several_events_in_one_sentence_are_each_checked():
    answer = _check(
        FALL, "The dog jumped on the man at 0:01, he fell to the ground by 0:03, and he walked away at 0:30."
    )
    assert answer.unknown_times == ("0:30",)


def test_two_clauses_of_a_clause_keep_their_own_times():
    assert _check(FALL, "He fell to the ground at 0:03 and walked away by 0:10.").unknown_times == ()


def test_words_that_fit_two_events_are_settled_by_the_time_or_left_unlinked():
    assert _check(FALL, "The dog was near him at 0:05.").unknown_times == ()
    assert _check(FALL, "The dog was near him at 0:04.").unknown_times == ("0:04",)


def test_a_time_with_no_event_to_stand_beside_is_not_linked():
    assert _check(FALL, "It rained at 0:03.").unknown_times == ("0:03",)


def test_a_report_with_no_timeline_links_no_written_time():
    report = {**FALL, "timeline": []}
    assert _check(report, "He fell at 0:03.").unknown_times == ("0:03",)


def test_an_event_with_no_time_gets_none():
    report = {**FALL, "timeline": [{"description": "The man falls to the ground and struggles."}]}
    answer = _check(report, "The man fell to the ground and struggled.")
    assert ca._TIME.search(answer.content) is None


def test_an_items_own_second_is_linked_only_when_the_clause_describes_no_event():
    assert _check(FALL, "The wooden bench is seen at 0:12.").unknown_times == ()
    assert _check(FALL, "The man in light shirt walked away at 0:10.").unknown_times == ("0:10",), (
        "his last-seen second cannot vouch for the event's end"
    )


def test_the_incident_window_is_linked():
    assert _check(FALL, "The incident starts at 0:01.").unknown_times == ()


def test_a_clause_that_plainly_describes_an_event_gets_its_time_from_the_report():
    answer = _check(FALL, "He struggled to get up while the dog remained nearby.")
    assert answer.content == "He struggled to get up while the dog remained nearby (0:05–0:07)."
    assert answer.unknown_times == ()


def test_each_clause_of_a_joined_sentence_gets_its_own_events_time():
    answer = _check(
        FALL, "The man fell to the ground as the dog attacked, then he managed to stand up and walked away."
    )
    assert "(0:03–0:05)" in answer.content and "(0:07–0:10)" in answer.content


def test_an_event_gets_its_time_once():
    answer = _check(FALL, "He struggled to get up, while the dog remained nearby, struggling to get up nearby.")
    assert answer.content.count("(0:05–0:07)") == 1


def test_an_event_the_answer_already_times_gets_no_second_time():
    answer = _check(FALL, "He struggled to get up at 0:05.")
    assert answer.content == "He struggled to get up at 0:05."


def test_the_text_is_never_rewritten_only_added_to():
    written = "The man fell to the ground at 0:07, and the vehicle was seen at 9:59."
    assert _check(FALL, written).content == written


def test_a_time_already_written_for_another_event_does_not_stop_an_attachment():
    answer = _check(FALL, "He fell to the ground at 0:03. He struggled to get up while the dog remained nearby.")
    assert answer.content.endswith("nearby (0:05–0:07).")


def test_attached_times_are_never_reported_as_unsupported():
    answer = _check(FALL, "He struggled to get up while the dog remained nearby.")
    assert "0:05" in answer.content and answer.unknown_times == ()


def test_a_clause_describing_two_events_equally_gets_no_time():
    report = {
        **FALL,
        "timeline": [
            {"start_seconds": 1, "end_seconds": 3, "description": "The red van stops by the gate."},
            {"start_seconds": 5, "end_seconds": 7, "description": "The red van stops by the gate again."},
        ],
    }
    assert ca._TIME.search(_check(report, "The red van stopped by the gate.").content) is None


def test_a_vague_clause_gets_no_time():
    assert _check(FALL, "Something happened near the dog.").content == "Something happened near the dog."


def test_a_denial_or_a_description_of_an_object_gets_no_time():
    denied = "The report does not say the man struggled to get up."
    assert _check(FALL, denied).content == denied
    described = "The bench is described as a dog ground man bench."
    assert _check(FALL, described).content == described


def test_nothing_is_added_to_the_interpretation_or_what_is_not_established():
    answer = _check(FALL, "It is unclear.", interpretation="He struggled to get up while the dog remained nearby.")
    assert ca._TIME.search(answer.content) is None


def test_a_partial_answer_keeps_cards_for_what_it_affirms_and_none_for_what_it_denies():
    answer = _check(
        FALL,
        "The report does not mention a collar on the black dog; it records the man in light shirt falling.",
        insufficient_evidence=True,
    )
    assert answer.item_ids == ("E1",)


def test_a_flat_denial_has_no_card():
    answer = _check(FALL, "The report does not mention a collar on the black dog.", insufficient_evidence=True)
    assert answer.item_ids == ()


def test_a_card_does_not_depend_on_the_clause_having_a_time():
    assert _check(FALL, "The man in light shirt walked away at 0:30.").item_ids == ("E1",)


def test_item_ids_in_event_text_are_read_as_their_items():
    report = {**FALL, "timeline": [{"start_seconds": 3, "end_seconds": 5, "description": "E1 falls to the ground."}]}
    assert _check(report, "The man fell to the ground at 0:03.").unknown_times == ()
