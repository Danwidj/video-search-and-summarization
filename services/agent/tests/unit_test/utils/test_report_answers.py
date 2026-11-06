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
"""Answers composed from one incident report: references resolved, kinds of question, no ids in the prose."""

from __future__ import annotations

import pytest

from vss_agents.utils import report_answers as ra


def _report(**overrides):
    report = {
        "incident": {
            "type": "burglary",
            "title": "Shop door forced",
            "start_timestamp": 5,
            "end_timestamp": 65,
            "description": "E1 forces the door with I1.",
            "severity_level": 3,
            "severity_reason": "Property damage only.",
        },
        "entities": [
            {
                "entity_id": "E1",
                "type": "person",
                "description": "Person in a dark hood",
                "label": "hooded person",
                "first_seen_seconds": 5,
                "last_seen_seconds": 60,
            }
        ],
        "instruments": [
            {
                "instrument_id": "I1",
                "entity_id": "E1",
                "name": "crowbar",
                "description": "Pry bar",
                "threat_level": 3,
                "timestamp_seconds": 12,
            }
        ],
        "assets": [
            {"asset_id": "A1", "name": "shop door", "description": "Glass door of the shop", "timestamp_seconds": 12}
        ],
        "timeline": [
            {"start_seconds": 12, "end_seconds": 20, "description": "E1 forces A1 open with I1."},
            {"start_seconds": 5, "end_seconds": None, "description": "E1 walks to A1."},
        ],
    }
    report.update(overrides)
    return report


def test_clock_matches_the_console():
    assert [ra.clock(v) for v in (0, 9.9, 61, 3600, 3725, None, "7", True)] == [
        "0:00",
        "0:09",
        "1:01",
        "1:00:00",
        "1:02:05",
        None,
        None,
        None,
    ]


def test_references_resolve_to_descriptions_and_parenthesised_ids_are_dropped():
    mentions = {"E1": "the hooded person", "I1": "the crowbar"}
    assert ra.resolve_references("E1 (E1) forces the door with I1.", mentions) == (
        "The hooded person forces the door with the crowbar."
    )
    assert ra.resolve_references("a person (E1, I1) waits", mentions) == "A person waits"
    assert ra.resolve_references("Q9 stays", mentions) == "Q9 stays", "an id the report does not hold is kept"
    assert ra.resolve_references("E10 left", {"E1": "x"}) == "A person left", "whole tokens: E1 never matches in E10"
    assert ra.referenced_ids("E1 hands I1 to E1", ["E1", "I1"]) == ["E1", "I1"]


def test_the_timeline_is_sorted_by_start_and_ties_keep_their_order():
    view = ra.report_view(
        _report(
            timeline=[
                {"start_seconds": 9, "description": "b"},
                {"start_seconds": None, "description": "z"},
                {"start_seconds": 3, "description": "a"},
                {"start_seconds": 9, "description": "c"},
                {"description": " "},
            ]
        )
    )
    assert [e["description"] for e in view.timeline] == ["a", "b", "c", "z"]


def test_a_revision_saved_without_its_report_falls_back_to_its_evidence():
    view = ra.report_view(
        None,
        [
            {
                "item_type": "instrument",
                "item_id": "I1",
                "item_name": "crowbar",
                "description": "Pry bar",
                "timestamp_seconds": 8,
            },
            {
                "item_type": "entity",
                "item_id": "E1",
                "item_name": "person",
                "label": "hooded person",
                "box_seconds": 12,
            },
        ],
    )
    assert [(i.kind, i.item_id, i.seconds) for i in view.items] == [("instrument", "I1", 8.0), ("entity", "E1", 12.0)]
    assert view.items[1].is_person and view.mentions() == {"I1": "the crowbar", "E1": "the hooded person"}


