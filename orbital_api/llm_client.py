"""Minimal OpenAI-compatible client for local Ollama / Nemotron."""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests

log = logging.getLogger(__name__)

_err_lock = threading.Lock()
_last_error: str | None = None


def get_last_error() -> str | None:
    with _err_lock:
        return _last_error


def _set_last_error(msg: str | None) -> None:
    global _last_error
    with _err_lock:
        _last_error = msg


def read_llm_config() -> dict[str, Any]:
    return {
        "agent_mode": os.environ.get("AGENT_MODE", ""),
        "llm_base_url": os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/"),
        "llm_model": os.environ.get("LLM_MODEL", "nemotron-3-nano-30b-a3b-fp8"),
        "llm_timeout_s": float(os.environ.get("LLM_TIMEOUT_S", "180")),
    }


def chat_completions_url() -> str:
    base = read_llm_config()["llm_base_url"].rstrip("/") + "/"
    return urljoin(base, "chat/completions")


def models_url() -> str:
    base = read_llm_config()["llm_base_url"].rstrip("/") + "/"
    return urljoin(base, "models")


@dataclass
class ChatCompletionResult:
    raw_text: str
    error: str | None


def chat_completion(
    *,
    system: str,
    user: str,
    temperature: float = 0.2,
) -> ChatCompletionResult:
    cfg = read_llm_config()
    url = chat_completions_url()
    timeout = cfg["llm_timeout_s"]
    body = {
        "model": cfg["llm_model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    try:
        r = requests.post(url, json=body, timeout=timeout, headers={"Accept": "application/json"})
    except requests.exceptions.Timeout as e:
        err = f"timeout: {e}"
        log.warning("LLM %s", err)
        _set_last_error(err)
        return ChatCompletionResult("", err)
    except requests.exceptions.RequestException as e:
        err = f"request_error: {e}"
        log.warning("LLM %s", err)
        _set_last_error(err)
        return ChatCompletionResult("", err)

    if r.status_code >= 400:
        err = f"http_{r.status_code}: {r.text[:800]}"
        _set_last_error(err)
        return ChatCompletionResult(r.text or "", err)

    try:
        data = r.json()
    except json.JSONDecodeError as e:
        err = f"invalid_response_json: {e}"
        _set_last_error(err)
        return ChatCompletionResult(r.text or "", err)

    choices = data.get("choices") or []
    if not choices:
        err = "no_choices_in_response"
        _set_last_error(err)
        return ChatCompletionResult(json.dumps(data)[:2000], err)

    msg = choices[0].get("message") or {}
    content = msg.get("content")
    raw = content if isinstance(content, str) else ("" if content is None else str(content))
    _set_last_error(None)
    return ChatCompletionResult(raw, None)


def probe_model_connected() -> bool:
    """Best-effort: OpenAI-compatible GET /v1/models."""
    try:
        r = requests.get(models_url(), timeout=5.0)
        return r.status_code == 200
    except requests.exceptions.RequestException:
        return False
