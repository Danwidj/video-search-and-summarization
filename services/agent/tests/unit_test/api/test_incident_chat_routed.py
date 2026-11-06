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
"""The routes of ``routed`` chat mode: nothing but the fake model and the fake store, so no test makes a real call."""

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from vss_agents.api.incident_chat import create_incident_chat_router
from vss_agents.api.incident_video_check import create_incident_video_check_router
from vss_agents.utils import chat_routing
from vss_agents.utils import grounded_chat
from vss_agents.utils import report_answers
from vss_agents.utils import video_check

VIDEO = "V1"


def _revision(revision_id: int = 7, **overrides: Any) -> dict[str, Any]:
    payload = {
        "incident": {
            "type": "assault",
            "title": "Elevator assault",
            "description": "A man pushes another man.",
            "start_timestamp": 21,
            "end_timestamp": 46,
            "severity_level": 4,
            "severity_reason": "A person was pushed to the floor.",
        },
        "entities": [
            {
                "entity_id": "E1",
                "type": "human",
                "label": "man in blue shirt",
                "description": "",
                "timestamp_seconds": 3,
            },
            {
                "entity_id": "E2",
                "type": "human",
                "label": "man in white shirt",
                "description": "",
                "timestamp_seconds": 21,
            },
        ],
        "instruments": [],
        "assets": [{"asset_id": "A1", "name": "wall", "label": "wall", "description": "", "timestamp_seconds": 22}],
        "timeline": [
            {
                "start_seconds": 22,
                "end_seconds": 22,
                "description": "The man in the white shirt pushes him to the wall.",
            },
            {"start_seconds": 30, "end_seconds": 36, "description": "The man in the white shirt restrains him."},
        ],
        "uncertainties": ["The cause of the push is not clear."],
        **overrides,
    }
    evidence = [
        {"item_type": "entity", "item_id": "E1", "image": f"evidence/{revision_id}/E1.jpg", "timestamp_seconds": 3},
        {"item_type": "entity", "item_id": "E2", "image": None, "timestamp_seconds": 21, "box_seconds": 21.5},
        {"item_type": "asset", "item_id": "A1", "image": f"evidence/{revision_id}/A1.jpg", "timestamp_seconds": 22},
    ]
    return {"id": revision_id, "video_id": VIDEO, "payload": payload, "evidence": evidence}


class Store:
    def __init__(self, revisions: dict[int, dict[str, Any]], official: int | None = None) -> None:
        self.revisions, self.official = revisions, official

    async def get_revision(self, revision_id: int) -> dict[str, Any] | None:
        return self.revisions.get(revision_id)

    async def get_official_revision_id(self, video_id: str) -> int | None:
        return self.official


class FakeModel:
    model = "fake-chat"

    def __init__(self, **reply: Any) -> None:
        self.reply = {
            "answer": "The man in the white shirt pushes him.",
            "interpretation": "",
            "not_established": "",
            "citations": [{"item_id": "E2"}],
            "insufficient_evidence": False,
            "video_could_answer": False,
            **reply,
        }
        self.calls: list[list[dict[str, str]]] = []
        self.last_usage = {"total_tokens": 10}

    async def complete(self, messages: Any, schema: Any) -> dict[str, Any]:
        self.calls.append([dict(m) for m in messages])
        return self.reply


def _ask(
    question: str | list[dict[str, str]],
    model: Any = None,
    *,
    version: int = 7,
    store: Any = None,
    **extra: Any,
) -> Any:
    app = FastAPI()
    app.include_router(
        create_incident_chat_router(
            revision_store=store or Store({7: _revision()}), chat_model=model or FakeModel(), mode="routed"
        )
    )
    messages = [{"role": "user", "content": question}] if isinstance(question, str) else question
    return TestClient(app).post("/api/v1/incidents/chat", json={"messages": messages, "version_id": version, **extra})


@pytest.fixture
def video_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(video_check.ENABLED_ENV, "1")


@pytest.fixture(autouse=True)
def video_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(video_check.ENABLED_ENV, raising=False)


