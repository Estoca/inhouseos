"""Standalone login: iho-server is the OAuth server the agent connects to (claude.ai, Claude Code).

The MCP SDK serves the OAuth routes (/register, /authorize, /token, /revoke and the metadata) and
asks this provider for storage and for the login itself. Login is delegated upstream:

    agent → /authorize → Google (or any OpenID provider) → /oauth/callback → agent, with our code

The callback admits a person only with a verified e-mail from an allowed domain (for Google, the
Workspace domain `hd` must match too: a personal Google account opened with a work address has no
`hd`) or an invited e-mail. The code it hands back carries that e-mail as the subject, and every
token minted from it does too: that subject is who iho.actor says is calling.

Tokens are opaque random strings; only their SHA-256 is stored. A grant (one login) has one access
and one refresh token at a time; refreshing rotates both, revoking either drops the whole grant.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from iho.config import Settings

CALLBACK_PATH = "/oauth/callback"
PENDING_SECONDS = 600
CODE_SECONDS = 300

SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_clients (client_id TEXT PRIMARY KEY, info TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_pending (
    state TEXT PRIMARY KEY, client_id TEXT NOT NULL, params TEXT NOT NULL, verifier TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_codes (
    code_hash TEXT PRIMARY KEY, client_id TEXT NOT NULL, subject TEXT NOT NULL, scopes TEXT NOT NULL,
    code_challenge TEXT NOT NULL, redirect_uri TEXT NOT NULL, explicit INTEGER NOT NULL, resource TEXT,
    expires_at REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS oauth_tokens (
    token_hash TEXT PRIMARY KEY, kind TEXT NOT NULL, grant_id TEXT NOT NULL, client_id TEXT NOT NULL,
    subject TEXT NOT NULL, scopes TEXT NOT NULL, resource TEXT, expires_at INTEGER NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS oauth_tokens_grant ON oauth_tokens (grant_id);
"""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class LoginRefused(Exception):
    """The upstream login worked, but this person may not use this server."""


