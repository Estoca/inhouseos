# Pitfalls

Things that have already made an agent go wrong, and the rule each one produced. Every skill that writes files or calls an API makes the agent read this page. A new pitfall goes here, not into the skill.

## A versioned file: re-read from disk before editing

The person edits the repo during the session (a wiki editor, another terminal, a manual commit). An edit built from the copy read at the start of the session can overwrite what they changed, or become a silent no-op when the passage it looks for no longer exists.

Before editing the schema file, the tracker views, templates, the person's own page, or any rule file: check `git status` and the file's recent log; re-read from disk; build the edit on that read; after editing, confirm the change is there. A replace that found nothing is not a success. If the person changed the same section, show both versions and ask. Do not choose.

## An inference written as a fact

The agent wrote, in a second brain and in the company brain, that a colleague had removed a line from a contract before signing. There was no source: it was a deduction from a promise in a thread. The signed contract, read the next day, still had the line. The wrong sentence was already in two pages, one of them shared.

Rule: **facts only with a source.** Before writing a statement of fact, ask where it comes from. If the answer is "because someone said they would", write that ("X said on 09-01 they would adjust before signing; to confirm in the contract"). If it is a deduction, mark it `(inferred)`. Counts double on promotion.

## A tracker view written by hand

The agent wrote the open-actions view by hand: invented a field, lost the bump and the link, left out an item that existed in the tracker and, when "regenerating", replaced a correct owner in the view with a wrong one from the tracker. First rule: views change only by a sync script, and divergence is fixed in the tracker. Later the views were removed altogether: the tracker is the only source, read through its tools, and an item is cited by id, link and title. A copy that can drift will drift.

## A partial delivery noted only in the wiki

The daily close recorded that half of a deliverable had shipped. The action in the tracker bundled both halves, and with no rule for partial delivery it stayed as it was. On Monday the agent asked the person whether the first half was done. Two causes: the action should have been born as two, and the partial delivery should have changed the title. Both are now rules in the tracker protocol.

## The wrong id closes the wrong item, silently

The agent meant to decide decision 5 and called decision 6. The tracker recorded an unrelated outcome and answered 200. Every close and decide now carries a guard (`expect_title_contains`, `expect_question_contains`) with a distinctive term; a wrong id with the guard is an error with nothing written. If it happens anyway, reopen; never recreate.

## The UI is not the source of the loaded version

The plugin version the agent platform's UI shows is the account's. The one the agent executes is the one materialized on disk, and it changes only when the application is fully quit; reloading plugins or restarting the session is not enough. The agent spent three rounds and two wrong diagnoses before noticing it still ran the old version. Check the loaded version on disk before concluding a fix did not ship. A new MCP tool appearing does not prove the plugin came with it; and in an open session the client adds new tools but keeps the old schema of existing ones. A changed schema needs a new session.

## A parent team includes its children's members

On GitHub, listing a team's members includes members of child teams. Parent and child can return the same list, which says nothing about where the person is a direct member. The agent gave two wrong explanations in a row for "why am I in this team". Read the `inherited` field per member; the membership endpoint does not help (it also counts children); walk the child teams until `inherited: false`. Never state the cause before having one of those.

**204 is not confirmation.** A delete returns 204 even when there was nothing to delete. Every write to any API: read the state afterwards, and only then say it was done.

## Two backup modes on one repo

A person's repo diverged from the server: 24 local commits against 20 remote, with the **same tree** and different hashes. Cause: a server-side sync (which creates commits on the server) alternated with manual push and rebase. The rebase then aborted on append-only files. One mode per repo. If the content is equal, align the references and move on; do not rebase.

## Long paths on Windows

A restore failed on Windows: the agent's session folder plus the file names under `raw/` and `wiki/` passed 260 characters, and `git add` said `Filename too long`. A `|| true` in the restore script hid the failure, so the commit never happened and the next step ran without a `HEAD`. Set `core.longpaths` before adding, and stop on the first error.

## Opening actions nobody asked for

In the first days of rollout, one person's agent registered items as owed by a colleague who had never been asked. The colleague spent time undoing them. The agent of the *requester* is the one that opens an action, and only when the request was made to a named person. Direct conversation resolved on the spot does not become a card. Two agents registering the same request also produced duplicates, which is why the tracker now refuses a similar open action for the same person.

## Five sensitive items with the same neutral title

Neutral titles for sensitive actions were all identical, and neither the owner nor the duplicate check could tell them apart. Neutral, but unique: area, date, counter.