@pytest.mark.parametrize(
    ("question", "kind", "start"),
    [
        (
            "What happened, in order?",
            "chronology",
            "The report describes a burglary from 0:05 to 1:05.\n\n"
            "\u2022 0:05 The hooded person walks to the shop door.\n"
            "\u2022 0:12\u20130:20 The hooded person forces the shop door open with the crowbar.",
        ),
        ("When did it start?", "time", "The incident runs from 0:05 to 1:05 in the video (60 seconds)."),
        ("Who is involved?", "people", "One person is involved: a person in a dark hood (seen from 0:05 to 1:00)."),
        ("Which tools were used?", "objects", "Objects used: a crowbar (pry bar), held by the hooded person"),
        ("Who held the crowbar?", "people", "The crowbar is held by a person in a dark hood."),
        ("How serious was it?", "severity", "The report rates the severity 3 of 5 (medium): property damage only."),
        ("What type of incident is this?", "type", "It is a burglary: Shop door forced."),
        ("Is there a dog?", "absent", 'This report doesn\'t mention "dog". It records one person and two objects'),
        ("What colour was the sky?", "unanswerable", 'This report doesn\'t mention "colour" and "sky".'),
    ],
)
def test_each_kind_of_question_gets_its_answer(question, kind, start):
    answer = ra.compose(question, ra.report_view(_report()))
    assert answer.kind == kind and answer.text.startswith(start), answer.text
    assert not ra._ID.search(answer.text)
    assert answer.insufficient_evidence == (kind in ("absent", "unanswerable"))
    assert (answer.item_ids == ()) == (kind in ("absent", "unanswerable", "time", "type", "severity"))


def test_without_a_timeline_the_description_answers_and_without_either_the_report_cannot():
    described = ra.compose("What happened?", ra.report_view(_report(timeline=[])))
    assert described.text.startswith(
        "The report has no event-by-event timeline. It describes the incident as follows: "
        "The hooded person forces the door with the crowbar."
    )
    assert described.item_ids == ("E1", "I1")
    bare = ra.compose("What happened?", ra.report_view({"incident": {"type": "burglary"}}))
    assert bare.insufficient_evidence and bare.item_ids == ()


def test_a_long_timeline_is_told_up_to_twelve_events():
    events = [{"start_seconds": 5 + s, "description": f"Step {s}."} for s in range(14)]
    answer = ra.compose("What happened?", ra.report_view(_report(timeline=events)))
    assert "0:16 Step 11." in answer.text and "Step 12" not in answer.text
    assert answer.text.endswith("The timeline records two more events.")


def _chronology(**overrides):
    return ra.compose("What happened, in order?", ra.report_view(_report(**overrides)))


def _asset(asset_id, name, label=""):
    return {"asset_id": asset_id, "name": name, "description": "", "label": label, "timestamp_seconds": 0}


def _entity(entity_id, label, kind="human"):
    return {"entity_id": entity_id, "type": kind, "description": "", "label": label, "timestamp_seconds": 0}


def _cited(*events, entities=(), assets=(), instruments=()):
    report = _report(
        entities=list(entities),
        assets=list(assets),
        instruments=list(instruments),
        timeline=[_event(10 + n, None, text) for n, text in enumerate(events)],
    )
    return list(ra.compose("What happened?", ra.report_view(report)).item_ids)


def test_a_chronology_cites_the_items_its_events_name_and_not_the_others():
    assert _cited(
        "The dog approaches the coffee table and knocks over the vase of sunflowers.",
        "The vase shatters on the floor, spilling the sunflowers.",
        "The dog jumps onto the coffee table and then jumps down.",
        entities=[_entity("E1", "black and tan dog", "animal")],
        assets=[
            _asset("A1", "vase", "broken vase with sunflowers"),
            _asset("A2", "coffee table", "wooden coffee table"),
            _asset("A3", "sofa", "white sectional sofa"),
        ],
    ) == ["E1", "A2", "A1"], "each once, in the order the events name them; the sofa is never mentioned"


def test_an_event_id_is_a_citation_even_when_the_item_is_not_named():
    assert _cited("E2 strikes.", "A1 falls.", entities=[_entity("E2", "man")], assets=[_asset("A1", "vase")]) == [
        "E2",
        "A1",
    ]


def test_ids_and_names_combine_in_one_answer():
    assert _cited("E2 lifts the vase.", entities=[_entity("E2", "man in blue")], assets=[_asset("A1", "vase")]) == [
        "E2",
        "A1",
    ]


