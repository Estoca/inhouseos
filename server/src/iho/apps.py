"""Screens inside the chat (MCP Apps, io.modelcontextprotocol/ui 2026-01-26).

A tool links to `ui://iho/app.html` through `_meta.ui.resourceUri`; the host renders that page in a
sandboxed frame and hands it the tool result. The page can call tools back through the host.

Approvals are the point of the proof: a write that needs a human goes through os_request_approval,
and only the screen can answer it. os_decide_approval is visible to the app only (`visibility: ["app"]`),
and it also needs a nonce that travels in the result `_meta` alone, never in the text the model reads,
so a host that ignores visibility still cannot let the model approve its own request.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from iho.errors import IhoError

APP_URI = "ui://iho/app.html"
APP_MIME = "text/html;profile=mcp-app"
NONCE_KEY = "iho/approval_nonce"

SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL,
    summary     TEXT NOT NULL,
    details     TEXT,
    nonce_hash  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL,
    decided_at  TEXT,
    decided_by  TEXT,
    note        TEXT
)
"""


def ui_meta(*, app_only: bool = False) -> dict[str, Any]:
    # the flat "ui/resourceUri" is the legacy key; the ext-apps SDK still writes both and hosts read it
    return {"ui": {"resourceUri": APP_URI, "visibility": ["app"] if app_only else ["model", "app"]},
            "ui/resourceUri": APP_URI}


def app_html() -> str:
    return resources.files("iho").joinpath("ui/app.html").read_text(encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _hash(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()


@dataclass(frozen=True)
class Approval:
    id: int
    email: str
    summary: str
    details: str | None
    status: str
    created_at: str
    decided_at: str | None
    decided_by: str | None
    note: str | None

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "summary": self.summary, "details": self.details, "status": self.status,
                "requested_by": self.email, "created_at": self.created_at, "decided_at": self.decided_at,
                "decided_by": self.decided_by, "note": self.note}


class ApprovalStore:
    """Pending approvals in the server database. Only the hash of each nonce is kept."""

    def __init__(self, db_path: Path):
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute(SCHEMA)

    def request(self, email: str, summary: str, details: str | None) -> tuple[Approval, str]:
        nonce = secrets.token_urlsafe(24)
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO approvals (email, summary, details, nonce_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (email, summary.strip(), (details or "").strip() or None, _hash(nonce), _now()))
            approval_id = cur.lastrowid
        return self.get(email, approval_id), nonce

    def get(self, email: str, approval_id: int) -> Approval:
        with self._lock:
            row = self._db.execute(
                "SELECT id, email, summary, details, status, created_at, decided_at, decided_by, note "
                "FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        # someone else's approval answers as missing: ids are not a way to probe other people
        if row is None or row[1] != email:
            raise IhoError(404, "approval_not_found", f"No approval #{approval_id} for you.")
        return Approval(*row)

    def decide(self, email: str, approval_id: int, nonce: str, decision: str, note: str | None) -> Approval:
        if decision not in ("approved", "rejected"):
            raise IhoError(400, "invalid_decision", "decision is approved or rejected.")
        with self._lock:
            row = self._db.execute("SELECT email, nonce_hash, status FROM approvals WHERE id = ?",
                                   (approval_id,)).fetchone()
            if row is None or row[0] != email:
                raise IhoError(404, "approval_not_found", f"No approval #{approval_id} for you.")
            if not hmac.compare_digest(row[1], _hash(nonce or "")):
                raise IhoError(403, "approval_nonce_invalid", "Only the approval screen can answer this request.")
            if row[2] != "pending":
                raise IhoError(409, "approval_already_decided", f"Approval #{approval_id} is already {row[2]}.")
            self._db.execute(
                "UPDATE approvals SET status = ?, decided_at = ?, decided_by = ?, note = ? WHERE id = ? AND status = 'pending'",
                (decision, _now(), email, (note or "").strip() or None, approval_id))
        return self.get(email, approval_id)


def queue_view(tracker_run, actor) -> dict[str, Any]:
    """The caller's queue for the screen: what waits on them and what they wait for."""
    mine = tracker_run("tracker_list_actions", {"waiting_on": actor.email}, actor)["items"]
    asked = tracker_run("tracker_list_actions", {"requester": actor.email}, actor)["items"]
    waiting = [a for a in asked if a["waiting_on"]["email"] != actor.email]

    def row(a: dict[str, Any]) -> dict[str, Any]:
        return {"id": a["id"], "title": a["title"], "sev": a["sev"], "type": a["type"],
                "requester": a["requester"]["email"], "waiting_on": a["waiting_on"]["email"],
                "age_days": a["age_days"], "overdue_by": a["overdue_by"], "due_at": a.get("due_at"),
                "waiting_external": a.get("waiting_external"), "source_ref": a.get("source_ref")}

    return {"view": "queue", "me": actor.email, "generated_at": _now(),
            "on_you": [row(a) for a in mine], "you_wait": [row(a) for a in waiting]}


def queue_text(view: dict[str, Any]) -> str:
    def line(a: dict[str, Any]) -> str:
        late = f", {a['overdue_by']}d late" if a["overdue_by"] > 0 else ""
        return f"- #{a['id']} {a['title']} (sev {a['sev']}{late})"

    parts = [f"Queue of {view['me']}: {len(view['on_you'])} on you, {len(view['you_wait'])} you wait for."]
    if view["on_you"]:
        parts += ["On you:", *map(line, view["on_you"])]
    if view["you_wait"]:
        parts += ["You wait for:", *(f"{line(a)} waiting on {a['waiting_on']}" for a in view["you_wait"])]
    return "\n".join(parts)
