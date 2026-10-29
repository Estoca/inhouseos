"""The iho-server application: one process, one /mcp endpoint, one data volume."""
from __future__ import annotations

import os

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from iho import __version__
from iho.actor import build_verifier, current_actor
from iho.config import Settings

INSTRUCTIONS = (
    "InHouseOS: each person's private second brain, the company's shared tracker, its compass "
    "and its company brain. Act only for the authenticated person. Private content (raw sources, "
    "the person's wiki) never leaves that person's brain unless they promote it."
)

HOME_HTML = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>InHouseOS</title></head>'
    "<body><p>InHouseOS server. Connect your agent to the <code>/mcp</code> endpoint.</p></body></html>"
)


def prepare_data_dir(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.repos_dir.mkdir(parents=True, exist_ok=True)


def create_application(settings: Settings, *, token_verifier: TokenVerifier | None = None) -> Starlette:
    prepare_data_dir(settings)
    public_url = AnyHttpUrl(settings.normalized_public_url)

    mcp = FastMCP(
        name="InHouseOS",
        instructions=INSTRUCTIONS,
        token_verifier=token_verifier or build_verifier(settings),
        auth=AuthSettings(issuer_url=public_url, resource_server_url=public_url, required_scopes=[]),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )

    @mcp.tool()
    def iho_whoami() -> dict:
        """Who you are on this InHouseOS server, and which server it is."""
        actor = current_actor()
        return {
            "email": actor.email,
            "domain": actor.domain,
            "server": settings.normalized_public_url,
            "version": __version__,
            "auth_mode": settings.auth_mode.value,
        }

    app = mcp.streamable_http_app()

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "service": "iho-server",
            "version": __version__,
            "commit_sha": os.environ.get("GIT_COMMIT_SHA", "unknown"),
        })

    async def home(_: Request) -> HTMLResponse:
        return HTMLResponse(HOME_HTML)

    app.routes[:0] = [
        Route("/health", health, methods=["GET"]),
        Route("/", home, methods=["GET"]),
    ]
    return app
