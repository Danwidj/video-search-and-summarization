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
"""Ordinary questions against reports of different shapes: rich, sparse, untyped people, no people, malformed fields."""

from typing import Any

import pytest

from vss_agents.utils import chat_followups
from vss_agents.utils import chat_routing
from vss_agents.utils import grounded_chat
from vss_agents.utils import report_answers as ra


def _lift(**incident: Any) -> dict[str, Any]:
    """The shape that drew "This report records no people": people typed "unknown", timeline wording apart from labels."""
    return {
        "incident": {
            "type": "assault",
            "title": "Physical altercation in a lift",
            "start_timestamp": 0,
            "end_timestamp": 56,
            "description": "A man enters and fights another man, with one man appearing to be more aggressive.",
            "location": "lift lobby and interior",
            "severity_level": 3,
            "severity_reason": "Physical contact could escalate.",
            **incident,
        },
        "entities": [
            {
                "entity_id": "E1",
                "type": "unknown",
                "label": "person in white t-shirt",
                "description": "A person wearing a white shirt, standing in a hallway.",
                "first_seen_seconds": 3,
                "last_seen_seconds": 52,
            },
            {
                "entity_id": "E2",
                "type": "unknown",
                "label": "person in grey shirt",
                "description": "A person wearing a grey shirt, standing near a railing.",
                "first_seen_seconds": 0,
                "last_seen_seconds": 56,
            },
        ],
        "instruments": [],
        "assets": [],
        "timeline": [
            {"start_seconds": 0, "end_seconds": 3, "description": "A man in a white shirt enters the lift lobby."},
            {"start_seconds": 3, "end_seconds": 10, "description": "The man enters the lift and presses a button."},
            {"start_seconds": 10, "end_seconds": 30, "description": "The man fights another man inside the lift."},
            {"start_seconds": 30, "end_seconds": 38, "description": "The fight continues with pushing and shoving."},
            {"start_seconds": 38, "end_seconds": 56, "description": "The man leaves the other man inside."},
        ],
        "uncertainties": [
            "The exact cause of the fight is unclear.",
            "The extent of any injuries is not visible in the video.",
        ],
    }


def _no_listed_people() -> dict[str, Any]:
    report = _lift()
    report["entities"] = []
    return report


def _crash() -> dict[str, Any]:
    return {
        "incident": {
            "type": "road accident",
            "title": "Collision at a junction",
            "start_timestamp": 5,
            "end_timestamp": 20,
            "description": "A white van collides with a blue car and the driver is injured.",
            "location": "road junction",
            "severity_level": 4,
            "severity_reason": "A collision at speed.",
        },
        "entities": [],
        "instruments": [],
        "assets": [
            {"asset_id": "A1", "name": "white van", "label": "white van", "description": "", "timestamp_seconds": 6},
            {"asset_id": "A2", "name": "blue car", "label": "blue car", "description": "", "timestamp_seconds": 6},
        ],
        "timeline": [
            {"start_seconds": 5, "end_seconds": 8, "description": "The white van collides with the blue car."},
            {"start_seconds": 8, "end_seconds": 20, "description": "Smoke rises from the blue car."},
        ],
        "uncertainties": [],
    }


def _bear() -> dict[str, Any]:
    return {
        "incident": {
            "type": "animal attack",
            "title": "Bear in a shop",
            "start_timestamp": 0,
            "end_timestamp": 10,
            "description": "A bear walks through a shop.",
            "location": "shop interior",
            "severity_level": 2,
            "severity_reason": "Property only.",
        },
        "entities": [
            {
                "entity_id": "E1",
                "type": "animal",
                "label": "black bear",
                "description": "A black bear",
                "first_seen_seconds": 0,
                "last_seen_seconds": 10,
            }
        ],
        "instruments": [],
        "assets": [],
        "timeline": [{"start_seconds": 0, "end_seconds": 10, "description": "The bear pulls packets off a shelf."}],
        "uncertainties": [],
    }


