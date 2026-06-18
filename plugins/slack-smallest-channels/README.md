# Slack Smallest Channels

Finds the smallest Slack channels you're a member of that contain all the users you name. Useful for picking the most focused channel to reach a specific group of people.

## Requirements

- **macOS** (reads your Slack token from the Claude Code keychain entry).
- The **Slack MCP** connected in your Claude Code. See [Using Claude and Cursor with Slack MCP at Datadog](https://datadoghq.atlassian.net/wiki/x/UIVDfAE).
- If you hit an auth error, run any Slack command once to refresh, then retry.

## Install

```
/plugin marketplace add xlamorlette-datadog/claude-tools
/plugin install slack-smallest-channels@claude-tools
/reload-plugins
```

## Use

Example:
```
/slack-smallest-channels:find Marcel Dupont, john.smith@datadoghq.com
```

- Separate users with commas or semicolons.
- Each user can be a **full name**, an **email**, or a **Slack ID** (`U…`).
- Optional: add a trailing number to change the number of results (default 3): `…, 5`.
