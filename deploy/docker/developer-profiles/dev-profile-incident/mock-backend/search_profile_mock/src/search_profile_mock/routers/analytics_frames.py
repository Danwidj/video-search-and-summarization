"""video-analytics-api surface: frame metadata for search-by-image bboxes.

Mirrors `GET /frames` from
services/analytics/video-analytics-api/src/app/specification/openapi.json
(`controller.frames.getRawFrames`), served in real deployments under the
`/video-analytics-api` HAProxy prefix
(`NEXT_PUBLIC_MDX_WEB_API_URL=.../video-analytics-api`). The search tab
queries it as
`{mdxWebApiUrl}/frames?sensorId=...&fromTimestamp=...&toTimestamp=...` -
see services/ui/packages/nv-metropolis-bp-vss-ui/search/lib-src/hooks/useSearchByImage.ts.

There is no real DeepStream perception or Elasticsearch frame index behind
this mock: bboxes are deterministic hashes of (sensor, timestamp) via
templates.build_frames_response. The UI tolerates an empty object list, so
unknown sensors still get a well-shaped, box-free frame.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from search_profile_mock.templates import build_frames_response

router = APIRouter(prefix="/video-analytics-api")


@router.get("/frames")
async def get_frames(
    sensorId: str,  # noqa: N803 - query param name is the UI's contract
    fromTimestamp: str | None = None,  # noqa: N803 - range bound is the UI's contract, unused by this static mock
    toTimestamp: str | None = None,  # noqa: N803 - range bound is the UI's contract, unused by this static mock
) -> dict[str, Any]:
    timestamp = toTimestamp or fromTimestamp or ""
    return build_frames_response(sensorId, timestamp)