def test_no_named_item_means_no_citations_and_never_every_person():
    assert (
        _cited(
            "Smoke fills the road.",
            entities=[_entity("E1", "person near billboard"), _entity("E2", "person near car")],
            assets=[_asset("A1", "billboard")],
        )
        == []
    )


def test_a_person_is_matched_by_label_or_outfit_whatever_the_articles():
    assert _cited(
        "The man in dark shorts attacks the man in the dark pants.",
        entities=[
            _entity("E1", "man in white shirt and dark pants"),
            _entity("E2", "man in white shirt and dark shorts"),
            _entity("E3", "pedestrian with large bag"),
        ],
    ) == ["E2", "E1"]
    assert _cited("A person wearing a dark jacket enters.", entities=[_entity("E1", "person in dark jacket")]) == ["E1"]


def test_a_head_word_counts_only_when_one_entity_has_it():
    assert _cited("The child opens the door.", entities=[_entity("E1", "child in white shirt")]) == ["E1"]
    assert _cited("The bear runs.", entities=[_entity("E1", "black bear", "animal")]) == ["E1"]
    two_men = [_entity("E1", "man in light shirt"), _entity("E2", "man in dark shirt")]
    assert _cited("The man walks away.", entities=two_men) == []


def test_text_that_could_mean_several_items_cites_none_of_them():
    cars = [_asset("A1", "car", "silver hatchback"), _asset("A2", "car", "white sedan")]
    assert _cited("The car stops.", assets=cars) == []
    same_label = [_entity("E1", "man in light shirt"), _entity("E2", "man in light shirt")]
    assert _cited("A man in a light shirt runs.", entities=same_label) == []


def test_the_longest_name_decides_which_item_the_text_means():
    vans = [_asset("A1", "van", "white van"), _asset("A2", "van", "blue van")]
    assert _cited("The white van stops.", assets=vans) == ["A1"]


def test_one_object_filed_twice_gets_one_citation():
    instrument = {"instrument_id": "I1", "name": "till", "label": "till", "description": "", "timestamp_seconds": 3}
    assert _cited(
        "He empties the till.", "He closes the till.", instruments=[instrument], assets=[_asset("A1", "till", "till")]
    ) == ["I1"]


def test_a_label_after_its_connector_names_nothing():
    backpack = _asset("A1", "backpack", "backpack on ground")
    assert _cited("He remains on the ground.", assets=[backpack]) == [], "'on ground' is not the backpack"
    assert _cited("He sits at the table.", assets=[_asset("A1", "chair", "chairs and table")]) == []


def test_a_name_inside_a_longer_word_or_a_vague_label_does_not_match():
    assert _cited("He enters the bathroom.", assets=[_asset("A1", "bat")]) == []
    assert _cited("He holds an object.", assets=[_asset("A1", "", "object")]) == []


def test_plural_and_label_tail_forms_match():
    assert _cited("Two vases fall.", assets=[_asset("A1", "vase")]) == ["A1"]
    assert _cited("He leans on the display rack.", assets=[_asset("A1", "toy display", "aisle display rack")]) == ["A1"]


def test_a_typed_and_a_suggested_chronology_cite_the_same_items():
    view = ra.report_view(_report())
    answers = [
        ra.compose(q, view) for q in ("What happened?", "What happened, in order?", "Show the timeline of events")
    ]
    assert {a.item_ids for a in answers} == {("E1", "A1", "I1")}
    assert {a.text for a in answers} == {answers[0].text}


def test_the_description_fallback_and_a_taking_cite_by_name_too():
    assets = [_asset("A1", "safe"), _asset("A2", "sofa")]
    no_timeline = _report(
        incident={"type": "burglary", "description": "The safe is forced."}, assets=assets, timeline=[], instruments=[]
    )
    assert ra.compose("What happened?", ra.report_view(no_timeline)).item_ids == ("A1",)
    taking = _report(assets=assets, instruments=[], timeline=[_event(10, None, "He steals the safe.")])
    assert ra.compose("Was anything taken?", ra.report_view(taking)).item_ids == ("A1",)


