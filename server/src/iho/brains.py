"""The second-brain tools. Same names and contracts as estoca-brain-sync 0.4.0, on local git.

The rule that holds it together: the repo comes from the caller's email (iho.actor), never from an
argument. No tool takes a repo owner, so nobody reads or writes someone else's brain.

Backup and restore go through single-use links (brain_upload_link / brain_download_link): files go
from disk to the server with `curl`, not through the model. brain_push and brain_pull are for small
files or places without `curl`. Without a local folder (chat, Cowork), reading goes through
brain_list, brain_read and brain_search over an in-memory copy of the repo (iho.snapshot).
"""
from __future__ import annotations

import base64
import logging
import re
from importlib.resources import files as package_files
from typing import Any

from iho import snapshot
from iho.actor import Actor
from iho.config import Settings
from iho.errors import IhoError
from iho.gitstore import GitStore, Items
from iho.links import LinkStore
from iho.snapshot import SnapshotCache

logger = logging.getLogger("iho.audit")

_EMAIL = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)+$")


def brain_repo(email: str) -> str:
    if not _EMAIL.match(email):
        raise IhoError(400, "invalid_actor", f"Cannot map {email!r} to a brain.")
    return f"people/{email}"


def clean_path(path: str) -> str:
    p = (path or "").strip().replace("\\", "/")
    parts = p.split("/")
    if not p or p.startswith("/") or any(x in ("", ".", "..") for x in parts) or parts[0] == ".git":
        raise IhoError(400, "invalid_path", f"Invalid path: {path!r}")
    if parts[-1] == ".env" or parts[-1].startswith(".env."):
        raise IhoError(400, "forbidden_path", "Secret files are not stored in the brain.")
    return p


def template_files() -> dict[str, bytes]:
    """The files a new brain starts with (package data under iho/brain_template)."""
    out: dict[str, bytes] = {}

    def walk(node, prefix: str) -> None:
        for child in node.iterdir():
            rel = f"{prefix}{child.name}"
            if child.is_dir():
                walk(child, rel + "/")
            elif child.name != "__init__.py":
                out[rel] = child.read_bytes()

    walk(package_files("iho") / "brain_template", "")
    return out


