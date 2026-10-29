"""The tracker on the server's /mcp: same tool names as estoca-project-tracker, SQLite underneath."""
from __future__ import annotations

import asyncio
import sqlite3

from conftest import call, mcp_session
from iho.tracker.tools import CATALOG

EXPECTED = {
    "tracker_digest", "tracker_list_actions", "tracker_create_action", "tracker_update_action",
    "tracker_bump_action", "tracker_close_action", "tracker_reopen_action", "tracker_list_decisions",
    "tracker_create_decision", "tracker_update_decision", "tracker_decide", "tracker_reopen_decision",
    "tracker_list_projects", "tracker_create_project", "tracker_update_project", "tracker_post_project_update",
    "tracker_list_project_updates", "tracker_project_report", "tracker_add_project_member",
    "tracker_remove_project_member", "tracker_record_event", "tracker_adoption", "tracker_team_stuck",
    "tracker_add_absence", "tracker_update_person", "tracker_create_suggestion", "tracker_suggestion_outcome",
    "tracker_metrics",
}


def run(base, fn):
    return asyncio.run(mcp_session(base, fn))


def test_catalog_is_served_without_snapshot_link(server):
    base, _ = server

    async def go(s):
        return {t.name: t for t in (await s.list_tools()).tools}

    tools = run(base, go)
    assert {n for n in tools if n.startswith("tracker_")} == EXPECTED
    assert "tracker_snapshot_link" not in tools
    assert tools["tracker_create_action"].inputSchema["required"] == ["waiting_on_email", "title"]
    assert "brain_search" in tools and "iho_whoami" in tools
    text = " ".join(t["description"] for t in CATALOG)
    assert "Estoca" not in text and "Feedz" not in text and "escritorio" not in text


def test_action_lifecycle(server):
    base, _ = server

    async def go(s):
        created = await call(s, "tracker_create_action", {
            "waiting_on_email": "bia@example.com", "title": "Revisar contrato do fornecedor", "sev": 2,
            "source": "slack:#compras"})
        dup = await call(s, "tracker_create_action", {
            "waiting_on_email": "bia@example.com", "title": "Revisar contrato do fornecedor", "sev": 2})
        listed = await call(s, "tracker_list_actions", {"requester": "ana@example.com"})
        bumped = await call(s, "tracker_bump_action", {"action_id": created["id"]})
        wrong = await call(s, "tracker_close_action", {"action_id": created["id"], "evidence": "x",
                                                       "expect_title_contains": "outra coisa"})
        closed = await call(s, "tracker_close_action", {"action_id": created["id"], "evidence": "respondeu na thread",
                                                        "expect_title_contains": "contrato"})
        digest = await call(s, "tracker_digest")
        return created, dup, listed, bumped, wrong, closed, digest

    created, dup, listed, bumped, wrong, closed, digest = run(base, go)
    assert created["id"] >= 1 and created["status"] == "open"
    assert created["requester"]["email"] == "ana@example.com"
    assert "error" in dup
    assert [a["id"] for a in listed["items"]] == [created["id"]]
    assert bumped["id"] == created["id"]
    assert "error" in wrong
    assert closed["status"] == "done"
    assert isinstance(digest, dict) and "error" not in digest


def test_decision_and_project(server):
    base, _ = server

    async def go(s):
        project = await call(s, "tracker_create_project", {"slug": "piloto-x", "name": "Piloto X"})
        decision = await call(s, "tracker_create_decision", {"question": "Seguimos com o piloto X?",
                                                             "decider_email": "ana@example.com",
                                                             "project": "piloto-x"})
        decided = await call(s, "tracker_decide", {"decision_id": decision["id"], "outcome": "Sim, por 30 dias",
                                                   "expect_question_contains": "piloto X"})
        projects = await call(s, "tracker_list_projects")
        return project, decision, decided, projects

    project, decision, decided, projects = run(base, go)
    assert project["slug"] == "piloto-x"
    assert decided["status"] == "decided"
    assert [p["slug"] for p in projects["items"]] == ["piloto-x"]


def test_tracker_lives_in_the_server_database(server):
    base, settings = server

    async def go(s):
        return await call(s, "tracker_create_action", {"waiting_on_email": "bia@example.com", "title": "Algo"})

    run(base, go)
    with sqlite3.connect(settings.db_path) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"links", "actions", "people"} <= tables
        assert db.execute("SELECT count(*) FROM actions").fetchone()[0] == 1
