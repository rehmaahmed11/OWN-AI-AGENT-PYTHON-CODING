"""Client for the llama.cpp server (OpenAI-compatible /v1/chat/completions).

Uses only urllib so this runs on a fresh Termux Python with zero pip installs.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class LLMError(RuntimeError):
    pass


def chat(messages: list[dict], cfg: dict, max_tokens: int) -> str:
    """Send a chat request and return the assistant's text."""
    url = cfg["base_url"].rstrip("/") + "/v1/chat/completions"
    payload = {
        "messages": messages,
        "temperature": cfg["temperature"],
        "max_tokens": max_tokens,
        "stream": False,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg["timeout_s"]) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise LLMError(
            f"Cannot reach the model server at {url}\n"
            f"Reason: {e}\n"
            "Start it first, e.g.:  bash start_model.sh"
        )
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise LLMError(f"Unexpected response from model server: {e}: {data!r}")


def server_up(cfg: dict) -> bool:
    """Health check used by `doctor`. llama.cpp exposes /health and /v1/models."""
    for path in ("/health", "/v1/models"):
        try:
            with urllib.request.urlopen(cfg["base_url"].rstrip("/") + path, timeout=5):
                return True
        except Exception:
            continue
    return False
