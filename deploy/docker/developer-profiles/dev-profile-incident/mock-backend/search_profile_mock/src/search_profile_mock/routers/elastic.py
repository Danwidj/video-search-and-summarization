"""Elasticsearch / Logstash info stubs for smoke checks.

The UI never calls Elasticsearch or Logstash directly - the agent's
embed_search tool and the analytics pipeline do. These minimal stubs exist
so cluster health checks and index probes against the mock get well-shaped
answers instead of 404s. Hit counts derive from the in-memory stream
catalog; `_search` never scores anything real.

Kafka has no plain-HTTP surface (broker protocol only), so there is
nothing to stub here - see README.md. DeepStream perception likewise has
no UI-facing HTTP surface; its observable output (indexed embeddings and
frame bboxes) is mocked via `/api/v1/search` and
`/video-analytics-api/frames`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request

from search_profile_mock.state import AppState
from search_profile_mock.state import get_state

router = APIRouter()


@router.get("/")
async def es_info() -> dict[str, Any]:
    return {
        "name": "mock-es",
        "cluster_name": "mock-search",
        "cluster_uuid": "mock-uuid",
        "version": {"number": "8-mock", "build_flavor": "mock"},
        "tagline": "You Know, for Search",
    }


@router.get("/_cluster/health")
async def cluster_health() -> dict[str, Any]:
    return {
        "cluster_name": "mock-search",
        "status": "green",
        "timed_out": False,
        "number_of_nodes": 1,
        "number_of_data_nodes": 1,
        "active_primary_shards": 1,
        "active_shards": 1,
    }


@router.api_route("/{index}/_search", methods=["GET", "POST"])
async def index_search(index: str, request: Request, state: AppState = Depends(get_state)) -> dict[str, Any]:  # noqa: ARG001 - request accepted for body-GET parity with ES, unused by this static mock
    async with state.lock:
        streams = list(state.streams.values())
    hits = [
        {
            "_index": index,
            "_id": stream.stream_id,
            "_score": 1.0,
            "_source": {"sensor_id": stream.stream_id, "video_name": stream.filename},
        }
        for stream in streams
    ]
    return {
        "took": 0,
        "timed_out": False,
        "hits": {"total": {"value": len(hits), "relation": "eq"}, "hits": hits},
    }


@router.get("/_node/stats")
async def logstash_node_stats() -> dict[str, Any]:
    """Logstash monitoring-API-shaped stub (real Logstash serves this on 9600)."""
    return {
        "host": "mock-logstash",
        "version": "8-mock",
        "http_address": "mock",
        "pipeline": {"workers": 1, "batch_size": 125, "events": {"in": 0, "out": 0}},
    }