class OAuthProvider:
    def __init__(self, settings: Settings, db_path: Path,
                 http_factory: Callable[[], httpx.AsyncClient] | None = None):
        self.s = settings
        self._http_factory = http_factory or (lambda: httpx.AsyncClient(timeout=15))
        self._discovery: dict[str, Any] | None = None
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)

    @property
    def callback_url(self) -> str:
        return f"{self.s.normalized_public_url}{CALLBACK_PATH}"

    def _q(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # ------------------------------------------------------------ clients (DCR)
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        rows = self._q("SELECT info FROM oauth_clients WHERE client_id = ?", (client_id,))
        return OAuthClientInformationFull.model_validate_json(rows[0][0]) if rows else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        allowed = self.s.oauth_redirect_host_set
        for uri in client_info.redirect_uris or []:
            if (uri.host or "").lower() not in allowed:
                raise RegistrationError(error="invalid_redirect_uri",
                                        error_description=f"Redirects to {uri.host} are not accepted by this server.")
        self._q("INSERT OR REPLACE INTO oauth_clients (client_id, info, created_at) VALUES (?, ?, ?)",
                (client_info.client_id, client_info.model_dump_json(), time.time()))

    # ------------------------------------------------------------ login
    async def _oidc(self) -> dict[str, Any]:
        if self._discovery is None:
            url = f"{self.s.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
            async with self._http_factory() as http:
                r = await http.get(url)
                r.raise_for_status()
                self._discovery = r.json()
        return self._discovery

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        try:
            oidc = await self._oidc()
        except httpx.HTTPError as exc:
            raise AuthorizeError(error="temporarily_unavailable",
                                 error_description="The sign-in provider did not answer.") from exc
        state = secrets.token_urlsafe(32)
        verifier, challenge = _pkce_pair()
        self._q("INSERT INTO oauth_pending (state, client_id, params, verifier, expires_at) VALUES (?, ?, ?, ?, ?)",
                (state, client.client_id or "", params.model_dump_json(), verifier, time.time() + PENDING_SECONDS))
        query = {"client_id": self.s.oidc_client_id, "redirect_uri": self.callback_url, "response_type": "code",
                 "scope": "openid email profile", "state": state, "code_challenge": challenge,
                 "code_challenge_method": "S256", "prompt": "select_account"}
        if self.s.oidc_provider == "google" and len(self.s.allowed_domain_set) == 1:
            query["hd"] = next(iter(self.s.allowed_domain_set))  # a hint for the account chooser, not a check
        return f"{oidc['authorization_endpoint']}?{urlencode(query)}"

    def admit(self, info: dict[str, Any]) -> str:
        """The e-mail this upstream identity signs in as, or LoginRefused."""
        email = str(info.get("email") or "").strip().lower()
        if "@" not in email:
            raise LoginRefused("The sign-in provider did not share an e-mail address.")
        verified = info.get("email_verified")
        if verified is False or str(verified).lower() == "false" or (self.s.oidc_provider == "google" and verified is not True):
            raise LoginRefused(f"{email} is not verified by the sign-in provider.")
        if email in self.s.allowed_email_set:
            return email
        domain = email.rsplit("@", 1)[1]
        if domain not in self.s.allowed_domain_set:
            raise LoginRefused(f"{email} is not part of this company's InHouseOS.")
        if self.s.oidc_provider == "google" and str(info.get("hd") or "").lower() != domain:
            raise LoginRefused(f"{email} must sign in with the company's Google Workspace account.")
        return email

    async def callback(self, request: Request) -> Response:
        state = request.query_params.get("state", "")
        rows = self._q("SELECT client_id, params, verifier, expires_at FROM oauth_pending WHERE state = ?", (state,))
        self._q("DELETE FROM oauth_pending WHERE state = ? OR expires_at < ?", (state, time.time()))
        if not rows or rows[0][3] < time.time():
            return _page(400, "This sign-in link expired. Start again from your agent.")
        client_id, params_json, verifier, _ = rows[0]
        params = AuthorizationParams.model_validate_json(params_json)

        def back(**extra: str | None) -> RedirectResponse:
            return RedirectResponse(construct_redirect_uri(str(params.redirect_uri), state=params.state, **extra),
                                    status_code=302)

        if request.query_params.get("error"):
            return back(error="access_denied", error_description="Sign-in was cancelled.")
        try:
            email = self.admit(await self._userinfo(request.query_params.get("code", ""), verifier))
        except LoginRefused as exc:
            return back(error="access_denied", error_description=str(exc))
        except httpx.HTTPError:
            return back(error="temporarily_unavailable", error_description="The sign-in provider did not answer.")
        code = secrets.token_urlsafe(32)
        self._q("INSERT INTO oauth_codes (code_hash, client_id, subject, scopes, code_challenge, redirect_uri, explicit,"
                " resource, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_hash(code), client_id, email, json.dumps(params.scopes or []), params.code_challenge,
                 str(params.redirect_uri), int(params.redirect_uri_provided_explicitly), params.resource,
                 time.time() + CODE_SECONDS))
        return back(code=code)

    async def _userinfo(self, code: str, verifier: str) -> dict[str, Any]:
        oidc = await self._oidc()
        async with self._http_factory() as http:
            r = await http.post(oidc["token_endpoint"], data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": self.callback_url,
                "client_id": self.s.oidc_client_id, "client_secret": self.s.oidc_client_secret,
                "code_verifier": verifier})
            r.raise_for_status()
            # userinfo over TLS from the issuer's own endpoint, with the token it just issued: no id_token
            # signature to verify on our side
            u = await http.get(oidc["userinfo_endpoint"], headers={"Authorization": f"Bearer {r.json()['access_token']}"})
            u.raise_for_status()
            return u.json()

    # ------------------------------------------------------------ codes
    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> AuthorizationCode | None:
        rows = self._q("SELECT client_id, subject, scopes, code_challenge, redirect_uri, explicit, resource, expires_at"
                       " FROM oauth_codes WHERE code_hash = ? AND used = 0", (_hash(authorization_code),))
        if not rows or rows[0][0] != client.client_id:
            return None
        cid, subject, scopes, challenge, redirect_uri, explicit, resource, expires = rows[0]
        return AuthorizationCode(code=authorization_code, client_id=cid, subject=subject, scopes=json.loads(scopes),
                                 code_challenge=challenge, redirect_uri=redirect_uri,
                                 redirect_uri_provided_explicitly=bool(explicit), resource=resource, expires_at=expires)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        with self._lock:
            cur = self._db.execute("UPDATE oauth_codes SET used = 1 WHERE code_hash = ? AND used = 0",
                                   (_hash(authorization_code.code),))
        if cur.rowcount != 1:
            raise TokenError(error="invalid_grant", error_description="Authorization code already used.")
        return self._issue(secrets.token_hex(16), client.client_id or "", authorization_code.subject or "",
                           authorization_code.scopes, authorization_code.resource)

    # ------------------------------------------------------------ tokens
    def _issue(self, grant_id: str, client_id: str, subject: str, scopes: list[str], resource: str | None) -> OAuthToken:
        if not subject:
            raise TokenError(error="invalid_grant", error_description="No person behind this grant.")
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        now = int(time.time())
        rows = [(access, "access", now + self.s.access_token_seconds),
                (refresh, "refresh", now + self.s.refresh_token_days * 86400)]
        with self._lock:
            for token, kind, expires in rows:
                self._db.execute(
                    "INSERT INTO oauth_tokens (token_hash, kind, grant_id, client_id, subject, scopes, resource, expires_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (_hash(token), kind, grant_id, client_id, subject, json.dumps(scopes), resource, expires))
        return OAuthToken(access_token=access, expires_in=self.s.access_token_seconds, refresh_token=refresh,
                          scope=" ".join(scopes) or None)

    def _token_row(self, token: str, kind: str) -> tuple | None:
        rows = self._q("SELECT grant_id, client_id, subject, scopes, resource, expires_at FROM oauth_tokens"
                       " WHERE token_hash = ? AND kind = ? AND revoked = 0 AND expires_at > ?",
                       (_hash(token), kind, int(time.time())))
        return rows[0] if rows else None

    async def load_access_token(self, token: str) -> AccessToken | None:
        row = self._token_row(token, "access")
        if row is None:
            return None
        _, client_id, subject, scopes, resource, expires = row
        return AccessToken(token=token, client_id=client_id, subject=subject, scopes=json.loads(scopes),
                           resource=resource, expires_at=expires)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        row = self._token_row(refresh_token, "refresh")
        if row is None or row[1] != client.client_id:
            return None
        _, client_id, subject, scopes, _, expires = row
        return RefreshToken(token=refresh_token, client_id=client_id, subject=subject, scopes=json.loads(scopes),
                            expires_at=expires)

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken,
                                     scopes: list[str]) -> OAuthToken:
        row = self._token_row(refresh_token.token, "refresh")
        if row is None:
            raise TokenError(error="invalid_grant", error_description="Refresh token expired or revoked.")
        grant_id, _, subject, _, resource, _ = row
        self._q("UPDATE oauth_tokens SET revoked = 1 WHERE grant_id = ?", (grant_id,))
        return self._issue(grant_id, client.client_id or "", subject, scopes or refresh_token.scopes, resource)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        rows = self._q("SELECT grant_id FROM oauth_tokens WHERE token_hash = ?", (_hash(token.token),))
        if rows:
            self._q("UPDATE oauth_tokens SET revoked = 1 WHERE grant_id = ?", (rows[0][0],))


def _page(status: int, message: str) -> HTMLResponse:
    return HTMLResponse(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>InHouseOS</title></head>'
                        f"<body><p>{message}</p></body></html>", status_code=status)
