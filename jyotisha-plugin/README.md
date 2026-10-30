# jyotisha (Claude Code plugin)

A jyotisha advisor for decisions, running against a local database.

All astronomy is computed by Swiss Ephemeris. No model ever produces a
position, a date, or a dasha boundary — and the tools refuse to return claims
the birth time cannot support, rather than leaving that to a prompt.

## Load it

```
claude --plugin-dir ./jyotisha-plugin
```

## Skills

| Skill | For |
| --- | --- |
| `/jyotisha:onboard` | set up a profile: birth data, time confidence, life events |
| `/jyotisha:ask` | ask about a decision and get a timed answer |
| `/jyotisha:journal` | review past advice, record choices and outcomes |

The MCP server is bundled and starts automatically. Its `.mcp.json` holds
this machine's folder paths, so it is not in the repository: `jyotisha.py
install` (or `repair`) writes it. The web app is optional —
it exists for looking at the chart and browsing the journal, and nothing in the
core loop requires it.
