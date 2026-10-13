---
title: ticketsmith, how it works
subtitle: What runs on its own, what waits for a click, where your own agent fits
---
Linear holds the goal. The dashboard holds the how, locally. Nothing reaches Linear, Slack or Voxer until you click Post. Your own agent works the tickets you name or mark Tonight.

## A The loop
```flow LR
(Sync, hourly or button) -> [Local check]: branches per ticket
[Local check] -> [Linear]: all my issues, 30 days of done
[Linear] -> [Slack + Voxer]: newer than cursors
[Slack + Voxer] -> {Changes a goal, decision, or asks me?}
{Changes a goal, decision, or asks me?} -> [Needs you item]: yes
{Changes a goal, decision, or asks me?} --> [Ignored list]: chat, FYI
[Needs you item] -> [You: Edit, Post, Copy, Done]
[You: Edit, Post, Copy, Done] -> [Linear]: Post only
```
Sync is one headless run with read tools only. The dashboard shows your clicks at once and the next run applies them.

## B One sync, in order
```sequence
participants: Server, Claude, Linear, Slack, Voxer, Files
Server -> Files: local.json, branches named after a ticket
Server -> Claude: sync, with Now
Claude -> Files: apply inbox clicks (edit, resolve, sort, approve)
Claude -> Linear: list my issues, full list
Linear --> Claude: masters, subs, done in 30 days
Claude -> Linear: read changed descriptions and comments
Claude -> Slack: with:me, mentions, after cursor
Claude -> Voxer: threads since cursor
Claude -> Files: state.json, tasks/<ticket>.md, cursors
note Claude: what you wrote yourself (a Linear comment, a DM) becomes steps, decisions and next in the tasks file; it never becomes a Needs-you item, since you cannot owe yourself an answer
```

## C Home page
```tree
Home
  Needs you | drafts and questions, newest first
  New, not sorted yet | appeared since last sync; Todo or Backlog buttons file it
  Ready for review | a work item exists, or In Review in Linear
  Active | In progress, Blocked, Todo
  Everything else | Triage and Backlog, collapsed
  Done recently | 30 days, collapsed, pages still work
```
Each row: status, chips for blocked, tonight and local branch count, sub-issue progress, next step.

## D Ticket page
```tree
Ticket page
  Tonight button | puts the ticket in a work queue for your agent to pick up later
  A Where things stand | next step, open items, local branches with sha and pushed
  B Goal | one line from Linear
  C.. How | the tasks file as panels: diagram, steps, decisions, questions
  Sub-issues | one line each
  Needs you | drafts to edit and post, questions to answer
  Thread | talk to the agent; work on this starts your agent
```

## E What a click does
| Click | Writes where | Reaches outside? |
|---|---|---|
| Edit draft, Save | inbox.jsonl, applied next sync | no never |
| Post, twice | Linear comment or issue | ok Linear, this only |
| Copy | clipboard | no you send it |
| Done, Done with reason | item closed, reason remembered | no never |
| Todo, Backlog | master sorted locally | no Linear unchanged |
| Tonight | master queued locally for your agent | no Linear unchanged |
| Thread: plain text | reply run edits drafts and tasks file | no never |
| Thread: work on this, plan this | your agent runs | no no push, no PR |

## F Your agent, on work on this
```flow
(Thread post, or a scheduled curl on the inbox card) -> [commands entry in config.toml]: match, skill, tools, deny
[commands entry in config.toml] -> [Your skill, headless]: card name
[Your skill, headless] -> [Read state.json, tasks, threads]: approved = the Tonight queue
[Read state.json, tasks, threads] -> [Work in your own worktree]
[Work in your own worktree] -> [Thread post per phase]: progress on the ticket page
[Thread post per phase] -> [Work item + page + tasks file]: ticket moves to Ready for review
```
The skill is yours: a Claude Code skill, or a wrapper around any CLI agent. The README section Bring your own worker has the contract and the cron line.

## G By tool, and what to type
| You have | What changes |
|---|---|
| Linear only | ok items come from comments on your tickets; paste a message into the thread to get a draft |
| Slack | ok DMs, mentions and your threads become items; `slack_channels` in config.toml adds channels |
| Voxer | ok same for Voxer threads, transcripts included; untranscribed audio is skipped |
| Notion | ok nothing to set; pages are read when a ticket links to them |
| Your own agent | ok a `[[commands]]` entry in config.toml routes a thread keyword to your skill |

Thread requests that work as typed: shorten this draft, draft a reply to Ben, draft a sub-issue for the retry case, add the decision we made in standup, redraw the flow with the new queue.

## H Files, all in ~/.voxer-ticketsmith
```kv
state.json: masters, items, cursors; Claude is the only writer
inbox.jsonl: your clicks, one line each; the server is the only writer
local.json: branches per ticket; the server writes it before each sync
tasks/<ticket>.md: steps, decisions, questions, diagrams; shown as How panels
threads/<ticket>.md: your posts and the agent's, one per phase
pages/: your agent's report pages
config.toml: workspace, inputs, slack_channels, [[commands]] for your agent
```

## I Never
```callout warn Hard lines
- Only Post writes to Linear. Sync, reply and your agent have no Linear write tools.
- Slack and Voxer are read only. Replies are copy and paste.
- Your agent never pushes, opens a PR or comments. Branches are --no-track.
- Branch names stay local: never in a draft, an item title or Linear.
- Colleagues can point their own agent at the same queue: state.json approved, tasks and threads.
```
