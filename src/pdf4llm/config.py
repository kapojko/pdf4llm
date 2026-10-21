"""User-local LLM settings (endpoint, api key, model).

Stored as JSON in the platform user-config dir:
  - Windows: %APPDATA%/pdf4llm/config.json
  - POSIX:   ~/.config/pdf4llm/config.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP = "pdf4llm"


def config_path() -> Path:
    """Windows: %APPDATA%/pdf4llm/config.json; POSIX: ~/.config/pdf4llm/config.json."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", "~\\AppData\\Roaming"))
    else:
        base = Path.home() / ".config"
    return base / APP / "config.json"


def load_config() -> dict:
    p = config_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_config(cfg: dict) -> Path:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return p


def fetch_models(endpoint: str, api_key: str) -> list[str]:
    """Fetch available model ids from an OpenAI-compatible /v1/models endpoint.

    Returns an empty list on any error so the caller can fall back to manual
    input.
    """
    if not endpoint:
        return []
    url = endpoint.rstrip("/") + "/models"
    try:
        import requests

        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        items = data.get("data") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        return [
            it["id"]
            for it in items
            if isinstance(it, dict) and it.get("id")
        ]
    except Exception:
        return []


def mask(value: str) -> str:
    """Mask an API key for display (never reveal any of it)."""
    return "***" if value else ""
