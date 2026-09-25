"""File-free live channel: scan alarm and voice notes over a WebSocket."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading
import time
from typing import Any, Callable

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_MESSAGE = 200_000
AUDIO_ROLES = ("screen", "desk")


def accept_key(key: str) -> str:
    digest = hashlib.sha1((key.strip() + WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_frame(text: str) -> bytes:
    payload = text.encode("utf-8")
    return _encode_raw(0x1, payload)


def encode_pong(payload: bytes = b"") -> bytes:
    return _encode_raw(0xA, payload)


def _encode_raw(opcode: int, payload: bytes) -> bytes:
    n = len(payload)
    if n < 126:
        header = struct.pack("!BB", 0x80 | opcode, n)
    elif n < 65536:
        header = struct.pack("!BBH", 0x80 | opcode, 126, n)
    else:
        header = struct.pack("!BBQ", 0x80 | opcode, 127, n)
    return header + payload


def read_frame(read: Callable[[int], bytes]) -> tuple[str, bytes | str] | None:
    """Return ('text', str), ('ping', bytes), ('pong', bytes), or None on close."""
    head = read(2)
    if len(head) < 2:
        return None
    opcode = head[0] & 0x0F
    masked = (head[1] & 0x80) != 0
    length = head[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", read(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", read(8))[0]
    if length > MAX_MESSAGE:
        raise ValueError("websocket message too large")
    mask = read(4) if masked else b""
    payload = read(length) if length else b""
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    if opcode == 0x8:
        return None
    if opcode == 0x9:
        return ("ping", payload)
    if opcode == 0xA:
        return ("pong", payload)
    if opcode == 0x1:
        return ("text", payload.decode("utf-8", errors="replace"))
    return ("other", payload)


class ScreenLead:
    """Rotate which screensaver monitor shows the QR (one at a time)."""

    SLOT_S = 15
    STALE_S = 25

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}

    def ping(self, monitor: str) -> dict[str, Any]:
        now = time.time()
        name = (monitor or "").strip()[:64]
        with self._lock:
            if name:
                self._seen[name] = now
            self._seen = {
                key: seen
                for key, seen in self._seen.items()
                if now - seen < self.STALE_S
            }
            monitors = sorted(self._seen)
            slot = int(now // self.SLOT_S)
            lead = monitors[slot % len(monitors)] if monitors else name
            until = (slot + 1) * self.SLOT_S
            return {
                "lead": lead,
                "show": bool(name) and lead == name,
                "until": until,
                "slot": slot,
                "period": self.SLOT_S,
                "monitors": monitors,
            }


class Hub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: list[dict[str, Any]] = []
        self._seen: set[str] = set()
        self._last_scan: dict[str, Any] | None = None
        self._last_reply: dict[str, Any] | None = None

    def add(self, role: str, nonce: str, send: Callable[[str], None]) -> dict[str, Any]:
        client = {"role": role, "nonce": nonce, "send": send}
        with self._lock:
            self._clients.append(client)
        return client

    def remove(self, client: dict[str, Any]) -> None:
        with self._lock:
            self._clients = [item for item in self._clients if item is not client]

    def desk_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "scan": dict(self._last_scan) if self._last_scan else None,
                "reply": dict(self._last_reply) if self._last_reply else None,
                "clients": len(self._clients),
            }

    def announce_scan(self, nonce: str) -> bool:
        with self._lock:
            if nonce in self._seen:
                return False
            self._seen.add(nonce)
            self._last_scan = {"nonce": nonce, "ts": time.time()}
            targets = [item for item in self._clients if item["role"] in AUDIO_ROLES]
        note = json.dumps({"type": "scanned", "nonce": nonce})
        for item in targets:
            _safe_send(item["send"], note)
        return True

    def announce_reply(self, comment: str, *, ts: str = "", ip: str = "", nonce: str = "") -> None:
        payload = {
            "type": "reply",
            "comment": comment[:500],
            "ts": ts,
            "ip": ip,
            "nonce": nonce,
        }
        with self._lock:
            self._last_reply = {
                "comment": payload["comment"],
                "ts": ts,
                "ip": ip,
                "nonce": nonce,
                "at": time.time(),
            }
            targets = [item for item in self._clients if item["role"] in AUDIO_ROLES]
        note = json.dumps(payload, ensure_ascii=False)
        for item in targets:
            _safe_send(item["send"], note)

    def relay_audio(self, sender: dict[str, Any], mime: str, data: str) -> None:
        if not data or len(data) > MAX_MESSAGE:
            return
        note = json.dumps({"type": "audio", "mime": mime or "audio/webm", "data": data})
        with self._lock:
            if sender["role"] == "visitor":
                targets = [item for item in self._clients if item["role"] in AUDIO_ROLES]
            else:
                targets = [item for item in self._clients if item["role"] == "visitor"]
        for item in targets:
            _safe_send(item["send"], note)


def _safe_send(send: Callable[[str], None], text: str) -> None:
    try:
        send(text)
    except Exception:
        return
