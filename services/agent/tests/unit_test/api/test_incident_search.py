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

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from pydantic import ValidationError
import pytest

from vss_agents.api.incident_search import CriticEvaluator
from vss_agents.api.incident_search import CriticVerdict
from vss_agents.api.incident_search import DefaultQueryEmbedder
from vss_agents.api.incident_search import EvidenceCandidate
from vss_agents.api.incident_search import IncidentHit
from vss_agents.api.incident_search import InMemorySearchStore
from vss_agents.api.incident_search import ItemHit
from vss_agents.api.incident_search import SearchRequest
from vss_agents.api.incident_search import SearchResponse
from vss_agents.api.incident_search import VlmCriticEvaluator
from vss_agents.api.incident_search import create_incident_search_router
from vss_agents.api.incident_search import register_incident_search_routes

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
        assert req.min_similarity == 0.2
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
        router = create_incident_search_router(store=store, critic=critic, embedder=DefaultQueryEmbedder())
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
