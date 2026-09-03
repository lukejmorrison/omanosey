"""OmaNosey config and paths. Stdlib only."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PLUGIN_ID = "wizwam.omanosey"
DEFAULT_PORT = 8765
DEFAULT_PUBLIC_URL = "https://e1.yahvehyireh.com"
DEFAULT_IDLE = True

STRING_DEFAULTS = {
    "title": "Nosey Bugger!",
    "subtitle": "Since you're clearly curious, leave me a note.",
    "placeholder": "Go on then, say something…",
    "send": "Send",
    "thanks": "Thanks!",
    "thanks_sub": "Your curiosity has been noted.",
    "again": "OI! isn't once enough?!",
    "expired": "Nothing to see here.",
    "expired_sub": "This little link has wandered off.",
}


def xdg_config() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def xdg_state() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))


def config_dir() -> Path:
    return xdg_config() / "omarchy" / "omanosey"


def config_path() -> Path:
    return config_dir() / "config.json"


def state_dir() -> Path:
    return xdg_state() / "omarchy" / "omanosey"


def private_dir() -> Path:
    return state_dir() / "private"


def plugin_root() -> Path:
    return Path(__file__).resolve().parent.parent


def web_root() -> Path:
    return plugin_root() / "web"


def previous_launch_path() -> Path:
    return state_dir() / "previous-launch"


def default_config() -> dict[str, Any]:
    return {
        "idle": DEFAULT_IDLE,
        "public_url": DEFAULT_PUBLIC_URL,
        "port": DEFAULT_PORT,
        "bind": "0.0.0.0",
        "spline_scene": "",
    }


def load_config() -> dict[str, Any]:
    data = default_config()
    path = config_path()
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            data.update({k: v for k, v in raw.items() if v is not None})
    port = int(data.get("port") or DEFAULT_PORT)
    if port < 1024 or port > 65535:
        port = DEFAULT_PORT
    data["port"] = port
    data["idle"] = bool(data.get("idle", DEFAULT_IDLE))
    data["public_url"] = str(data.get("public_url") or "").rstrip("/")
    data["bind"] = str(data.get("bind") or "0.0.0.0")
    data["spline_scene"] = str(data.get("spline_scene") or "")
    return data


def save_config(data: dict[str, Any]) -> dict[str, Any]:
    merged = load_config()
    merged.update(data)
    config_dir().mkdir(parents=True, exist_ok=True)
    path = config_path()
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return merged


def load_strings() -> dict[str, str]:
    out = dict(STRING_DEFAULTS)
    path = private_dir() / "strings.json"
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(value, str) and key in out:
                    out[key] = value
    return out
