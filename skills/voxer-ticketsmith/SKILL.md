---
name: voxer-ticketsmith
description: Keeps your Linear tickets organized from the conversations around them. Reads Linear, Slack and Voxer through your MCP connections, keeps one card per master ticket on a local dashboard with progress, Needs-you items and draft replies, and writes to Linear only when you click. Use for "/voxer-ticketsmith", "ticketsmith", "open my ticket dashboard", "sync my tickets", "what needs me", or when the dashboard runs a command (sync, post <item>, reply <card>).
---

# voxer-ticketsmith

Linear holds the goal. This skill holds the how, locally, and keeps the two in step.

- Home: `$TICKETSMITH_HOME`, default `~/.voxer-ticketsmith`. Every file below is relative to it.
- Skill dir: the folder of this file. Scripts are in `scripts/`.
- Commands: `dashboard`, `sync`, `post <item-id>`, `reply <card>`. The dashboard server runs the last three for you as `claude -p`; you can also run them in a session.

## Files

| File | Written by | What |
|---|---|---|
| `config.toml` | owner | optional; keys in `scripts/server.py` DEFAULTS (`inputs`, `slack_channels`, `product_teams`, `model`, `interval_min`, `port`) |
| `style.md` | owner | optional; overrides the skill's `style.md` for drafts |
| `state.json` | you (Claude) only | everything the dashboard shows; schema below |
| `inbox.jsonl` | dashboard only | owner clicks, one JSON per line: `{"at","item","action","text"}`, action is `edit`, `post`, `resolve`, `reject` or `answer` |
| `inbox.done.jsonl` | you | inbox lines you applied, appended in order |
| `threads/<card>.md` | both (append only) | owner and agent posts: `## you · <time>` / `## agent · <time>` then the text |
| `tasks/<master>.md` | you | the how for one master, as an answer-me-with-html draft (format below); the dashboard renders it as a sheet of diagrams |
| `run.lock` | whoever runs | `{"name","started"}` while a command runs |

`<card>` is a master identifier (`ENG-8692`) or `inbox` for items with no master.

### state.json

```json
{
  "synced_at": "ISO time of the last finished sync",
  "me": "your Linear display name",
  "cursors": {"linear": "ISO", "slack": "unix ts", "voxer": "ISO"},
  "masters": [{
    "id": "ENG-8692", "title": "", "url": "", "status": "In Progress", "statusType": "started",
    "goal": "the end goal in one line, from the Linear description",
    "product": {"id": "PROD-13", "url": ""},
    "subs": [{"id": "", "title": "", "url": "", "status": "", "statusType": "started", "assignee": "", "mine": true, "blockedBy": ["ENG-1"]}],
    "next": "the next action in one line",
    "updatedAt": "newest Linear updatedAt of the master and its subs at this sync"
  }],
  "items": [{
    "id": "i-<8 hex>", "master": "ENG-8692 or null", "kind": "reply | question | change | drift | unrouted",
    "title": "one line", "why": "one line: why it needs the owner",
    "source": {"label": "Slack #eng · Patrick", "url": ""}, "quote": "the message it is about, max 300 chars",
    "draft": "text to send, or the new description for a change; null if none",
    "options": ["for questions: 2-3 suggested answers"],
    "target": {"type": "linear_comment", "issue": "ENG-8692", "parentId": "comment id to reply under, optional"},
    "details": {"optional label": "text, shown as a table"}, "command": "optional one line the owner can copy",
    "page": "optional file name in pages/ (letters, digits, . _ -, ends .html); the dashboard links it as the item's explain page",
    "status": "open | posted | resolved | rejected | failed", "result": "posted URL or error",
    "created": "ISO"
  }],
  "ignored_day": "YYYY-MM-DD", "ignored": [{"source": "", "snippet": "", "url": ""}],
  "rejected": ["one line per suggestion the owner rejected, with their reason"]
}
```

