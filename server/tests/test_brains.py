"""The brain tools end to end: MCP over HTTP for the tools, plain HTTP for the single-use links."""
from __future__ import annotations

import asyncio
import io
import tarfile
from pathlib import Path

import httpx
import pytest

from conftest import call, mcp_session
from iho.actor import Actor
from iho.brains import Brains, template_files
from iho.config import Settings
from iho.errors import IhoError
from iho.gitstore import GitStore
from iho.links import LinkStore

REPO = "people/ana@example.com"


def run(base, fn):
    return asyncio.run(mcp_session(base, fn))


def test_before_bootstrap_tools_say_what_to_do(server):
    base, _ = server

    async def go(s):
        return await call(s, "brain_status"), await call(s, "brain_list")

    status, listed = run(base, go)
    assert status == {"repo": None, "next": "brain_bootstrap"}
    assert listed["error"].startswith("brain_missing")


def test_bootstrap_is_idempotent_and_starts_from_the_template(server):
    base, settings = server

    async def go(s):
        first = await call(s, "brain_bootstrap")
        again = await call(s, "brain_bootstrap")
        return first, again, await call(s, "brain_list")

    first, again, listed = run(base, go)
    assert first["created"] is True and first["repo"] == REPO
    assert again["created"] is False and again["head"] == first["head"]
    assert sorted(e["path"] for e in listed["entries"]) == sorted(template_files())
    assert (settings.repos_dir / f"{REPO}.git").is_dir()


def test_template_is_the_published_schema():
    schema = Path(__file__).resolve().parents[2] / "templates" / "second-brain-schema.md"
    assert template_files()["CLAUDE.md"] == schema.read_bytes()


def test_read_search_append_and_edit(server):
    base, _ = server

    async def go(s):
        await call(s, "brain_bootstrap")
        await call(s, "brain_push", {"message": "pages", "files": [
            {"path": "wiki/daily/2026-10-28.md", "content": "Decisão: piloto CrossDo\n"},
            {"path": "wiki/daily/2026-10-29.md", "content": "decisao adiada\nlinha 2\n"},
        ]})
        appended = await call(s, "brain_append", {"path": "wiki/log.md", "text": "## [2026-10-29] manual | teste",
                                                  "message": "log"})
        tail = await call(s, "brain_read", {"path": "wiki/log.md", "offset": -1})
        found = await call(s, "brain_search", {"query": "decisão", "prefix": "wiki/daily/"})
        edited = await call(s, "brain_edit", {"path": "wiki/daily/2026-10-29.md", "old": "adiada",
                                              "new": "tomada", "message": "edit"})
        missing = await call(s, "brain_edit", {"path": "wiki/daily/2026-10-29.md", "old": "adiada",
                                               "new": "x", "message": "edit"})
        stale = await call(s, "brain_edit", {"path": "wiki/daily/2026-10-29.md", "old": "tomada", "new": "y",
                                             "message": "edit", "base_head": appended["head"]})
        page = await call(s, "brain_read", {"path": "wiki/daily/2026-10-29.md"})
        bad = await call(s, "brain_read", {"path": "../etc/passwd"})
        return appended, tail, found, edited, missing, stale, page, bad

    appended, tail, found, edited, missing, stale, page, bad = run(base, go)
    assert appended["committed"] is True
    assert tail["content"] == "## [2026-10-29] manual | teste\n"
    assert [m["path"] for m in found["matches"]] == ["wiki/daily/2026-10-29.md", "wiki/daily/2026-10-28.md"]
    assert edited["committed"] is True
    assert missing["error"].startswith("old_not_found")
    assert stale["conflict"] is True and stale["committed"] is False
    assert page["content"] == "decisao tomada\nlinha 2\n"
    assert bad["error"].startswith("invalid_path")


def test_pull_pages_and_hints(server):
    base, settings = server
    settings.pull_hint_bytes = 10

    async def go(s):
        await call(s, "brain_bootstrap")
        return await call(s, "brain_pull", {"prefix": "wiki/"})

    pulled = run(base, go)
    assert {f["path"] for f in pulled["files"]} == {"wiki/index.md", "wiki/log.md"}
    assert pulled["next_cursor"] is None and "hint" in pulled


def test_upload_and_download_links(server, tmp_path):
    base, _ = server

    async def go(s):
        boot = await call(s, "brain_bootstrap")
        up = await call(s, "brain_upload_link", {"message": "backup: test", "base_head": boot["head"]})
        return boot, up

    boot, up = run(base, go)
    files = [("file", ("wiki/topics/x.md", b"novo\n")), ("delete", (None, "raw/.gitkeep"))]
    r = httpx.post(up["url"], files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["committed"] is True
    assert {c["path"]: c["operation"] for c in body["changed"]} == {"wiki/topics/x.md": "create",
                                                                     "raw/.gitkeep": "delete"}
    again = httpx.post(up["url"], files=files)
    assert again.status_code == 404 and again.json()["error"]["code"] == "link_invalid"

    async def stale_upload(s):
        return await call(s, "brain_upload_link", {"message": "late", "base_head": boot["head"]})

    late = httpx.post(run(base, stale_upload)["url"], files=[("file", ("wiki/topics/y.md", b"y"))]).json()
    assert late["conflict"] is True and late["remote_changes"]

    async def down(s):
        return await call(s, "brain_download_link")

    link = run(base, down)
    tgz = httpx.get(link["url"])
    assert tgz.status_code == 200
    with tarfile.open(fileobj=io.BytesIO(tgz.content), mode="r:gz") as t:
        names = {m.name.split("/", 1)[1] for m in t if m.isfile()}
    assert "wiki/topics/x.md" in names and "raw/.gitkeep" not in names
    assert httpx.get(link["url"]).status_code == 404


def test_upload_refuses_bad_paths(server):
    base, _ = server

    async def go(s):
        await call(s, "brain_bootstrap")
        return await call(s, "brain_upload_link", {"message": "backup"})

    up = run(base, go)
    r = httpx.post(up["url"], files=[("file", (".env", b"SECRET=1"))])
    assert r.status_code == 400 and r.json()["error"]["code"] == "forbidden_path"


def test_each_person_sees_only_their_own_brain(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, auth_mode="dev", dev_token="x" * 24, dev_user="a@b.com")
    settings.repos_dir.mkdir(parents=True)
    brains = Brains(settings, GitStore(settings.repos_dir), LinkStore(tmp_path / "iho.db"))
    ana, bia = Actor("ana@example.com", "t"), Actor("bia@example.com", "t")
    brains.bootstrap(ana)
    brains.push(ana, "secret", [{"path": "wiki/ana.md", "content": "da Ana"}], None)
    with pytest.raises(IhoError) as exc:
        brains.list(bia, None, None)
    assert exc.value.code == "brain_missing"
    brains.bootstrap(bia)
    assert brains.search(bia, "da Ana", prefix=None, regex=False, case_sensitive=False, context=0,
                         max_results=None, files_only=True)["files_matched"] == 0
    with pytest.raises(IhoError):
        brains.status(Actor("not an email", "t"))
