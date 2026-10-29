"""The iho-server application: one process, one /mcp endpoint, one data volume."""
from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from typing import Annotated, Any, Callable

import anyio

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ContentBlock, Tool as MCPTool
from pydantic import AnyHttpUrl, Field
from starlette.applications import Starlette
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from iho import __version__
from iho.actor import Actor, build_verifier, current_actor
from iho.backup import BackupScheduler
from iho.brains import Brains, clean_path
from iho.config import AuthMode, Settings
from iho.errors import IhoError
from iho.gitstore import GitStore
from iho.links import LinkStore
from iho.oauth import CALLBACK_PATH, OAuthProvider
from iho.tracker.service import Tracker

logger = logging.getLogger("iho.audit")

INSTRUCTIONS = (
    "InHouseOS: each person's private second brain, the company's shared tracker, its compass "
    "and its company brain. Act only for the authenticated person. Private content (raw sources, "
    "the person's wiki) never leaves that person's brain unless they promote it. "
    "Without the brain folder on disk, read with brain_list, brain_read and brain_search, and write "
    "with brain_append and brain_edit; with a shell and curl, use brain_download_link and brain_upload_link."
)

HOME_HTML = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>InHouseOS</title></head>'
    "<body><p>InHouseOS server. Connect your agent to the <code>/mcp</code> endpoint.</p></body></html>"
)

Path_ = Annotated[str, Field(description="Path from the brain root, e.g. wiki/daily/2026-10-29.md")]
Message = Annotated[str, Field(min_length=3, description="Commit message.")]
BaseHead = Annotated[str | None, Field(description="Head read before writing; if the repo moved, nothing is written.")]


