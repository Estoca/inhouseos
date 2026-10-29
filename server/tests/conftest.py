from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

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


async def mcp_session(base: str, fn, token: str = TOKEN):
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(headers=headers) as http:
        async with streamable_http_client(f"{base}/mcp", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)


async def call(session: ClientSession, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """A tool result as a dict; a tool error as {"error": "<code>: <message>"}."""
    r = await session.call_tool(name, args or {})
    text = r.content[0].text
    if r.isError:
        # FastMCP wraps ToolError as "Error executing tool <name>: <code>: <message>"
        prefix = f"Error executing tool {name}: "
        return {"error": text.removeprefix(prefix)}
    return json.loads(text)
