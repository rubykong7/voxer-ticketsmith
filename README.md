# voxer-ticketsmith

A Claude Code skill that keeps your Linear tickets organized from the conversations around them.

- Reads Linear, Slack and Voxer through the MCP connections your Claude Code already has. A source you haven't connected is skipped.
- A calm local dashboard. The home page says what needs you and what is in progress, nothing else. Each ticket opens as its own page: goal, sub-issue tree, drafts to edit and post, and a thread to tell the agent what to change.
- Syncs every hour. Ignores chatter; only messages that change a goal, a decision or ask you something become items.
- Linear keeps the goal. The how (steps, decisions, open questions) stays local in `~/.voxer-ticketsmith/tasks/`.
- Nothing is written to Linear until you click Post. Slack and Voxer replies are copy-only.

## Install

```sh
git clone git@github.com:rubykong7/voxer-ticketsmith.git
ln -s "$PWD/voxer-ticketsmith/skills/voxer-ticketsmith" ~/.claude/skills/voxer-ticketsmith
```

Or as a plugin from inside Claude Code: `/plugin marketplace add rubykong7/voxer-ticketsmith`, then `/plugin install voxer-ticketsmith@voxer-ticketsmith`.

Then in Claude Code: `/voxer-ticketsmith dashboard`, or start it yourself:

```sh
python3 voxer-ticketsmith/skills/voxer-ticketsmith/scripts/server.py
```

Open http://127.0.0.1:8790. The first sync starts within a minute.

## Make it yours

Optional files in `~/.voxer-ticketsmith/`:

- `config.toml`: `interval_min`, `model`, `port`, `inputs` (`["slack", "voxer"]`), `slack_channels`, `product_teams`, and `read_tools` / `write_tools` if your MCP servers have different names.
- `style.md`: how your drafts should sound. Start from `skills/voxer-ticketsmith/style.md`. Its `## Never write` list feeds the draft checker.

A new source or task system is one markdown file in `inputs/` or `tasks/` that says which MCP tools to read and how.

A thread post can start a skill of your own: add a `[[commands]]` entry to `config.toml` with `match` (a regex on the post), `skill`, and optionally `tools`, `deny`, `cwd` and `timeout_min`. The run gets the card name and can add items to the ticket page.

## How it runs

The dashboard server (`scripts/server.py`, Python 3.11+ stdlib) runs `claude -p` one at a time: `sync` every interval, `post <item>` when you click Post, `reply <card>` when you send a thread message. Only `post` gets Linear write tools. Each run shows up under Sessions with a resume command.

Drafts are checked by `scripts/check_draft.py`: banned phrases from your style file, em dashes, bold, and a small Simplified Technical English pass (sentences over 25 words, passive voice, wordy phrases). No extra tools.

## Credits

The ticket page's look (one screen of lettered panels, verdict first, a tree and a callout) and the STE draft check borrow their ideas from [answer-me-with-html](https://github.com/QingYunA/answer-me-with-html) by QingYunA (MIT). They are re-done in plain Python here so nothing else needs installing. The per-ticket thread and the headless-session list come from an earlier personal runner.

Self-checks: `python3 scripts/server.py --test` and `python3 scripts/check_draft.py --test`.
