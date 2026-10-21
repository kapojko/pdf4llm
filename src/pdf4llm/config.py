"""User-local LLM settings (endpoint, api key, model).

Stored as JSON in the platform user-config dir:
  - Windows: %APPDATA%/pdf4llm/config.json
  - POSIX:   ~/.config/pdf4llm/config.json
"""
from __future__ import annotations

import json
from pathlib import Path

from platformdirs import user_config_dir

APP = "pdf4llm"


def config_path() -> Path:
    return Path(user_config_dir(APP)) / "config.json"


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


def mask(value: str) -> str:
    """Mask an API key for display."""
    if not value:
        return ""
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***{value[-3:]}"
