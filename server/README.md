# iho-server

The InHouseOS server: tracker, brains, compass, skills and the MCP endpoint in one process, with everything it keeps in one volume (`/data`). One instance per company.

Status: `/health`, `/mcp` with `iho_whoami`, the second-brain tools, the tracker, standalone login, snapshots (LAB-50 to LAB-54) skills served over MCP (LAB-56) and a first screen in the chat (MCP Apps). Agent install (LAB-55) comes next.

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

## Skills

The rituals are served by the server itself, so the agent needs no plugin: `os_list_skills` lists them (name, what it does, when to use it) and `os_get_skill(name)` returns the step by step plus the support docs it references. The MCP `instructions` field tells the agent to fetch the skill before acting when the person says a trigger ("bom dia", "abrir pacote", "fechar pacote", `/sweep`...). Lookup takes the name, an alias or the slash command (`/abrir-pacote`, "abrir pacote").

| Skill | Aliases | Does |
|---|---|---|
| `bomdia` | `abrir-pacote` | the morning package: agenda, the queue, offers, what arrived, chases, decisions, meetings to prepare and ingest |
| `fechar-pacote` | `boanoite` | the evening close: bumps sent, closes with evidence, outcomes of the day's suggestions, what is due tomorrow |
| `sweep` | `varredura` | all sources since the last sweep, classified, with proposed actions and pages |

They are package data under `src/iho/skills/`: `<name>/SKILL.md` with a small frontmatter (`name`, `description`, `when`, `aliases`, `docs`), and shared support docs at the root (`tracker.md`, `compass.md`, `brain.md`, `armadilhas.md`). They read the brain with the `brain_*` tools, the tracker with `tracker_*`, and chat, email and calendar through each person's own connectors. Company values are `{{placeholders}}` filled from `IHO_COMPANY_*`, never written in the text. The skills are in Portuguese for now.

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
| `IHO_AUTH_MODE` | `dev` | `dev` (one fixed token) or `standalone` (own OAuth, people sign in with Google or another OpenID provider); `iht` (behind inhouse.technology) is planned |
| `IHO_OIDC_PROVIDER` | `google` | `google`, or `oidc` for any OpenID provider with discovery (e.g. a Microsoft tenant) |
| `IHO_OIDC_ISSUER` | `https://accounts.google.com` | for Microsoft, the tenant issuer `https://login.microsoftonline.com/<tenant id>/v2.0` |
| `IHO_OIDC_CLIENT_ID`, `IHO_OIDC_CLIENT_SECRET` | | the OAuth client you create at the provider, with redirect URI `<IHO_PUBLIC_URL>/oauth/callback` |
| `IHO_ALLOWED_DOMAINS` | | who signs in: verified e-mails of these domains (with Google, the Workspace domain must match too) |
| `IHO_ALLOWED_EMAILS` | | invited people from other domains |
| `IHO_COMPANY_NAME` | | the company name the skills and the MCP instructions use |
| `IHO_COMPANY_DOMAIN` | first of `IHO_ALLOWED_DOMAINS` | the company's e-mail domain |
| `IHO_COMPANY_CONNECTORS` | `Slack,Gmail,Google Calendar,Google Drive` | connectors each person is expected to have on their agent; the skills check them, they do not install them |
| `IHO_COMPANY_MEETING_NOTES` | | the official source of meeting notes, e.g. `Gemini notes in Google Drive` |
| `IHO_BACKUP_DIR` | unset (off) | scheduled snapshots go here (in the image: `/backups`) |
| `IHO_BACKUP_EVERY_HOURS`, `IHO_BACKUP_KEEP` | `24`, `7` | how often, and how many to keep |
| `IHO_OAUTH_REDIRECT_HOSTS` | `claude.ai,claude.com,localhost,127.0.0.1` | agents allowed to register and receive login codes |
| `IHO_DEV_TOKEN` | | dev mode only: the one accepted bearer token, 24+ characters |
| `IHO_DEV_USER` | | dev mode only: the email that token stands for |

Dev mode has one token and one person. Publish it on localhost only, as `compose.yaml` does.

## Tracker

The shared tracker of actions, decisions, projects and suggestions, from estoca-project-tracker 0.16.2, runs inside the same process on the same SQLite file (`/data/iho.db`). Its 28 `tracker_*` tools keep their names and contracts and are served from its own catalog (`iho.tracker.tools`). Left out: its web screens and REST routes (they trusted proxy headers that nothing validates here) and `tracker_snapshot_link` (only the old local views used it).

Until `setup-os` fills the org chart, nobody has leadership or C-level roles: each person sees their own items, and `IHO_TRACKER_ADMIN_EMAILS` sees everything. Tables are created on start; schema changes after the first release will need SQLite migrations.

## Snapshots, export and import

A snapshot is one `.tar.gz` with the whole instance: `iho.db` copied with SQLite's online backup API (consistent while the server runs), one git bundle per brain with every ref, and a manifest. It is both the backup and the way to move an instance (hosted to your own machine, or back).

```bash
docker exec iho iho export /backups/move.tar.gz      # while running
docker run --rm -v <new data volume>:/data -v <backups>:/backups iho-server iho import /backups/move.tar.gz
```

Import goes into a stopped instance; it refuses a data dir that already has data unless `--force`, which moves the current data aside instead of deleting it. With `IHO_BACKUP_DIR` set, the server writes a snapshot on start and every `IHO_BACKUP_EVERY_HOURS`, keeps the newest `IHO_BACKUP_KEEP`, and reports the last one in `/health` (`backup.ok`, or the error). `iho backup-now` takes one on demand. Copying snapshots off the machine is your tool's job (rclone, restic, a NAS sync): the folder is the boundary, so the server holds no cloud credentials. A host folder mounted on `/backups` must be writable by uid 10001.

## Standalone login

The server is the OAuth server agents connect to: the MCP SDK serves `/register` (dynamic client registration, which claude.ai needs), `/authorize`, `/token`, `/revoke` and the metadata, and `iho.oauth` stores clients, codes and tokens in `/data/iho.db` (only hashes of tokens). `/authorize` sends the person to the sign-in provider; `/oauth/callback` admits a verified e-mail from an allowed domain or an invited one and hands the agent a code whose subject is that e-mail. Access tokens last an hour, refresh tokens 30 days; a refresh rotates both, and revoking either drops the whole login.

Registration is open, but only redirects to the hosts in `IHO_OAUTH_REDIRECT_HOSTS` are accepted, so another site cannot register itself and collect sign-ins. Not done yet: cutting access when someone leaves the company (today it ends when the refresh token expires); revocation through the SDK needs an empty `client_secret` field even from public clients.

## Auth, in one place

Every tool asks `iho.actor.current_actor()` who is calling. The auth mode only picks the `TokenVerifier` that turns a bearer token into that person, so adding a login mode never touches a tool.

## Tests

```bash
cd server
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
```