@pytest.mark.parametrize(
    "question",
    [
        "Show the timeline of events",
        "What happened?",
        "What happened, in order?",
        "Who appears in the incident?",
        "Was anything taken?",
        "Were any weapons involved?",
        "How severe was the incident?",
        "When did the incident start?",
        "What objects were identified?",
    ],
)
def test_a_report_field_question_is_answered_by_code_with_no_model_call(question: str) -> None:
    model = FakeModel()
    body = _ask(question, model).json()
    assert model.calls == []
    assert body["message"]["source"] == "report"
    assert body["grounding"]["route"] in ("deterministic", "insufficient") and body["grounding"]["model"] is None


@pytest.mark.parametrize(
    "question",
    [
        "What was the man in the white shirt doing?",
        "How did the altercation begin?",
        "What happened immediately after the person fell?",
        "What happened after the man fell?",
        "Which objects were near the attacker?",
        "Was anyone visibly injured?",
        "Why was this classified as high severity?",
        "What did the man do after he fell?",
    ],
)
def test_a_question_that_needs_reading_goes_to_the_model(question: str) -> None:
    model = FakeModel()
    body = _ask(question, model).json()
    assert len(model.calls) == 1
    assert body["message"]["source"] == "report_llm" and body["grounding"]["route"] == "report_llm"


def test_the_timeline_answer_is_the_same_whatever_the_mode_and_keeps_its_cards() -> None:
    content = _ask("Show the timeline of events").json()["message"]
    assert "• 0:22 The man in the white shirt pushes him to the wall." in content["content"]
    assert [c["item_id"] for c in content["citations"]] == ["E2", "A1"]


def test_the_model_reads_the_report_its_uncertainties_and_the_conversation() -> None:
    model = FakeModel()
    _ask(
        [
            {"role": "user", "content": "What did the man in the white shirt do?"},
            {"role": "assistant", "content": "He pushes another man."},
            {"role": "user", "content": "What did he do next?"},
        ],
        model,
    )
    system, report, *turns = model.calls[0]
    assert "You see the report only" in system["content"]
    assert "The cause of the push is not clear." in report["content"]
    assert '"evidence_second": 21.5' in report["content"]
    assert [t["content"] for t in turns] == [
        "What did the man in the white shirt do?",
        "He pushes another man.",
        "What did he do next?",
    ]


def test_a_follow_up_stays_on_the_version_asked_about() -> None:
    other = _revision(8, uncertainties=["Only in version eight."])
    model = FakeModel()
    _ask("What did the man do next?", model, store=Store({7: _revision(), 8: other}))
    assert "Only in version eight." not in model.calls[0][1]["content"]


def test_a_draft_is_what_the_model_reads() -> None:
    model = FakeModel()
    draft = {"incident": {"description": "Edited by a reviewer."}, "entities": [], "instruments": [], "assets": []}
    body = _ask("What did the man do?", model, draft_report=draft).json()
    assert "Edited by a reviewer." in model.calls[0][1]["content"]
    assert body["grounding"]["draft"] is True and body["message"]["citations"] == []


def test_the_parts_of_an_answer_keep_their_labels() -> None:
    content = _ask(
        "Was the man hurt?",
        FakeModel(
            answer="The report records him on the floor.",
            interpretation="He may have been hurt.",
            not_established="Whether he was injured.",
        ),
    ).json()["message"]["content"]
    assert content == (
        "The report records him on the floor.\n\n"
        "Interpretation, not recorded in the report: He may have been hurt.\n\n"
        "Not established: Whether he was injured."
    )


def test_an_invented_citation_gets_no_card_and_a_real_one_keeps_its_stored_second() -> None:
    body = _ask("Who pushed?", FakeModel(citations=[{"item_id": "E9"}, {"item_id": "E2"}])).json()
    assert [(c["item_id"], c["timestamp_seconds"]) for c in body["message"]["citations"]] == [("E2", 21.5)]
    assert body["grounding"]["dropped_citations"] == ["E9"]


def test_an_item_the_answer_names_gets_a_card_even_if_the_model_forgot_to_cite_it() -> None:
    body = _ask("Who pushed him?", FakeModel(answer="The man in the white shirt pushed him to the wall.")).json()
    assert [c["item_id"] for c in body["message"]["citations"]] == ["E2", "A1"]


