# Input: Slack

Tools: the Slack MCP, read tools only (`slack_search_public_and_private`, `slack_read_thread`, `slack_read_channel`, `slack_read_user_profile`). Never send.

Cursor: `cursors.slack`, a unix timestamp. First run: the last 24 hours.

Read only these, newer than the cursor (pass it as `after`):

1. DMs and group DMs to the owner: `channel_types: "im,mpim"`.
2. Messages that mention the owner (their user id is in the search tool's description): filter by the mention.
3. New replies in threads the owner posted in: search `is:thread` with the owner, then `slack_read_thread` for threads with new replies.
4. Channels named in config `slack_channels`, if any.

Skip bot messages unless they quote a ticket the owner works on. For each message keep: channel, author, time, text, permalink. A reply item for Slack always has `target: {"type": "copy"}`.
