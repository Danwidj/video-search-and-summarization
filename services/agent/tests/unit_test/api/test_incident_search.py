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

"""Unit tests for incident search endpoint, contract fixtures, always-on critic, and SearchStore."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import time
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from pydantic import ValidationError
import pytest

from vss_agents.api.incident_search import CRITIC_DELAY_ENV_VAR
from vss_agents.api.incident_search import DEFAULT_CRITIC_DELAY_SECONDS
from vss_agents.api.incident_search import CriticEvaluator
from vss_agents.api.incident_search import CriticVerdict
from vss_agents.api.incident_search import DefaultQueryEmbedder
from vss_agents.api.incident_search import EvidenceCandidate
from vss_agents.api.incident_search import IncidentHit
from vss_agents.api.incident_search import InMemorySearchStore
from vss_agents.api.incident_search import ItemHit
from vss_agents.api.incident_search import SearchRequest
from vss_agents.api.incident_search import SearchResponse
from vss_agents.api.incident_search import SupabaseSearchStore
from vss_agents.api.incident_search import VlmCriticEvaluator
from vss_agents.api.incident_search import _get_critic_delay_seconds
from vss_agents.api.incident_search import create_incident_search_router
from vss_agents.api.incident_search import get_default_search_store
from vss_agents.api.incident_search import register_incident_search_routes
from vss_agents.utils.embeddings import RemoteTextEmbedder

REPO_ROOT = Path(__file__).resolve().parents[5]
CONTRACT_FIXTURES_DIR = (
    REPO_ROOT / "deploy/docker/developer-profiles/dev-profile-incident/contracts/search-contract-v1/fixtures"
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class MockCriticEvaluator(CriticEvaluator):
    """Configurable mock critic for testing deterministic verdicts and simulated failures."""

    def __init__(
        self,
        verdict: str = "confirmed",
        confidence: float | None = 0.95,
        rationale: str = "Mock verification passed",
        should_raise: Exception | None = None,
    ) -> None:
        self.verdict = verdict
        self.confidence = confidence
        self.rationale = rationale
        self.should_raise = should_raise

    async def evaluate_candidate(
        self,
        query: str,
        item: ItemHit,
        incident: IncidentHit,
    ) -> CriticVerdict:
        if self.should_raise is not None:
            raise self.should_raise
        return CriticVerdict(
            verdict=self.verdict,  # type: ignore[arg-type]
            confidence=self.confidence,
            rationale=self.rationale,
        )


@pytest.fixture
def sample_candidates() -> list[EvidenceCandidate]:
    return [
        EvidenceCandidate(
            incident_id="Assault001",
            model_run_id="run-001",
            playback_url="https://pub-r2.example.com/videos/assault1.mp4",
            incident_type="assault",
            severity_level=4,
            incident_title="ATM alteraction",
            incident_description="Altercation with weapon",
            incident_window=[10.0, 25.0],
            item_type="instrument",
            item_id="I1",
            item_name="machete",
            item_label="machete",
            item_description="Long blade weapon",
            threat_level=4,
            holder_entity_id="E1",
            crop_image_url="https://pub-r2.example.com/crops/I1.jpg",
            timestamp_seconds=14,
            bounding_box=[100, 200, 300, 400],
            similarity_score=0.88,
        ),
        EvidenceCandidate(
            incident_id="Assault001",
            model_run_id="run-001",
            playback_url="https://pub-r2.example.com/videos/assault1.mp4",
            incident_type="assault",
            severity_level=4,
            incident_title="ATM altercation",
            incident_description="Altercation with weapon",
            incident_window=[10.0, 25.0],
            item_type="entity",
            item_id="E1",
            item_name="suspect",
            item_label="person",
            item_description="Aggressor in hoodie",
            threat_level=5,
            holder_entity_id=None,
            crop_image_url="https://pub-r2.example.com/crops/E1.jpg",
            timestamp_seconds=12,
            bounding_box=[50, 150, 800, 600],
            similarity_score=0.82,
        ),
        EvidenceCandidate(
            incident_id="Burglary002",
            model_run_id="run-002",
            playback_url="https://pub-r2.example.com/videos/burglary2.mp4",
            incident_type="burglary",
            severity_level=3,
            incident_title="Storefront breach",
            incident_description="Forced entry with pry tool",
            incident_window=[5.0, 30.0],
            item_type="instrument",
            item_id="I1",
            item_name="crowbar",
            item_label="crowbar",
            item_description="Heavy metal pry tool",
            threat_level=3,
            holder_entity_id="E1",
            crop_image_url="https://pub-r2.example.com/crops/crowbar.jpg",
            timestamp_seconds=18,
            bounding_box=[300, 400, 500, 600],
            similarity_score=0.75,
        ),
        EvidenceCandidate(
            incident_id="Accident003",
            model_run_id="run-003",
            playback_url="https://pub-r2.example.com/videos/accident3.mp4",
            incident_type="road accident",
            severity_level=2,
            incident_title="Intersection collision",
            incident_description="Car crash",
            incident_window=[2.0, 10.0],
            item_type="asset",
            item_id="A1",
            item_name="sedan",
            item_label="car",
            item_description="Silver sedan",
            threat_level=2,
            holder_entity_id=None,
            crop_image_url="https://pub-r2.example.com/crops/car.jpg",
            timestamp_seconds=5,
            bounding_box=None,
            similarity_score=0.60,
        ),
    ]


# =============================================================================
# 1. Contract Validation Against search-contract-v1 Fixtures
# =============================================================================


class TestContractFixturesValidation:
    """Validate Pydantic models directly against the canonical search-contract-v1 JSON fixtures."""

    def test_valid_request_minimal(self) -> None:
        path = CONTRACT_FIXTURES_DIR / "valid/minimal-request.json"
        assert path.exists()
        data = _load_json(path)
        req = SearchRequest.model_validate(data)
        assert req.query == "sharp weapon"
        assert req.top_k == 10
        assert req.min_similarity == 0.0
        assert req.hide_rejected is True
        assert req.filters is None

    def test_valid_request_full(self) -> None:
        path = CONTRACT_FIXTURES_DIR / "valid/full-request.json"
        assert path.exists()
        data = _load_json(path)
        req = SearchRequest.model_validate(data)
        assert req.query == "person holding machete or knife"
        assert req.top_k == 5
        assert req.min_similarity == 0.35
        assert req.filters is not None
        assert req.filters.incident_types == ["assault", "burglary"]
        assert req.filters.item_types == ["entity", "instrument"]
        assert req.filters.min_severity == 2
        assert req.filters.max_severity == 5

    def test_invalid_request_missing_query(self) -> None:
        path = CONTRACT_FIXTURES_DIR / "invalid/request-missing-query.json"
        assert path.exists()
        data = _load_json(path)
        with pytest.raises(ValidationError):
            SearchRequest.model_validate(data)

    def test_invalid_request_invalid_top_k(self) -> None:
        path = CONTRACT_FIXTURES_DIR / "invalid/request-invalid-top-k.json"
        assert path.exists()
        data = _load_json(path)
        with pytest.raises(ValidationError):
            SearchRequest.model_validate(data)

    def test_invalid_request_invalid_item_type(self) -> None:
        path = CONTRACT_FIXTURES_DIR / "invalid/request-invalid-item-type.json"
        assert path.exists()
        data = _load_json(path)
        with pytest.raises(ValidationError):
            SearchRequest.model_validate(data)

    def test_valid_response_empty(self) -> None:
        path = CONTRACT_FIXTURES_DIR / "valid/empty-response.json"
        assert path.exists()
        data = _load_json(path)
        resp = SearchResponse.model_validate(data)
        assert resp.total_hits == 0
        assert resp.hits == []

    def test_valid_response_full(self) -> None:
        path = CONTRACT_FIXTURES_DIR / "valid/full-response.json"
        assert path.exists()
        data = _load_json(path)
        resp = SearchResponse.model_validate(data)
        assert resp.total_hits == 2
        assert len(resp.hits) == 2
        first = resp.hits[0]
        assert first.item.item_type == "instrument"
        assert first.item.timestamp_seconds == 14
        assert first.critic.verdict == "confirmed"
        assert first.critic.confidence == 0.96

    def test_invalid_response_missing_critic(self) -> None:
        path = CONTRACT_FIXTURES_DIR / "invalid/response-missing-critic.json"
        assert path.exists()
        data = _load_json(path)
        with pytest.raises(ValidationError):
            SearchResponse.model_validate(data)

    def test_invalid_response_invalid_verdict(self) -> None:
        path = CONTRACT_FIXTURES_DIR / "invalid/response-invalid-verdict.json"
        assert path.exists()
        data = _load_json(path)
        with pytest.raises(ValidationError):
            SearchResponse.model_validate(data)

    def test_invalid_response_negative_timestamp(self) -> None:
        path = CONTRACT_FIXTURES_DIR / "invalid/response-negative-timestamp.json"
        assert path.exists()
        data = _load_json(path)
        with pytest.raises(ValidationError):
            SearchResponse.model_validate(data)


# =============================================================================
# 2. Critic Verdict Handling & Degradation (Never Drop Hits)
# =============================================================================


class TestCriticVerdictHandling:
    """Tests for always-on critic evaluation, failure degradation, and fallback preservation."""

    @pytest.mark.asyncio
    async def test_critic_confirmed_verdict(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "verdict": "confirmed",
                                "confidence": 0.98,
                                "rationale": "Weapon clearly visible in subject hand",
                            }
                        )
                    }
                }
            ]
        }
        mock_client.post.return_value = mock_response

        critic = VlmCriticEvaluator(http_client=mock_client)
        item = ItemHit(
            item_type="instrument",
            item_id="I1",
            name="knife",
            label="knife",
            description="hunting knife",
            crop_image_url="https://pub-r2.example.com/i1.jpg",
            timestamp_seconds=10,
        )
        incident = IncidentHit(
            incident_id="inc-1",
            model_run_id="run-1",
            incident_type="assault",
            severity_level=4,
            description="Knife attack",
            playback_url="https://pub-r2.example.com/vid.mp4",
            incident_window=[5.0, 15.0],
        )
        verdict = await critic.evaluate_candidate("knife attack", item, incident)
        assert verdict.verdict == "confirmed"
        assert verdict.confidence == 0.98
        assert "clearly visible" in verdict.rationale

    @pytest.mark.asyncio
    async def test_critic_rejected_verdict(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "verdict": "rejected",
                                "confidence": 0.85,
                                "rationale": "Candidate is a smartphone, not a weapon",
                            }
                        )
                    }
                }
            ]
        }
        mock_client.post.return_value = mock_response

        critic = VlmCriticEvaluator(http_client=mock_client)
        item = ItemHit(
            item_type="instrument",
            item_id="I2",
            name="phone",
            label="cell phone",
            description="handheld electronic device",
            crop_image_url="https://pub-r2.example.com/i2.jpg",
            timestamp_seconds=12,
        )
        incident = IncidentHit(
            incident_id="inc-1",
            model_run_id="run-1",
            incident_type="assault",
            severity_level=4,
            description="Bystander with phone",
            playback_url="https://pub-r2.example.com/vid.mp4",
            incident_window=[5.0, 15.0],
        )
        verdict = await critic.evaluate_candidate("firearm", item, incident)
        assert verdict.verdict == "rejected"
        assert verdict.confidence == 0.85
        assert "smartphone" in verdict.rationale

    @pytest.mark.asyncio
    async def test_vlm_critic_boolean_confidence_degrades_to_none(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "verdict": "confirmed",
                                "confidence": True,
                                "rationale": "Match found but confidence is boolean flag",
                            }
                        )
                    }
                }
            ]
        }
        mock_client.post.return_value = mock_response

        critic = VlmCriticEvaluator(http_client=mock_client)
        item = ItemHit(
            item_type="instrument",
            item_id="I1",
            name="knife",
            label="knife",
            description="hunting knife",
            crop_image_url="https://pub-r2.example.com/i1.jpg",
            timestamp_seconds=10,
        )
        incident = IncidentHit(
            incident_id="inc-1",
            model_run_id="run-1",
            incident_type="assault",
            severity_level=4,
            description="Knife attack",
            playback_url="https://pub-r2.example.com/vid.mp4",
            incident_window=[5.0, 15.0],
        )
        verdict = await critic.evaluate_candidate("knife attack", item, incident)
        assert verdict.verdict == "confirmed"
        assert verdict.confidence is None

    @pytest.mark.asyncio
    async def test_vlm_critic_degrades_to_unverified_on_http_error(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"
        mock_client.post.return_value = mock_response

        vlm_critic = VlmCriticEvaluator(http_client=mock_client)
        item = ItemHit(
            item_type="instrument",
            item_id="I1",
            name="crowbar",
            label="crowbar",
            description="metal bar",
            crop_image_url="https://pub-r2.example.com/crowbar.jpg",
            timestamp_seconds=20,
        )
        incident = IncidentHit(
            incident_id="inc-1",
            model_run_id="run-1",
            incident_type="burglary",
            severity_level=3,
            description="Burglary",
            playback_url="https://pub-r2.example.com/vid.mp4",
            incident_window=[10.0, 30.0],
        )

        verdict = await vlm_critic.evaluate_candidate("crowbar", item, incident)
        assert verdict.verdict == "unverified"
        assert verdict.confidence is None
        assert "HTTP 503" in verdict.rationale

    @pytest.mark.asyncio
    async def test_vlm_critic_degrades_to_unverified_on_timeout(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = httpx.TimeoutException("Connection timed out")

        vlm_critic = VlmCriticEvaluator(http_client=mock_client)
        item = ItemHit(
            item_type="instrument",
            item_id="I1",
            name="crowbar",
            label="crowbar",
            description="metal bar",
            crop_image_url="https://pub-r2.example.com/crowbar.jpg",
            timestamp_seconds=20,
        )
        incident = IncidentHit(
            incident_id="inc-1",
            model_run_id="run-1",
            incident_type="burglary",
            severity_level=3,
            description="Burglary",
            playback_url="https://pub-r2.example.com/vid.mp4",
            incident_window=[10.0, 30.0],
        )

        verdict = await vlm_critic.evaluate_candidate("crowbar", item, incident)
        assert verdict.verdict == "unverified"
        assert verdict.confidence is None
        assert "timed out" in verdict.rationale.lower()

    @pytest.mark.asyncio
    async def test_vlm_critic_parses_valid_json_completion(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "verdict": "confirmed",
                                "confidence": 0.94,
                                "rationale": "High-confidence visual match on machete.",
                            }
                        )
                    }
                }
            ]
        }
        mock_client.post.return_value = mock_response

        vlm_critic = VlmCriticEvaluator(http_client=mock_client)
        item = ItemHit(
            item_type="instrument",
            item_id="I1",
            name="machete",
            label="machete",
            description="blade",
            crop_image_url="https://pub-r2.example.com/machete.jpg",
            timestamp_seconds=14,
        )
        incident = IncidentHit(
            incident_id="inc-1",
            model_run_id="run-1",
            incident_type="assault",
            severity_level=4,
            description="Assault",
            playback_url="https://pub-r2.example.com/vid.mp4",
            incident_window=[10.0, 30.0],
        )

        verdict = await vlm_critic.evaluate_candidate("machete", item, incident)
        assert verdict.verdict == "confirmed"
        assert verdict.confidence == 0.94
        assert "High-confidence" in verdict.rationale


# =============================================================================
# 3. Route Tests with Fakes & Store Persistence
# =============================================================================


class TestSearchRouteEndToEnd:
    """Integration tests for POST /api/v1/incidents/search using FastAPI TestClient and fakes."""

    def test_search_route_flow_with_fakes_persists_audit(self, sample_candidates: list[EvidenceCandidate]) -> None:
        app = FastAPI()
        store = InMemorySearchStore(candidates=sample_candidates)
        critic = MockCriticEvaluator(verdict="confirmed", confidence=0.91, rationale="Verified evidence match")
        router = create_incident_search_router(
            store=store, critic=critic, embedder=DefaultQueryEmbedder(remote=RemoteTextEmbedder(api_key=""))
        )
        app.include_router(router)

        client = TestClient(app)
        resp = client.post("/api/v1/incidents/search", json={"query": "machete blade", "top_k": 2})
        assert resp.status_code == 200
        data = resp.json()

        # Contract assertion
        validated = SearchResponse.model_validate(data)
        assert validated.total_hits == 2
        assert len(validated.hits) == 2
        assert validated.query == "machete blade"
        assert validated.execution_time_ms >= 0.0

        # Ranks and critic verdicts
        assert validated.hits[0].rank == 1
        assert validated.hits[0].similarity_score >= validated.hits[1].similarity_score
        assert validated.hits[0].critic.verdict == "confirmed"
        assert validated.hits[0].critic.confidence == 0.91

        # Check persistence in store
        query_id = validated.query_id
        assert query_id in store.queries
        assert store.queries[query_id]["query_text"] == "machete blade"
        persisted_results = [r for r in store.query_results if r["query_id"] == query_id]
        assert len(persisted_results) == 2
        assert persisted_results[0]["critic_verdict"] == "confirmed"
        assert persisted_results[0]["rank"] == 1

    def test_search_route_never_drops_hits_on_critic_failure(self, sample_candidates: list[EvidenceCandidate]) -> None:
        app = FastAPI()
        store = InMemorySearchStore(candidates=sample_candidates)
        # Critic that raises a network exception
        failing_critic = MockCriticEvaluator(should_raise=RuntimeError("Switchyard unreachable"))
        router = create_incident_search_router(store=store, critic=failing_critic)
        app.include_router(router)

        client = TestClient(app)
        resp = client.post("/api/v1/incidents/search", json={"query": "machete blade", "top_k": 3})
        assert resp.status_code == 200
        data = resp.json()

        validated = SearchResponse.model_validate(data)
        assert validated.total_hits == 3
        # Hits must NOT be dropped, but degraded to unverified
        for hit in validated.hits:
            assert hit.critic.verdict == "unverified"
            assert hit.critic.confidence is None

    def test_search_route_filters_by_item_type(self, sample_candidates: list[EvidenceCandidate]) -> None:
        app = FastAPI()
        store = InMemorySearchStore(candidates=sample_candidates)
        router = create_incident_search_router(store=store)
        app.include_router(router)

        client = TestClient(app)
        resp = client.post(
            "/api/v1/incidents/search",
            json={
                "query": "weapons only",
                "filters": {"item_types": ["instrument"]},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_hits"] == 2
        for hit in data["hits"]:
            assert hit["item"]["item_type"] == "instrument"

    def test_search_route_filters_by_severity(self, sample_candidates: list[EvidenceCandidate]) -> None:
        app = FastAPI()
        store = InMemorySearchStore(candidates=sample_candidates)
        router = create_incident_search_router(store=store)
        app.include_router(router)

        client = TestClient(app)
        resp = client.post(
            "/api/v1/incidents/search",
            json={
                "query": "high severity",
                "filters": {"min_severity": 4},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_hits"] == 2
        for hit in data["hits"]:
            assert hit["incident"]["severity_level"] >= 4

    def test_search_route_filters_by_min_similarity(self, sample_candidates: list[EvidenceCandidate]) -> None:
        app = FastAPI()
        store = InMemorySearchStore(candidates=sample_candidates)
        router = create_incident_search_router(store=store)
        app.include_router(router)

        client = TestClient(app)
        resp = client.post(
            "/api/v1/incidents/search",
            json={
                "query": "strict match",
                "min_similarity": 0.85,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_hits"] == 1
        assert data["hits"][0]["similarity_score"] >= 0.85

    def test_search_route_default_has_no_similarity_cutoff(self) -> None:
        low = EvidenceCandidate(
            incident_id="I1",
            model_run_id="run-001",
            playback_url="",
            incident_type="burglary",
            severity_level=2,
            incident_description="",
            incident_window=[0.0, 1.0],
            item_type="instrument",
            item_id="I1",
            item_name="Tool",
            item_label="Tool",
            item_description="Prying tool",
            crop_image_url="",
            timestamp_seconds=1,
            similarity_score=0.192,
        )
        app = FastAPI()
        app.include_router(create_incident_search_router(store=InMemorySearchStore(candidates=[low])))
        client = TestClient(app)
        assert client.post("/api/v1/incidents/search", json={"query": "edged weapon"}).json()["total_hits"] == 1
        resp = client.post("/api/v1/incidents/search", json={"query": "edged weapon", "min_similarity": 0.2})
        assert resp.json()["total_hits"] == 0

    def test_search_route_hide_rejected(self, sample_candidates: list[EvidenceCandidate]) -> None:
        app = FastAPI()
        app.include_router(
            create_incident_search_router(
                store=InMemorySearchStore(candidates=sample_candidates),
                critic=MockCriticEvaluator(verdict="rejected"),
            )
        )
        client = TestClient(app)
        hidden = client.post("/api/v1/incidents/search", json={"query": "weapon"}).json()
        assert hidden["total_hits"] == 0
        shown = client.post("/api/v1/incidents/search", json={"query": "weapon", "hide_rejected": False}).json()
        assert shown["total_hits"] == len(sample_candidates)
        assert all(hit["critic"]["verdict"] == "rejected" for hit in shown["hits"])

    def test_search_route_rejects_extra_request_properties(self) -> None:
        app = FastAPI()
        register_incident_search_routes(app)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/incidents/search",
            json={"query": "test query", "unknown_field": 123},
        )
        assert resp.status_code == 422


# =============================================================================
# 4. SearchStore Port & Adapter Tests
# =============================================================================


class TestSearchStores:
    """Unit tests for SearchStore adapters."""

    @pytest.mark.asyncio
    async def test_in_memory_store_default_candidates(self) -> None:
        store = InMemorySearchStore()
        hits = await store.search_evidence_items(query_embedding=[], top_k=10, min_similarity=0.2)
        assert len(hits) > 0
        assert hits[0].similarity_score >= hits[-1].similarity_score

    def test_get_default_search_store_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("INCIDENT_SEARCH_STORE", raising=False)
        monkeypatch.delenv("INCIDENT_SUPABASE_URL", raising=False)
        monkeypatch.delenv("INCIDENT_SUPABASE_SERVICE_ROLE_KEY", raising=False)

        # 1. Unconfigured -> InMemorySearchStore
        store = get_default_search_store()
        assert isinstance(store, InMemorySearchStore)

        # 2. Configured Supabase -> SupabaseSearchStore
        monkeypatch.setenv("INCIDENT_SUPABASE_URL", "https://xyz.supabase.co")
        monkeypatch.setenv("INCIDENT_SUPABASE_SERVICE_ROLE_KEY", "secret-key")
        store = get_default_search_store()
        assert isinstance(store, SupabaseSearchStore)

        # 3. Explicit override to memory -> InMemorySearchStore
        monkeypatch.setenv("INCIDENT_SEARCH_STORE", "memory")
        store = get_default_search_store()
        assert isinstance(store, InMemorySearchStore)

        # 4. Explicit override to supabase -> SupabaseSearchStore
        monkeypatch.delenv("INCIDENT_SUPABASE_URL", raising=False)
        monkeypatch.setenv("INCIDENT_SEARCH_STORE", "supabase")
        store = get_default_search_store()
        assert isinstance(store, SupabaseSearchStore)

    @pytest.mark.asyncio
    async def test_supabase_search_store_empty_embedding(self) -> None:
        mock_client = MagicMock()
        store = SupabaseSearchStore(client=mock_client)
        hits = await store.search_evidence_items(query_embedding=[])
        assert hits == []
        mock_client.rpc.assert_not_called()

    @pytest.mark.asyncio
    async def test_supabase_search_store_requires_configured_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("INCIDENT_SUPABASE_URL", raising=False)
        monkeypatch.delenv("INCIDENT_SUPABASE_SERVICE_ROLE_KEY", raising=False)
        store = SupabaseSearchStore()
        with pytest.raises(RuntimeError, match="Incident Supabase DB is not configured"):
            await store.search_evidence_items(query_embedding=[0.1] * 10)

    @pytest.mark.asyncio
    async def test_supabase_search_store_search_evidence_items_mapping(self) -> None:
        mock_client = MagicMock()
        rpc_builder = MagicMock()
        sample_rpc_row = {
            "incident_id": "Assault007_x264",
            "model_run_id": "m86a5c319e26659804b0",
            "video_filepath": "videos/anomaly/assault/Assault007_x264.mp4",
            "incident_type": "assault",
            "severity_level": 4,
            "incident_title": "Assault incident",
            "incident_description": "Perpetrator brandishes blade.",
            "incident_start_timestamp": "10.0",
            "incident_end_timestamp": "28.0",
            "item_type": "instrument",
            "item_id": "I1",
            "item_name": "machete",
            "item_label": "machete",
            "item_description": "Long curved blade held by assailant.",
            "threat_level": 4,
            "holder_entity_id": "E1",
            "image": "evidence/Assault007_x264/m86a5c319e26659804b0/instruments/I1.jpg",
            "timestamp_seconds": 14,
            "bounding_box": [320, 450, 510, 600],
            "similarity_score": 0.89,
        }
        rpc_builder.execute = AsyncMock(return_value=MagicMock(data=[sample_rpc_row]))
        mock_client.rpc = MagicMock(return_value=rpc_builder)

        def fake_signer(ref: str) -> str:
            return f"https://mock-r2.test/{ref}"

        store = SupabaseSearchStore(client=mock_client, r2_resolver=fake_signer)
        hits = await store.search_evidence_items(
            query_embedding=[0.5] * 1024,
            top_k=5,
            min_similarity=0.3,
            item_types=["instrument"],
            incident_types=["assault"],
            min_severity=2,
            max_severity=5,
        )

        assert len(hits) == 1
        cand = hits[0]
        assert cand.incident_id == "Assault007_x264"
        assert cand.model_run_id == "m86a5c319e26659804b0"
        assert cand.playback_url == "https://mock-r2.test/videos/anomaly/assault/Assault007_x264.mp4"
        assert cand.crop_image_url == (
            "https://mock-r2.test/evidence/Assault007_x264/m86a5c319e26659804b0/instruments/I1.jpg"
        )
        assert cand.item_type == "instrument"
        assert cand.item_id == "I1"
        assert cand.incident_window == [10.0, 28.0]
        assert cand.similarity_score == 0.89

        mock_client.rpc.assert_called_once_with(
            "search_evidence_items",
            {
                "p_query_embedding": [0.5] * 1024,
                "p_top_k": 5,
                "p_min_similarity": 0.3,
                "p_item_types": ["instrument"],
                "p_incident_types": ["assault"],
                "p_min_severity": 2,
                "p_max_severity": 5,
            },
        )

    @pytest.mark.asyncio
    async def test_supabase_search_store_persists_queries_and_results(self) -> None:
        mock_client = MagicMock()
        table_mock = MagicMock()
        upsert_mock = MagicMock()
        upsert_mock.execute = AsyncMock()
        table_mock.upsert = MagicMock(return_value=upsert_mock)
        mock_client.table = MagicMock(return_value=table_mock)

        store = SupabaseSearchStore(client=mock_client)

        await store.persist_query("q-123", "edged weapon")
        mock_client.table.assert_called_with("queries")
        table_mock.upsert.assert_called_once()
        upsert_call_args = table_mock.upsert.call_args[0][0]
        assert upsert_call_args["id"] == "q-123"
        assert upsert_call_args["query_text"] == "edged weapon"

        table_mock.reset_mock()
        results = [
            {
                "id": "res-1",
                "incident_id": "Assault007",
                "model_run_id": "m1",
                "item_type": "instrument",
                "item_id": "I1",
                "rank": 1,
                "similarity_score": 0.9,
                "critic_verdict": "confirmed",
                "critic_rationale": "Verified weapon",
            }
        ]
        await store.persist_query_results("q-123", results)
        mock_client.table.assert_called_with("query_results")
        table_mock.upsert.assert_called_once()
        results_call_args = table_mock.upsert.call_args[0][0]
        assert len(results_call_args) == 1
        assert results_call_args[0]["query_id"] == "q-123"
        assert results_call_args[0]["critic_verdict"] == "confirmed"

    def test_search_route_with_supabase_store_e2e(self) -> None:
        mock_client = MagicMock()
        rpc_builder = MagicMock()
        sample_rpc_row = {
            "incident_id": "Assault007_x264",
            "model_run_id": "m86a5c319e26659804b0",
            "video_filepath": "videos/Assault007_x264.mp4",
            "incident_type": "assault",
            "severity_level": 4,
            "incident_title": "Assault incident",
            "incident_description": "Perpetrator brandishes blade.",
            "incident_start_timestamp": "10.0",
            "incident_end_timestamp": "28.0",
            "item_type": "instrument",
            "item_id": "I1",
            "item_name": "machete",
            "item_label": "machete",
            "item_description": "Long curved blade held by assailant.",
            "threat_level": 4,
            "holder_entity_id": "E1",
            "image": "evidence/Assault007_x264/m86a5c319e26659804b0/instruments/I1.jpg",
            "timestamp_seconds": 14,
            "bounding_box": [320, 450, 510, 600],
            "similarity_score": 0.89,
        }
        rpc_builder.execute = AsyncMock(return_value=MagicMock(data=[sample_rpc_row]))
        mock_client.rpc = MagicMock(return_value=rpc_builder)

        table_mock = MagicMock()
        upsert_mock = MagicMock()
        upsert_mock.execute = AsyncMock()
        table_mock.upsert = MagicMock(return_value=upsert_mock)
        mock_client.table = MagicMock(return_value=table_mock)

        def fake_signer(ref: str) -> str:
            return f"https://real-r2.test/{ref}"

        store = SupabaseSearchStore(client=mock_client, r2_resolver=fake_signer)
        critic = MockCriticEvaluator(verdict="confirmed", confidence=0.92, rationale="Object matches query")

        app = FastAPI()
        register_incident_search_routes(app, store=store, critic=critic)
        client = TestClient(app)

        resp = client.post("/api/v1/incidents/search", json={"query": "machete", "top_k": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_hits"] == 1
        hit = data["hits"][0]
        assert hit["critic"]["verdict"] == "confirmed"
        assert hit["critic"]["confidence"] == 0.92
        assert hit["item"]["crop_image_url"] == (
            "https://real-r2.test/evidence/Assault007_x264/m86a5c319e26659804b0/instruments/I1.jpg"
        )


# =============================================================================
# 5. Critic Call Delay Spacing Tests
# =============================================================================


class TimingCriticEvaluator(CriticEvaluator):
    """Fake critic evaluator that records call timestamps and candidate item IDs."""

    def __init__(
        self,
        verdict: str = "confirmed",
        confidence: float | None = 0.95,
        rationale: str = "Timing test passed",
        raise_on_item_id: str | None = None,
        simulated_work_seconds: float = 0.0,
    ) -> None:
        self.verdict = verdict
        self.confidence = confidence
        self.rationale = rationale
        self.raise_on_item_id = raise_on_item_id
        self.simulated_work_seconds = simulated_work_seconds
        self.call_records: list[dict[str, Any]] = []

    async def evaluate_candidate(
        self,
        query: str,
        item: ItemHit,
        incident: IncidentHit,
    ) -> CriticVerdict:
        call_time = time.perf_counter()
        self.call_records.append(
            {
                "item_id": item.item_id,
                "timestamp": call_time,
                "rank_hint": len(self.call_records) + 1,
            }
        )
        if self.simulated_work_seconds > 0:
            await asyncio.sleep(self.simulated_work_seconds)
        if self.raise_on_item_id and item.item_id == self.raise_on_item_id:
            raise RuntimeError(f"Simulated critic failure for {item.item_id}")
        return CriticVerdict(
            verdict=self.verdict,  # type: ignore[arg-type]
            confidence=self.confidence,
            rationale=self.rationale,
        )


class TestCriticDelaySpacing:
    """Unit tests verifying configurable delay spacing between critic calls."""

    def test_critic_delay_applied_between_calls(self, sample_candidates: list[EvidenceCandidate]) -> None:
        """Verify that critic calls start spaced by the configured delay."""
        store = InMemorySearchStore(candidates=sample_candidates)
        critic = TimingCriticEvaluator()
        configured_delay = 0.08

        app = FastAPI()
        router = create_incident_search_router(
            store=store,
            critic=critic,
            critic_delay_seconds=configured_delay,
        )
        app.include_router(router)

        client = TestClient(app)
        resp = client.post("/api/v1/incidents/search", json={"query": "weapon search", "top_k": 3})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_hits"] == 3
        assert len(critic.call_records) == 3

        # Call timestamps should be separated by at least ~configured_delay
        t0 = critic.call_records[0]["timestamp"]
        t1 = critic.call_records[1]["timestamp"]
        t2 = critic.call_records[2]["timestamp"]

        assert t1 - t0 >= configured_delay * 0.8
        assert t2 - t1 >= configured_delay * 0.8

        # Rank order must strictly match candidate order
        for idx, hit in enumerate(data["hits"], start=1):
            assert hit["rank"] == idx
            assert hit["item"]["item_id"] == sample_candidates[idx - 1].item_id
            assert hit["critic"]["verdict"] == "confirmed"

    def test_critic_delay_zero_disables_spacing(self, sample_candidates: list[EvidenceCandidate]) -> None:
        """Verify that delay=0 restores concurrent execution without delay spacing."""
        store = InMemorySearchStore(candidates=sample_candidates)
        critic = TimingCriticEvaluator()

        app = FastAPI()
        router = create_incident_search_router(
            store=store,
            critic=critic,
            critic_delay_seconds=0.0,
        )
        app.include_router(router)

        client = TestClient(app)
        t_start = time.perf_counter()
        resp = client.post("/api/v1/incidents/search", json={"query": "weapon search", "top_k": 3})
        t_total = time.perf_counter() - t_start

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_hits"] == 3
        assert len(critic.call_records) == 3

        # Calls should launch almost instantaneously with no 1s sleeps
        t0 = critic.call_records[0]["timestamp"]
        t2 = critic.call_records[2]["timestamp"]
        assert t2 - t0 < 0.05
        assert t_total < 0.2

        # Rank order preserved
        for idx, hit in enumerate(data["hits"], start=1):
            assert hit["rank"] == idx
            assert hit["item"]["item_id"] == sample_candidates[idx - 1].item_id

    def test_order_preserved_when_critic_calls_take_varying_durations(
        self, sample_candidates: list[EvidenceCandidate]
    ) -> None:
        """Verify rank order is strictly preserved even when earlier calls take longer than later ones."""
        store = InMemorySearchStore(candidates=sample_candidates)

        class VariableDurationCritic(CriticEvaluator):
            async def evaluate_candidate(self, query: str, item: ItemHit, incident: IncidentHit) -> CriticVerdict:
                # Rank 1 sleeps longer than rank 2 and 3
                if item.item_id == sample_candidates[0].item_id:
                    await asyncio.sleep(0.06)
                return CriticVerdict(verdict="confirmed", confidence=0.9, rationale="ok")

        app = FastAPI()
        router = create_incident_search_router(
            store=store,
            critic=VariableDurationCritic(),
            critic_delay_seconds=0.01,
        )
        app.include_router(router)

        client = TestClient(app)
        resp = client.post("/api/v1/incidents/search", json={"query": "weapon search", "top_k": 3})

        assert resp.status_code == 200
        data = resp.json()
        assert [h["rank"] for h in data["hits"]] == [1, 2, 3]
        assert [h["item"]["item_id"] for h in data["hits"]] == [
            sample_candidates[0].item_id,
            sample_candidates[1].item_id,
            sample_candidates[2].item_id,
        ]

    def test_critic_failure_degrades_to_unverified_with_delay(self, sample_candidates: list[EvidenceCandidate]) -> None:
        """Verify that critic failures degrade gracefully to unverified and hits are never dropped."""
        store = InMemorySearchStore(candidates=sample_candidates)
        # Item E1 fails; I1 succeeds
        failing_item_id = sample_candidates[1].item_id
        critic = TimingCriticEvaluator(raise_on_item_id=failing_item_id)

        app = FastAPI()
        router = create_incident_search_router(
            store=store,
            critic=critic,
            critic_delay_seconds=0.02,
        )
        app.include_router(router)

        client = TestClient(app)
        resp = client.post("/api/v1/incidents/search", json={"query": "weapon search", "top_k": 3})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_hits"] == 3
        # Hits are in rank order
        assert [h["rank"] for h in data["hits"]] == [1, 2, 3]
        # Item 0 passed
        assert data["hits"][0]["critic"]["verdict"] == "confirmed"
        # Item 1 degraded to unverified
        assert data["hits"][1]["critic"]["verdict"] == "unverified"
        assert data["hits"][1]["critic"]["confidence"] is None
        assert "Simulated critic failure" in data["hits"][1]["critic"]["rationale"]
        # Item 2 passed
        assert data["hits"][2]["critic"]["verdict"] == "confirmed"

    def test_critic_delay_environment_variable(
        self, monkeypatch: pytest.MonkeyPatch, sample_candidates: list[EvidenceCandidate]
    ) -> None:
        """Verify helper and router resolution of INCIDENT_SEARCH_CRITIC_DELAY_SECONDS."""
        # Unset defaults to 1.0
        monkeypatch.delenv(CRITIC_DELAY_ENV_VAR, raising=False)
        assert _get_critic_delay_seconds() == DEFAULT_CRITIC_DELAY_SECONDS
        assert DEFAULT_CRITIC_DELAY_SECONDS == 1.0

        # Custom float string
        monkeypatch.setenv(CRITIC_DELAY_ENV_VAR, "0.05")
        assert _get_critic_delay_seconds() == 0.05

        # 0 disables delay
        monkeypatch.setenv(CRITIC_DELAY_ENV_VAR, "0")
        assert _get_critic_delay_seconds() == 0.0

        # Negative value clamped to 0.0
        monkeypatch.setenv(CRITIC_DELAY_ENV_VAR, "-2.5")
        assert _get_critic_delay_seconds() == 0.0

        # Invalid string falls back to default
        monkeypatch.setenv(CRITIC_DELAY_ENV_VAR, "invalid_num")
        assert _get_critic_delay_seconds() == DEFAULT_CRITIC_DELAY_SECONDS

        # Explicit parameter override takes precedence over env var
        assert _get_critic_delay_seconds(configured_delay=0.25) == 0.25
        assert _get_critic_delay_seconds(configured_delay=0.0) == 0.0

    def test_route_uses_env_var_dynamically(
        self, monkeypatch: pytest.MonkeyPatch, sample_candidates: list[EvidenceCandidate]
    ) -> None:
        """Verify that route reads INCIDENT_SEARCH_CRITIC_DELAY_SECONDS if not overridden."""
        monkeypatch.setenv(CRITIC_DELAY_ENV_VAR, "0.05")
        store = InMemorySearchStore(candidates=sample_candidates)
        critic = TimingCriticEvaluator()

        app = FastAPI()
        # No critic_delay_seconds passed: resolves from env var
        router = create_incident_search_router(store=store, critic=critic)
        app.include_router(router)

        client = TestClient(app)
        resp = client.post("/api/v1/incidents/search", json={"query": "test query", "top_k": 2})

        assert resp.status_code == 200
        assert len(critic.call_records) == 2
        t0 = critic.call_records[0]["timestamp"]
        t1 = critic.call_records[1]["timestamp"]
        assert t1 - t0 >= 0.05 * 0.8


class TestDefaultQueryEmbedder:
    """DefaultQueryEmbedder uses the remote embedding endpoint when configured, else a placeholder."""

    @pytest.mark.asyncio
    async def test_uses_remote_embedder_when_configured(self) -> None:
        remote = RemoteTextEmbedder(api_key="k")
        remote.embed_query = AsyncMock(return_value=[0.1] * 1024)  # type: ignore[method-assign]

        vector = await DefaultQueryEmbedder(remote=remote).embed_query("edged weapon")

        assert vector == [0.1] * 1024
        remote.embed_query.assert_awaited_once_with("edged weapon")

    @pytest.mark.asyncio
    async def test_falls_back_to_placeholder_without_api_key(self) -> None:
        vector = await DefaultQueryEmbedder(remote=RemoteTextEmbedder(api_key="")).embed_query("edged weapon")

        assert len(vector) == 1024
        assert abs(sum(x * x for x in vector) - 1.0) < 1e-3