def test_with_no_citation_the_cards_come_from_what_the_text_names() -> None:
    body = _ask("Where did the man end up?", FakeModel(answer="He was pushed to the wall.", citations=[])).json()
    assert [c["item_id"] for c in body["message"]["citations"]] == ["A1"]


def test_a_time_the_report_does_not_hold_is_reported_so_it_is_not_linked() -> None:
    body = _ask(
        "When was he pushed?", FakeModel(answer="He pushes him to the wall at 0:22, then again at 0:58.")
    ).json()
    assert body["grounding"]["unknown_times"] == ["0:58"]


def test_a_time_in_any_report_field_is_held_by_the_report() -> None:
    context = grounded_chat.routed_context(_revision()["payload"], _revision()["evidence"])
    assert grounded_chat.unknown_times("At 0:03, 0:21, 0:22, 0:36 and 0:46.", context) == []


def test_a_time_stated_in_the_reports_own_words_is_held_by_the_report() -> None:
    report = _revision(incident={"type": "assault", "description": "At 0:07 he falls; at 1:15 he leaves."})["payload"]
    assert grounded_chat.unknown_times("He falls at 0:07.", grounded_chat.routed_context(report, [])) == []


def test_a_time_stated_in_seconds_is_held_rounded_either_way() -> None:
    report = _revision(incident={"type": "assault", "description": "He leaves at about 4.5s, then 7-8.5 seconds."})[
        "payload"
    ]
    text = "He leaves at 0:04 or 0:05, then 0:07 to 0:08 or 0:09, not 0:15."
    assert grounded_chat.unknown_times(text, grounded_chat.routed_context(report, [])) == ["0:15"]


def test_a_time_beside_the_wrong_event_is_reported_so_it_is_not_linked() -> None:
    answer = "The man in the white shirt restrains him at 0:36."
    body = _ask("When was he restrained?", FakeModel(answer=answer, citations=[])).json()
    assert body["grounding"]["unknown_times"] == ["0:36"]
    assert body["message"]["content"] == answer, "the text stays as written: only the link is withheld"


def test_a_model_answer_gets_the_events_time_and_keeps_its_card_at_the_stored_second() -> None:
    body = _ask(
        "What happened at the wall?", FakeModel(answer="He pushes him to the wall.", citations=[{"item_id": "E2"}])
    ).json()
    assert body["message"]["content"] == "He pushes him to the wall (0:22)."
    assert [(c["item_id"], c["timestamp_seconds"]) for c in body["message"]["citations"]] == [("E2", 21.5), ("A1", 22)]


def test_an_id_the_question_wrote_is_not_rewritten() -> None:
    body = _ask("Who is holding stick I2?", FakeModel(answer="The report has no item I2.", citations=[])).json()
    assert "no item I2" in body["message"]["content"] and body["grounding"]["ids_resolved"] == []


def test_ids_stay_out_of_the_text() -> None:
    body = _ask("Who pushed him?", FakeModel(answer="E2 pushes E1.")).json()
    assert "E2" not in body["message"]["content"] and body["grounding"]["ids_resolved"] == ["E2", "E1"]


def test_an_answer_the_report_cannot_give_is_the_insufficient_route_with_no_cards() -> None:
    body = _ask(
        "What colour was the shirt?",
        FakeModel(answer="The report doesn't say.", citations=[{"item_id": "E2"}], insufficient_evidence=True),
    ).json()
    assert body["grounding"]["route"] == "insufficient" and body["message"]["citations"] == []
    assert "video_offer" not in body["message"]


def test_a_partial_answer_flagged_insufficient_keeps_cards_for_what_it_names_and_no_others() -> None:
    body = _ask(
        "How did it start?",
        FakeModel(
            answer="The man in the white shirt pushes him. It does not say why.",
            citations=[{"item_id": "A1"}],
            insufficient_evidence=True,
        ),
    ).json()
    assert [c["item_id"] for c in body["message"]["citations"]] == ["E2"], (
        "A1 is cited but not named, so it is not trusted"
    )


