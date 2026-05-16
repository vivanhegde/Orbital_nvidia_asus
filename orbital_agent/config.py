"""Environment-driven configuration for the orbital agent sidecar."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    return float(raw)


@dataclass(frozen=True)
class AgentConfig:
    # Inference (Ollama, OpenAI-compatible)
    ollama_base_url: str
    ollama_model: str

    # OpenClaw gateway
    openclaw_gateway_url: str        # ws://host:port (used by future WebSocket client)
    openclaw_rest_url: str           # http://host:port  (REST: POST /api/message)
    openclaw_gateway_token: str      # OPENCLAW_GATEWAY_TOKEN — empty string disables
    openclaw_agent_id: str           # Which configured OpenClaw agent to address

    # Orbital API (where the runner POSTs agent events for SSE fan-out — Feature 5)
    api_base_url: str

    # Persistence
    db_path: Path

    # Runner cadence
    poll_interval_seconds: float
    heartbeat_seconds: float

    # Misc
    log_level: str


def load() -> AgentConfig:
    return AgentConfig(
        ollama_base_url=_env("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_model=_env("ORBITAL_MODEL", "nemotron-3-nano:30b"),
        openclaw_gateway_url=_env("OPENCLAW_GATEWAY_URL", "ws://localhost:18789"),
        openclaw_rest_url=_env("OPENCLAW_REST_URL", "http://localhost:18789"),
        openclaw_gateway_token=_env("OPENCLAW_GATEWAY_TOKEN", ""),
        openclaw_agent_id=_env("ORBITAL_AGENT_ID", "orbital"),
        api_base_url=_env("ORBITAL_API_BASE_URL", "http://127.0.0.1:8000"),
        db_path=Path(_env("ORBITAL_DB_PATH", str(_ROOT / "orbital_data" / "orbital.db"))),
        poll_interval_seconds=_env_float("ORBITAL_POLL_INTERVAL_S", 5.0),
        heartbeat_seconds=_env_float("ORBITAL_HEARTBEAT_S", 30.0),
        log_level=_env("ORBITAL_LOG_LEVEL", "INFO"),
    )
