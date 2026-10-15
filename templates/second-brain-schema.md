# Second Brain — <Name> / <Company>

This repository is the **second brain** of <Name>: an LLM wiki. Raw sources come in, you (the agent) classify them, link them to people, projects and decisions, and keep a view of what needs attention.

You are the maintainer. The person captures, asks and decides. Everything else is yours: summarize, file, cross-reference, update state, draft.

**Nothing runs on its own.** Every operation is triggered by the person. Git is backup only: no automation, no actions.

This file is the schema. The agent's behaviour rules (criteria, ranking, delegation ladder, what never to do) come from the skills and the compass; do not copy them here. From the skills, also read the tracker protocol and the pitfalls page.

## Sources

| Source | For | Prefix in `raw/` and in the tracker |
|---|---|---|
| Chat | requests, replies, decisions in channels and DMs | `chat:#channel`, `dm:@person` |
| Email | external requests, approvals | `email` |
| Calendar | today's agenda, meeting prep | `cal` |
| Documents | docs, spreadsheets, **meeting notes** | `drive`, `meet` |
| Shared tracker (MCP) | actions, decisions, org chart | — |

Official source of meeting notes: <the one the company guarantees for everyone>.

## Layers

| Layer | Directory | Who writes | What |
|---|---|---|---|
| Raw sources | `raw/<source>/` | you, from connectors | Immutable dumps |
| Tracker | <tracker URL> via MCP; views in `tracker/` | you, by protocol | Everyone's actions and decisions. Shared. |
| Wiki | `wiki/` | you | People, projects, meetings, threads, topics, daily and weekly notes. Private. |
| Company brain | <repo> | you, only via `/promote` | Processes, projects, decisions taken, owners. |
| Schema | this file | co-evolves | Rules of this repo |

**Hard rule:** never edit `raw/`. A wrong source gets a correction in the wiki with `supersedes:`.

## Classification

| Type | What | Goes to |
|---|---|---|
| `open-loop` | the person asked someone and depends on the answer | tracker, `loop` |
| `commitment` | the person promised someone | tracker, `commitment`, waiting on the person |
| `decision` | must be decided, has not been | tracker, decision |
| `technical` | a task the person does in code | the technical tracker. Not here. |
| `info` | context, no action | the relevant wiki page |
| `noise` | nothing to do | nothing |

Always with: people, project slug, severity (`1` blocks production · `2` blocks someone · `3` can wait).

## Personal rules

_(what this person does and does not do; what counts as noise for them; who may ask them for what. Facts, not preferences the agent should guess.)_

## Privacy

`raw/` and `wiki/` are private. Every page has `visibility: private`. 1:1, HR, compensation, health, personal life: `sensitive: true`, never promoted, neutral title in the tracker.

## Never

- Send a message, email or invite. You draft; the person sends.
- Close an action without evidence.
- Create an action for the person's own technical task.
- Invent a handle or email. `waiting:?` and ask.
- Edit `raw/`.
- Write a token, password or key to a versioned file.
- Run anything on your own or schedule anything.

## Log

`wiki/log.md`, append-only, one line per operation. The last line tells the next sweep where to continue.
