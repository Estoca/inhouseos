# iho-server

The InHouseOS server: tracker, brains, compass, skills and the MCP endpoint in one process, with everything it keeps in one volume (`/data`). One instance per company.

Status: skeleton (LAB-50). It answers `/health` and serves `/mcp` with one tool, `iho_whoami`. Brains in git (LAB-51), the tracker (LAB-52), real login (LAB-53), backup (LAB-54) and agent install (LAB-55) come next.

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

## Auth, in one place

Every tool asks `iho.actor.current_actor()` who is calling. The auth mode only picks the `TokenVerifier` that turns a bearer token into that person, so adding a login mode never touches a tool.

## Tests

```bash
cd server
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
```