def _theft() -> dict[str, Any]:
    return {
        "incident": {
            "type": "robbery",
            "title": "Till robbed",
            "start_timestamp": 2,
            "end_timestamp": 40,
            "description": "The robber threatens the cashier with a knife and takes the cash.",
            "location": "Unit 4, Mill Road",
            "severity_level": 5,
            "severity_reason": "A knife was used.",
        },
        "entities": [
            {"entity_id": "E1", "type": "human", "label": "man in black", "description": "A man in black"},
            {"entity_id": "E2", "type": "human", "label": "woman at the till", "description": "A woman at the till"},
        ],
        "instruments": [
            {
                "instrument_id": "I1",
                "entity_id": "E1",
                "name": "knife",
                "label": "knife",
                "description": "A kitchen knife",
                "threat_level": 4,
                "timestamp_seconds": 5,
            }
        ],
        "assets": [{"asset_id": "A1", "name": "cash", "label": "cash", "description": "", "timestamp_seconds": 20}],
        "timeline": [
            {"start_seconds": 5, "end_seconds": 15, "description": "E1 threatens E2 with I1."},
            {"start_seconds": 20, "end_seconds": 25, "description": "E1 takes the cash from the till."},
        ],
        "uncertainties": [],
    }


def _answer(question: str, report: dict[str, Any]) -> ra.ComposedAnswer:
    return ra.compose(question, ra.report_view(report))


def _followup(turns: list[str], report: dict[str, Any]) -> ra.ComposedAnswer | None:
    roles = ("user", "assistant")
    history = [{"role": roles[n % 2], "content": text} for n, text in enumerate(turns)]
    return chat_followups.resolve(turns[-1], history, ra.report_view(report))


# The two reported failures, and their paraphrases.


@pytest.mark.parametrize(
    "question",
    [
        "who are involved",
        "Who was involved?",
        "Who are the people in the video?",
        "who were the ppl involved",
        "who was involed",
        "Which individuals are in this?",
    ],
)
def test_people_typed_unknown_are_people(question: str) -> None:
    answer = _answer(question, _lift())
    assert answer.kind == "people" and answer.item_ids == ("E1", "E2")
    assert answer.text.startswith("Two people are involved: a person wearing a white shirt")
    assert answer.text.endswith("The report does not establish their identities.")


@pytest.mark.parametrize(
    "question",
    [
        "where the incident take place",
        "Where did the incident take place?",
        "Where did this happen?",
        "Where was the incident?",
        "where did it occur",
        "wher did it hapen",
        "what was the location",
        "Location?",
        "whats the location of this incident",
    ],
)
def test_a_location_question_gets_the_location_and_never_the_theft_answer(question: str) -> None:
    answer = _answer(question, _lift())
    assert answer.kind == "location"
    assert answer.text == (
        "The report gives the location as: lift lobby and interior. "
        "The report does not specify the exact building or address."
    )


def test_a_location_that_gives_an_address_does_not_deny_one() -> None:
    assert _answer("Where was it?", _theft()).text == "The report gives the location as: unit 4, Mill Road."


def test_a_report_with_no_location_names_what_its_text_mentions_or_says_it_does_not_say() -> None:
    report = _lift(location=None)
    answer = _answer("Where did it happen?", report)
    assert answer.text.startswith("The report records no location, but") or "doesn't record" in answer.text
    bare = {"incident": {"type": "assault"}, "timeline": [{"description": "Two men argue."}]}
    assert _answer("Where did it happen?", bare).text == "The report doesn't record where this happened."


def test_where_about_a_named_item_or_a_movement_is_not_the_incident_location() -> None:
    assert _answer("Where was the knife?", _theft()).kind != "location"
    assert _answer("Where did the man go?", _lift()).kind != "location"


@pytest.mark.parametrize(
    ("question", "kind"),
    [
        ("What was taken?", "taken"),
        ("what did they take", "taken"),
        ("Was anything stolen?", "taken"),
        ("was anything stollen", "taken"),
    ],
)
def test_a_taking_is_still_a_taking(question: str, kind: str) -> None:
    answer = _answer(question, _theft())
    assert answer.kind == kind and "the cash" in answer.text


