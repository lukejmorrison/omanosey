#!/usr/bin/env python3
"""Screensaver diagnostics. Stdlib only.

Normal launches append one line per lifecycle event to the state log so a
flash-and-gone screensaver can be inspected after it closes. Debug hold uses
`dismiss_action` to keep the window up while those events are still recorded.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from config import state_dir  # noqa: E402

MAX_BYTES = 200_000
KEEP_LINES = 150


def log_path() -> Path:
    return state_dir() / "screensaver.log"


def _iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_event(kind: str, **fields: Any) -> str:
    kind_text = "".join(ch if not ch.isspace() else "-" for ch in str(kind)) or "event"
    parts = [_iso(), kind_text]
    for key in sorted(fields):
        value = fields[key]
        if value is None:
            continue
        key_text = "".join(ch for ch in str(key) if not ch.isspace())
        if not key_text:
            continue
        text = str(value).replace("\n", " ").replace("\r", " ").replace("\t", " ")
        if text == "" or any(ch.isspace() for ch in text) or "=" in text:
            text = json.dumps(text, ensure_ascii=False)
        parts.append(f"{key_text}={text}")
    return " ".join(parts)


def dismiss_action(*, kind: str, armed: bool, debug: bool, key: str = "") -> str:
    """Return quit, hold, or ignore.

    Only a key press or mouse click dismisses after the grace period. Pointer
    motion and focus-out are logged but never quit. Debug mode holds until Esc.
    Signals always quit.
    """
    if kind == "signal":
        return "quit"
    if debug and key.lower() in {"escape", "esc"}:
        return "quit"
    if kind in {"motion", "focus-out"}:
        if debug and armed:
            return "hold"
        return "ignore"
    if not armed:
        return "ignore"
    if debug:
        return "hold"
    return "quit"


def _append(path: Path, line: str, *, max_bytes: int, keep_lines: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (line + "\n").encode("utf-8")
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size <= max_bytes:
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    kept = [item for item in lines if item.strip()][-keep_lines:]
    path.write_text(("\n".join(kept) + ("\n" if kept else "")), encoding="utf-8")


def write_event(
    kind: str,
    *,
    max_bytes: int = MAX_BYTES,
    keep_lines: int = KEEP_LINES,
    **fields: Any,
) -> str:
    fields.setdefault("pid", os.getpid())
    line = format_event(kind, **fields)
    try:
        _append(log_path(), line, max_bytes=max_bytes, keep_lines=keep_lines)
    except OSError as exc:
        sys.stderr.write(f"omanosey: debug log failed: {exc}\n")
    return line


def recent_events(limit: int = 40) -> list[str]:
    if limit < 1:
        return []
    path = log_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-limit:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="omanosey-debuglog")
    sub = parser.add_subparsers(dest="cmd", required=True)
    event = sub.add_parser("event", help="append one screensaver diagnostic line")
    event.add_argument("kind")
    event.add_argument("fields", nargs="*")
    tail = sub.add_parser("tail", help="print the latest screensaver diagnostic lines")
    tail.add_argument("-n", type=int, default=40)
    args = parser.parse_args(argv)
    if args.cmd == "event":
        fields: dict[str, str] = {}
        for item in args.fields:
            key, sep, value = item.partition("=")
            if not sep or not key:
                raise SystemExit(f"field must be key=value, got {item!r}")
            fields[key] = value
        print(write_event(args.kind, **fields))
        return 0
    if args.cmd == "tail":
        for line in recent_events(args.n):
            print(line)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