def test_an_item_removed_in_a_draft_is_not_cited_by_its_old_name():
    base = _report(assets=[_asset("A1", "vase")], instruments=[], timeline=[_event(10, None, "The vase falls.")])
    draft = {"incident": {"description": "x"}, "entities": base["entities"], "instruments": [], "assets": []}
    report = ra.overlay_draft(base, draft)
    view = ra.report_view(report, retired=ra.item_ids(base) - ra.item_ids(report))
    assert "A1" not in ra.compose("What happened?", view).item_ids


def _event(start, end, description):
    return {"start_seconds": start, "end_seconds": end, "description": description}


def test_every_event_is_told_once_in_time_order_with_its_report_time():
    events = [_event(30, 31, "Third."), _event(10, 10, "First."), _event(20, None, "Second."), _event(10, 40, "Tied.")]
    lines = [line for line in _chronology(timeline=events).text.split("\n") if line.startswith("\u2022")]
    assert lines == [
        "\u2022 0:10 First.",
        "\u2022 0:10\u20130:40 Tied.",
        "\u2022 0:20 Second.",
        "\u2022 0:30\u20130:31 Third.",
    ]


def test_an_overlapping_last_event_is_not_called_final():
    events = [_event(5, 60, "The fight goes on."), _event(12, 20, "A bystander shouts.")]
    assert "Finally" not in _chronology(timeline=events).text


def test_events_outside_the_incident_window_are_context_not_dropped():
    events = [_event(2, 4, "He enters."), _event(10, 20, "He strikes."), _event(70, 75, "He leaves the area.")]
    text = _chronology(timeline=events).text
    assert text.index("Before the incident:\n\u2022 0:02\u20130:04 He enters.") < text.index("During the incident:")
    assert text.index("During the incident:\n\u2022 0:10\u20130:20 He strikes.") < text.index("After the incident:")
    assert "After the incident:\n\u2022 1:10\u20131:15 He leaves the area." in text
    assert text.startswith("The report describes a burglary from 0:05 to 1:05.\n\n")


def test_an_event_running_into_the_window_belongs_to_the_incident():
    assert (
        "incident:" not in _chronology(timeline=[_event(2, 8, "He forces the door."), _event(60, 70, "He runs.")]).text
    )


def test_with_all_events_inside_the_window_there_are_no_headings():
    assert "incident:" not in _chronology().text


def test_with_no_window_or_no_event_time_nothing_is_placed_outside():
    incident = {"type": "burglary", "description": "A break-in."}
    assert "incident:" not in _chronology(incident=incident, timeline=[_event(2, 4, "He enters.")]).text
    untimed = _chronology(timeline=[{"description": "He enters."}, _event(10, 20, "He strikes.")]).text
    assert "incident:" not in untimed
    assert "\u2022 He enters." in untimed, "no time is invented for an event without one"


def test_a_chronology_adds_only_uncertainties_about_what_it_tells():
    text = _chronology(
        uncertainties=[
            "It is unclear whether the crowbar was brought to the scene.",
            "The weather outside cannot be determined.",
            "The identities of the people are not clear.",
        ]
    ).text
    assert text.endswith(
        "What the report could not establish:\n\u2022 It is unclear whether the crowbar was brought to the scene."
    )
    assert "weather" not in text and "identities" not in text


def test_uncertainties_read_without_ids_are_shown_once_and_are_capped():
    same = "It is unclear what I1 is."
    text = _chronology(
        uncertainties=[
            same,
            "It is unclear what I1 is",
            "The door may be locked.",
            "The shop door lock is unclear.",
            "The door handle is unclear.",
            "The door frame is unclear.",
        ]
    ).text
    block = text.split("What the report could not establish:\n")[1]
    assert block.split("\n")[0] == "\u2022 It is unclear what the crowbar is."
    assert block.count("\u2022") == 3
    assert not ra._ID.search(text)


def test_an_uncertainty_can_relate_through_the_incident_description():
    report = {"title": "Altercation at the door", "description": "Two men argue."}
    text = _chronology(
        incident={**_report()["incident"], **report}, uncertainties=["The cause of the altercation is not clear."]
    ).text
    assert "The cause of the altercation is not clear." in text


def test_a_chronology_with_no_uncertainties_has_no_block():
    assert "could not establish" not in _chronology(uncertainties=[]).text
    assert "could not establish" not in _chronology().text
    assert "could not establish" not in _chronology(uncertainties=["", 3, None]).text


