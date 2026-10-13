# Task system: Linear

Tools: the Linear MCP (`list_issues`, `get_issue`, `list_comments`, `get_user`; `save_comment` and `save_issue` only in `post`).

## Build `masters`

1. `list_issues` with `assignee: "me"`, `limit: 100`, fields `id, title, url, status, statusType, parentId, updatedAt, assignee, team`. No `updatedAt` filter: the whole list, every sync, so a ticket closed or assigned since last time moves or appears.
   - Done issues (`statusType` `completed`, `canceled` or `duplicate`) stay in `masters` when their `updatedAt` is within 30 days of `Now`; drop older ones. The dashboard files them under Done recently and their pages keep working. Keep their stored `goal`, `subs` and `next` as they were; never spend a `get_issue` on a done master.
2. An issue with a `parentId` belongs to that parent: the parent is the master. An issue with no parent is its own master.
   - Carry `new` and `sorted` over from the stored master. A master that is not in the stored `masters` gets `new: true`, unless there was no stored state (first sync). Drop `sorted` when the status changed in Linear since the last sync: Linear now says where it goes.
3. For each master: `list_issues` with `parentId: <master>` (same fields) for its subs, all assignees. `mine` is true when the sub is assigned to the owner.
4. `get_issue` with `includeRelations: true` for every master whose stored `goal` is empty, and for every master or sub whose `updatedAt` moved. At most 10 per sync, started and todo first; the rest catch up on later syncs. A master with an empty `goal` is unread even when nothing changed in Linear.
   - `goal`: the end goal from the description in one line.
   - `product`: the related issue whose team key is in config `product_teams` (default `PROD`).
   - `blockedBy` on subs: from `blocks` relations only.
5. `next`: the first open sub that is not blocked, or the first open Step in `tasks/<master>.md`. Empty for done masters.
6. New comments since the stored `updatedAt`: `list_comments` on the changed issue. Comments by others go through the relevance check.

## Ticket shape (for `change` items you draft)

- Two levels only: master, then sub-issues. A sub-issue that needs its own children becomes a new master.
- A master links to its product ticket with `relatedTo`, never as its sub-issue.
- Between siblings, only `blocks` / `blockedBy`. Never add `relatedTo` between engineering tickets.
- Description: the end goal in 1-3 sentences, then `Done when:` as a short list. Under ~80 words. Reasons only where they are not obvious.
- Never in a description: status, branch names, "pushed", "local", dated updates, methodology essays.
- Comments: at most 3 lines.
- Only propose `save_issue` edits on issues the owner is assigned to or masters they own. On anything else, propose a comment.
