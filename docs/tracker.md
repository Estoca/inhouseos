# Protocol 2: The Shared Tracker

The tracker is the **source** of every person's actions and decisions, and the only one: second brains keep no copy of it, and the agent reads and writes it through the tracker's tools. Every skill that opens, chases, closes or decides follows this protocol; without it, a person's action stays locked in their own repo and no one else's agent can see it.

## Why Shared

Who sees an action: the requester, the person who owes it, the members of its project at the time they look (someone who leaves a project stops seeing its actions, except the ones they are requester or owner of), and leadership (the owner's management chain and the people the company names as such). An action without a project is seen by requester, owner and leadership only. There is no private action. The same rules apply to decisions, with "who decides" in place of "who owes". Sensitive matters enter with a neutral title, for actions and decisions alike; the detail stays in the second brain ([privacy.md](privacy.md)).

## Entities

| Entity | Fields that matter |
|---|---|
| Action | id, kind (`loop` or `commitment`), title, source, requester, `waiting_on` (one person, by email), `asked_at`, `registered_on`, last bump, severity, `due_at`, `waiting_external`, `review_at`, project slug, status, notes, events |
| Decision | id, question, opened at, who decides, deadline, priority (`high`/`medium`/`low`), origin, outcome |
| Project | slug, name, owner, members, weight (mirrored from the compass; not a source), update cadence |
| Suggestion | what the agent offered to do, the rule that produced it, the outcome (accepted, declined, ignored) |
| Adoption | per person: days the daily digest was requested vs. expected working days |

Identity: the tracker identifies people by email. The caller of the API is identified by login, so every write is attributed without configuration.

## Rules

- **Explicit request, named recipient.** Open an action when someone asked a *named* person for something and the answer has not come. A `loop` is opened by the agent of the person who asked; a `commitment` is opened by the agent of the person who promised, with themselves as `waiting_on`. Nobody's agent opens an action that puts a third person as `waiting_on`. Do not open: a conversation resolved on the spot, a diffuse request to a channel, a line in a plan or spreadsheet, or something the agent deduced someone owes. Never put someone as `waiting_on` unless the request was made to them. When in doubt, ask the person before opening.
- **Check for duplicates first.** The tracker refuses a create when a similar open action exists for the same person, and lists the similar ones. Show them; if it is the same request, add a note to the existing one; if not, create with `allow_duplicate` and a title that tells them apart. Never pass `allow_duplicate` blindly.
- **One person per action.** Several people, several actions.
- **One deliverable per action.** A request with distinct deliverables and deadlines is born as several actions, each with its own deadline. Together, a finished part has no way to close.
- **Partial delivery neither closes nor stays.** When evidence covers part of an action: change the title to what is missing, or split it. Either way, record the delivered part as a note with its evidence. Never close the whole item on partial evidence; never leave it untouched, or the next session asks again what was already done.
- **Read the second brain before touching an action.** Notes on the action, the latest daily and weekly pages. The title in the tracker may lag what the person already delivered and the agent already wrote down.
- **SLA counts from registration.** Without a deadline, an action is overdue by its severity's SLA from the latest of last bump or `registered_on`. An old request registered today does not arrive overdue; its age still counts from `asked_at`. Never adjust `asked_at` to dodge the SLA.
- **Waiting on an outsider is not overdue.** When a supplier, customer or platform is what blocks, `waiting_on` stays the internal owner and `waiting_external` names who outside is expected. Set `review_at`. The item leaves the SLA and does not generate chases. Never record a fake bump to reset the clock; mark `waiting_external`. When the ball returns inside, clear it and the SLA restarts.
- **An agreed deadline goes in `due_at`, not in the title.** The severity SLA is the chase cadence; the deadline is the delivery date. The item is overdue only after it, and no chase is drafted before it; the severity cadence resumes after the deadline passes. Do not change severity to fit a date.
- **Reassign is an update, never close and recreate.** Changed who owes, who asked, severity, title, deadline: update. The id stays, every link and mention of it keeps pointing to the same item, and history shows before and after. Close-and-recreate generates a new id, orphans every reference to the old one and records a close that never happened.
- **Email, not handle.** Resolve handles through the chat profile. Never invent. If the agent does not know who someone is, it does not create in the tracker: it notes the item in the day's note with `waiting:?` and asks.
- **Project by slug** from the company brain and the compass. No clear project, no project.
- **Closing requires evidence**: a permalink or a quote of the reply. Disappearing from the radar does not close.
- **Close and decide say what they close.** Every close carries `expect_title_contains`, every decide carries `expect_question_contains`, with a distinctive term from the item. A wrong id with the guard is an error with nothing written; without it, the wrong item closes silently.
- **Project priority is leadership's.** The tracker mirrors the compass; it is not a source.
- **Every cited item carries link and title.** Never just an id: the person does not know what action 19 is.

## Chasing

For every overdue action the agent drafts the chase, ready to paste: short, in the channel's tone, in the thread of the original message. Escalate per bump: first neutral, second with an explicit deadline, third proposes taking it out of chat and resolving it in a meeting. After 30 days the agent proposes closing as stale or escalating, and stops chasing. A stale close is the one close that needs no reply as evidence: the evidence is the person's explicit ok to drop it, recorded as the closing note, and the status is `wontfix`, never `done`.

Only the person sends. The agent records the bump after the person confirms it was sent.

## Suggestions and Their Outcomes

The daily package does not only list; it offers to do. Each offer is recorded as a suggestion with the rule that produced it. The evening close asks for the outcome of each. Over time this gives the one number that says whether the agent is useful: the share of suggestions accepted.

## Citing Items

An item is named by its tracker id with leading zeros, `OL-NNNN` for actions and `D-NNNN` for decisions, never by a local numbering. Whenever the agent mentions an item to the person, the id is a link to it followed by its short title ("can I close [OL-0019](…), reduce the transport tasks?"): a bare number means nothing to the person. The tracker stores people by email; a chat handle is only for reading, and the agent never types an email where a handle goes or a handle into the tracker.

Second brains keep **no copy** of the tracker. Until version 0.31 of the reference implementation each brain held regenerated views (`tracker/open.md`, `decisions.md`, `closed.md`) refreshed by a sync script. They were removed: a view edited by hand invented fields, dropped items and swapped owners ([pitfalls.md](pitfalls.md)), and a view that only a shell can regenerate does not exist in a chat or cloud session. The agent reads the tracker when it needs it, and a wiki page links to an item by its id.

## Without the Tracker

If the API is unreachable, the agent says so in one line and goes on without guessing:

1. **Read.** There is no local copy. The morning package goes out without the tracker part, said in one line. The "still open" list of the last evening close can serve as a reminder, marked with its date and "not checked against the tracker"; it is never presented as the current state.
2. **Write.** What the person approves goes to a `## Para o tracker` ("for the tracker"; the skills write in Portuguese) section of the day's note (`wiki/daily/`), one line per operation with the tool and its fields, so it can be replayed without reinterpretation: `- [ ] tracker_create_action {"title": "...", "waiting_on_email": "...", "sev": 2}`. Chasing or closing an existing item uses its real id; a new item gets no number until it is in the tracker, and is cited by title.
3. **Replay.** The next skill with the tracker available looks for unchecked lines in that section of the last seven daily notes, replays them in order under the same rules (a duplicate goes back to the person, closes and decisions keep their title guard), and turns each line into `- [x] ... → OL-NNNN`, or the error the tracker returned. The replay is noted in the log.

A line still unchecked after a day is a repo-health finding. Nothing is silently lost and nothing is silently local.

## Adoption

The company's agreement: **every person opens the daily package on at least 80% of their working days.** The tracker measures it alone: the person's own digest request records the day as opened. Working days discount holidays and recorded absences. A day without a package gets one neutral question ("no package yesterday; reason?"), once, and the answer is recorded. Leadership sees their reports' numbers, the same numbers each person sees on their own board, and never quotes a number to a person before the person has seen it.
