# Protocol 3: The Compass

The direction every agent in the company follows. Two parts: the **constitution** (ranking criteria, delegation ladder, signals, the never-list), which changes rarely and ships with the skills; and the **direction of the period**, a table leadership revises when strategy changes, kept in its own repo so it can change without republishing anything.

Every skill that ranks work reads both before ranking. The tracker mirrors project weights from here; it is not a source.

## 1. Ranking Criteria

The order in which the agent ranks what a person must do today. Ties go to the next criterion.

1. **Production or release blocked** (sev1), overdue. Always first.
2. **A decision past its deadline** that the person owns. A stuck decision blocks more people than a stuck task.
3. **Alignment with the direction of the period**: an item of a heavier project comes first.
4. **How many people wait**: an item that unblocks someone else (sev2) before one only the person waits on.
5. **Age**: oldest first. After 30 days the agent proposes closing or escalating; it does not keep chasing.

SLA without a chase: sev1 one day · sev2 three days · sev3 seven days.

## 2. Delegation Ladder

By kind of action. The level says how far the agent goes alone. It only rises by a published change here.

| Level | The agent | Examples |
|---|---|---|
| 0 | observes and proposes | point out a pattern (no 1:1 in weeks, a recurring meeting with no decision), suggest closing a dead loop |
| 1 | drafts, the person sends | a chase in a thread, a follow-up email, a request for a decision |
| 2 | executes with confirmation | create an issue, open or close an action in the tracker, schedule a 1:1 |
| 3 | executes and reports | write the daily note and the log, back up the repo |

## 3. Direction of the Period

A versioned file in its own repository. Template in [`templates/direction.md`](../templates/direction.md). Fields: `version` (`YYYY-MM-DD.n`), `period_end`, `owner`, `maintainer`. One table:

| Weight | Project or theme | Slug in the tracker | Owner | Why now |
|---|---|---|---|---|

Weight **3** = what the company needs to happen this period; **2** = important, not urgent; **1** = maintenance. A project not in the table has weight 1.

Rules for writing it: pull before editing, bump `version`, add a line to `## History`, commit, push. Never force-push. Never delete a history line. Only leadership (and whoever they name, typically a chief of staff) writes it, by hand or through the `/compass` skill.

If the agent cannot read the direction (no access, no network) it says so and proceeds with weight 1 for every project.

### Work outside the direction

Not everything a company does belongs in the table, and that can be on purpose. Exploratory work owned by a founder or an innovation role can stay outside the direction so it does not compete with execution for the same ranking. Such work is not weight 1 by default; it is simply not ranked by the compass. If it matures into an area commitment, it enters the table, and that is a success signal. State this explicitly in the direction file, or agents will treat it as neglect.

## 4. Management Signals

What the agent observes and points out (level 0), with the threshold that turns it into a signal.

| Signal | Threshold | What the agent does |
|---|---|---|
| Manager without a 1:1 with a report | 21 days | points it out in the manager's morning package and proposes a slot |
| Recurring meeting with no recorded decision | 3 editions in a row | proposes an agenda with the pending decision made explicit |
| Item without reply | past SLA | chase ready; from the third bump, proposes taking it out of chat |
| Company process not followed | 1 occurrence | records a deviation event in the tracker and tells the person |
| Open loop | 30 days | proposes closing as stale or escalating |
| Meeting the person organizes without a pre-read | 2 working days before | drafts the brief as pre-read and the message to circulate it; the person sends |

## 5. Never

For every agent, at every delegation level. Mirrored in the agent platform's managed settings where possible.

- Send a message, an email or an invite without delegation for that kind of action.
- Act in someone else's name.
- Delete data or pages.
- Share `sensitive` content.
- Write a secret to a versioned file, or ask for one in chat.
- Call a service outside the official connectors.

## History

Keep a `## History` section at the end of the constitution file too, one line per version, newest first, with the reason for each change. The reasons are how the next maintainer learns why a criterion exists.
