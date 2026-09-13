"""Kibana surface for the dashboard tab, served under the `/kibana` prefix.

In real deployments the UI embeds Kibana at
`NEXT_PUBLIC_DASHBOARD_TAB_KIBANA_BASE_URL=.../kibana` via an iframe (see
services/ui/packages/nv-metropolis-bp-vss-ui/dashboard/lib-src/DashboardComponent.tsx)
and its SSR layer lists dashboards through
`{kibanaBaseUrl}/api/saved_objects/_find?type=dashboard...` (see
dashboard/lib-src/server.ts). This router serves both: a canned
saved-objects listing and a placeholder HTML page so the iframe loads
instead of erroring. It is not a Kibana replacement.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import HTMLResponse

from search_profile_mock.templates import build_kibana_dashboards

router = APIRouter(prefix="/kibana")


@router.get("/api/saved_objects/_find")
async def find_saved_objects(type: str | None = None) -> dict[str, Any]:  # noqa: ARG001 - filter is the API's contract; this mock serves one dashboard
    return build_kibana_dashboards()


@router.get("/api/status")
async def kibana_status() -> dict[str, Any]:
    return {
        "status": {"overall": {"state": "green", "title": "Green (mock)"}},
        "version": {"number": "mock", "build_snapshot": False},
    }


@router.get("/app/dashboards")
async def dashboards_app(request: Request) -> HTMLResponse:
    base = str(request.base_url).rstrip("/")
    return HTMLResponse(
        "<!doctype html><html><head><title>Kibana (mock)</title></head>"
        "<body><h1>Kibana placeholder (mock)</h1>"
        "<p>This stand-in is served by the search-profile mock backend. Dashboards "
        f'listed at <a href="{base}/kibana/api/saved_objects/_find?type=dashboard">'
        "/kibana/api/saved_objects/_find</a>.</p></body></html>"
    )