def _encode(data: bytes) -> dict[str, str]:
    try:
        return {"content": data.decode("utf-8"), "encoding": "text"}
    except UnicodeDecodeError:
        return {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"}


def _decode(f: dict[str, Any], max_bytes: int) -> bytes:
    content = f.get("content")
    if content is None:
        raise IhoError(400, "missing_content", f"No content for {f.get('path')!r}.")
    data = base64.b64decode(content) if f.get("encoding") == "base64" else str(content).encode("utf-8")
    if len(data) > max_bytes:
        raise IhoError(400, "file_too_large", f"{f.get('path')!r} is over {max_bytes} bytes.")
    return data


def _message(message: str | None) -> str:
    m = (message or "").strip()
    if len(m) < 3:
        raise IhoError(400, "invalid_message", "Commit message needs at least 3 characters.")
    return m


class Brains:
    def __init__(self, settings: Settings, git: GitStore, links: LinkStore):
        self.s, self.git, self.links = settings, git, links
        self.snapshots = SnapshotCache(settings.snapshot_cache_repos)

    def _audit(self, tool: str, actor: Actor, result: dict[str, Any]) -> dict[str, Any]:
        logger.info("tool=%s actor=%s head=%s", tool, actor.email, result.get("head"))
        return result

    def _existing(self, actor: Actor) -> str:
        repo = brain_repo(actor.email)
        if not self.git.exists(repo):
            raise IhoError(404, "brain_missing", "Your second brain does not exist yet: run brain_bootstrap.")
        return repo

    def _snapshot(self, repo: str) -> tuple[str | None, dict[str, bytes]]:
        head = self.git.head(repo)
        return head, self.snapshots.get(repo, head, lambda: self.git.files(repo, head))

    def _link_url(self, kind: str, token: str) -> str:
        return f"{self.s.normalized_public_url}/cli/{kind}/{token}"

    def commit(self, actor: Actor, *, message: str, base_head: str | None, items: Items) -> dict[str, Any]:
        repo = self._existing(actor)
        result = self.git.commit(repo, items=items, message=_message(message), base_head=base_head,
                                 author_name=actor.email.split("@")[0], author_email=actor.email)
        return {"repo": repo, **result}

    # ------------------------------------------------------------ lifecycle
    def status(self, actor: Actor) -> dict[str, Any]:
        repo = brain_repo(actor.email)
        if not self.git.exists(repo):
            return {"repo": None, "next": "brain_bootstrap"}
        return {"repo": repo, "head": self.git.head(repo), "next": "brain_download_link"}

    def bootstrap(self, actor: Actor) -> dict[str, Any]:
        repo = brain_repo(actor.email)
        created = False
        if not self.git.exists(repo):
            self.git.create(repo)
            created = True
        if self.git.head(repo) is None:
            self.git.commit(repo, items=sorted(template_files().items()), message="bootstrap: new second brain",
                            author_name=actor.email.split("@")[0], author_email=actor.email)
        return self._audit("brain_bootstrap", actor, {**self.status(actor), "created": created})

    # ------------------------------------------------------------ links
    def upload_link(self, actor: Actor, message: str, base_head: str | None) -> dict[str, Any]:
        repo = self._existing(actor)
        token, expires = self.links.create(email=actor.email, kind="upload", repo=repo, message=_message(message),
                                           base_head=(base_head or "").strip() or None,
                                           ttl_seconds=self.s.link_ttl_seconds)
        url = self._link_url("upload", token)
        return {"repo": repo, "head": self.git.head(repo), "url": url, "expires_at": expires, "single_use": True,
                "usage": f"curl -fsS -F 'file=@\"<path>\";filename=\"<path>\"' [-F 'delete=<path>'] '{url}'",
                "notes": "One -F per file, with the path relative to the brain root as filename. "
                         f"Up to {self.s.max_files_per_upload} files and {self.s.max_upload_bytes} bytes per link."}

    def download_link(self, actor: Actor) -> dict[str, Any]:
        repo = self._existing(actor)
        head = self.git.head(repo)
        if head is None:
            raise IhoError(409, "brain_empty", "Your second brain has no commit yet: run brain_bootstrap.")
        token, expires = self.links.create(email=actor.email, kind="download", repo=repo, message=None,
                                           base_head=head, ttl_seconds=self.s.link_ttl_seconds)
        url = self._link_url("download", token)
        return {"repo": repo, "head": head, "url": url, "expires_at": expires, "single_use": True,
                "usage": f"curl -fsSL '{url}' | tar -xzf - --strip-components=1 -C <brain folder>",
                "notes": "Overwrites the files in the package; does not delete local files that are not in the repo."}

    def download(self, link_email: str, link_repo: str, head: str) -> tuple[str, bytes]:
        if brain_repo(link_email) != link_repo or not self.git.exists(link_repo):
            raise IhoError(409, "link_stale", "The brain changed since the link was created. Ask for another.")
        return link_repo.split("/", 1)[1], self.git.archive_targz(link_repo, head, "second-brain")

    # ------------------------------------------------------------ reads
    def list(self, actor: Actor, prefix: str | None, depth: int | None) -> dict[str, Any]:
        repo = self._existing(actor)
        head, files = self._snapshot(repo)
        listed = snapshot.list_entries(files, (prefix or "").strip(), depth, self.s.max_list_entries)
        return {"repo": repo, "head": head, **listed}

    def read(self, actor: Actor, path: str, offset: int | None, limit: int | None) -> dict[str, Any]:
        repo = self._existing(actor)
        p = clean_path(path)
        head, files = self._snapshot(repo)
        if p not in files:
            raise IhoError(404, "not_found", f"{p} is not in your second brain. Use brain_list or brain_search.")
        lines = max(1, limit or self.s.read_default_lines)
        return {"repo": repo, "head": head, **snapshot.read_lines(p, files[p], offset or 1, lines, self.s.max_read_bytes)}

    def search(self, actor: Actor, query: str, *, prefix: str | None, regex: bool, case_sensitive: bool,
               context: int, max_results: int | None, files_only: bool) -> dict[str, Any]:
        repo = self._existing(actor)
        head, files = self._snapshot(repo)
        found = snapshot.search(
            files, (prefix or "").strip(), query, regex=regex, case_sensitive=case_sensitive,
            context=min(max(0, context), self.s.max_search_context),
            max_results=min(max(1, max_results or self.s.search_default_results), self.s.max_search_results),
            files_only=files_only, max_line_chars=self.s.max_line_chars)
        return {"repo": repo, "head": head, **found}

    def pull(self, actor: Actor, prefix: str | None, cursor: int | None) -> dict[str, Any]:
        repo = self._existing(actor)
        head, files = self._snapshot(repo)
        paths = snapshot.under(files, (prefix or "").strip())
        i = start = max(0, cursor or 0)
        out: list[dict[str, Any]] = []
        total = 0
        while i < len(paths) and len(out) < self.s.max_files_per_pull:
            data = files[paths[i]]
            if out and total + len(data) > self.s.max_bytes_per_pull:
                break
            out.append({"path": paths[i], **_encode(data)})
            total += len(data)
            i += 1
        result = {"repo": repo, "head": head, "files": out, "total": len(paths), "cursor": start,
                  "next_cursor": i if i < len(paths) else None}
        if total > self.s.pull_hint_bytes:
            result["hint"] = (f"This read brought {total // 1000} KB into the conversation. To find something, use "
                              "brain_search; for one file or a slice, brain_read; for the layout, brain_list.")
        return result

    # ------------------------------------------------------------ writes
    def _write_one(self, actor: Actor, path: str, data: bytes, message: str, base_head: str | None) -> dict[str, Any]:
        if len(data) > self.s.max_file_bytes:
            raise IhoError(400, "file_too_large", f"{path} would be over {self.s.max_file_bytes} bytes.")
        return self._audit("write", actor, self.commit(actor, message=message, base_head=base_head,
                                                       items=[(path, data)]))

    def append(self, actor: Actor, path: str, text: str, message: str) -> dict[str, Any]:
        repo = self._existing(actor)
        p = clean_path(path)
        if not text:
            raise IhoError(400, "invalid_text", "Empty text.")
        head, files = self._snapshot(repo)
        current = files.get(p, b"")
        sep = b"\n" if current and not current.endswith(b"\n") else b""
        added = text.encode("utf-8") + (b"" if text.endswith("\n") else b"\n")
        # append applies on top of the current head with that head as base: what another machine
        # wrote stays before it, and a write that lands in between is refused instead of lost
        return self._write_one(actor, p, current + sep + added, message, head)

    def edit(self, actor: Actor, path: str, old: str, new: str, message: str, *, replace_all: bool,
             base_head: str | None) -> dict[str, Any]:
        repo = self._existing(actor)
        p = clean_path(path)
        if not old:
            raise IhoError(400, "invalid_old", "Empty old.")
        head, files = self._snapshot(repo)
        if p not in files:
            raise IhoError(404, "not_found", f"{p} is not in your second brain.")
        text = snapshot.text_of(files[p])
        if text is None:
            raise IhoError(400, "binary_file", f"{p} is not text.")
        n = text.count(old)
        if n == 0:
            raise IhoError(409, "old_not_found", f"The text is not in {p} at head {(head or '')[:7]}. "
                                                 "Read it again with brain_read and retry.")
        if n > 1 and not replace_all:
            raise IhoError(400, "old_ambiguous", f"The text appears {n} times in {p}. Add context to `old` "
                                                 "or use replace_all.")
        return self._write_one(actor, p, text.replace(old, new).encode("utf-8"), message, base_head or head)

    def push(self, actor: Actor, message: str, files_in: list[dict[str, Any]], base_head: str | None) -> dict[str, Any]:
        if not files_in or len(files_in) > self.s.max_files_per_push:
            raise IhoError(400, "invalid_files", f"Between 1 and {self.s.max_files_per_push} files per call.")
        items: Items = []
        for f in files_in:
            p = clean_path(str(f.get("path", "")))
            items.append((p, None if f.get("delete") else _decode(f, self.s.max_file_bytes)))
        return self._audit("brain_push", actor, self.commit(actor, message=message, base_head=base_head, items=items))
