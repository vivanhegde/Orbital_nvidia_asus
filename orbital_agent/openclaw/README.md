# OpenClaw configuration for the Orbital agent

OpenClaw discovered: native MCP support (`openclaw mcp set/show/list/serve`)
and a `agents add` command that creates isolated agents with their own
workspace dir. Orbital uses a dedicated agent so the default `main` agent
(coding-agent persona with shell/file-write tools) isn't disturbed and we
don't inherit its tool surface.

## Layout

- `workspace/SOUL.md` — agent identity (role, rules, tools, output format).
  This directory is passed to OpenClaw as the agent's workspace; OpenClaw
  injects any `.md` files inside it into the system prompt at every turn,
  so only put files here that the model should always see.
- `README.md` (this file) — repo-only notes; lives one level above the
  workspace so OpenClaw does not inject it.

OpenClaw will look for these workspace files at runtime — present ones are
injected, missing ones are skipped silently:

| File | Status | Notes |
|---|---|---|
| `SOUL.md` | present | system-prompt identity |
| `AGENTS.md` | omitted | redundant with SOUL.md for our narrow agent |
| `TOOLS.md`, `IDENTITY.md`, `USER.md`, `HEARTBEAT.md`, `BOOTSTRAP.md` | omitted | coding-agent boilerplate we don't need |

## Creating the agent on the Spark

After pulling these files onto the Spark:

```bash
cd ~/Orbital_nvidia_asus
openclaw agents add orbital \
  --workspace "$(pwd)/orbital_agent/openclaw/workspace" \
  --model ollama/nemotron-3-nano:30b \
  --non-interactive \
  --json
```

Verify with:

```bash
openclaw agents list
openclaw agent --agent orbital --json \
  --message "Reply with exactly the word: ready"
```

The reply's `result.payloads[0].text` should be `ready` (give or take
whitespace), `executionTrace.winnerModel` should be `nemotron-3-nano:30b`,
and `systemPromptReport.injectedWorkspaceFiles` should list `SOUL.md` as
present and everything else as missing. That confirms the agent is using
*our* workspace, not the default `main` workspace.

## MCP server registration (Feature 2 — coming next)

Once the MCP server exists at `orbital_agent/mcp_server.py`:

```bash
openclaw mcp set orbital '{
  "command": "python",
  "args": ["-m", "orbital_agent.mcp_server"],
  "cwd": "/home/asus/Orbital_nvidia_asus",
  "transport": "stdio"
}'
openclaw mcp list
```

Final shape verified by checking that the next `openclaw agent --agent orbital`
run lists our 11 tools in `systemPromptReport.tools.entries`.
