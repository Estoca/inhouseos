"""Skills served by the server: the catalog, company values filled in, the MCP tools and instructions."""
from __future__ import annotations

import asyncio
import re

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from conftest import TOKEN, call
from iho.config import Settings
from iho.errors import IhoError
from iho.skillbook import SkillBook


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path, auth_mode="dev", dev_token=TOKEN,
                    dev_user="ana@example.com", **overrides)


@pytest.fixture
def book(tmp_path):
    return SkillBook(_settings(tmp_path, company_name="Acme", company_domain="Acme.com",
                               company_connectors="Slack, Gmail ,Google Calendar"))


def test_first_skills_ship_with_their_docs(book):
    assert {"bomdia", "fechar-pacote", "sweep"} <= set(book.skills)
    for name in book.skills:
        skill = book.get(name)
        assert skill["text"].startswith("# /")
        assert {d["name"] for d in skill["docs"]} >= {"tracker.md", "armadilhas.md"}
        # every support doc a skill names in its text comes along with it
        named = set(re.findall(r"`([a-z-]+\.md)`", skill["text"]))
        assert named <= {d["name"] for d in skill["docs"]}, name


def test_company_values_come_from_settings_not_the_text(book):
    skill = book.get("bomdia")
    everything = skill["text"] + "".join(d["text"] for d in skill["docs"])
    assert "{{" not in everything
    assert "Acme" in everything
    assert "Slack, Gmail, Google Calendar" in everything
    assert skill["company"]["domain"] == "acme.com"


def test_domain_defaults_to_the_allowed_domain(tmp_path):
    values = SkillBook(_settings(tmp_path, allowed_domains="example.org")).values
    assert values["domain"] == "example.org"
    assert values["company"] == "a empresa"


def test_skill_data_is_free_of_the_origin_company(book):
    banned = re.compile(r"estoca|metabase|_radar|hubspot|crm_|taemprod|\bcava\b|plugin_root", re.I)
    texts = [s.body for s in book.skills.values()] + list(book.docs.values())
    hits = [m.group(0) for t in texts for m in banned.finditer(t)]
    assert hits == []


@pytest.mark.parametrize("name", ["bomdia", "/bomdia", "abrir-pacote", "/abrir-pacote", "Abrir pacote", "bom dia"])
def test_aliases_and_slash_commands_find_bomdia(book, name):
    assert book.get(name)["name"] == "bomdia"


def test_unknown_skill_lists_the_available_ones(book):
    with pytest.raises(IhoError) as err:
        book.get("setup-os")
    assert err.value.code == "skill_not_found"
    assert "bomdia" in err.value.message


def test_instructions_name_every_trigger(book):
    text = book.instructions()
    assert "os_get_skill" in text
    for trigger in ('"bom dia"', '"abrir pacote"', '"fechar pacote"', "/sweep"):
        assert trigger in text


def test_mcp_serves_skills_and_tells_the_agent_when(server):
    base, _ = server

    async def run():
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}) as http:
            async with streamable_http_client(f"{base}/mcp", http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    tools = {t.name: t for t in (await session.list_tools()).tools}
                    listed = await call(session, "os_list_skills")
                    got = await call(session, "os_get_skill", {"name": "abrir pacote"})
                    missing = await call(session, "os_get_skill", {"name": "nope"})
                    return init.instructions, tools, listed, got, missing

    instructions, tools, listed, got, missing = asyncio.run(run())
    assert "os_get_skill" in instructions and '"bom dia"' in instructions
    assert tools["os_get_skill"].annotations.readOnlyHint is True
    assert {"bomdia", "fechar-pacote", "sweep"} <= {s["name"] for s in listed["skills"]}
    assert all(s["when"] for s in listed["skills"])
    assert got["name"] == "bomdia" and "tracker_digest" in got["text"]
    assert any(d["name"] == "tracker.md" for d in got["docs"])
    assert missing["error"].startswith("skill_not_found")
