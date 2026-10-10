# Input: Voxer

Tools: the Voxer MCP (`list_threads`, `list_recent_messages`, `get_message`, `search_messages`). Read-only.

Cursor: `cursors.voxer`, an ISO time with timezone. First run: the last 24 hours.

1. `list_threads` with `since: <cursor>`; page until `nextCursor` is absent.
2. For each thread, `list_recent_messages` and keep messages newer than the cursor that the owner did not send.
3. Audio messages carry their transcript in `body`. `body: null` with `hasAudio: true` means not transcribed yet: skip it and do not move the cursor past it.

For each message keep: thread subject, author, time, text. A reply item for Voxer always has `target: {"type": "copy"}`.
