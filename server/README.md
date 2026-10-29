# iho-server

The InHouseOS server: tracker, brains, compass, skills and the MCP endpoint in one process, with everything it keeps in one volume (`/data`). One instance per company.

Status: `/health`, `/mcp` with `iho_whoami`, the second-brain tools and the tracker (LAB-50 to LAB-52). Real login (LAB-53), backup (LAB-54) and agent install (LAB-55) come next.

## Brains

Each person's second brain is a bare git repository at `/data/repos/people/<email>.git`. The repo comes from the caller's identity, never from a tool argument, so nobody reaches someone else's brain. No Gitea: the server drives `git` plumbing directly, and anyone can `git clone` a brain out of the volume.

| Tool | Does |
|---|---|
| `brain_status`, `brain_bootstrap` | state of your brain; create it from the template (`src/iho/brain_template`, whose `CLAUDE.md` is `templates/second-brain-schema.md`) |
| `brain_upload_link`, `brain_download_link` | single-use links for backup and restore with `curl`, without file content passing through the conversation |
| `brain_list`, `brain_read`, `brain_search` | `ls`, line reads and `grep` on the server, for chat and Cowork where there is no folder |
| `brain_append`, `brain_edit` | write a piece of a file without the model rewriting it |
| `brain_pull`, `brain_push` | whole files through the conversation, for small files |

Writes are built in a throwaway index and published with `git update-ref <branch> <new> <old>`: if another write got in first, nothing is written and the answer lists what changed. Same contracts as estoca-brain-sync 0.4.0.

Measured on a synthetic brain the size of a real one (215 files, 2.3 MB), in the container: upload of 200 files 0.18 s, `brain_list` 14 ms, a search over the whole brain 81 ms, 49 MB RAM.

## Try it

```bash
cd server
printf 'IHO_DEV_TOKEN=%s\nIHO_DEV_USER=you@example.com\n' "$(openssl rand -hex 24)" > .env
docker compose up --build
curl http://localhost:8080/health
```

Point an MCP client at `http://localhost:8080/mcp` with `Authorization: Bearer <IHO_DEV_TOKEN>`.

## Settings

All from `IHO_*` variables (or `server/.env`).

| Variable | Default | What |
|---|---|---|
| `IHO_DATA_DIR` | `/data` | `iho.db` and `repos/` live here |
| `IHO_PUBLIC_URL` | `http://localhost:8080` | the URL agents connect to |
| `IHO_AUTH_MODE` | `dev` | `dev` today; `standalone` (own OAuth with Google/Microsoft login) and `iht` (behind inhouse.technology) are planned |
| `IHO_DEV_TOKEN` | | dev mode only: the one accepted bearer token, 24+ characters |
| `IHO_DEV_USER` | | dev mode only: the email that token stands for |

Dev mode has one token and one person. Publish it on localhost only, as `compose.yaml` does.

## Tracker

The shared tracker of actions, decisions, projects and suggestions, from estoca-project-tracker 0.16.2, runs inside the same process on the same SQLite file (`/data/iho.db`). Its 28 `tracker_*` tools keep their names and contracts and are served from its own catalog (`iho.tracker.tools`). Left out: its web screens and REST routes (they trusted proxy headers that nothing validates here) and `tracker_snapshot_link` (only the old local views used it).

Until `setup-os` fills the org chart, nobody has leadership or C-level roles: each person sees their own items, and `IHO_TRACKER_ADMIN_EMAILS` sees everything. Tables are created on start; schema changes after the first release will need SQLite migrations.

## Auth, in one place

Every tool asks `iho.actor.current_actor()` who is calling. The auth mode only picks the `TokenVerifier` that turns a bearer token into that person, so adding a login mode never touches a tool.

## Tests

```bash
cd server
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
```