@pytest.mark.parametrize("question", ["What about that one?", "What did he do?", "What did he do next?"])
def test_a_pointer_with_nothing_before_it_is_asked_about_with_no_model_call(question: str) -> None:
    model = FakeModel()
    body = _ask(question, model).json()
    assert model.calls == [] and body["grounding"]["route_reason"] == "no_subject"
    assert body["message"]["content"].startswith("Which person or object")


@pytest.mark.parametrize("question", ["Was the object a weapon?", "When did that happen?"])
def test_a_judgement_or_a_pointer_at_the_last_answer_goes_to_the_model(question: str) -> None:
    model = FakeModel()
    messages = [
        {"role": "user", "content": "What happened to the vase?"},
        {"role": "assistant", "content": "It fell."},
        {"role": "user", "content": question},
    ]
    assert _ask(messages, model).json()["message"]["source"] == "report_llm" and len(model.calls) == 1


def test_a_failed_model_is_an_error_not_an_answer() -> None:
    class Broken(FakeModel):
        async def complete(self, messages: Any, schema: Any) -> dict[str, Any]:
            raise grounded_chat.ChatModelError("down")

    assert _ask("How did it begin?", Broken()).status_code == 502


def test_a_model_reply_without_the_parts_is_an_error() -> None:
    model = FakeModel()
    del model.reply["interpretation"]
    assert _ask("How did it begin?", model).status_code == 502


def _real_model(handler: Any) -> grounded_chat.OpenAIChatModel:
    return grounded_chat.OpenAIChatModel(
        model="m",
        base_url="http://llm.test",
        api_key="k",
        client_factory=lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw),
    )


def test_a_rate_limit_is_a_plain_error_that_shows_no_account_details() -> None:
    secret = '{"error":{"message":"Rate limit exceeded for api_key: abc123"}}'
    resp = _ask("How did it begin?", _real_model(lambda request: httpx.Response(429, text=secret)))
    assert resp.status_code == 502 and "rate limited" in resp.json()["detail"]
    assert "abc123" not in resp.text


def test_a_provider_error_body_never_reaches_the_client() -> None:
    resp = _ask("How did it begin?", _real_model(lambda request: httpx.Response(500, text="internal key=abc123")))
    assert resp.status_code == 502 and "abc123" not in resp.text


def test_a_model_timeout_is_an_error_not_an_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    assert _ask("How did it begin?", _real_model(handler)).status_code == 502


@pytest.mark.parametrize("content", ["not json", "[]", '{"answer": ""}'])
def test_an_invalid_model_reply_is_an_error_not_an_answer(content: str) -> None:
    body = {"choices": [{"message": {"content": content}}]}
    assert _ask("How did it begin?", _real_model(lambda request: httpx.Response(200, json=body))).status_code == 502


def test_a_report_with_no_timeline_answers_and_invents_no_time() -> None:
    store = Store({7: _revision(timeline=[])})
    body = _ask("How did it begin?", FakeModel(answer="It began at 0:58.", citations=[]), store=store).json()
    assert body["grounding"]["unknown_times"] == ["0:58"]
    deterministic = _ask("Show the timeline of events", store=store).json()["message"]["content"]
    assert deterministic.startswith("The report has no event-by-event timeline.")


def test_a_report_with_no_evidence_gives_cards_only_for_items_with_a_stored_second() -> None:
    revision = _revision()
    revision["evidence"] = []
    body = _ask(
        "Who pushed?", FakeModel(answer="He pushes.", citations=[{"item_id": "E2"}]), store=Store({7: revision})
    ).json()
    card = body["message"]["citations"][0]
    assert (card["item_id"], card["timestamp_seconds"], card["crop_image_url"]) == ("E2", 21, "")
    del revision["payload"]["entities"][1]["timestamp_seconds"]
    body = _ask(
        "Who pushed?", FakeModel(answer="He pushes.", citations=[{"item_id": "E2"}]), store=Store({7: revision})
    ).json()
    assert body["message"]["citations"] == []


def test_a_blank_question_is_refused_before_any_model_call() -> None:
    model = FakeModel()
    assert _ask("   ", model).status_code == 400 and model.calls == []


