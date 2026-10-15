# Rituals

Each ritual is a skill the agent runs when the person asks. Nothing runs on a schedule. Every ritual starts by reading the person's schema file and the compass, and ends with a backup.

| Skill | When | What it does |
|---|---|---|
| `/setup` | once | Connectors, repo from template, the person's own page, tracker access, first sweep |
| `/morning` | start of day | Agenda, the queue, what arrived, overdue with chases ready, stuck decisions, meeting prep, offers |
| `/close` | end of day | What happened since the morning, bumps sent, closes with evidence, outcomes of the day's offers, meetings ingested, what is due tomorrow |
| `/weekly` | end of week | Presence, packages opened, what was done, what stayed open, next week |
| `/sweep` | on request | All sources since the last sweep, classified, with proposed actions and pages |
| `/ingest` | a link or pasted text | One source. Discuss, then write |
| `/meeting` | before or after | Before: context. After: ingest the notes |
| `/project` | kickoff and updates | Project page in the company brain, project in the tracker, update cadence |
| `/promote` | when something is the company's | Process, project, decision or owner to the company brain |
| `/compass` | read or revise | The direction; leadership revises |
| `/lint` | periodically | Health of the repo and of the views |
| `/backup` | end of every skill | Commit and push, or the company's sync |

## The Morning Package

The one ritual that decides adoption. It is read in two minutes and acted on in ten. Sections, in order:

1. **Agenda**: today's meetings, who, with the open items with each participant.
2. **Your queue**: one numbered list of everything that depends on the person today, ranked by the compass criteria. Commitments, decisions they own, chases to send, pull requests asking something of them, new direct requests, meetings to prepare, items others assigned to them, project updates due. Not in the queue: waiting on outsiders, things they only follow, information.
3. **I can do**: up to five offers, lettered, each tied to a queue item. Analysis, a document, an investigation, a tracker operation, an issue, a draft message. Never: deciding for the person, anything only they can approve, credentials, sending anything. Every offer is recorded as a suggestion; the close asks its outcome.
4. **Arrived**: what came in since the last package, classified, with what the agent proposes to create.
5. **Chase**: each overdue action with the message ready to paste, escalated by bump count.
6. **Decide**: decisions the person owns, overdue or due this week.
7. **Prepare**: meetings the person organizes without a pre-read.
8. **Waiting on outsiders**: one line each, with any news.
9. **Repo health**: pages without source, views diverging from the tracker, loops past 30 days.
10. **Package**: the adoption line (days opened of expected), the question about a missed day if any.

The package is written to `wiki/daily/` and the log gets one line.

## The Evening Close

Reads what happened since the morning (chat, email, tracker events), records the bumps the person says they sent, proposes closing what now has evidence, asks the outcome of each morning offer, ingests the day's meetings that have notes and no page (and older ones that were left behind), and shows what is due tomorrow. Writes a `## Close` section into the day's page and backs up.

## Meetings

Before: who attends, what is open with each of them, pending decisions, notes of the previous edition, and a brief the person can circulate as pre-read. After: ingest the official notes into a meeting page, with decisions under `## Decisions` (date, who decided), actions proposed to the tracker, and a line per participant page.

## Chases

Drafted, never sent. Short, in the channel's tone, in the thread of the original. First bump neutral; second with an explicit deadline; third proposes a meeting. Recorded in the tracker only after the person confirms sending.
