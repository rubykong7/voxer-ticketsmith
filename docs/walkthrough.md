---
title: voxer-ticketsmith walkthrough
subtitle: From install to your first posted comment, whatever tools you use
---
Linear holds the goal. The skill holds the how, locally, and writes to Linear only when you click Post.

## A What you need
| Tool | Needed? | Why |
|---|---|---|
| Claude Code with a plan | ok required | the agent runs are headless `claude -p` |
| Linear connector in claude.ai | ok required | tickets, comments, Post |
| Python 3.11+ and Node 20+ | ok required | the dashboard server and the diagram renderer |
| Slack connector | warn optional | DMs, mentions and chosen channels become items |
| Voxer connector | warn optional | same for Voxer threads, transcripts included |
| Notion connector | warn optional | read only when a ticket links to a page |
| Cursor or another editor | no not involved | the dashboard is a plain local web page |

## B First run
```sequence
participants: You, Claude Code, Server, Linear
You -> Claude Code: /voxer-ticketsmith dashboard
Claude Code -> Server: start scripts/server.py
Server --> You: http://127.0.0.1:8790
Server -> Linear: sync: issues assigned to me
Linear --> Server: masters, sub-issues, descriptions
Server --> You: home page, within a minute
note Server: repeats every hour in the background
```
Install first: clone the repo and symlink `skills/voxer-ticketsmith` into `~/.claude/skills`, or add it as a plugin. The README has both commands.

## C Home page
```tree
Home
  Needs you | items with a draft or a question, newest first
  New, not sorted yet | tickets that appeared since the last sync; file each as Todo or Backlog
  Ready for review | a branch to look at, or In Review in Linear
  Active | In progress, Blocked, Todo
  Everything else | Triage and Backlog, collapsed
  Done recently | closed in the last 30 days, collapsed; pages and threads stay
```
The lead sentence at the top is the whole status. Each row opens the ticket page; the small Linear link opens Linear. The Todo, Backlog and Tonight buttons change this page only, never Linear.

Tonight marks a ticket `approved` for your own evening commands; this skill never reads it.

## D Ticket page
```tree
Ticket page
  A Where things stand | sub-issues done, next action
  B Goal | one line from the Linear description
  C.. How | diagrams and lists from the ticket's tasks file
  Sub-issues | one line each, colour says done, started, blocked
  Needs you | drafts to edit, questions to answer
  Thread | tell the agent what to change
```
Only the goal and the sub-issue list come from Linear. The rest lives in `~/.voxer-ticketsmith/`.

## E Act on an item
```flow LR
(Item) -> [Edit draft] -> {Where does it go?}
{Where does it go?} -> [Post, two clicks]: Linear comment
{Where does it go?} -> [Copy]: Slack or Voxer
(Item) -> [Done]
[Done] --> [Done with a reason]: never suggested again
```
Post is the only thing that writes to Linear. Slack and Voxer replies are copy-only; you send them yourself.

## F Talk to the agent
Write a plain request in the Thread box and click Send now:
- shorten this draft
- draft a reply to Ben
- draft a sub-issue for the retry case
- add the decision we made in standup
- redraw the flow with the new queue

The answer lands in the thread and the page updates. Nothing reaches Linear from the thread.

## G By tool
| You have | What changes |
|---|---|
| Linear only | ok items come from comments on your tickets; paste a message into the thread to get a draft |
| Slack | ok set `inputs = ["slack"]` and `slack_channels` in config.toml; relevant DMs and mentions become items |
| Voxer | ok add `"voxer"` to `inputs`; it skips untranscribed audio |
| Notion | ok nothing to set; pages are read when a ticket links to them |
| Your own automation | ok a `[[commands]]` entry in config.toml routes a thread keyword to your skill |

## H Make it yours
```kv
config.toml: interval_min, model, port, inputs, slack_channels, product_teams, workspace (your repos: ticket branches show on the page)
style.md: how drafts should sound; its Never write list feeds the checker
tasks/<ticket>.md: the how, as diagrams; the agent keeps it current
your own worker: a [[commands]] entry runs your skill on "work on this"; it reads state.json, tasks and threads, and writes a work item back
```
Both files are optional and live in `~/.voxer-ticketsmith/`. The README section Bring your own worker has the full contract and a cron line for a nightly run over the tickets you marked Tonight.
