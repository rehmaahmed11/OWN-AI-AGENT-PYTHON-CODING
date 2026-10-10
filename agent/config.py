"""Configuration loading.

Priority (later wins):
  1. DEFAULTS below
  2. agent_config.json in the repo root (your local settings)
  3. Environment variables: OWN_AGENT_BASE_URL, OWN_AGENT_WORKSPACE
"""

from __future__ import annotations

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    # Where the llama.cpp server listens (OpenAI-compatible, no /v1 suffix).
    "base_url": "http://127.0.0.1:8080",
    # Root folder (relative to repo) the agent is ALWAYS allowed to write in.
    "workspace": "workspace",
    # Extra named roots you approve later, e.g. after termux-setup-storage:
    #   "extra_roots": {"shared": "/sdcard/SharedProjects"}
    "extra_roots": {},
    # Generation budgets — small defaults for 4GB phones.
    "temperature": 0.2,
    "max_tokens_plan": 512,
    "max_tokens_file": 1536,
    "max_tokens_review": 256,
    "max_files": 25,          # hard cap on files per project
    "memory_results": 3,      # how many past-task snippets to inject
    "timeout_s": 600,         # phone CPUs are slow; be patient
    "review": True,           # ask the model "what's missing?" at the end
    # Self-learning chat GUI budgets.
    "max_tokens_chat": 512,   # max reply length in the chat GUI
    "chat_results": 5,        # how many past chats to recall per reply
    "chat_port": 8765,        # default web-GUI port
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    cfg_path = REPO_ROOT / "agent_config.json"
    if cfg_path.exists():
        try:
            cfg.update(json.loads(cfg_path.read_text()))
        except json.JSONDecodeError as e:
            raise SystemExit(f"agent_config.json is not valid JSON: {e}")
    if os.environ.get("OWN_AGENT_BASE_URL"):
        cfg["base_url"] = os.environ["OWN_AGENT_BASE_URL"]
    if os.environ.get("OWN_AGENT_WORKSPACE"):
        cfg["workspace"] = os.environ["OWN_AGENT_WORKSPACE"]
    return cfg
