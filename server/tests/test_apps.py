"""Screens in the chat (MCP Apps): the queue screen and approvals only a person can answer."""
from __future__ import annotations

import asyncio
import json

from pydantic import AnyUrl

from conftest import call, mcp_session
from iho.apps import APP_MIME, APP_URI, NONCE_KEY, ApprovalStore


def run(base, fn):
    return asyncio.run(mcp_session(base, fn))


def test_tools_link_to_the_screen_and_decide_is_app_only(server):
    base, _ = server

    async def go(s):
        tools = {t.name: t for t in (await s.list_tools()).tools}
        page = await s.read_resource(AnyUrl(APP_URI))
        return tools, page

    tools, page = run(base, go)
    assert tools["os_show_queue"].meta["ui"] == {"resourceUri": APP_URI, "visibility": ["model", "app"]}
    assert tools["os_request_approval"].meta["ui"]["resourceUri"] == APP_URI
    assert tools["os_decide_approval"].meta["ui"]["visibility"] == ["app"]
    assert "ui" not in (tools["os_approval_status"].meta or {})
    content = page.contents[0]
    assert content.mimeType == APP_MIME
    assert content.meta == {"ui": {"prefersBorder": True}}
    assert "ui/initialize" in content.text and "os_decide_approval" in content.text


def test_queue_screen_has_what_waits_on_you_and_what_you_wait_for(server):
    base, _ = server

    async def go(s):
        await call(s, "tracker_create_action", {"waiting_on_email": "bia@example.com", "title": "Mandar a proposta"})
        await call(s, "tracker_create_action", {"waiting_on_email": "ana@example.com", "title": "Revisar o contrato",
                                                "requester_email": "bia@example.com"})
        return await s.call_tool("os_show_queue", {})

    result = run(base, go)
    view = result.structuredContent
    assert view["view"] == "queue" and view["me"] == "ana@example.com"
    assert [a["title"] for a in view["on_you"]] == ["Revisar o contrato"]
    assert [(a["title"], a["waiting_on"]) for a in view["you_wait"]] == [("Mandar a proposta", "bia@example.com")]
    assert "1 on you, 1 you wait for" in result.content[0].text


def test_approval_needs_the_nonce_that_only_the_screen_gets(server):
    base, _ = server

    async def go(s):
        asked = await s.call_tool("os_request_approval", {"summary": "Abrir PR com o fix do frete",
                                                          "details": "repo wms, branch fix/frete"})
        approval_id = asked.structuredContent["approval"]["id"]
        nonce = asked.meta[NONCE_KEY]
        without = await call(s, "os_decide_approval", {"approval_id": approval_id, "decision": "approved",
                                                       "nonce": "guessed-by-the-model"})
        before = await call(s, "os_approval_status", {"approval_id": approval_id})
        decided = await s.call_tool("os_decide_approval", {"approval_id": approval_id, "decision": "approved",
                                                           "nonce": nonce})
        again = await call(s, "os_decide_approval", {"approval_id": approval_id, "decision": "rejected",
                                                     "nonce": nonce})
        after = await call(s, "os_approval_status", {"approval_id": approval_id})
        missing = await call(s, "os_approval_status", {"approval_id": approval_id + 1})
        return asked, nonce, without, before, decided, again, after, missing

    asked, nonce, without, before, decided, again, after, missing = run(base, go)
    # the model reads content and structuredContent: the nonce is in neither
    assert nonce not in asked.content[0].text
    assert nonce not in json.dumps(asked.structuredContent)
    assert asked.structuredContent["approval"]["status"] == "pending"
    assert without["error"].startswith("approval_nonce_invalid")
    assert before["status"] == "pending"
    assert decided.structuredContent["approval"]["status"] == "approved"
    assert again["error"].startswith("approval_already_decided")
    assert after["status"] == "approved" and after["decided_by"] == "ana@example.com"
    assert missing["error"].startswith("approval_not_found")


def test_someone_else_cannot_see_or_answer_your_approval(tmp_path):
    store = ApprovalStore(tmp_path / "iho.db")
    approval, nonce = store.request("ana@example.com", "Enviar o e-mail ao cliente", None)
    for attempt in (lambda: store.get("bia@example.com", approval.id),
                    lambda: store.decide("bia@example.com", approval.id, nonce, "approved", None)):
        try:
            attempt()
        except Exception as exc:  # noqa: BLE001
            assert getattr(exc, "code", "") == "approval_not_found"
        else:
            raise AssertionError("another person reached the approval")
    assert store.get("ana@example.com", approval.id).status == "pending"
