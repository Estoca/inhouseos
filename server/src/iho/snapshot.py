"""A brain in memory, per (repo, head), so the server can list, read a slice and search.

In chat, Cowork or a cloud session without `curl`, the agent has no `ls`, no `grep` and no line
reads. These functions play that role on the server: the agent gets only what it asked for, instead
of whole folders. Ported from estoca-brain-sync 0.4.0 (app/snapshot.py).

A copy is valid while the head does not move. A bounded number of repos stay in memory (LRU); the
server is one process (uvicorn without --workers).
"""
from __future__ import annotations

import re
import threading
import unicodedata
from collections import OrderedDict
from typing import Any, Callable

from iho.errors import IhoError

Files = dict[str, bytes]


class SnapshotCache:
    def __init__(self, max_repos: int):
        self._max = max_repos
        self._items: OrderedDict[str, tuple[str, Files]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, repo: str, head: str | None, fetch: Callable[[], Files]) -> Files:
        if head is None:
            return {}
        with self._lock:
            hit = self._items.get(repo)
            if hit and hit[0] == head:
                self._items.move_to_end(repo)
                return hit[1]
        files = fetch()
        with self._lock:
            self._items[repo] = (head, files)
            self._items.move_to_end(repo)
            while len(self._items) > self._max:
                self._items.popitem(last=False)
        return files


def text_of(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def line_count(data: bytes) -> int:
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def under(files: Files, prefix: str) -> list[str]:
    return sorted(p for p in files if p.startswith(prefix))


# ---------------------------------------------------------------- list
def list_entries(files: Files, prefix: str, depth: int | None, max_entries: int) -> dict[str, Any]:
    paths = under(files, prefix)
    entries: list[dict[str, Any]] = []
    dirs: dict[str, dict[str, Any]] = {}
    for p in paths:
        parts = p.split("/")
        if depth is not None and len(parts) > depth:
            d = "/".join(parts[:depth]) + "/"
            if d not in dirs:
                dirs[d] = {"path": d, "files": 0, "bytes": 0}
                entries.append(dirs[d])
            dirs[d]["files"] += 1
            dirs[d]["bytes"] += len(files[p])
        else:
            entries.append({"path": p, "bytes": len(files[p]), "lines": line_count(files[p])})
    return {"entries": entries[:max_entries], "truncated": len(entries) > max_entries,
            "total_files": len(paths), "total_bytes": sum(len(files[p]) for p in paths)}


# ---------------------------------------------------------------- read
def read_lines(path: str, data: bytes, offset: int, limit: int, max_bytes: int) -> dict[str, Any]:
    text = text_of(data)
    if text is None:
        raise IhoError(400, "binary_file", f"{path} is not text; use brain_pull or brain_download_link.")
    lines = text.splitlines(keepends=True)
    total = len(lines)
    start = max(0, total + offset) if offset < 0 else max(0, offset - 1)
    out: list[str] = []
    size = 0
    end = start
    while end < total and len(out) < limit:
        n = len(lines[end].encode("utf-8"))
        if out and size + n > max_bytes:
            break
        out.append(lines[end])
        size += n
        end += 1
    return {"path": path, "content": "".join(out), "start_line": start + 1 if out else None,
            "end_line": end if out else None, "total_lines": total,
            "next_offset": end + 1 if end < total else None}


# ---------------------------------------------------------------- search
def fold(s: str) -> str:
    """Strip accents (decisao finds decisão). Case is left to re.IGNORECASE."""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def search(files: Files, prefix: str, query: str, *, regex: bool, case_sensitive: bool, context: int,
           max_results: int, files_only: bool, max_line_chars: int) -> dict[str, Any]:
    if not query:
        raise IhoError(400, "invalid_query", "Empty query.")
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern_src = query if regex else re.escape(query)
    if not case_sensitive:
        pattern_src = fold(pattern_src)
    try:
        pattern = re.compile(pattern_src, flags)
    except re.error as exc:
        raise IhoError(400, "invalid_regex", f"Invalid regex: {exc}") from exc

    def clip(s: str) -> str:
        s = s.rstrip("\r\n")
        return s if len(s) <= max_line_chars else s[:max_line_chars] + "…"

    matches: list[dict[str, Any]] = []
    by_file: list[dict[str, Any]] = []
    total = 0
    # paths in descending order: dated file names come newest first
    for path in sorted(under(files, prefix), reverse=True):
        text = text_of(files[path])
        if text is None:
            continue
        lines = text.splitlines()
        hits = [i for i, line in enumerate(lines)
                if pattern.search(line if case_sensitive else fold(line))]
        if not hits:
            continue
        total += len(hits)
        by_file.append({"path": path, "matches": len(hits)})
        if files_only:
            continue
        for i in hits:
            if len(matches) >= max_results:
                break
            m: dict[str, Any] = {"path": path, "line": i + 1, "text": clip(lines[i])}
            if context:
                m["before"] = [clip(x) for x in lines[max(0, i - context):i]]
                m["after"] = [clip(x) for x in lines[i + 1:i + 1 + context]]
            matches.append(m)
    result: dict[str, Any] = {"total_matches": total, "files_matched": len(by_file)}
    if files_only:
        result["files"] = by_file[:max_results]
        result["truncated"] = len(by_file) > max_results
    else:
        result["matches"] = matches
        result["truncated"] = total > len(matches)
    return result
