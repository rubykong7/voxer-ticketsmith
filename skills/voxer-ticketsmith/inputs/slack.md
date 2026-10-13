# Input: Slack

Tools: the Slack MCP, read tools only (`slack_search_public_and_private`, `slack_read_thread`, `slack_read_channel`, `slack_read_user_profile`). Never send.

Cursor: `cursors.slack`, a unix timestamp. First run: the last 24 hours.

Read only these, newer than the cursor (pass it as `after`, `sort: "timestamp"`, page to the end). `OWNER` is the owner's user id from the search tool's description. A search with no keywords and only `channel_types` returns nothing: do not use it.

1. DMs, group DMs and threads the owner is in: `filters: "with:<@OWNER>"`, no keywords.
2. Mentions: `keywords: ["<@OWNER>"]`.
3. Channels named in config `slack_channels`, if any: `filters: "in:<#CHANNEL>"`.

Skip bot messages unless they quote a ticket the owner works on. The owner's own messages are facts for `tasks/<master>.md`, never items. For each message keep: channel, author, time, text, permalink. A reply item for Slack always has `target: {"type": "copy"}`.
