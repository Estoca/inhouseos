"""End to end over real HTTP: uvicorn in a thread, the official MCP client against /mcp."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from mcp import ClientSession
from pydantic import ValidationError

from conftest import TOKEN, mcp_session
from iho.config import Settings


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

    names, result = asyncio.run(mcp_session(base, run))
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