def test_the_description_fallback_keeps_its_relevant_uncertainty_and_invents_no_time():
    text = _chronology(timeline=[], uncertainties=["It is unclear who forces the door."]).text
    assert text.startswith("The report has no event-by-event timeline.")
    assert text.endswith("What the report could not establish:\n\u2022 It is unclear who forces the door.")


def test_a_question_about_one_item_keeps_its_lead_and_stays_short():
    answer = ra.compose(
        "What happened to the crowbar?",
        ra.report_view(_report(uncertainties=["It is unclear whether the crowbar was brought."])),
    )
    assert answer.text.startswith("Here is what the report records about the crowbar, in order:\n\u2022 0:12")
    assert "could not establish" not in answer.text


def test_search_hits_are_grouped_by_incident_without_ids():
    one = ra.compose_hits(
        [
            {
                "item": {"item_type": "instrument", "name": "crowbar", "timestamp_seconds": 8},
                "incident": {"incident_id": "V1", "incident_type": "burglary"},
            },
            {"item": {"item_type": "asset", "name": "door"}, "incident": {"incident_id": "V1"}},
        ]
    )
    assert one == "I found two matching items in a burglary: a crowbar (seen at 0:08) and a door."


def test_ids_the_report_no_longer_holds_read_neutrally_and_other_tokens_stay():
    mentions = ra.Mentions({"E1": "the guard", "new-E2": "the courier"})
    mentions.retired = frozenset({"A2"})
    assert ra.resolve_references("new-E2 hands E1 a parcel.", mentions) == "The courier hands the guard a parcel."
    assert ra.resolve_references("new-E3 waits; E7 drops I9.", mentions) == "A person waits; a person drops an object."
    assert ra.resolve_references("E1 takes A2 from the A1 shelf of A4 paper.", mentions) == (
        "The guard takes an item from the A1 shelf of A4 paper."
    )
    assert ra.resolve_references("xE1, E1x and E1-2 are not ids", mentions) == "XE1, E1x and E1-2 are not ids"
    assert ra.replaced_ids("new-E2 and E7 meet near A4 paper", mentions) == ["new-E2", "E7"]
    assert ra.referenced_ids("new-E2 hands E1 a parcel", ["E1", "E2", "new-E2"]) == ["new-E2", "E1"]


def test_a_draft_is_overlaid_on_its_base_version():
    base = _report()
    draft = {
        "incident": {"type": "robbery", "description": "E1 forces the door."},
        "entities": [{"entity_id": "E1", "type": "person", "description": "Person in a dark hood"}],
        "instruments": [],
        "assets": [],
    }
    report = ra.overlay_draft(base, draft)
    assert report["incident"]["type"] == "robbery" and report["incident"]["title"] == "Shop door forced"
    assert report["timeline"] == base["timeline"] and report["instruments"] == []
    retired = ra.item_ids(base) - ra.item_ids(report)
    assert retired == {"I1", "A1"}
    view = ra.report_view(report, retired=retired)
    answer = ra.compose("What happened, in order?", view)
    assert "0:05 The person in a dark hood walks to an item." in answer.text
    assert "The person in a dark hood forces an item open with an object" in answer.text
    assert not ra._ID.search(answer.text)


@pytest.mark.parametrize(
    ("question", "start", "kind"),
    [
        (
            "Did the hooded person steal anything?",
            "The report doesn't say the hooded person took anything. What it records about the hooded person, in "
            "order: At 0:05, the hooded person walks to the shop door.",
            "taken",
        ),
        ("Was the door broken?", "Here is what the report records about the shop door, in order:", "chronology"),
        ("Is there a crowbar?", "Yes: the report records a crowbar (pry bar)", "objects"),
        ("Any crowbars?", "Yes: the report records a crowbar (pry bar)", "objects"),
    ],
)
def test_yes_is_said_only_to_a_bare_existence_question(question, start, kind):
    answer = ra.compose(question, ra.report_view(_report()))
    assert answer.text.startswith(start) and answer.kind == kind, answer.text
    if kind in ("chronology", "taken"):
        assert "Yes" not in answer.text