def test_a_question_about_another_version_reads_that_version_only() -> None:
    model = FakeModel()
    store = Store({7: _revision(), 8: _revision(8, uncertainties=["Only in version eight."])})
    _ask("What did the man do?", model, version=8, store=store)
    assert "Only in version eight." in model.calls[0][1]["content"]


def test_with_checks_off_nothing_is_offered_whatever_the_model_says() -> None:
    body = _ask(
        "What colour was his shirt?", FakeModel(insufficient_evidence=True, video_could_answer=True, citations=[])
    ).json()
    assert "video_offer" not in body["message"]


def test_a_missing_visible_detail_offers_a_check(video_on: None) -> None:
    body = _ask(
        "What colour was his shirt?",
        FakeModel(
            answer="The report doesn't say.",
            not_established="The colour of his shirt.",
            insufficient_evidence=True,
            video_could_answer=True,
            citations=[],
        ),
    ).json()
    assert body["message"]["video_offer"] == {"reason": "The colour of his shirt."}
    assert body["grounding"]["route"] == "report_llm", "an offer is a way forward, not a dead end"


@pytest.mark.parametrize(
    "question",
    [
        "Was that actually a dog or a monkey?",
        "Can you check the video?",
        "I think the report is wrong",
        "Are you sure?",
    ],
)
def test_a_dispute_or_a_request_offers_a_check_and_never_runs_one(video_on: None, question: str) -> None:
    looker = FakeLooker()
    body = _ask(question).json()
    assert "video_offer" in body["message"] and looker.looked == []


def test_a_motive_is_never_offered_a_check(video_on: None) -> None:
    body = _ask(
        "Why did the person attack him?",
        FakeModel(not_established="Why he did it.", video_could_answer=True, citations=[]),
    ).json()
    assert "video_offer" not in body["message"]
    assert chat_routing.decide("Why did he attack?", report_answers.report_view({})).reason == "motive"


def test_why_the_report_rated_something_is_a_question_about_the_report() -> None:
    assert (
        chat_routing.decide("Why was this classified as high severity?", report_answers.report_view({})).video
        != "never"
    )


def test_after_the_incident_uses_the_timeline_then_offers_the_footage_after_it(video_on: None) -> None:
    model = FakeModel()
    body = _ask("What happened after the incident ended?", model).json()
    assert model.calls == []
    assert body["message"]["video_offer"] == {
        "reason": "The report records nothing after the incident ends.",
        "from_seconds": 46,
    }
    timeline = [{"start_seconds": 50, "end_seconds": 52, "description": "He walks away."}]
    store = Store({7: _revision(timeline=timeline)})
    answered = _ask("What happened after the incident ended?", store=store).json()["message"]
    assert "0:50–0:52 He walks away." in answered["content"] and "video_offer" not in answered


class FakeLooker:
    model = "fake-vlm"

    def __init__(self, look: video_check.VideoLook | None = None, error: str | None = None) -> None:
        self.result = look or video_check.VideoLook(True, "The animal appears to be a monkey.")
        self.error = error
        self.looked: list[tuple[str, str]] = []
        self.last_usage = {"total_tokens": 100}

    async def look(self, video_url: str, question: str) -> video_check.VideoLook:
        self.looked.append((video_url, question))
        if self.error:
            raise video_check.VideoCheckError(self.error)
        return self.result


class FakeCompare:
    model = "fake-chat"
    last_usage = {"total_tokens": 5}

    def __init__(self, reply: Any = None) -> None:
        self.reply = reply or {"relation": "conflicts", "note": "The report says dog; the look says monkey."}
        self.messages: list[Any] = []

    async def complete(self, messages: Any, schema: Any) -> Any:
        self.messages.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def _check(looker: Any, compare: Any = None, *, video: Any = None) -> Any:
    async def read(video_id: str) -> Any:
        return video if video is not None else {"filepath": "videos/clip.mp4"}

    app = FastAPI()
    app.include_router(create_incident_video_check_router(looker, compare or FakeCompare(), read))
    return TestClient(app).post(
        f"/api/v1/incidents/{VIDEO}/video-check",
        json={"question": "Was that a dog?", "stored_answer": "The report identifies the animal as a dog."},
    )


