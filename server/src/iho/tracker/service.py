"""The tracker inside iho-server: same database file as the server, tools on the server's /mcp.

The tables are created on start (create_all). Schema changes after the first release will need
migrations for SQLite; the Postgres migrations of estoca-project-tracker are not carried over.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import create_engine, event

from iho.actor import Actor
from iho.errors import IhoError
from iho.tracker import db as tracker_db
from iho.tracker.auth import Identity, get_or_create_person
from iho.tracker.models import Base
from iho.tracker.tools import CATALOG, ProviderError, _dispatch, _dump

logger = logging.getLogger("iho.audit")

NAMES = {t["name"] for t in CATALOG}


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


class Tracker:
    def __init__(self, db_path: Path):
        self.engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        event.listen(self.engine, "connect", _sqlite_pragmas)
        Base.metadata.create_all(self.engine)
        tracker_db.SessionLocal.configure(bind=self.engine)

    def catalog(self) -> list[dict[str, Any]]:
        return CATALOG

    def run(self, name: str, args: dict[str, Any], actor: Actor) -> dict[str, Any]:
        if name not in NAMES:
            raise IhoError(404, "tool_not_found", f"Unknown tool: {name}")
        db = tracker_db.SessionLocal()
        try:
            # roles (c_level, leadership) and reports come from the org chart, which setup-os fills (LAB-57);
            # until then nobody sees beyond their own items, except IHO_TRACKER_ADMIN_EMAILS
            ident = Identity(email=actor.email, via="mcp")
            ident.person = get_or_create_person(db, actor.email)
            db.commit()
            result = _dispatch(name, args or {}, db, ident)
            data = _dump(result)
        except ProviderError as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
            raise IhoError(exc.status_code, detail.get("code", "error"), detail.get("message", "")) from exc
        except HTTPException as exc:  # router errors (403/404/409/422)
            code = {403: "tool_access_denied", 404: "not_found", 409: "conflict", 422: "invalid_arguments"}.get(
                exc.status_code, "error")
            raise IhoError(exc.status_code, code, str(exc.detail)) from exc
        finally:
            db.close()
        logger.info("tool=%s actor=%s", name, actor.email)
        return data if isinstance(data, dict) else {"items": data, "count": len(data)}
