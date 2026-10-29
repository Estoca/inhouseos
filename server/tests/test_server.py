"""End to end over real HTTP: uvicorn in a thread, the official MCP client against /mcp."""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError

from iho.config import Settings
from iho.server import create_application

TOKEN = "dev-token-for-tests-0123456789"
USER = "Ana@Example.com"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(tmp_path):
    port = _free_port()
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        public_url=f"http://127.0.0.1:{port}",
        auth_mode="dev",
        dev_token=TOKEN,
        dev_user=USER,
    )
    app = create_application(settings)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not srv.started:
        if time.time() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", settings
    srv.should_exit = True
    thread.join(timeout=5)


async def _session_call(base: str, token: str, fn):
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(headers=headers) as http:
        async with streamable_http_client(f"{base}/mcp", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)


def test_health_and_data_dir(server):
    base, settings = server
    r = httpx.get(f"{base}/health")
    assert r.status_code == 200
    assert r.json()["service"] == "iho-server"
    assert settings.repos_dir.is_dir()


def test_mcp_lists_tools_and_knows_the_caller(server):
    base, _ = server

    async def run(session: ClientSession):
        tools = await session.list_tools()
        result = await session.call_tool("iho_whoami", {})
        return [t.name for t in tools.tools], result

    names, result = asyncio.run(_session_call(base, TOKEN, run))
    assert "iho_whoami" in names
    payload = json.loads(result.content[0].text)
    assert payload["email"] == "ana@example.com"
    assert payload["domain"] == "example.com"
    assert payload["auth_mode"] == "dev"


def test_mcp_refuses_missing_or_wrong_token(server):
    base, _ = server
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    headers = {"Accept": "application/json, text/event-stream"}
    assert httpx.post(f"{base}/mcp", json=body, headers=headers).status_code == 401
    wrong = {**headers, "Authorization": "Bearer not-the-token-not-the-token"}
    assert httpx.post(f"{base}/mcp", json=body, headers=wrong).status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {"dev_token": "", "dev_user": "a@b.com"},
        {"dev_token": "short", "dev_user": "a@b.com"},
        {"dev_token": TOKEN, "dev_user": "not-an-email"},
        {"auth_mode": "standalone", "dev_token": TOKEN, "dev_user": "a@b.com"},
    ],
)
def test_settings_refuse_unsafe_or_unimplemented(tmp_path, overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, data_dir=tmp_path, **({"auth_mode": "dev"} | overrides))
