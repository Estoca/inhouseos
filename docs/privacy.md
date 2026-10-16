# Protocol 4: Privacy and Promotion

Three circles: the person's, the tracker's, the company's. Content moves outward only by explicit rules, never by default.

## The Person's Circle

`raw/` and `wiki/` are private to the person. Every page carries `visibility: private` in its frontmatter. Nobody else's agent reads them, and no colleague can open the repo: it is a private repository with the person as its only owner.

**Private from colleagues, a policy towards the operator.** Whoever operates the git host can read any repository on it: a site administrator account, anyone with a shell on the server, anyone holding a backup of its disk, and the service account that writes the backups. No git host setting removes that. What the company does instead: it publishes who those operators are and keeps them few; it keeps the host's audit log on; it encrypts the server disk and the backups; and it commits, as policy, to never open a person's repo without that person asking. Client-side encryption of `wiki/` and `raw/` is possible and would make the host blind by construction, at the cost of cloud sessions and of recovery by anyone but the person; it is not part of the protocol today. None of this hides content from the LLM provider the agent runs on, which reads everything the agent reads.

## Sensitive

Content from 1:1s, HR, compensation, health or personal life gets `sensitive: true` and **never** leaves the person's circle. In the tracker it appears with a neutral title that is still unique: area, date of the request and a counter, such as `People: pending item of 10-08 (2 of 5)`. Five actions all called "People pending item (detail in source)" left even their owner unable to tell them apart.

A meeting page is `sensitive` when the meeting was. A mentoring session, a performance conversation, a conversation about someone's departure: the whole page, not just a paragraph.

## The Tracker's Circle

Actions and decisions are shared by design: requester, owner, project members, leadership. What crosses from the second brain is the minimum the action needs: title, who, when, severity, project, link to the source thread when the thread is itself shared. The agent's notes on an action are visible to everyone who sees the action, so notes about a sensitive action say "delivered part 1" and not what part 1 was.

## The Company's Circle

The company brain holds what is the company's: processes, projects, decisions taken, who owns what. It is written only by **promotion**, one item at a time, from a second brain. Promotion is a skill the person runs; nothing is promoted on a sweep's own initiative, though a skill may say "this looks like a process; promote it?".

Rules of promotion:

- **Decisions need consent.** A decision is promoted with the date and who decided, and only after whoever decided agrees it goes in. The person running the promotion asks; the agent drafts the question.
- **`sensitive` never crosses**, whatever the reason.
- **Facts only with a source**, and this counts double here: the company brain is read by every agent in the company. An inference written as fact there spreads to everyone's package the next morning.
- **The promoted item links back** to nothing private. Sources become permalinks to shared threads or documents. A fact whose only source is private is promoted with its source described, not linked ("decided in the 1:1 of 2026-09-12, confirmed by both"), and the person who promotes it vouches for it; a fact with no describable source is not promoted.
- **Owner, not opinion.** A page about a process says who owns it and what it is, not what anyone thinks of it.

Who can write the company brain is a team on the git host (writers), separate from who can read it (everyone). Automation adds new hires to readers; writers are added by hand. A person who is not a writer promotes the same way: their agent prepares the page and opens a pull request (or hands the draft to a writer named in the compass), and a writer merges it. The `/project` kickoff is a promotion like any other: the project's owner is the one giving consent, and the page is created under their name.

## Agent Memory

The agent's own persistent memory (what it learns about how the person works) is part of the person's circle and follows the same rules. It never holds secrets: credentials live in a local, ignored `.env` the person writes alone.

## Retention and Removal

`raw/` is immutable for the agent, not for the law or for the person. A source that must be removed (a legal request, a message its author withdrew, personal content that should never have been captured) is deleted by the person from `raw/` and from the git history of their own repo; the agent then lists every wiki page, tracker note and promoted item that cited it, so the person can decide what else goes. Actions in the tracker that came from the removed source keep their title and status: they are the company's record of a request, not a copy of the source. The company states a retention period for `raw/` in its compass (none, by default: the person keeps what they keep).

## What the Person Can Always Do

- Read everything their agent wrote about them.
- Mark any page `sensitive` after the fact; the agent then checks whether anything derived from it crossed outward, and reports.
- Delete their own repo. The tracker keeps the actions, because those were never only theirs.