`kind` is free text; the four above are the ones sync makes. Custom thread commands (config `[[commands]]`: `match` regex on the owner's post, `skill`, `tools`, `deny`, `cwd`, `timeout_min`) run their own skill with the card name and may add items of their own kind.

`target.type` is `linear_comment`, `linear_issue` (`{"type":"linear_issue","id":"ENG-1 or null to create","fields":{save_issue args except description}}`; the description is `draft`), or `copy` (Slack and Voxer replies: the owner copies and sends them).

Write `state.json` whole with the Write tool. Keep every field you did not change. Keep items that are not `open` for 2 days, then drop them.

### tasks/<master>.md

An answer-me-with-html draft: frontmatter, then `## ` panels. The dashboard renders it with `scripts/am.mjs` (vendored, MIT) into `pages/<master>.html` and shows it in panel C. Keep these panels, in this order, and add diagram panels where a picture says it better than a list:

```markdown
---
title: ENG-8692 · media as reference links
---
## A How it works
```flow
client -> broker: GET /exports/<id>/media/<file>?tk
broker -> {token valid?}
{token valid?} -> GCS: 302 to 5-minute signed URL
{token valid?} --> client: 401
```
One or two sentences under the diagram: what the picture does not say.

## B Steps
1. [x] read the export job
2. add the broker route

## C Decisions
- 302 to signed URLs, no proxying (2026-10-10, not published to Linear)

## D Open questions
- Do media links share the export expiry? (asked of Patrick)

## E Sources
- threads/ENG-8692.md
```

Rules: in `flow`, the bracket text is the node's identity, so name a node once and write it the same way every time (`[Export job]`, never `[Export job | path]` on one line and `[Export job]` on another); file paths go in the text under the diagram. One diagram panel at least (`flow` for what talks to what, `sequence` for messages over time, `tree` for files or pieces; mark changes with `+ `, `- `, `~ `). Only things you read in code or notes; never invent a box. `node scripts/am.mjs help flow` (or `tree`, `sequence`) shows the syntax; `node scripts/am.mjs lint <file>` checks the text. Panel letters are optional. Lists stay short; the diagram carries the structure.

## Every command starts like this

The prompt gives you `Now`. Use it for every timestamp. You have no clock; never guess a time.

1. If `run.lock` exists and is younger than 30 minutes, stop and say a run is in progress. Otherwise write it (`{"name": "<command>", "started": "<now>"}`); delete it when you finish, also on failure.
2. Read `config.toml` (if any), `state.json` (if any) and `inbox.jsonl` (if any).
3. Apply the inbox in order:
   - `edit`: set the item's `draft` to `text`.
   - `resolve` / `reject`: set `status`. For `reject`, add a line to `rejected`: what was suggested and the owner's reason (`text`). Never suggest it again.
   - `answer`: the owner answered a question item with `text`. Write it as a decision in `tasks/<master>.md`. If Product or someone else needs the answer, add a `reply` item with a draft that says it. Resolve the question.
   - `post`: leave it for the `post` command (the dashboard queues one per click).
   Then append the applied lines to `inbox.done.jsonl` and remove them from `inbox.jsonl`. Leave `post` lines for the `post` command.

## sync

Run hourly by the dashboard. Read-only outside the home folder. No Bash.

1. Linear: follow `tasks/linear.md` to rebuild `masters` from the owner's open issues. For each master or sub whose `updatedAt` is newer than stored, read what changed (description, status, new comments).
2. Sync rules between Linear and `tasks/<master>.md`:
   - Only Linear changed (someone else, or the owner by hand): Linear wins. Check the Steps in `tasks/<master>.md`. If they no longer fit the goal, add a `drift` item that says which step and why. Never edit Linear for this.
   - Only local changed (a decision in `tasks/<master>.md` that changes the goal or structure and is not marked published): add a `change` item with the exact `linear_issue` edit or a `linear_comment` that explains it.
   - Both changed: add a `drift` item that shows both sides and ask the owner.
3. Inputs: for each name in config `inputs` (default `slack`, `voxer`), follow `inputs/<name>.md` if you have its MCP tools; skip it silently if not. Read only messages newer than its cursor. Then judge each message (below). New Linear comments from others on the owner's masters and subs go through the same judgment.
4. Relevance. Compare each message with the active masters (title and goal). It is relevant only if it changes a goal or scope, makes or reverses a decision, adds a requirement or bug, asks the owner to do or answer something, blocks or unblocks work, or sets a deadline.
   - Relevant and clear: add a `reply` item (with a draft) when it asks the owner something; add a `change` item when it changes a goal, scope or structure; otherwise add the fact to `tasks/<master>.md` and add no item.
   - Mentions an active master but you can't tell what changed: add a `question` item.
   - Relevant to work that has no master yet: add an `unrouted` item with `master: null` and, if it is real work, a `change` item that drafts the new ticket.
   - Everything else (thanks, chat, FYI, other projects): append to `ignored` (reset the list when `ignored_day` is not today). No item.
   - Before adding an item, check `rejected` and open items. Never add the same suggestion twice.
5. Drafts: write every draft per the skill's `style.md` (or the home `style.md` if it exists): no phrase from its `## Never write` list, no em dash, no bold, sentences under 25 words, active voice. The dashboard runs `scripts/check_draft.py` on each draft and shows what it flags.
6. Set `cursors` to the newest message time you read per source (or leave a cursor as it was when that source had nothing new), `synced_at` to the `Now` given in the prompt, write `state.json`.
7. Finish with 1-3 lines: what changed, how many items added, any source skipped and why.

## post <item-id>

Run when the owner clicks Post. The only command allowed to write to Linear.

1. Find the last `post` line for this item in `inbox.jsonl`. No such line: stop and write nothing. Its `text` is the final text; use it exactly, do not reword.
2. `linear_comment`: `save_comment` with `issueId` (or `parentId` to reply in a thread) and `body` = the text.
   `linear_issue`: `save_issue` with `fields`, plus `description` = the text when it is not empty, plus `id` when updating.
3. Set the item's `status` to `posted` and `result` to the URL, or `failed` and the error. If a `change` was posted, mark the matching decision in `tasks/<master>.md` as published.
4. Move that `post` line to `inbox.done.jsonl` and write `state.json`.

## reply <card>

Run when the owner posts in a card's thread. Read `threads/<card>.md`, the card's master in `state.json`, its items and `tasks/<card>.md`. Answer the owner's last post:

- Do what they asked inside the home folder: edit a draft, add or drop an item, change steps or decisions. No writes outside the home folder.
- Append your answer as `## agent · <time>` to the thread. Lead with the answer. 2-5 sentences, no preamble, no recap. Say what you changed and how you checked it, and what you did not check. If you are guessing, say so in one line.

## dashboard

Run in a session when the owner asks for the dashboard.

1. `curl -s -m 2 http://127.0.0.1:<port>/api/sig` (port from config, default 8790). If it answers, give the URL.
2. Otherwise start it: `nohup python3 <skill>/scripts/server.py >> ~/.voxer-ticketsmith/server.log 2>&1 &`, wait 2 seconds, check again, and give the URL. The server runs the first sync itself when `state.json` is missing or older than `interval_min`.

## Never

- Write to Linear outside `post`. Post to Slack or Voxer at all: those drafts are `copy` targets.
- Edit tickets the owner is not assigned to and does not own as master. On others' tickets, only comments, and only through `post`.
- Read Notion pages, transcripts or meeting notes unless a ticket links to them or the owner gave them to you.
- Store a ticket description in `tasks/`. Linear keeps the goal; `tasks/` keeps steps, decisions, questions and sources.
