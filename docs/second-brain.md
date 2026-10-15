# Protocol 1: The Second Brain

One private git repository per person. The agent maintains it; the person reads it (any markdown wiki viewer works) and almost never edits it.

## Layers Inside the Repo

| Directory | Who writes | What it is | Mutable |
|---|---|---|---|
| `raw/<source>/` | the agent, from connectors | Dumps of threads, emails, meeting notes, documents | **No.** Never edited. |
| `wiki/` | the agent | People, projects, meetings, threads, topics, daily and weekly notes | Yes, by rules below |
| `tracker/` | regenerated from the shared tracker | `open.md`, `decisions.md`, `closed.md` | Only by regeneration |
| schema file | co-evolves with the person | Rules and conventions of this repo, personal rules, what the agent must never do for this person | Yes, with care |

The schema file is the contract. It states the sources, the layers, the classification, personal rules ("I do not review pull requests unless X asks", "invoices are finance's, not mine, unless overdue") and the never-list. The behaviour rules of the agent (priority criteria, delegation ladder) are **not** copied there; they come from the compass and the skills. Template in [`templates/second-brain-schema.md`](../templates/second-brain-schema.md).

## Sources

Connectors are per person and live in the person's agent account, not in the repo. The minimum set:

| Source | For | Prefix used in `raw/` and in the tracker |
|---|---|---|
| Chat (channels and DMs) | requests, replies, decisions in the open | `chat:#channel`, `dm:@person` |
| Email | external requests, approvals, what arrives from outside | `email` |
| Calendar | today's agenda, who meets whom, meeting prep | `cal` |
| Documents | docs, spreadsheets, **meeting notes** | `drive`, `meet` |
| Shared tracker (via MCP) | actions, decisions, org chart, adoption | — |

Pick **one official source of meeting notes** that the company guarantees for everyone (an auto-recorder that drops notes into shared documents). A personal recorder may complement it, marked as such in `sources`; never ask anyone to install or pay for one.

Technical task trackers (issues, boards) are auxiliary: tasks live there, not here. A *project* can have a wiki page with the link; the page tracks the project's state and dependencies, never duplicates issues.

## Classification

Every item that comes in (a message, an email, a passage of meeting notes) gets **one** type:

| Type | What it is | Goes to |
|---|---|---|
| `open-loop` | the person asked someone for something and depends on the answer | tracker, action of kind `loop` |
| `commitment` | the person promised something to someone | tracker, action of kind `commitment`, waiting on the person |
| `decision` | something must be decided and has not been | tracker, decision |
| `technical` | a task the person will do themselves in code | the technical tracker (suggest an issue). Never here. |
| `info` | useful context, no action | the relevant wiki page |
| `noise` | nothing to do | nothing |

And always: the **people** involved, the **project** (slug from the company brain, if any), and **severity or priority**.

Severity: `1` blocks production or a release · `2` blocks someone's work · `3` can wait. SLA without a chase: sev1 one day, sev2 three days, sev3 seven days.

## Discuss Before Writing

In sweeps and ingests, the agent lists what it understood and what it intends to create or update, then waits for the ok. The exceptions are derived files, written directly: daily notes, weekly notes, and the operations log.

## Writing Conventions

- Frontmatter on every page: `title`, `created`, `updated`, `tags`, `sources`, `visibility`.
- Wikilinks everywhere. The graph depends on it.
- ISO dates.
- **A page about a person holds no opinion.** It holds what they touch, what tends to block with them, typical response time, open items. Facts, not judgment.
- **Facts only with a source.** Every statement of fact points to its source (`sources`, a wikilink, a permalink). What the agent deduced is marked `(inferred)` or phrased as "to confirm". An unverified fact written as certain contaminates everything that reads it later; see [pitfalls.md](pitfalls.md).
- **Corrections keep the old text** struck through with a `supersedes:` note. Nothing is deleted.
- File names: `YYYY-MM-DD-<slug>.md` for meetings, threads and daily notes; `<slug>.md` for people, projects and topics.

## Operations Log

`wiki/log.md` is append-only, one line per operation:

```
## [2026-09-18] sweep | chat+email since 09-15: 14 items, 3 new actions, 1 closed, 1 decision
```

The last line tells the next sweep where to continue.

## Backup

Git is backup, nothing else: no actions, no automation, no hooks. Every skill that writes ends by committing and pushing (or by the company's sync mechanism). Use **one** mode per repo; mixing a push-based backup with a server-side sync produced divergent histories with identical trees ([pitfalls.md](pitfalls.md)).