@pytest.mark.parametrize("question", ["Who took part?", "What action did the man take?"])
def test_take_in_a_phrase_is_no_taking(question: str) -> None:
    assert _answer(question, _theft()).kind != "taken"


def test_an_empty_people_list_is_not_a_statement_that_nobody_was_there() -> None:
    answer = _answer("who are involved", _no_listed_people())
    assert answer.kind == "people_described"
    assert "people list" not in answer.text and "0:10\u20130:30 The man fights another man" in answer.text
    assert "records no people" not in answer.text


def test_people_only_in_the_description_are_found_too() -> None:
    report = {"incident": {"description": "A man hits a woman."}, "entities": []}
    answer = _answer("who was involved?", report)
    assert answer.kind == "people_described" and "A man hits a woman." in answer.text


def test_described_people_are_not_counted() -> None:
    assert "It gives no count" in _answer("How many people were involved?", _no_listed_people()).text


def test_a_report_with_animals_only_shows_them_instead_of_no_people() -> None:
    answer = _answer("who was involved?", _bear())
    assert answer.text.startswith("The report describes no people. It records a black bear")
    assert answer.item_ids == ("E1",)


def test_a_report_with_nobody_says_so() -> None:
    assert _answer("who was involved?", _crash()).kind == "people_described"  # "the driver" in its description
    report = _crash()
    report["incident"]["description"] = "Two vehicles collide."
    assert _answer("who was involved?", report).text == "This report records no people."


@pytest.mark.parametrize("question", ["Who is the attacker?", "Who attacked first?", "Who started it?"])
def test_nobody_is_called_the_attacker_on_the_answer_s_own_authority(question: str) -> None:
    text = _answer(question, _lift()).text
    assert "does not establish" in text or "doesn't state" in text
    assert "attacker is the" not in text and "white t-shirt" not in text


def test_the_report_s_own_role_wording_is_quoted() -> None:
    answer = _answer("Who is the attacker?", _theft())
    assert answer.kind == "role" and "The robber threatens the cashier" in answer.text


def test_who_is_the_victim_is_not_guessed() -> None:
    answer = _answer("Who is the victim?", _lift())
    assert answer.text.startswith("The report does not establish who the victim is.")
    assert answer.insufficient_evidence


def test_a_name_the_report_lacks_gets_what_it_does_establish() -> None:
    answer = _answer("What is the full name of the attacker?", _lift())
    assert answer.text.startswith("The report doesn't give anyone's name or identity. It describes two people:")
    assert "No people" not in answer.text


@pytest.mark.parametrize("question", ["Was anyone injured?", "was anybody hurt", "did anyone get hurt?"])
def test_an_injury_question_is_not_answered_with_weapons(question: str) -> None:
    answer = _answer(question, _lift())
    assert answer.kind == "injury" and "weapon" not in answer.text
    assert answer.text.startswith("The report doesn't state whether anyone was injured.")
    assert "The extent of any injuries is not visible in the video." in answer.text


def test_a_stated_injury_is_quoted_and_silence_is_not_a_denial() -> None:
    assert "the driver is injured" in _answer("Was anyone injured?", _crash()).text
    assert _answer("Was anyone injured?", _bear()).text == "The report doesn't state whether anyone was injured."


def test_what_could_cause_harm_is_still_the_instruments() -> None:
    assert _answer("What could cause harm?", _theft()).kind == "harm"


def test_a_cause_the_report_could_not_establish_says_so_with_what_it_records() -> None:
    answer = _answer("What caused the incident?", _lift())
    assert answer.kind == "cause" and answer.text.startswith("The report doesn't state what caused the incident.")
    assert "The exact cause of the fight is unclear." in answer.text and "0:10\u20130:30" in answer.text


