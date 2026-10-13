# voxer-ticketsmith

A Claude Code skill that watches your Linear tickets and the conversations around them, and keeps a small local dashboard that tells you what needs you.

It reads Linear, Slack and Voxer through the MCP connections you already have in Claude Code. It never writes to any of them on its own. The only way anything reaches Linear is you clicking Post.

## What you get

A local web page at http://127.0.0.1:8790 with two kinds of screen.

The home page says, in one sentence, what needs you today. Below it: items waiting for you, new tickets to sort, tickets ready for review, tickets in progress. Done tickets stay for 30 days in a collapsed section.

Each ticket has its own page: the goal from Linear, the sub-issue tree, the steps and decisions so far, drafts to edit and post, and a thread where you tell the agent what to change.

## Install

You need Claude Code with a plan, the Linear connector in claude.ai, Python 3.11 or newer, and Node 20 or newer. Slack and Voxer connectors are optional.

```sh
git clone git@github.com:rubykong7/voxer-ticketsmith.git
ln -s "$PWD/voxer-ticketsmith/skills/voxer-ticketsmith" ~/.claude/skills/voxer-ticketsmith
```

Or inside Claude Code: `/plugin marketplace add rubykong7/voxer-ticketsmith`, then `/plugin install voxer-ticketsmith@voxer-ticketsmith`.

Then run `/voxer-ticketsmith dashboard` in Claude Code, or start the server yourself:

```sh
python3 voxer-ticketsmith/skills/voxer-ticketsmith/scripts/server.py
```

Open http://127.0.0.1:8790. The first sync starts within a minute and takes about one more.

## How it works

Every hour, or when you click Sync now, one headless Claude run does this, in order:

1. Lists every Linear issue assigned to you, and reads the ones that changed since last time.
2. Reads new Slack DMs, mentions and threads you are in, and new Voxer messages.
3. Keeps only messages that change a goal, make a decision, add a requirement, or ask you something. Chat and FYI go to an ignored list you can see.
4. Turns what it kept into items on your dashboard: a draft reply, a proposed ticket change, or a question for you.
5. Writes what you said yourself, in Linear comments or DMs, into the ticket's local notes as steps and decisions. Your own words never become an item.

Everything it learns lives in `~/.voxer-ticketsmith/`. Linear keeps the goal. The how, meaning steps, decisions, open questions and diagrams, stays local in `tasks/<ticket>.md` and shows on the ticket page.

## What you can click

| Click | What happens |
|---|---|
| Edit a draft | Saved locally, applied on the next sync |
| Post, twice | Writes the comment or issue change to Linear. The only thing that writes to Linear |
| Copy | Copies a Slack or Voxer reply. You paste and send it yourself |
| Done, or Done with a reason | Closes the item. With a reason, the same suggestion is never made again |
| Todo, Backlog | Files a new ticket on the dashboard only. Linear is unchanged |
| Tonight | Queues the ticket for your own agent, if you have one. Linear is unchanged |
| Send in the thread | The agent edits the draft or the notes as you asked. Nothing leaves the machine |

`docs/how-it-works.html` shows all of this on one page. Open it in a browser. Its source is `docs/how-it-works.md`; re-render with `node skills/voxer-ticketsmith/scripts/am.mjs render docs/how-it-works.md -o docs/how-it-works.html --no-open`.

## Settings

All optional, in `~/.voxer-ticketsmith/`:

`config.toml`

| Key | Default | What it does |
|---|---|---|
| `interval_min` | 60 | Minutes between syncs |
| `inputs` | `["slack", "voxer"]` | Sources to read besides Linear. Remove one to skip it |
| `slack_channels` | none | Channel ids to read on top of DMs, mentions and your threads |
| `workspace` | none | A folder of git repos. Branches named after a ticket show on its page |
| `product_teams` | `["PROD"]` | Linear teams whose tickets count as product tickets |
| `model` | `sonnet` | Model for the headless runs |
| `port` | 8790 | Dashboard port |
| `read_tools`, `write_tools` | see `DEFAULTS` in `server.py` | Only if your MCP servers have other names |

`style.md`: how your drafts should sound. Copy `skills/voxer-ticketsmith/style.md` and edit it. Its `## Never write` list feeds the draft checker.

## Bring your own agent

The dashboard is a queue and an inbox. The agent that does the work on a ticket can be anything you run: a Claude Code skill of your own, or a wrapper around any CLI agent. The contract is a few files in `~/.voxer-ticketsmith/`.

Your agent reads:

- `state.json`: the list `masters`. Each has `goal`, `next`, `subs`, and `approved` when you clicked Tonight. The queue is every master with `approved` set.
- `tasks/<ticket>.md`: steps, decisions, open questions, diagrams.
- `threads/<ticket>.md`: your last post is the brief.

Your agent writes:

- One `work` item into `state.json` `items` (the schema is in the SKILL file), with a `page` in `pages/` if it renders one. The ticket then shows under Ready for review.
- Posts in `threads/<ticket>.md` as `## agent · <time>`, one per phase, so the ticket page shows progress while it runs.
- Ticks and additions in `tasks/<ticket>.md`.
- Never Linear, Slack, Voxer, or a git push.

Start it from a thread post by adding this to `config.toml`:

```toml
[[commands]]
match = "^\\s*(work on (this|it)|work:)"   # a regex on your thread post
skill = "my-worker"                        # your skill
tools = ["Edit", "Write", "Bash", "Agent"]
deny = ["Bash(git push:*)", "Bash(gh:*)"]
cwd = "~/code"
timeout_min = 120
```

Or start it on a schedule. A post on the inbox card starts the same run, so cron or launchd can do it:

```sh
curl -s -X POST -H 'X-Dash: 1' -H 'Content-Type: application/json' \
  -d '{"card":"inbox","text":"work on this: tonight"}' http://127.0.0.1:8790/api/reply
```

Your skill decides what `tonight` means. The obvious reading: every master with `approved`, in the order of `next`.

## Under the hood

`scripts/server.py` is a Python 3.11 standard-library server. It runs `claude -p` one at a time: `sync` every interval, `post <item>` when you click Post, `reply <card>` when you send a thread message. Only `post` gets Linear write tools. Each run is listed under Agent sessions with a resume command.

Drafts go through `scripts/check_draft.py`: banned phrases from your style file, em dashes, bold, and a small Simplified Technical English pass (long sentences, passive voice, wordy phrases).

Self-checks: `python3 scripts/server.py --test` and `python3 scripts/check_draft.py --test`.

To add a new source or task system, write one markdown file in `inputs/` or `tasks/` that says which MCP tools to read and how.

## Credits

The ticket page's look and the STE draft check borrow their ideas from [answer-me-with-html](https://github.com/QingYunA/answer-me-with-html) by QingYunA (MIT), re-done in plain Python here. The How panel renders `tasks/<ticket>.md` with am's single-file CLI, vendored as `scripts/am.mjs` (version in `scripts/AM_UPSTREAM`).
