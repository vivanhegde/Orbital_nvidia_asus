"""Orbital agent: OpenClaw-orchestrated reasoning loop over Nemotron via Ollama.

This package is the Python sidecar that:
  * polls SQLite for newly screened conjunctions
  * pokes the local OpenClaw daemon with a kickoff message per event
  * subscribes to OpenClaw's event stream and forwards it as SSE to the UI
  * exposes the 11 domain tools to OpenClaw via an MCP server (Feature 2)

The actual reasoning loop runs inside the OpenClaw Node daemon, not here.
"""