def test_a_check_is_refused_with_no_model_call_while_the_flag_is_off() -> None:
    looker = FakeLooker()
    assert _check(looker).status_code == 404 and looker.looked == []


def test_a_conflict_is_shown_apart_and_flagged_for_a_person(video_on: None) -> None:
    body = _check(FakeLooker()).json()
    assert body["source"] == "video" and body["relation"] == "conflicts"
    assert body["content"] == (
        "Stored report: The report identifies the animal as a dog.\n\n"
        "Video reanalysis: The animal appears to be a monkey.\n\n"
        "Discrepancy: The report says dog; the look says monkey. This needs human review."
    )


def test_the_look_is_blind_to_the_report(video_on: None) -> None:
    looker = FakeLooker()
    _check(looker)
    assert looker.looked[0][1] == "Was that a dog?"
    assert "identifies the animal" not in str(looker.looked)


def test_a_clip_that_cannot_answer_says_so_and_compares_nothing(video_on: None) -> None:
    compare = FakeCompare()
    body = _check(FakeLooker(video_check.VideoLook(False, "The clip does not show the animal.")), compare).json()
    assert body["can_answer"] is False and compare.messages == []
    assert "Discrepancy" not in body["content"]


def test_a_failed_comparison_leaves_both_accounts_for_a_reviewer(video_on: None) -> None:
    body = _check(FakeLooker(), FakeCompare(grounded_chat.ChatModelError("down"))).json()
    assert body["relation"] == "unclear" and "A reviewer should compare" in body["content"]


@pytest.mark.parametrize("reply", [{"relation": "maybe", "note": ""}, {"relation": "agrees"}])
def test_a_comparison_outside_its_schema_decides_nothing(video_on: None, reply: dict[str, Any]) -> None:
    assert _check(FakeLooker(), FakeCompare(reply)).json()["relation"] == "unclear"


def test_a_failed_look_is_a_clear_error_and_no_answer(video_on: None) -> None:
    resp = _check(FakeLooker(error="The video check timed out, so nothing was learned from the video."))
    assert resp.status_code == 502 and "timed out" in resp.json()["detail"]


def test_a_missing_video_is_a_404(video_on: None) -> None:
    looker = FakeLooker()
    assert _check(looker, video={"filepath": None}).status_code == 404 and looker.looked == []


def _looker_with(handler: Any) -> video_check.OpenAIVideoLooker:
    return video_check.OpenAIVideoLooker(
        model="vlm",
        base_url="http://vlm.test/v1",
        api_key="k",
        client_factory=lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw),
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(429), "busy"),
        (httpx.Response(500), "HTTP 500"),
        (httpx.Response(200, json={"choices": []}), "could not be read"),
        (httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}), "could not be read"),
    ],
)
async def test_a_bad_reply_from_the_video_model_is_a_clear_error(response: httpx.Response, message: str) -> None:
    with pytest.raises(video_check.VideoCheckError, match=message):
        await _looker_with(lambda request: response).look("https://r2/clip.mp4", "q")


@pytest.mark.anyio
async def test_a_timeout_says_nothing_was_learned() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(video_check.VideoCheckError, match="timed out"):
        await _looker_with(handler).look("https://r2/clip.mp4", "q")


@pytest.mark.anyio
async def test_the_request_is_the_analysis_shape_with_the_question_only() -> None:
    sent: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        reply = '{"can_answer": true, "observation": "A dog."}'
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}], "usage": {"total_tokens": 9}})

    look = await _looker_with(handler).look("https://r2/clip.mp4", "Was it a dog?")
    assert look == video_check.VideoLook(True, "A dog.")
    assert str(sent[0].url) == "http://vlm.test/v1/chat/completions"
    assert b'"video_url"' in sent[0].content and b"Question: Was it a dog?" in sent[0].content


def test_routed_is_never_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from vss_agents.api import incident_chat

    monkeypatch.delenv(incident_chat.CHAT_MODE_ENV, raising=False)
    assert incident_chat.chat_mode() == "template"
    assert video_check.enabled() is False