def test_a_yes_no_question_about_an_item_with_no_event_says_the_report_does_not_answer():
    report = _report(timeline=[{"start_seconds": 5, "description": "E1 walks in."}])
    answer = ra.compose("Was the door broken?", ra.report_view(report))
    assert answer.text == "The report records the shop door but says nothing more about it that answers this."
    assert answer.insufficient_evidence and answer.item_ids == ()


def test_plurals_match_singulars_and_missing_words_are_quoted_as_asked():
    report = _report(instruments=[{"instrument_id": "I1", "entity_id": "E1", "name": "knife", "threat_level": 4}])
    found = ra.compose("Were there any knives?", ra.report_view(report))
    assert found.text.startswith("Yes: the report records a knife"), found.text
    missing = ra.compose("Were there any witnesses?", ra.report_view(report))
    assert missing.text.startswith('This report doesn\'t mention "witnesses".'), missing.text


def test_labels_that_name_each_other_never_put_an_id_in_the_prose():
    report = _report(
        entities=[
            {"entity_id": "E1", "type": "person", "label": "man beside E2", "description": "Man beside E2"},
            {"entity_id": "E2", "type": "person", "label": "man beside E1", "description": "Man beside E1"},
        ]
    )
    view = ra.report_view(report)
    assert all(not ra._ID.search(m) for m in view.mentions().values()), view.mentions()
    for question in ("Who is involved?", "What happened, in order?", "Is there a dog?"):
        assert not ra._ID.search(ra.compose(question, view).text), question


# -- "what was taken?" and "what could cause harm?": answered from the report, each part of a compound question ----


def test_a_taking_in_the_timeline_answers_what_was_taken():
    report = _report(
        timeline=[{"start_seconds": 30, "end_seconds": 40, "description": "E1 takes the till drawer and runs."}]
    )
    answer = ra.compose("What was stolen?", ra.report_view(report))
    assert (
        answer.text
        == "The report records this taking: From 0:30 to 0:40, the hooded person takes the till drawer and runs."
    )
    assert answer.kind == "taken" and not answer.insufficient_evidence and answer.item_ids == ("E1",)


def test_nothing_recorded_as_taken_is_said_and_never_guessed():
    answer = ra.compose("Was anything taken?", ra.report_view(_report()))
    assert answer.text == "The report doesn't say anything was taken. The property it records is the shop door."
    assert answer.insufficient_evidence and answer.item_ids == ()


def test_harm_lists_the_instruments_most_threatening_first_with_their_levels():
    report = _report(
        instruments=[
            {"instrument_id": "I1", "name": "crowbar", "description": "Pry bar", "threat_level": 3},
            {"instrument_id": "I2", "name": "knife", "description": "Kitchen knife", "threat_level": 5},
        ]
    )
    answer = ra.compose("What could cause harm?", ra.report_view(report))
    assert answer.text.startswith(
        "The report lists two objects that could be used to cause harm: a knife (kitchen knife) (threat level 5 of 5) "
        "and a crowbar (pry bar) (threat level 3 of 5)."
    ), answer.text
    assert answer.item_ids == ("I2", "I1") and answer.kind == "harm"


def test_no_instrument_means_the_report_lists_nothing_that_could_cause_harm():
    answer = ra.compose("Were there any weapons?", ra.report_view(_report(instruments=[])))
    assert answer.text == "The report lists no weapon or other object that could cause harm."
    assert answer.item_ids == () and not answer.insufficient_evidence


def test_a_compound_question_answers_both_parts():
    answer = ra.compose("What was taken, or what could cause harm?", ra.report_view(_report()))
    assert answer.text.startswith("The report doesn't say anything was taken.")
    assert "The report lists one object that could be used to cause harm: a crowbar (pry bar)" in answer.text
    assert answer.kind == "taken-harm" and answer.item_ids == ("I1",) and not answer.insufficient_evidence
    assert not ra._ID.search(answer.text)


def test_a_question_naming_a_kind_of_object_is_about_objects_not_people():
    answer = ra.compose("Which objects were involved?", ra.report_view(_report()))
    assert answer.kind == "objects" and answer.text.startswith("Objects used: a crowbar"), answer.text
