"""Thin client for the OpenClaw daemon.

OpenClaw runs as a long-lived Node daemon (default `ws://localhost:18789`).
Its WebSocket protocol is not publicly documented — the official path is to
use one of OpenClaw's first-party clients (e.g. `openclaw-node` on npm). For
day-1 we use the documented REST endpoint `POST /api/message`, which is the
simplest reliable Python entrypoint, and leave streaming as a TODO that needs
verification against an actual OpenClaw install on the Spark.

What works now:
  * health_check() — confirms the gateway is reachable (HTTP GET on the base URL)
  * send_message_rest() — fires a one-shot user turn via REST and returns the
    final assistant text (no streaming events; blocks until the turn ends).

What's stubbed (NotImplementedError, with clear next steps in the docstring):
  * subscribe_events() — the streaming WebSocket event stream that Feature 5
    will fan out as SSE. Needs OpenClaw protocol details we don't have yet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from orbital_agent.config import AgentConfig

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class GatewayHealth:
    reachable: bool
    detail: str


class OpenClawGateway:
    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._headers: dict[str, str] = {}
        if config.openclaw_gateway_token:
            self._headers["Authorization"] = f"Bearer {config.openclaw_gateway_token}"

    async def health_check(self, timeout_s: float = 3.0) -> GatewayHealth:
        """Confirm the OpenClaw daemon is up by hitting the REST root."""
        url = self._config.openclaw_rest_url
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.get(url, headers=self._headers)
            return GatewayHealth(
                reachable=resp.status_code < 500,
                detail=f"HTTP {resp.status_code} from {url}",
            )
        except httpx.HTTPError as exc:
            return GatewayHealth(reachable=False, detail=f"{type(exc).__name__}: {exc}")

    async def send_message_rest(
        self,
        message: str,
        *,
        agent_id: str | None = None,
        session_key: str | None = None,
        timeout_s: float = 120.0,
    ) -> dict:
        """Fire a one-shot user turn via OpenClaw's REST API.

        Returns the raw JSON response from the gateway. Not streaming — use
        this for the smoke test and for testing prompts; production reasoning
        uses subscribe_events() once that's wired.
        """
        url = f"{self._config.openclaw_rest_url.rstrip('/')}/api/message"
        payload: dict[str, object] = {"message": message}
        if agent_id or self._config.openclaw_agent_id:
            payload["agentId"] = agent_id or self._config.openclaw_agent_id
        if session_key:
            payload["sessionKey"] = session_key

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(url, headers=self._headers, json=payload)
        resp.raise_for_status()
        return resp.json()

    async def subscribe_events(self) -> AsyncIterator[dict]:
        """Yield events from OpenClaw's streaming gateway.

        TODO(feature-1-followup): the OpenClaw WebSocket protocol is not
        publicly documented. The Node client (`openclaw-node`) uses a
        challenge-response handshake with OPENCLAW_GATEWAY_TOKEN and streams
        chunks with types {text, tool_use, tool_result, agent_start, agent_end,
        done, error}. Pick one of:

        (a) Port the Node client's handshake to Python (reverse-engineer from
            its source) and yield events with the same {type, text} shape.
        (b) Run `openclaw-node` as a child Node process and read newline-
            delimited JSON from its stdout (simplest, hides protocol details).
        (c) If OpenClaw exposes an SSE endpoint at `/api/events` or similar
            (probe with `curl` once installed), prefer it over WebSocket.

        Verify on the Spark with: `openclaw --help`, `openclaw gateway --help`,
        and `ls ~/.openclaw/` — then come back here and implement.
        """
        raise NotImplementedError(
            "OpenClaw event streaming not yet wired — see TODO in this docstring."
        )
        # Unreachable; keeps mypy/pyright happy about return type.
        if False:
            yield {}
