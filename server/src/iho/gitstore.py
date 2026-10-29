"""Bare git repositories on the data volume, driven by the `git` binary.

Every brain stays a plain git repository: history, undo and audit come for free, and a person can
take theirs away with `git clone`. No Gitea, no git library: a handful of plumbing commands.

Writes never touch a working tree. A commit is built in a throwaway index file and published with
`git update-ref <branch> <new> <old>`, which git applies only if the branch still points at <old>.
Two writers racing on the same repo cannot overwrite each other: the second one gets a conflict.
A per-repo lock in this process keeps the common case from even getting there.
"""
from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tarfile
import tempfile
import threading
from pathlib import Path
from typing import Any

from iho.errors import IhoError

ZERO = "0" * 40
Files = dict[str, bytes]
Items = list[tuple[str, bytes | None]]  # (clean path, content | None to delete)


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


class GitStore:
    def __init__(self, root: Path, branch: str = "main"):
        self.root = root
        self.branch = branch
        self._ref = f"refs/heads/{branch}"
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ------------------------------------------------------------ plumbing
    def path(self, name: str) -> Path:
        return self.root / f"{name}.git"

    def _git(self, name: str, *args: str, input: bytes | None = None, env: dict[str, str] | None = None,
             ok: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[bytes]:
        r = subprocess.run(["git", f"--git-dir={self.path(name)}", *args], input=input, capture_output=True,
                           env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", **(env or {})}, check=False)
        if r.returncode not in ok:
            raise IhoError(500, "git_error", f"git {args[0]} failed: {r.stderr.decode(errors='replace').strip()}")
        return r

    def _lock(self, name: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(name, threading.Lock())

    # ------------------------------------------------------------ reads
    def exists(self, name: str) -> bool:
        return (self.path(name) / "HEAD").is_file()

    def names(self) -> list[str]:
        """Every repo under the root, by name (people/ana@example.com)."""
        if not self.root.is_dir():
            return []
        return sorted(str(p.relative_to(self.root))[: -len(".git")]
                      for p in self.root.rglob("*.git") if (p / "HEAD").is_file())

    def create(self, name: str) -> None:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["git", "init", "--quiet", "--bare", f"--initial-branch={self.branch}", str(p)],
                           capture_output=True, check=False)
        if r.returncode != 0:
            raise IhoError(500, "git_error", f"git init failed: {r.stderr.decode(errors='replace').strip()}")

    def head(self, name: str) -> str | None:
        r = self._git(name, "rev-parse", "-q", "--verify", self._ref, ok=(0, 1))
        return r.stdout.decode().strip() or None

    def resolve(self, name: str, rev: str) -> str | None:
        r = self._git(name, "rev-parse", "-q", "--verify", f"{rev}^{{commit}}", ok=(0, 1, 128))
        if r.returncode != 0:
            return None
        return r.stdout.decode().strip() or None

    def files(self, name: str, ref: str | None) -> Files:
        """Every file at `ref`, by path. An empty repo has none."""
        if ref is None:
            return {}
        tar = self._git(name, "archive", "--format=tar", ref).stdout
        files: Files = {}
        with tarfile.open(fileobj=io.BytesIO(tar), mode="r:") as t:
            for m in t:
                if m.isfile():
                    f = t.extractfile(m)
                    if f is not None:
                        files[m.name] = f.read()
        return files

    def archive_targz(self, name: str, ref: str, prefix: str) -> bytes:
        """.tar.gz with everything under `prefix/`, the shape `tar --strip-components=1` expects."""
        return self._git(name, "archive", "--format=tar.gz", f"--prefix={prefix}/", ref).stdout

    def changed(self, name: str, base: str, head: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Commits in base..head and the NET change per file (a file added then deleted did not change)."""
        log = self._git(name, "log", "--format=%H%x1f%s%x1f%aI%x1e", f"{base}..{head}").stdout.decode()
        commits = []
        for rec in filter(None, (r.strip() for r in log.split("\x1e"))):
            sha, subject, date = rec.split("\x1f")
            commits.append({"sha": sha, "message": subject, "date": date})
        out = self._git(name, "diff", "--name-status", "--no-renames", "-z", base, head).stdout.decode()
        parts = out.split("\0")
        status = {"A": "added", "D": "deleted"}
        files = [{"path": parts[i + 1], "status": status.get(parts[i], "modified")}
                 for i in range(0, len(parts) - 1, 2)]
        return commits, sorted(files, key=lambda f: f["path"])

    # ------------------------------------------------------------ writes
    def commit(self, name: str, *, items: Items, message: str, author_name: str, author_email: str,
               base_head: str | None = None) -> dict[str, Any]:
        """One commit with `items` on top of the branch head.

        With `base_head`, nothing is written if the branch moved past it; the answer lists what changed.
        """
        with self._lock(name):
            head = self.head(name)
            base = (base_head or "").strip()
            if base and (head is None or not head.startswith(base)):
                return self._conflict(name, base, head)
            return self._commit_on(name, head, items, message, author_name, author_email)

    def _conflict(self, name: str, base: str, head: str | None) -> dict[str, Any]:
        resolved = self.resolve(name, base)
        changes = self.changed(name, resolved, head)[1] if resolved and head else []
        return {"committed": False, "conflict": True, "head": head, "remote_changes": changes,
                "next": "The repo moved since your base_head: fetch the files listed and try again."}

    def _commit_on(self, name: str, head: str | None, items: Items, message: str,
                   author_name: str, author_email: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            if head:
                self._git(name, "read-tree", head, env=env)
            else:
                self._git(name, "read-tree", "--empty", env=env)
            current = self._index(name, env)
            lines: list[str] = []
            changed: list[dict[str, str]] = []
            unchanged: list[str] = []
            for path, data in items:
                if data is None:
                    if path in current:
                        lines.append(f"0 {ZERO}\t{path}")
                        changed.append({"path": path, "operation": "delete"})
                    else:
                        unchanged.append(path)
                    continue
                if current.get(path) == blob_sha(data):
                    unchanged.append(path)
                    continue
                sha = self._git(name, "hash-object", "-w", "--stdin", input=data).stdout.decode().strip()
                lines.append(f"100644 {sha}\t{path}")
                changed.append({"path": path, "operation": "update" if path in current else "create"})
            if not lines:
                return {"committed": False, "head": head, "unchanged": unchanged}
            self._git(name, "update-index", "-z", "--index-info", input="\0".join(lines).encode() + b"\0", env=env)
            tree = self._git(name, "write-tree", env=env).stdout.decode().strip()
        who = {"GIT_AUTHOR_NAME": author_name, "GIT_AUTHOR_EMAIL": author_email,
               "GIT_COMMITTER_NAME": "iho-server", "GIT_COMMITTER_EMAIL": "iho-server@localhost"}
        parents = ["-p", head] if head else []
        new = self._git(name, "commit-tree", tree, *parents, "-m", message.strip(), env=who).stdout.decode().strip()
        moved = self._git(name, "update-ref", self._ref, new, head or ZERO, ok=(0, 1, 128))
        if moved.returncode != 0:
            # another process won the race between our read and our update-ref
            return self._conflict(name, head or "", self.head(name))
        return {"committed": True, "head": new, "changed": changed, "unchanged": unchanged}

    def _index(self, name: str, env: dict[str, str]) -> dict[str, str]:
        out = self._git(name, "ls-files", "-s", "-z", env=env).stdout.decode()
        index: dict[str, str] = {}
        for rec in filter(None, out.split("\0")):
            meta, path = rec.split("\t", 1)
            index[path] = meta.split()[1]
        return index
