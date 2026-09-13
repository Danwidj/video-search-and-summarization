"""Mock stand-in for HAProxy + vss-agent + VIOS/VST + search analytics.

Serves every path prefix the real bp_developer_search UI expects
(/api/v1/* incl. /search, /websocket, /chat/stream, /vst/api/v1/*,
/video-analytics-api/*, /kibana/*, /static/*) on one port, so the real,
unmodified UI can be exercised with zero GPU and zero NIM containers.
See README.md for run instructions and the exact NEXT_PUBLIC_* env vars
to point the UI at this server.

Superset of base_profile_mock: all base routes are present unchanged, plus
the search-profile additions (agent search endpoints, VST sensor list,
video-analytics-api /frames, Kibana stubs, ES/Logstash info stubs).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from search_profile_mock.routers import agent_chat_http
from search_profile_mock.routers import agent_rtsp
from search_profile_mock.routers import agent_search
from search_profile_mock.routers import agent_static
from search_profile_mock.routers import agent_video
from search_profile_mock.routers import analytics_frames
from search_profile_mock.routers import elastic
from search_profile_mock.routers import health
from search_profile_mock.routers import kibana
from search_profile_mock.routers import vst_replay
from search_profile_mock.routers import vst_sensor
from search_profile_mock.routers import vst_sensor_list
from search_profile_mock.routers import vst_storage
from search_profile_mock.routers import websocket


def create_app() -> FastAPI:
    app = FastAPI(title="search_profile_mock")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(agent_video.router)
    app.include_router(agent_rtsp.router)
    app.include_router(agent_search.router)
    app.include_router(agent_chat_http.router)
    app.include_router(agent_static.router)
    app.include_router(vst_storage.router)
    app.include_router(vst_sensor.router)
    app.include_router(vst_sensor_list.router)
    app.include_router(vst_replay.router)
    app.include_router(analytics_frames.router)
    app.include_router(kibana.router)
    app.include_router(elastic.router)
    app.include_router(websocket.router)

    return app


def main() -> None:
    import uvicorn

    from search_profile_mock.config import settings

    uvicorn.run("search_profile_mock.app:create_app", factory=True, host="0.0.0.0", port=settings.port, reload=True)


if __name__ == "__main__":
    main()
