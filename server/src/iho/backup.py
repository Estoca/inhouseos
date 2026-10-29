"""Export, import and scheduled snapshots of an iho-server instance.

A snapshot is one .tar.gz with everything the instance keeps:

    manifest.json           format, version, when, which repos
    iho.db                  SQLite, copied with the online backup API (consistent while the server runs)
    repos/<name>.bundle     one git bundle per repo with every ref (consistent per repo)

It is how an instance moves (hosted ↔ own machine) and how it comes back after losing the volume.
Getting snapshots off the machine is the operator's tool (rclone, restic, the homelab backup):
IHO_BACKUP_DIR is the boundary, so the server holds no cloud credentials.
"""
from __future__ import annotations

import io
import json
import logging
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from iho import __version__
from iho.config import Settings
from iho.gitstore import GitStore

logger = logging.getLogger("iho.backup")

FORMAT = "iho-snapshot/1"
PREFIX = "iho-backup-"


class BackupError(Exception):
    pass


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(time.time())
    info.mode = 0o600
    tar.addfile(info, io.BytesIO(data))


def export_snapshot(settings: Settings, dest: Path) -> dict[str, Any]:
    """Write a snapshot of the instance to `dest` (.tar.gz). Returns the manifest."""
    git = GitStore(settings.repos_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        db_copy = work / "iho.db"
        if settings.db_path.exists():
            src = sqlite3.connect(settings.db_path)
            dst = sqlite3.connect(db_copy)
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
        repos: list[dict[str, Any]] = []
        for name in git.names():
            head = git.head(name)
            entry: dict[str, Any] = {"name": name, "head": head}
            if head is not None:
                bundle = work / "repos" / f"{name}.bundle"
                bundle.parent.mkdir(parents=True, exist_ok=True)
                git._git(name, "bundle", "create", str(bundle), "--all")
                entry["bundle"] = f"repos/{name}.bundle"
            repos.append(entry)
        manifest = {"format": FORMAT, "version": __version__, "created_at": datetime.now(UTC).isoformat(),
                    "db": "iho.db" if db_copy.exists() else None, "repos": repos}
        partial = dest.with_name(dest.name + ".partial")
        with tarfile.open(partial, "w:gz") as tar:
            _add_bytes(tar, "manifest.json", json.dumps(manifest, indent=2).encode())
            if db_copy.exists():
                tar.add(db_copy, "iho.db")
            for r in repos:
                if "bundle" in r:
                    tar.add(work / r["bundle"], r["bundle"])
        partial.chmod(0o600)
        partial.replace(dest)  # a reader never sees a half-written snapshot
    logger.info("export %s: %d repos", dest, len(repos))
    return manifest


def import_snapshot(settings: Settings, src: Path, *, force: bool = False) -> dict[str, Any]:
    """Restore a snapshot into the data dir. Refuses a data dir that already has data unless `force`;
    with `force`, the current iho.db and repos/ are moved aside, not deleted."""
    git = GitStore(settings.repos_dir)
    has_data = settings.db_path.exists() or bool(git.names())
    if has_data and not force:
        raise BackupError(f"{settings.data_dir} already has data. Use --force to move it aside and restore.")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        with tarfile.open(src, "r:gz") as tar:
            tar.extractall(work, filter="data")
        manifest = json.loads((work / "manifest.json").read_text())
        if manifest.get("format") != FORMAT:
            raise BackupError(f"Unknown snapshot format: {manifest.get('format')!r}")
        if has_data:
            aside = settings.data_dir / f"replaced-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
            aside.mkdir(parents=True)
            for p in (settings.db_path, settings.db_path.with_name("iho.db-wal"),
                      settings.db_path.with_name("iho.db-shm"), settings.repos_dir):
                if p.exists():
                    shutil.move(str(p), aside / p.name)
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.repos_dir.mkdir(parents=True, exist_ok=True)
        if manifest.get("db"):
            shutil.copyfile(work / manifest["db"], settings.db_path)
        for r in manifest["repos"]:
            target = git.path(r["name"])
            target.parent.mkdir(parents=True, exist_ok=True)
            if "bundle" not in r:
                git.create(r["name"])
                continue
            out = subprocess.run(["git", "clone", "--quiet", "--mirror", str(work / r["bundle"]), str(target)],
                                 capture_output=True, check=False)
            if out.returncode != 0:
                raise BackupError(f"Could not restore {r['name']}: {out.stderr.decode(errors='replace').strip()}")
            # a mirror remembers where it came from; a restored repo has no remote
            git._git(r["name"], "remote", "remove", "origin", ok=(0, 2))
            if git.head(r["name"]) != r["head"]:
                raise BackupError(f"{r['name']} restored at {git.head(r['name'])}, expected {r['head']}")
    logger.info("import %s: %d repos", src, len(manifest["repos"]))
    return manifest


def prune(backup_dir: Path, keep: int) -> list[Path]:
    """Delete the oldest snapshots beyond `keep`. Returns what was deleted."""
    snaps = sorted(backup_dir.glob(f"{PREFIX}*.tar.gz"))
    old = snaps[:-keep] if keep > 0 else []
    for p in old:
        p.unlink()
    return old


class BackupScheduler:
    """A snapshot into IHO_BACKUP_DIR every IHO_BACKUP_EVERY_HOURS, keeping IHO_BACKUP_KEEP."""

    def __init__(self, settings: Settings):
        self.s = settings
        self.last: dict[str, Any] | None = None
        self._stop = threading.Event()

    @property
    def enabled(self) -> bool:
        return self.s.backup_dir is not None

    def run_once(self) -> Path:
        assert self.s.backup_dir is not None
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        dest = self.s.backup_dir / f"{PREFIX}{stamp}.tar.gz"
        started = time.monotonic()
        try:
            manifest = export_snapshot(self.s, dest)
            prune(self.s.backup_dir, self.s.backup_keep)
            self.last = {"ok": True, "at": manifest["created_at"], "file": dest.name,
                         "bytes": dest.stat().st_size, "seconds": round(time.monotonic() - started, 2)}
        except Exception as exc:  # a failed snapshot must not take the server down; /health shows it
            logger.exception("scheduled backup failed")
            self.last = {"ok": False, "at": datetime.now(UTC).isoformat(), "error": str(exc)}
            raise
        return dest

    def start(self) -> None:
        if not self.enabled:
            return

        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.run_once()
                except Exception:
                    pass
                self._stop.wait(self.s.backup_every_hours * 3600)

        threading.Thread(target=loop, name="iho-backup", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
