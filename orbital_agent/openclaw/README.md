# OpenClaw configuration for Orbital

This folder holds the OpenClaw agent configuration. The exact layout depends on
what OpenClaw expects on disk — the published docs are inconsistent (some
sources say `SOUL.md` + `config/*.yaml`, others mention `~/.openclaw/openclaw.json`).
Reconcile against your installed version before relying on this.

## Files

- `SOUL.md` — the agent's identity (role, rules, tools, output format).
  Copy or symlink this into the location OpenClaw expects for the `orbital`
  agent on your Spark install.

## Files to add after verifying the install (TODO)

- `AGENTS.md` — one-paragraph agent persona (referenced in some OpenClaw guides).
- Model provider config that points OpenClaw at Ollama. Likely either:
  - `config/models.yaml` with an `openai-compatible` provider entry
    (`base_url: http://localhost:11434/v1`, `model: nemotron-3-nano:30b`), or
  - `~/.openclaw/openclaw.json` keys for the same.
- MCP server registration so OpenClaw discovers the `orbital_agent.mcp_server`
  tools. Verify whether OpenClaw's current version supports MCP servers natively
  or whether tools must be exposed as OpenClaw "Skills" instead.

## Verifying your install

Run these commands on the Spark and capture the output — the answers determine
exactly what files belong here:

```
openclaw --version
openclaw --help
openclaw gateway --help
openclaw onboard --help
ls -la ~/.openclaw/
cat ~/.openclaw/openclaw.json 2>/dev/null || echo "no openclaw.json"
```

Bring the output back to the plan and we'll lock the config layout for real.
