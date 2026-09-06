"""Mock stand-in for HAProxy + vss-agent + VIOS/VST + LLM/VLM NIMs.

Serves every path prefix the real bp_developer_base UI expects
(/api/v1/*, /websocket, /chat/stream, /vst/api/v1/*, /static/*) on one port,
so the real, unmodified UI can be exercised with zero GPU and zero NIM
containers. See README.md for run instructions and the exact
NEXT_PUBLIC_* env vars to point the UI at this server.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from base_profile_mock.routers import agent_chat_http
from base_profile_mock.routers import agent_rtsp
from base_profile_mock.routers import agent_static
from base_profile_mock.routers import agent_video
from base_profile_mock.routers import health
from base_profile_mock.routers import vst_replay
from base_profile_mock.routers import vst_sensor
from base_profile_mock.routers import vst_storage
from base_profile_mock.routers import websocket


def create_app() -> FastAPI:
    app = FastAPI(title="base_profile_mock")

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
    app.include_router(agent_chat_http.router)
    app.include_router(agent_static.router)
    app.include_router(vst_storage.router)
    app.include_router(vst_sensor.router)
    app.include_router(vst_replay.router)
    app.include_router(websocket.router)

    return app


def main() -> None:
    import uvicorn

    from base_profile_mock.config import settings

    uvicorn.run("base_profile_mock.app:create_app", factory=True, host="0.0.0.0", port=settings.port, reload=True)


if __name__ == "__main__":
    main()
