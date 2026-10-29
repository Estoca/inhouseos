"""Standalone login end to end: the OAuth dance an agent like claude.ai does, against a fake Google.

Discovery → dynamic client registration → /authorize (redirects upstream) → upstream sends the
person back to /oauth/callback → code to the agent → /token with PKCE → /mcp with the token.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import threading
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import uvicorn

from conftest import _free_port, call
from iho.config import Settings
from iho.oauth import OAuthProvider
from iho.server import create_application

IDP = "https://idp.test"
REDIRECT = "https://claude.ai/api/mcp/auth_callback"
PROFILES = {
    "ana": {"email": "ana@example.com", "email_verified": True, "hd": "example.com"},
    "guest": {"email": "guest@outside.org", "email_verified": True},
    "stranger": {"email": "eve@elsewhere.com", "email_verified": True, "hd": "elsewhere.com"},
    "no-hd": {"email": "bob@example.com", "email_verified": True},
    "unverified": {"email": "carl@example.com", "email_verified": False, "hd": "example.com"},
}


def fake_idp(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/.well-known/openid-configuration":
        return httpx.Response(200, json={"issuer": IDP, "authorization_endpoint": f"{IDP}/auth",
                                         "token_endpoint": f"{IDP}/token", "userinfo_endpoint": f"{IDP}/userinfo"})
    if request.url.path == "/token":
        form = parse_qs(request.content.decode())
        assert form["client_secret"] == ["upstream-secret"] and form["code_verifier"][0]
        return httpx.Response(200, json={"access_token": f"up-{form['code'][0]}", "token_type": "Bearer"})
    if request.url.path == "/userinfo":
        who = request.headers["authorization"].removeprefix("Bearer up-")
        return httpx.Response(200, json=PROFILES[who])
    return httpx.Response(404)


@pytest.fixture
def oauth_server(tmp_path):
    port = _free_port()
    settings = Settings(
        _env_file=None, data_dir=tmp_path / "data", public_url=f"http://127.0.0.1:{port}",
        auth_mode="standalone", oidc_provider="google", oidc_issuer=IDP,
        oidc_client_id="upstream-client", oidc_client_secret="upstream-secret",
        allowed_domains="example.com", allowed_emails="guest@outside.org",
    )
    settings.data_dir.mkdir(parents=True)
    provider = OAuthProvider(settings, settings.db_path,
                             http_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake_idp)))
    app = create_application(settings, oauth_provider=provider)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not srv.started:
        if time.time() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=5)


def register(base: str, redirect: str = REDIRECT) -> httpx.Response:
    return httpx.post(f"{base}/register", json={
        "redirect_uris": [redirect], "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "client_name": "test agent"})


def login(base: str, who: str) -> tuple[str, dict, str]:
    """Run the dance up to the agent's redirect. Returns (client_id, redirect query, code_verifier)."""
    client_id = register(base).json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    r = httpx.get(f"{base}/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "state": "agent-state",
        "code_challenge": challenge, "code_challenge_method": "S256"})
    assert r.status_code == 302, r.text
    upstream = urlparse(r.headers["location"])
    q = parse_qs(upstream.query)
    assert f"{upstream.scheme}://{upstream.netloc}{upstream.path}" == f"{IDP}/auth"
    assert q["client_id"] == ["upstream-client"] and q["hd"] == ["example.com"]
    assert q["redirect_uri"] == [f"{base}/oauth/callback"] and q["code_challenge_method"] == ["S256"]
    back = httpx.get(f"{base}/oauth/callback", params={"code": who, "state": q["state"][0]})
    assert back.status_code == 302
    location = urlparse(back.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == REDIRECT
    return client_id, {k: v[0] for k, v in parse_qs(location.query).items()}, verifier


def token(base: str, **form: str) -> httpx.Response:
    return httpx.post(f"{base}/token", data=form)


async def _whoami(base: str, access: str) -> dict:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {access}"}) as http:
        async with streamable_http_client(f"{base}/mcp", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await call(session, "iho_whoami")


def test_metadata_points_agents_at_this_server(oauth_server):
    base = oauth_server
    meta = httpx.get(f"{base}/.well-known/oauth-authorization-server").json()
    assert meta["authorization_endpoint"] == f"{base}/authorize"
    assert meta["registration_endpoint"] == f"{base}/register"
    assert "S256" in meta["code_challenge_methods_supported"]
    unauth = httpx.post(f"{base}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                        headers={"Accept": "application/json, text/event-stream"})
    assert unauth.status_code == 401
    assert "resource_metadata=" in unauth.headers.get("www-authenticate", "")


def test_full_login_then_mcp_then_refresh_and_revoke(oauth_server):
    base = oauth_server
    client_id, back, verifier = login(base, "ana")
    assert back["state"] == "agent-state" and "code" in back
    wrong_pkce = token(base, grant_type="authorization_code", code=back["code"], redirect_uri=REDIRECT,
                       client_id=client_id, code_verifier="not-the-verifier-not-the-verifier-not-the-verifier")
    assert wrong_pkce.status_code == 400
    r = token(base, grant_type="authorization_code", code=back["code"], redirect_uri=REDIRECT,
              client_id=client_id, code_verifier=verifier)
    assert r.status_code == 200, r.text
    tokens = r.json()
    assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == 3600 and tokens["refresh_token"]
    reused = token(base, grant_type="authorization_code", code=back["code"], redirect_uri=REDIRECT,
                   client_id=client_id, code_verifier=verifier)
    assert reused.status_code == 400

    me = asyncio.run(_whoami(base, tokens["access_token"]))
    assert me["email"] == "ana@example.com" and me["auth_mode"] == "standalone"

    refreshed = token(base, grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=client_id)
    assert refreshed.status_code == 200, refreshed.text
    new = refreshed.json()
    assert asyncio.run(_whoami(base, new["access_token"]))["email"] == "ana@example.com"
    old = httpx.post(f"{base}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                     headers={"Authorization": f"Bearer {tokens['access_token']}",
                              "Accept": "application/json, text/event-stream"})
    assert old.status_code == 401  # rotation retires the previous pair
    assert token(base, grant_type="refresh_token", refresh_token=tokens["refresh_token"],
                 client_id=client_id).status_code == 400

    # the SDK's revocation model requires the client_secret field even for public clients: send it empty
    revoke = {"token": new["refresh_token"], "client_id": client_id, "client_secret": ""}
    assert httpx.post(f"{base}/revoke", data=revoke).status_code == 200
    gone = httpx.post(f"{base}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                      headers={"Authorization": f"Bearer {new['access_token']}",
                               "Accept": "application/json, text/event-stream"})
    assert gone.status_code == 401  # revoking the refresh token drops the whole grant


def test_invited_email_from_another_domain_gets_in(oauth_server):
    _, back, _ = login(oauth_server, "guest")
    assert "code" in back


@pytest.mark.parametrize("who,reason", [
    ("stranger", "not part of this company"),
    ("no-hd", "Google Workspace"),
    ("unverified", "not verified"),
])
def test_refused_logins_go_back_as_access_denied(oauth_server, who, reason):
    _, back, _ = login(oauth_server, who)
    assert back["error"] == "access_denied" and reason in back["error_description"]
    assert "code" not in back


def test_registration_only_for_known_agent_hosts(oauth_server):
    assert register(oauth_server).status_code == 201
    assert register(oauth_server, "http://localhost:33418/callback").status_code == 201
    evil = register(oauth_server, "https://evil.example/callback")
    assert evil.status_code == 400 and evil.json()["error"] == "invalid_redirect_uri"


def test_stale_or_unknown_callback_state_is_refused(oauth_server):
    r = httpx.get(f"{oauth_server}/oauth/callback", params={"code": "ana", "state": "made-up"})
    assert r.status_code == 400