@pytest.mark.parametrize(
    ("question", "shown", "hidden"),
    [
        ("What happened at 0:32?", "0:30\u20130:38", "0:10\u20130:30"),
        ("what was going on at 5 seconds?", "0:03\u20130:10", "0:30\u20130:38"),
        ("What happened after 0:38?", "0:38\u20130:56", "0:30\u20130:38"),
        ("What happened before 0:10", "0:03\u20130:10", "0:38\u20130:56"),
        ("what happened between 0:31 and 0:40?", "0:30\u20130:38", "0:00\u20130:03"),
    ],
)
def test_a_moment_gets_its_events_with_their_times_and_not_the_whole_timeline(
    question: str, shown: str, hidden: str
) -> None:
    answer = _answer(question, _lift())
    assert answer.kind == "moment" and shown in answer.text and hidden not in answer.text


def test_a_moment_with_no_event_is_labelled_as_nearest() -> None:
    answer = _answer("What happened at 0:50?", _crash())
    assert answer.text.startswith("The report records nothing at 0:50. The nearest it records is:")
    assert "0:08\u20130:20" in answer.text


def test_a_moment_keeps_its_evidence() -> None:
    assert _answer("What happened at 0:22?", _theft()).item_ids == ("E1", "A1")


def test_a_moment_with_no_timeline_says_so() -> None:
    answer = _answer("What happened at 0:30?", {"incident": {"description": "A fight."}})
    assert answer.insufficient_evidence and "no timed events" in answer.text


def test_the_moment_a_question_describes_is_the_event_that_fits_it_best() -> None:
    answer = _answer("What happened after the man entered the lift?", _lift())
    assert answer.text.startswith("The report puts that moment at 0:03.")


@pytest.mark.parametrize(
    "question", ["What is the weather tomorrow?", "tell me a joke", "What is the capital of France?"]
)
def test_a_question_about_something_else_is_redirected_to_the_incident(question: str) -> None:
    answer = _answer(question, _lift())
    assert answer.kind == "out_of_scope" and answer.text == ra.OUT_OF_SCOPE and answer.item_ids == ()


def test_a_report_that_mentions_the_topic_still_answers() -> None:
    report = _lift()
    report["timeline"][0]["description"] = "The weather turns as the man enters."
    assert _answer("What is the weather?", report).kind != "out_of_scope"
    assert _answer("What was the weather during the incident?", _lift()).kind != "out_of_scope"


def test_greetings_and_thanks_are_answered_politely() -> None:
    assert _answer("hello", _lift()).text == ra.GREETING
    assert _answer("thanks!", _lift()).text == ra.YOU_ARE_WELCOME


def test_a_reversed_window_is_shown_and_neither_end_is_picked() -> None:
    text = _answer("When did it happen?", _lift(start_timestamp=40, end_timestamp=10)).text
    assert "The report is inconsistent here: its incident ends at 0:10 but starts at 0:40." in text


@pytest.mark.parametrize(
    "report",
    [
        {"incident": "nonsense", "entities": 5, "instruments": "x", "assets": None, "timeline": 7, "uncertainties": 3},
        {"incident": {}, "entities": [1, "x", None], "timeline": ["a", {}], "uncertainties": "a sentence"},
        {},
    ],
)
@pytest.mark.parametrize(
    "question", ["who was involved", "where did it happen", "what happened", "what happened at 0:30", "was anyone hurt"]
)
def test_malformed_fields_never_crash_an_answer(report: dict[str, Any], question: str) -> None:
    view = ra.report_view(report, evidence=[1, "x"])  # type: ignore[list-item]
    assert ra.compose(question, view).text
    assert grounded_chat.routed_context(report, [1, "x"])["items"] == []  # type: ignore[list-item]


def test_a_string_uncertainty_field_is_not_read_letter_by_letter() -> None:
    assert ra.report_view({"uncertainties": "not a list"}).uncertainties == ()


def test_a_missing_field_uses_what_else_the_report_holds() -> None:
    report = _lift()
    del report["timeline"]
    answer = _answer("What happened?", report)
    assert answer.kind == "chronology" and "A man enters and fights another man" in answer.text


