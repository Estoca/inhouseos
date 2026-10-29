"""Single-use links for upload and download, so files go from disk to server with `curl`
without passing through the conversation. Only the hash of the token is stored."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    token_hash TEXT PRIMARY KEY,
    email      TEXT NOT NULL,
    kind       TEXT NOT NULL,
    repo       TEXT NOT NULL,
    message    TEXT,
    base_head  TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at    TEXT
)
"""


@dataclass(frozen=True)
class Link:
    email: str
    kind: str
    repo: str
    message: str | None
    base_head: str | None


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


class LinkStore:
    def __init__(self, db_path: Path):
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute(SCHEMA)

    def create(self, *, email: str, kind: str, repo: str, message: str | None, base_head: str | None,
               ttl_seconds: int) -> tuple[str, str]:
        """(token, expires_at ISO). The caller builds the URL."""
        token = secrets.token_urlsafe(32)
        now = _now()
        expires = now + timedelta(seconds=ttl_seconds)
        with self._lock:
            self._db.execute(
                "INSERT INTO links (token_hash, email, kind, repo, message, base_head, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (_hash(token), email, kind, repo, message, base_head, now.isoformat(), expires.isoformat()))
        return token, expires.isoformat()

    def consume(self, token: str, kind: str) -> Link | None:
        """The link, if it exists, is of this kind, has not expired and was not used; then it is used."""
        h = _hash(token)
        now = _now().isoformat()
        with self._lock:
            cur = self._db.execute(
                "UPDATE links SET used_at = ? WHERE token_hash = ? AND kind = ? AND used_at IS NULL"
                " AND expires_at > ?", (now, h, kind, now))
            if cur.rowcount != 1:
                return None
            row = self._db.execute("SELECT email, kind, repo, message, base_head FROM links WHERE token_hash = ?",
                                   (h,)).fetchone()
        return Link(*row)
