"""The git layer on its own: commits, conflicts and history in a bare repo."""
from __future__ import annotations

import io
import subprocess
import tarfile

import pytest

from iho.gitstore import GitStore

WHO = {"author_name": "ana", "author_email": "ana@example.com"}


@pytest.fixture
def git(tmp_path):
    g = GitStore(tmp_path / "repos")
    g.create("people/ana@example.com")
    return g, "people/ana@example.com"


def test_empty_repo_then_first_commit(git):
    g, repo = git
    assert g.exists(repo)
    assert g.head(repo) is None
    assert g.files(repo, None) == {}
    r = g.commit(repo, items=[("wiki/log.md", b"one\n"), ("raw/.gitkeep", b"")], message="first", **WHO)
    assert r["committed"] is True
    assert {c["operation"] for c in r["changed"]} == {"create"}
    assert g.head(repo) == r["head"]
    assert g.files(repo, r["head"]) == {"wiki/log.md": b"one\n", "raw/.gitkeep": b""}


def test_unchanged_update_and_delete(git):
    g, repo = git
    g.commit(repo, items=[("a.md", b"a"), ("b.md", b"b")], message="first", **WHO)
    same = g.commit(repo, items=[("a.md", b"a")], message="noop", **WHO)
    assert same == {"committed": False, "head": g.head(repo), "unchanged": ["a.md"]}
    r = g.commit(repo, items=[("a.md", b"A"), ("b.md", None), ("missing.md", None)], message="second", **WHO)
    assert r["changed"] == [{"path": "a.md", "operation": "update"}, {"path": "b.md", "operation": "delete"}]
    assert r["unchanged"] == ["missing.md"]
    assert g.files(repo, r["head"]) == {"a.md": b"A"}


def test_stale_base_head_writes_nothing_and_lists_net_changes(git):
    g, repo = git
    first = g.commit(repo, items=[("a.md", b"a")], message="first", **WHO)["head"]
    g.commit(repo, items=[("tmp.md", b"x"), ("b.md", b"b")], message="other machine", **WHO)
    head = g.commit(repo, items=[("tmp.md", None)], message="other machine again", **WHO)["head"]
    r = g.commit(repo, items=[("a.md", b"mine")], message="late", base_head=first[:7], **WHO)
    assert r["committed"] is False and r["conflict"] is True
    assert r["head"] == head
    assert r["remote_changes"] == [{"path": "b.md", "status": "added"}]  # tmp.md came and went
    assert g.files(repo, head)["a.md"] == b"a"


def test_unknown_base_head_is_a_conflict(git):
    g, repo = git
    g.commit(repo, items=[("a.md", b"a")], message="first", **WHO)
    r = g.commit(repo, items=[("a.md", b"b")], message="x", base_head="deadbeef", **WHO)
    assert r["conflict"] is True and r["remote_changes"] == []


def test_race_lost_on_update_ref_is_a_conflict(git):
    """Two writers read the same head; git's compare-and-swap lets only the first one in."""
    g, repo = git
    head = g.commit(repo, items=[("a.md", b"a")], message="first", **WHO)["head"]
    g.commit(repo, items=[("a.md", b"winner")], message="winner", **WHO)
    r = g._commit_on(repo, head, [("a.md", b"loser")], "loser", "ana", "ana@example.com")
    assert r["committed"] is False and r["conflict"] is True
    assert g.files(repo, g.head(repo))["a.md"] == b"winner"


def test_history_is_plain_git_with_the_person_as_author(git):
    g, repo = git
    g.commit(repo, items=[("a.md", b"a")], message="first", **WHO)
    g.commit(repo, items=[("a.md", b"b")], message="second", **WHO)
    log = subprocess.run(["git", f"--git-dir={g.path(repo)}", "log", "--format=%an <%ae> | %cn | %s"],
                         capture_output=True, text=True, check=True).stdout.splitlines()
    assert log == ["ana <ana@example.com> | iho-server | second", "ana <ana@example.com> | iho-server | first"]
    clone = g.root.parent / "clone"
    subprocess.run(["git", "clone", "-q", str(g.path(repo)), str(clone)], check=True)
    assert (clone / "a.md").read_text() == "b"


def test_archive_has_one_root_folder(git):
    g, repo = git
    head = g.commit(repo, items=[("wiki/x.md", b"x")], message="first", **WHO)["head"]
    with tarfile.open(fileobj=io.BytesIO(g.archive_targz(repo, head, "second-brain")), mode="r:gz") as t:
        names = [m.name for m in t if m.isfile()]
    assert names == ["second-brain/wiki/x.md"]


def test_paths_with_spaces_and_accents(git):
    g, repo = git
    r = g.commit(repo, items=[("wiki/reunião de time.md", "olá".encode())], message="first", **WHO)
    assert g.files(repo, r["head"]) == {"wiki/reunião de time.md": "olá".encode()}
