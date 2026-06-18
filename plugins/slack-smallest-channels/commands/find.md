---
description: Find the N smallest Slack channels I'm in that contain all the given users
argument-hint: name/email/ID, name/email/ID, ... [n=3]
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/slack_smallest_channels.py:*)
---

Users (comma- or semicolon-separated): $ARGUMENTS

1. Split users on `,`/`;` and trim. A trailing bare integer is the match count `-n N` (default 3).
2. Make one Bash call, quoting each user:
   `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/slack_smallest_channels.py [-n N] "user1" "user2" ...`
3. Relay the output verbatim. Don't re-implement this with MCP tools.

On "could not resolve user": pass that user's email or `U…` ID (use slack_search_users to find it), rerun.
On token/auth failure: run any Slack MCP tool once to refresh auth, rerun.
