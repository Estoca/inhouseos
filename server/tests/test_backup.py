"""Snapshots: export an instance, lose it, import it somewhere else, and get the same data back."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import tarfile
from pathlib import Path

import pytest

from iho import cli
from iho.actor import Actor
from iho.backup import BackupError, BackupScheduler, export_snapshot, import_snapshot
from iho.brains import Brains
from iho.config import Settings
from iho.gitstore import GitStore
from iho.links import LinkStore
from iho.tracker.service import Tracker

ANA = Actor("ana@example.com", "t")


def settings_at(root: Path, **extra) -> Settings:
    s = Settings(_env_file=None, data_dir=root, auth_mode="dev", dev_token="x" * 24, dev_user="a@b.com", **extra)
    s.repos_dir.mkdir(parents=True, exist_ok=True)
    return s


def populate(s: Settings) -> None:
    git = GitStore(s.repos_dir)
    brains = Brains(s, git, LinkStore(s.db_path))
    brains.bootstrap(ANA)
    brains.push(ANA, "pages", [{"path": "wiki/topics/x.md", "content": "reunião de time\n"}], None)
    brains.append(ANA, "wiki/log.md", "## [2026-10-29] manual | teste", "log")
    git.create("people/bob@example.com")  # an empty repo travels too
    Tracker(s.db_path).run("tracker_create_action", {"waiting_on_email": "bia@example.com", "title": "Algo"}, ANA)


def log_of(git: GitStore, name: str) -> list[str]:
    return subprocess.run(["git", f"--git-dir={git.path(name)}", "log", "--format=%H %an %s"],
                          capture_output=True, text=True, check=True).stdout.splitlines()


def test_export_then_import_elsewhere_gives_the_same_instance(tmp_path):
    a = settings_at(tmp_path / "a")
    populate(a)
    snap = tmp_path / "out" / "move.tar.gz"
    manifest = export_snapshot(a, snap)
    assert snap.stat().st_mode & 0o777 == 0o600
    with tarfile.open(snap) as t:
        assert sorted(m.name for m in t if m.isfile()) == [
            "iho.db", "manifest.json", "repos/people/ana@example.com.bundle"]
    assert {r["name"] for r in manifest["repos"]} == {"people/ana@example.com", "people/bob@example.com"}

    b = settings_at(tmp_path / "b")
    import_snapshot(b, snap)
    ga, gb = GitStore(a.repos_dir), GitStore(b.repos_dir)
    assert gb.names() == ga.names()
    name = "people/ana@example.com"
    assert gb.head(name) == ga.head(name)
    assert gb.files(name, gb.head(name)) == ga.files(name, ga.head(name))
    assert log_of(gb, name) == log_of(ga, name)
    assert gb.exists("people/bob@example.com") and gb.head("people/bob@example.com") is None
    remotes = subprocess.run(["git", f"--git-dir={gb.path(name)}", "remote"], capture_output=True, text=True).stdout
    assert remotes.strip() == ""

    # the restored instance keeps working: tracker data is there and brains accept writes
    listed = Tracker(b.db_path).run("tracker_list_actions", {"requester": "ana@example.com"}, ANA)
    assert [x["title"] for x in listed["items"]] == ["Algo"]
    brains_b = Brains(b, gb, LinkStore(b.db_path))
    assert brains_b.append(ANA, "wiki/log.md", "depois do restore", "log")["committed"] is True


def test_import_refuses_existing_data_and_force_moves_it_aside(tmp_path):
    a = settings_at(tmp_path / "a")
    populate(a)
    snap = tmp_path / "snap.tar.gz"
    export_snapshot(a, snap)
    b = settings_at(tmp_path / "b")
    populate(b)
    with pytest.raises(BackupError):
        import_snapshot(b, snap)
    import_snapshot(b, snap, force=True)
    aside = [p for p in b.data_dir.iterdir() if p.name.startswith("replaced-")]
    assert len(aside) == 1 and (aside[0] / "iho.db").exists() and (aside[0] / "repos").is_dir()


def test_unknown_format_is_refused(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"format": "something-else"}))
    with tarfile.open(bad, "w:gz") as t:
        t.add(manifest, "manifest.json")
    with pytest.raises(BackupError):
        import_snapshot(settings_at(tmp_path / "b"), bad)


def test_scheduler_writes_snapshots_and_keeps_the_newest(tmp_path):
    s = settings_at(tmp_path / "data", backup_dir=tmp_path / "backups", backup_keep=2)
    populate(s)
    sched = BackupScheduler(s)
    made = [sched.run_once() for _ in range(3)]
    kept = sorted(p.name for p in (tmp_path / "backups").glob("*.tar.gz"))
    assert kept == sorted(p.name for p in made[1:])
    assert sched.last["ok"] is True and sched.last["file"] == made[-1].name
    assert not list((tmp_path / "backups").glob("*.partial"))


def test_snapshot_is_consistent_while_the_database_is_open(tmp_path):
    a = settings_at(tmp_path / "a")
    populate(a)
    held = sqlite3.connect(a.db_path)  # another writer keeps the file open, as the server does
    held.execute("BEGIN IMMEDIATE")
    try:
        export_snapshot(a, tmp_path / "snap.tar.gz")
    finally:
        held.rollback()
        held.close()
    b = settings_at(tmp_path / "b")
    import_snapshot(b, tmp_path / "snap.tar.gz")
    with sqlite3.connect(b.db_path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_cli_export_and_import(tmp_path, monkeypatch, capsys):
    a = settings_at(tmp_path / "a")
    populate(a)
    monkeypatch.setattr(cli, "get_settings", lambda: a)
    assert cli.main(["export", str(tmp_path / "x.tar.gz")]) == 0
    b = settings_at(tmp_path / "b")
    monkeypatch.setattr(cli, "get_settings", lambda: b)
    assert cli.main(["import", str(tmp_path / "x.tar.gz")]) == 0
    assert cli.main(["import", str(tmp_path / "x.tar.gz")]) == 1  # data now there, no --force
    assert cli.main(["backup-now"]) == 2  # IHO_BACKUP_DIR not set
    assert GitStore(b.repos_dir).names() == GitStore(a.repos_dir).names()
