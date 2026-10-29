"""Who is calling. Every tool reads the caller from here, whatever the auth mode.

The auth mode only decides which TokenVerifier turns a bearer token into an AccessToken.
The subject of that token is the person's email; tools never look at the token itself.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.fastmcp.exceptions import ToolError

from iho.config import Settings


@dataclass(frozen=True)
class Actor:
    email: str
    client_id: str

    @property
    def domain(self) -> str:
        return self.email.rsplit("@", 1)[1]


def current_actor() -> Actor:
    token = get_access_token()
    if token is None or not token.subject:
        raise ToolError("Could not identify the authenticated person.")
    return Actor(email=token.subject.strip().lower(), client_id=token.client_id)


class DevTokenVerifier(TokenVerifier):
    """Accepts exactly one token, IHO_DEV_TOKEN, as IHO_DEV_USER."""

    def __init__(self, settings: Settings):
        self._token = settings.dev_token.encode()
        self._user = settings.dev_user.strip().lower()

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token.encode(), self._token):
            return None
        return AccessToken(token=token, client_id="dev", scopes=[], subject=self._user)


def build_verifier(settings: Settings) -> TokenVerifier:
    # Settings already refuses modes that are not implemented.
    return DevTokenVerifier(settings)