# Routing: only what code answers in full skips the model.


@pytest.mark.parametrize(
    "question",
    [
        "where the incident take place",
        "Where did this happen?",
        "What happened at 0:30?",
        "What is the weather tomorrow?",
    ],
)
def test_these_need_no_model(question: str) -> None:
    assert chat_routing.decide(question, ra.report_view(_lift())).route == "deterministic"


@pytest.mark.parametrize(
    "question",
    [
        "Who is the attacker?",
        "Who attacked first?",
        "Was anyone injured?",
        "What caused the incident?",
        "What is the name of the building where this happened?",
        "What colour was the car at 0:30?",
    ],
)
def test_these_are_read_by_the_model_in_routed_mode(question: str) -> None:
    assert chat_routing.decide(question, ra.report_view(_lift())).route == "report_llm"


def test_people_found_only_in_text_are_read_by_the_model_in_routed_mode() -> None:
    assert chat_routing.decide("who are involved", ra.report_view(_no_listed_people())).route == "report_llm"


# Follow-ups.


def test_what_happened_next_follows_the_last_event_the_answer_told() -> None:
    answer = _followup(
        ["What happened at 0:05?", "\u2022 0:03\u20130:10 The man enters.", "What happened next?"], _lift()
    )
    assert answer is not None and answer.kind == "sequence" and "0:10\u20130:30" in answer.text
    assert "0:30\u20130:38" not in answer.text


def test_what_happened_before_that_steps_back() -> None:
    answer = _followup(
        ["What happened at 0:32?", "\u2022 0:30\u20130:38 It goes on.", "what happened before that"], _lift()
    )
    assert answer is not None and "0:10\u20130:30" in answer.text


def test_next_after_the_last_event_says_nothing_follows() -> None:
    answer = _followup(["At 0:40?", "\u2022 0:38\u20130:56 The man leaves.", "and then?"], _lift())
    assert answer is not None and answer.text == "The report records nothing after that."


def test_a_person_s_seen_times_are_not_events() -> None:
    answer = _followup(["Who?", "A man (seen from 0:44 to 0:55).", "what happened next"], _lift())
    assert answer is not None and answer.text.startswith("After which moment?")


def test_what_happened_next_with_nothing_before_it_asks() -> None:
    answer = _followup(["What happened next?"], _lift())
    assert answer is not None and answer.kind == "clarify"


def test_an_ambiguous_pronoun_gets_a_question_naming_the_people() -> None:
    answer = _followup(["What happened to him?"], _lift())
    assert answer is not None and answer.kind == "clarify" and answer.item_ids == ()
    assert answer.text == "Which person do you mean: the person in white t-shirt or the person in grey shirt?"


def test_a_pronoun_is_resolved_by_the_person_the_last_turn_named() -> None:
    answer = _followup(["Who is the person in grey shirt?", "A person in grey.", "What happened to him?"], _lift())
    assert answer is not None and answer.kind != "clarify"


def test_a_pronoun_is_resolved_by_the_report_s_only_person() -> None:
    report = _theft()
    report["entities"] = report["entities"][:1]
    answer = _followup(["What did he do?"], report)
    assert answer is not None and answer.item_ids and answer.kind != "clarify"


def test_a_pronoun_is_resolved_by_who_it_can_fit() -> None:
    answer = _followup(["What happened to her?"], _theft())
    assert answer is not None and answer.kind != "clarify" and "woman at the till" in answer.text


def test_a_question_that_names_someone_stands_alone() -> None:
    assert _followup(["What did the man in black do?"], _theft()) is None


def test_a_name_question_needs_no_person_picked() -> None:
    assert _followup(["What is his name?"], _lift()) is None
    assert _answer("What is his name?", _lift()).kind == "identity"


def test_two_people_described_alike_are_not_named_as_one() -> None:
    report = _lift()
    report["entities"][1]["label"] = "person in white t-shirt"
    answer = _followup(["What happened to him?"], report)
    assert answer is not None and "alike" in answer.text
