"""Entrypoint: `python -m orbital_agent`.

Modes:
  --smoke                       Day-0 reachability smoke test
  --investigate <event_id>      Run one full investigation through OpenClaw
  --run                         Long-running sidecar loop (Feature 4)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import httpx

from orbital_agent.config import AgentConfig, load
from orbital_agent.gateway import OpenClawGateway


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _check_ollama(config: AgentConfig) -> tuple[bool, str]:
    """Verify Ollama is running and the configured model is present."""
    url = f"{config.ollama_base_url.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return False, f"Ollama unreachable at {url}: {type(exc).__name__}: {exc}"

    body = resp.json()
    tags = [m.get("name", "") for m in body.get("models", [])]
    wanted = config.ollama_model

    if wanted in tags:
        return True, f"OK — model `{wanted}` is loaded in Ollama"

    # Tag may have a `:latest` or similar suffix; do a prefix match too.
    prefix_matches = [t for t in tags if t.split(":", 1)[0] == wanted.split(":", 1)[0]]
    if prefix_matches:
        return True, (
            f"Configured model `{wanted}` not exact-match; family present as "
            f"{prefix_matches}. Update ORBITAL_MODEL or pull the exact tag."
        )

    return False, (
        f"Ollama is up but `{wanted}` is not pulled. Models present: {tags}. "
        f"Pull with: `ollama pull {wanted}`"
    )


async def _check_openclaw(config: AgentConfig) -> tuple[bool, str]:
    gateway = OpenClawGateway(config)
    health = await gateway.health_check()
    return health.reachable, health.detail


async def cmd_smoke(config: AgentConfig) -> int:
    """Day-0 integration smoke test.

    Implemented today:
      * Ollama is reachable and has the configured Nemotron model pulled
      * OpenClaw gateway is reachable on the configured URL

    Not yet implemented (blocked on OpenClaw protocol verification — see
    gateway.subscribe_events docstring):
      * Throwaway in-process MCP server with `echo` tool
      * Send kickoff, observe tool call, observe final assistant message
    """
    log = logging.getLogger("orbital_agent.smoke")

    ok_ollama, msg_ollama = await _check_ollama(config)
    print(f"[{'PASS' if ok_ollama else 'FAIL'}] Ollama: {msg_ollama}")

    ok_openclaw, msg_openclaw = await _check_openclaw(config)
    print(f"[{'PASS' if ok_openclaw else 'FAIL'}] OpenClaw gateway: {msg_openclaw}")

    if not (ok_ollama and ok_openclaw):
        print()
        print("Smoke test FAILED. Fix the failing checks above before continuing.")
        return 1

    print()
    print("Smoke test PARTIAL PASS — reachability OK.")
    print("Next: verify OpenClaw's MCP support and event-stream protocol on this")
    print("machine, then implement gateway.subscribe_events() and the throwaway-")
    print("MCP round-trip portion of the test. See gateway.py docstring.")
    log.info("Ollama=%s, OpenClaw=%s", ok_ollama, ok_openclaw)
    return 0


async def cmd_run(config: AgentConfig) -> int:
    print("--run is not implemented yet — Feature 4 (runner) builds this loop.")
    return 2


def cmd_investigate(config: AgentConfig, event_id: str) -> int:
    """Run one full investigation against the orbital agent."""
    from orbital_agent.kickoff import send_kickoff_for_event, summarize

    log = logging.getLogger("orbital_agent.investigate")
    log.info("Starting investigation for event_id=%s", event_id)
    try:
        result = send_kickoff_for_event(event_id, config=config)
    except (ValueError, RuntimeError) as exc:
        print(f"[FAIL] {exc}")
        return 1

    print(summarize(result))
    return 0 if result.verdict_written else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orbital_agent", description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--smoke", action="store_true", help="Day-0 reachability smoke test")
    mode.add_argument("--run", action="store_true", help="Run the agent sidecar loop")
    mode.add_argument(
        "--investigate",
        metavar="EVENT_ID",
        help="Run one full investigation for the given conjunction event ID",
    )
    args = parser.parse_args(argv)

    config = load()
    _setup_logging(config.log_level)

    if args.smoke:
        return asyncio.run(cmd_smoke(config))
    if args.run:
        return asyncio.run(cmd_run(config))
    if args.investigate:
        return cmd_investigate(config, args.investigate)
    return 2


if __name__ == "__main__":
    sys.exit(main())