def prepare_data_dir(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.repos_dir.mkdir(parents=True, exist_ok=True)


def _tool(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fn()
    except IhoError as exc:
        raise ToolError(f"{exc.code}: {exc.message}") from exc


class IhoMCP(FastMCP):
    """FastMCP plus tools that arrive with a ready JSON schema (the tracker's catalog).

    Native tools come from @tool; catalog tools are listed with their own schema and dispatched to a
    handler that takes the arguments dict. The handler runs in a thread: the tracker is sync SQLAlchemy.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        self._catalog: dict[str, tuple[MCPTool, Callable[[dict[str, Any]], dict[str, Any]]]] = {}
        super().__init__(*args, **kwargs)

    def add_catalog_tool(self, spec: dict[str, Any], handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        tool = MCPTool(name=spec["name"], description=spec["description"], inputSchema=spec["inputSchema"],
                       annotations=spec.get("annotations"))
        self._catalog[tool.name] = (tool, handler)

    async def list_tools(self) -> list[MCPTool]:
        return [*await super().list_tools(), *(t for t, _ in self._catalog.values())]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Sequence[ContentBlock] | dict[str, Any]:
        if name not in self._catalog:
            return await super().call_tool(name, arguments)
        handler = self._catalog[name][1]
        return await anyio.to_thread.run_sync(lambda: _tool(lambda: handler(arguments or {})))


def create_application(settings: Settings, *, token_verifier: TokenVerifier | None = None,
                       oauth_provider: OAuthProvider | None = None) -> Starlette:
    prepare_data_dir(settings)
    public_url = AnyHttpUrl(settings.normalized_public_url)
    brains = Brains(settings, GitStore(settings.repos_dir), LinkStore(settings.db_path))
    tracker = Tracker(settings.db_path)
    backups = BackupScheduler(settings)
    backups.start()

    # standalone: this server is the OAuth server (the SDK serves its routes); dev: one fixed token
    provider = None
    verifier = None
    if settings.auth_mode is AuthMode.STANDALONE:
        provider = oauth_provider or OAuthProvider(settings, settings.db_path)
    else:
        verifier = token_verifier or build_verifier(settings)

    mcp = IhoMCP(
        name="InHouseOS",
        instructions=INSTRUCTIONS,
        token_verifier=verifier,
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=public_url,
            resource_server_url=AnyHttpUrl(f"{settings.normalized_public_url}/mcp"),
            required_scopes=[],
            client_registration_options=ClientRegistrationOptions(enabled=True) if provider else None,
            revocation_options=RevocationOptions(enabled=True) if provider else None,
        ),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )

    @mcp.tool()
    def iho_whoami() -> dict:
        """Who you are on this InHouseOS server, and which server it is."""
        actor = current_actor()
        return {
            "email": actor.email,
            "domain": actor.domain,
            "server": settings.normalized_public_url,
            "version": __version__,
            "auth_mode": settings.auth_mode.value,
        }

    # ------------------------------------------------------------ second brain
    @mcp.tool()
    def brain_status() -> dict:
        """State of your second brain: whether it exists, its repo and its head. If it does not exist,
        `next` says to run brain_bootstrap."""
        return _tool(lambda: brains.status(current_actor()))

    @mcp.tool()
    def brain_bootstrap() -> dict:
        """Create your second brain from the template. Idempotent. Then brain_download_link to put it on disk,
        or brain_list to work without a local folder."""
        return _tool(lambda: brains.bootstrap(current_actor()))

    @mcp.tool()
    def brain_upload_link(message: Message, base_head: BaseHead = None) -> dict:
        """BACKUP (normal path). A single-use link, valid for a few minutes, to send changed files straight
        from disk with curl, without the content passing through the conversation. Run the `usage` command
        at the brain root, one -F per file; to delete, -F 'delete=<path>'. With base_head, nothing is written
        if the repo moved."""
        return _tool(lambda: brains.upload_link(current_actor(), message, base_head))

    @mcp.tool()
    def brain_download_link() -> dict:
        """RESTORE (normal path). A single-use link to download the whole brain as .tar.gz and extract it
        with curl and tar, without the content passing through the conversation."""
        return _tool(lambda: brains.download_link(current_actor()))

    @mcp.tool()
    def brain_list(
        prefix: Annotated[str | None, Field(description="Only paths starting with this, e.g. wiki/people/")] = None,
        depth: Annotated[int | None, Field(ge=1, description="Folder levels before grouping.")] = None,
    ) -> dict:
        """List the files of your second brain, no content: path, bytes and lines. The `ls` for when there
        is no local folder. With `depth`, deeper files are grouped by folder (depth=2 shows wiki/daily/ with
        a count). Then brain_read or brain_search."""
        return _tool(lambda: brains.list(current_actor(), prefix, depth))

    @mcp.tool()
    def brain_read(
        path: Path_,
        offset: Annotated[int, Field(description="First line (1 = start); negative counts from the end.")] = 1,
        limit: Annotated[int | None, Field(ge=1, description="Max lines (default 400).")] = None,
    ) -> dict:
        """Read only a slice of a file of your second brain. offset=-5 on wiki/log.md gives the last five
        entries. If `next_offset` comes back, there is more: call again with it."""
        return _tool(lambda: brains.read(current_actor(), path, offset, limit))

    @mcp.tool()
    def brain_search(
        query: Annotated[str, Field(min_length=1, description="Literal text, or a regex with regex=true.")],
        prefix: Annotated[str | None, Field(description="Only paths starting with this, e.g. wiki/")] = None,
        regex: bool = False,
        case_sensitive: bool = False,
        context: Annotated[int, Field(ge=0, le=5, description="Lines before and after each match.")] = 0,
        max_results: Annotated[int, Field(ge=1, le=200)] = 30,
        files_only: bool = False,
    ) -> dict:
        """Search your second brain and get `path:line` with the line, not whole files. The `grep` for when
        there is no local folder. Ignores case and accents (decisao finds Decisão) unless case_sensitive.
        Files with a date in the name come newest first. files_only=true returns only files and counts."""
        return _tool(lambda: brains.search(
            current_actor(), query, prefix=prefix, regex=regex, case_sensitive=case_sensitive, context=context,
            max_results=max_results, files_only=files_only))

    @mcp.tool()
    def brain_append(
        path: Path_,
        text: Annotated[str, Field(min_length=1, description="What goes at the end; gets a trailing newline.")],
        message: Message,
    ) -> dict:
        """Append text to the end of a file of your second brain (created if missing) without rewriting it.
        For files that only grow: wiki/log.md."""
        return _tool(lambda: brains.append(current_actor(), path, text, message))

    @mcp.tool()
    def brain_edit(
        path: Path_,
        old: Annotated[str, Field(min_length=1, description="Exact text that goes out.")],
        new: Annotated[str, Field(description="Text that comes in (empty deletes).")],
        message: Message,
        replace_all: bool = False,
        base_head: BaseHead = None,
    ) -> dict:
        """Replace a piece of a file of your second brain without rewriting the whole file: `old` must appear
        exactly once (or use replace_all). Read the piece first with brain_read or brain_search."""
        return _tool(lambda: brains.edit(current_actor(), path, old, new, message,
                                                  replace_all=replace_all, base_head=base_head))

    @mcp.tool()
    def brain_pull(
        prefix: str | None = None,
        cursor: Annotated[int | None, Field(ge=0)] = None,
    ) -> dict:
        """Read WHOLE files of your second brain through the conversation. To find something use brain_search;
        for one file or a slice, brain_read; for the layout, brain_list; for the whole folder on disk,
        brain_download_link. Paged: repeat with `cursor` while `next_cursor` comes back."""
        return _tool(lambda: brains.pull(current_actor(), prefix, cursor))

    @mcp.tool()
    def brain_push(
        message: Message,
        files: Annotated[list[dict[str, Any]], Field(
            min_length=1, description="[{path, content, encoding: text|base64, delete: bool}]")],
        base_head: BaseHead = None,
    ) -> dict:
        """Write small files through the conversation (the model writes the content). For backup prefer
        brain_upload_link. Files equal to the repo are skipped. With base_head, nothing is written if the
        repo moved."""
        return _tool(lambda: brains.push(current_actor(), message, files, base_head))

    # ------------------------------------------------------------ tracker (catalog of estoca-project-tracker)
    for spec in tracker.catalog():
        mcp.add_catalog_tool(spec, lambda args, name=spec["name"]: tracker.run(name, args, current_actor()))

    app = mcp.streamable_http_app()

    # ------------------------------------------------------------ single-use links (the token is the auth)
    async def upload(request: Request) -> Response:
        try:
            declared = int(request.headers.get("content-length") or 0)
            if declared > settings.max_upload_bytes:
                raise IhoError(413, "upload_too_large", f"Upload is over {settings.max_upload_bytes} bytes.")
            link = brains.links.consume(request.path_params["token"], "upload")
            if link is None:
                raise IhoError(404, "link_invalid", "Invalid, expired or used link. Ask for another.")
            items = await _read_items(request, settings)
            # the single-use link stands in for the bearer token: it was created by this person
            result = brains.commit(Actor(email=link.email, client_id="link"), message=link.message or "backup",
                                   base_head=link.base_head, items=list(items.items()))
            logger.info("cli=upload actor=%s files=%d committed=%s", link.email, len(items), result.get("committed"))
            return JSONResponse(result)
        except IhoError as exc:
            return JSONResponse(exc.as_json(), status_code=exc.status)

    async def download(request: Request) -> Response:
        try:
            link = brains.links.consume(request.path_params["token"], "download")
            if link is None:
                raise IhoError(404, "link_invalid", "Invalid, expired or used link. Ask for another.")
            name, data = brains.download(link.email, link.repo, link.base_head or "")
            logger.info("cli=download actor=%s bytes=%d", link.email, len(data))
            filename = name.replace("@", "_at_") + ".tar.gz"
            return Response(data, media_type="application/gzip",
                            headers={"Content-Disposition": f'attachment; filename="{filename}"'})
        except IhoError as exc:
            return JSONResponse(exc.as_json(), status_code=exc.status)

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "service": "iho-server",
            "version": __version__,
            "commit_sha": os.environ.get("GIT_COMMIT_SHA", "unknown"),
            "backup": backups.last if backups.enabled else "off",
        })

    async def home(_: Request) -> HTMLResponse:
        return HTMLResponse(HOME_HTML)

    app.routes[:0] = [
        Route("/health", health, methods=["GET"]),
        Route("/", home, methods=["GET"]),
        Route("/cli/upload/{token}", upload, methods=["POST"]),
        Route("/cli/download/{token}", download, methods=["GET"]),
    ]
    if provider is not None:
        app.routes.insert(0, Route(CALLBACK_PATH, provider.callback, methods=["GET"]))
    return app


async def _read_items(request: Request, settings: Settings) -> dict[str, bytes | None]:
    """Multipart: file=@<file>;filename=<path> writes, delete=<path> deletes."""
    form = await request.form(max_files=settings.max_files_per_upload, max_fields=settings.max_files_per_upload)
    items: dict[str, bytes | None] = {}
    total = 0
    for key, value in form.multi_items():
        if key == "file" and isinstance(value, UploadFile):
            path = clean_path(value.filename or "")
            data = await value.read()
            total += len(data)
            if total > settings.max_upload_bytes:
                raise IhoError(413, "upload_too_large", f"Upload is over {settings.max_upload_bytes} bytes.")
            items[path] = data
        elif key == "delete" and isinstance(value, str):
            items[clean_path(value)] = None
        else:
            raise IhoError(400, "invalid_field", f"Unexpected upload field {key!r}. Use file= or delete=.")
    if not items:
        raise IhoError(400, "no_files", "No files in the upload.")
    return items
