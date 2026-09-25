"""Nosey Bugger honeypot — Python port of Matt's unattended-screen QR trap."""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import hmac
import json
import os
import struct
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import escape
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from camera import snap as camera_snap, snap_path  # noqa: E402
from config import (  # noqa: E402
    AGAIN_LINES,
    load_config,
    load_strings,
    plugin_root,
    private_dir,
    save_config,
    state_dir,
    web_root,
)
from live import Hub, ScreenLead, accept_key, encode_frame, encode_pong, read_frame  # noqa: E402

NONCE_TTL = 120
LIVE = Hub()
SCREENS = ScreenLead()
COOKIE_TTL = 365 * 24 * 3600
COOKIE_NAME = "seen"
HEALTH_PATH = "/healthz"

MIME = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


def _now() -> int:
    return int(time.time())


def _iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_private() -> dict[str, Path]:
    root = private_dir()
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    files = {
        "replies": root / "replies.txt",
        "banned": root / "banned.tsv",
        "nonces": root / "nonces.txt",
        "key": root / "cookie.key",
        "strings": root / "strings.json",
    }
    return files


def _crypto_key(files: dict[str, Path]) -> bytes:
    path = files["key"]
    if not path.is_file():
        key = secrets.token_bytes(32)
        path.write_bytes(key)
        os.chmod(path, 0o600)
        return key
    return path.read_bytes()


def encrypt(plain: str, files: dict[str, Path]) -> str:
    key = _crypto_key(files)
    nonce = secrets.token_bytes(16)
    mac = hmac.new(key, nonce + plain.encode("utf-8"), hashlib.sha256).digest()
    blob = nonce + mac + plain.encode("utf-8")
    return base64.urlsafe_b64encode(blob).decode("ascii").rstrip("=")


def decrypt(blob: str, files: dict[str, Path]) -> str | None:
    try:
        pad = "=" * ((4 - len(blob) % 4) % 4)
        raw = base64.urlsafe_b64decode(blob + pad)
    except (ValueError, OSError):
        return None
    if len(raw) <= 48:
        return None
    nonce, mac, plain = raw[:16], raw[16:48], raw[48:]
    key = _crypto_key(files)
    expect = hmac.new(key, nonce + plain, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expect):
        return None
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError:
        return None


def nonce_new(files: dict[str, Path]) -> str:
    nonce = secrets.token_hex(16)
    with files["nonces"].open("a", encoding="utf-8") as fh:
        fh.write(f"{nonce}\t{_now()}\n")
    return nonce


def nonce_valid(nonce: str, files: dict[str, Path]) -> bool:
    if len(nonce) != 32 or any(c not in "0123456789abcdef" for c in nonce.lower()):
        return False
    if not files["nonces"].is_file():
        return False
    now = _now()
    found = False
    keep: list[str] = []
    for line in files["nonces"].read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        n, ts = (line.split("\t", 1) + ["0"])[:2]
        try:
            age = now - int(ts)
        except ValueError:
            continue
        if age > NONCE_TTL:
            continue
        keep.append(line)
        if hmac.compare_digest(n.lower(), nonce.lower()):
            found = True
    files["nonces"].write_text(("\n".join(keep) + ("\n" if keep else "")), encoding="utf-8")
    return found


def nonce_burn(nonce: str, files: dict[str, Path]) -> None:
    if not files["nonces"].is_file():
        return
    kept: list[str] = []
    for line in files["nonces"].read_text(encoding="utf-8").splitlines():
        n = line.split("\t", 1)[0] if line.strip() else ""
        if n and not hmac.compare_digest(n.lower(), nonce.lower()):
            kept.append(line)
    files["nonces"].write_text(("\n".join(kept) + ("\n" if kept else "")), encoding="utf-8")


def ban_count(ip: str, files: dict[str, Path]) -> int:
    if not files["banned"].is_file():
        return 0
    count = 0
    for line in files["banned"].read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        if len(cols) > 1 and cols[1] == ip:
            count += 1
    return count


def again_line(ip: str, files: dict[str, Path], strings: dict[str, str]) -> str:
    # ban_count is visits that already left a note; first return uses index 0.
    idx = max(0, ban_count(ip, files) - 1)
    if idx < len(AGAIN_LINES):
        return AGAIN_LINES[idx]
    return AGAIN_LINES[-1] if AGAIN_LINES else strings.get("again", "OI!")


def is_banned(ip: str, cookie_val: str, files: dict[str, Path]) -> bool:
    if cookie_val:
        plain = decrypt(cookie_val, files)
        if plain:
            try:
                data = json.loads(plain)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict) and data.get("seen") is True:
                return True
    if files["banned"].is_file():
        for line in files["banned"].read_text(encoding="utf-8").splitlines():
            cols = line.split("\t")
            if len(cols) > 1 and cols[1] == ip:
                return True
    return False


def ban_visitor(ip: str, ua: str, files: dict[str, Path], secure: bool) -> str:
    value = encrypt(json.dumps({"seen": True, "ts": _now()}), files)
    ua_clean = ua.replace("\t", " ").replace("\n", " ").replace("\r", " ")[:512]
    row = "\t".join([_iso(), ip, ua_clean, value]) + "\n"
    with files["banned"].open("a", encoding="utf-8") as fh:
        fh.write(row)
    return value


def save_reply(comment: str, nonce: str, ip: str, ua: str, files: dict[str, Path]) -> dict[str, str]:
    row = {
        "ts": _iso(),
        "ip": ip,
        "nonce": nonce,
        "ua": ua[:512],
        "comment": comment,
    }
    line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
    with files["replies"].open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return row


def recent_replies(files: dict[str, Path], limit: int = 40) -> list[dict[str, Any]]:
    path = files["replies"]
    if not path.is_file() or limit < 1:
        return []
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("comment"):
            out.append(
                {
                    "ts": str(data.get("ts") or ""),
                    "ip": str(data.get("ip") or ""),
                    "comment": str(data.get("comment") or "")[:500],
                }
            )
    return out


def layout(title: str, body_class: str, inner: str, scripts: str = "") -> str:
    return (
        "<!doctype html>\n"
        f'<html lang="en"><head>'
        f'<meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        f'<meta name="robots" content="noindex, nofollow">'
        f"<title>{escape(title)}</title>"
        f'<link rel="stylesheet" href="/public/nosey.css">'
        f"</head><body class=\"{escape(body_class)}\">"
        f"{inner}{scripts}</body></html>"
    )


def render_unattended(url: str, *, monitor: str = "") -> str:
    inner = (
        '<canvas id="matrix" aria-hidden="true"></canvas>'
        '<div id="thunder" aria-hidden="true"></div>'
        '<main class="owner" id="qr-plate">'
        '<div id="qr" aria-label="QR code"></div>'
        "</main>"
        '<div id="alarm"><h1>I&rsquo;ve just been scanned.</h1><p>Nosey bugger.</p></div>'
    )
    scripts = (
        '<script src="/public/qrcode.min.js"></script>'
        f'<script>document.body.dataset.live="screen";'
        f"document.body.dataset.qr={json.dumps(url)};"
        f"document.body.dataset.monitor={json.dumps(monitor)};</script>"
        '<script src="/public/matrix.js"></script>'
        '<script src="/public/live.js"></script>'
    )
    return layout("Unattended", "screen-owner", inner, scripts)


def render_form(nonce: str, strings: dict[str, str], nudge: bool = False) -> str:
    err = (
        f'<p class="nudge">{escape("Empty? Come on, you were nosey enough to scan it.")}</p>'
        if nudge
        else ""
    )
    inner = (
        '<main class="card">'
        f"<h1>{escape(strings['title'])}</h1>"
        f'<p class="subtitle">{escape(strings["subtitle"])}</p>'
        f'<figure class="snap" data-nonce={json.dumps(nonce)}>'
        '<img id="snap" alt="Looking at you" hidden>'
        "<figcaption>Smile — you&rsquo;re on the unattended camera.</figcaption>"
        "</figure>"
        f"{err}"
        f'<form method="post" action="?rand={escape(nonce)}" autocomplete="off">'
        f'<input type="hidden" name="nonce" value="{escape(nonce)}">'
        '<div class="row">'
        f'<input type="text" name="comment" maxlength="500" placeholder="{escape(strings["placeholder"])}" autofocus>'
        f'<button type="submit">{escape(strings["send"])}</button>'
        "</div></form>"
        '<button type="button" id="talk">Hold to talk</button>'
        "</main>"
    )
    scripts = (
        f'<script>document.body.dataset.live="visitor";document.body.dataset.nonce={json.dumps(nonce)};</script>'
        '<script src="/public/live.js"></script>'
    )
    return layout(strings["title"], "screen-visitor", inner, scripts)


def render_thanks(strings: dict[str, str]) -> str:
    inner = (
        '<main class="card thanks">'
        f"<h1>{escape(strings['thanks'])}</h1>"
        f'<p class="subtitle">{escape(strings["thanks_sub"])}</p>'
        "</main>"
    )
    return layout(strings["thanks"], "screen-visitor", inner)


def render_expired(strings: dict[str, str]) -> str:
    inner = (
        '<main class="card">'
        f"<h1>{escape(strings['expired'])}</h1>"
        f'<p class="subtitle">{escape(strings["expired_sub"])}</p>'
        "</main>"
    )
    return layout(strings["expired"], "screen-visitor", inner)


def render_desk() -> str:
    inner = (
        '<main class="card desk">'
        "<h1>Nosey desk</h1>"
        '<p class="subtitle">Leave this open on your phone. A scan rings here, and you can talk back.</p>'
        '<p id="live-status" class="subtitle">Connecting…</p>'
        '<button type="button" id="arm">Tap to arm alerts</button>'
        '<button type="button" id="talk" disabled>Hold to talk</button>'
        '<section id="alert-panel" class="alert-panel" hidden>'
        '<p class="alert-kicker">I&rsquo;ve just been scanned.</p>'
        '<img id="alert-snap" class="alert-snap" alt="Camera snap" hidden>'
        '<p id="alert-note" class="alert-note">Nosey bugger.</p>'
        '<button type="button" id="alarm-dismiss">Dismiss</button>'
        "</section>"
        "<h2>Messages</h2>"
        '<ul id="messages" class="messages"></ul>'
        "</main>"
    )
    scripts = '<script>document.body.dataset.live="desk";</script><script src="/public/live.js"></script>'
    return layout("Nosey desk", "screen-visitor", inner, scripts)


def render_oi(
    strings: dict[str, str],
    scene: str,
    *,
    line: str,
    nonce: str = "",
) -> str:
    form = ""
    if nonce:
        form = (
            '<main class="card oi-form">'
            f"<h1>{escape(line)}</h1>"
            f'<p class="subtitle">{escape(strings["subtitle"])}</p>'
            f'<figure class="snap" data-nonce={json.dumps(nonce)}>'
            '<img id="snap" alt="Looking at you" hidden>'
            "<figcaption>Smile — you&rsquo;re on the unattended camera.</figcaption>"
            "</figure>"
            f'<form method="post" action="?rand={escape(nonce)}" autocomplete="off">'
            f'<input type="hidden" name="nonce" value="{escape(nonce)}">'
            '<div class="row">'
            f'<input type="text" name="comment" maxlength="500" placeholder="{escape(strings["placeholder"])}" autofocus>'
            f'<button type="submit">{escape(strings["send"])}</button>'
            "</div></form>"
            '<button type="button" id="talk">Hold to talk</button>'
            "</main>"
        )
        scripts = (
            f'<script>document.body.dataset.live="visitor";document.body.dataset.nonce={json.dumps(nonce)};</script>'
            '<script src="/public/live.js"></script>'
        )
        return layout(line, "screen-visitor", form, scripts)
    inner = (
        f'<div id="oi"><h1>{escape(line)}</h1></div>'
        f'<div id="wave" data-scene="{escape(scene)}"></div>'
    )
    scripts = '<script src="/public/wave.js"></script>'
    return layout(line, "screen-oi", inner, scripts)


def _iface_ipv4(name: str) -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        info = fcntl.ioctl(sock.fileno(), 0x8915, struct.pack("256s", name.encode()[:15]))
    except OSError:
        return None
    finally:
        sock.close()
    return socket.inet_ntoa(info[20:24])


def lan_ip() -> str:
    wireless: list[str] = []
    net = Path("/sys/class/net")
    if net.is_dir():
        for iface in sorted(net.iterdir()):
            if not (iface / "wireless").exists():
                continue
            addr = _iface_ipv4(iface.name)
            if addr and not addr.startswith("127."):
                wireless.append(addr)
    if wireless:
        return wireless[0]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def looks_like_nosey(body: bytes) -> bool:
    lower = body.lower()
    return b'id="qr"' in lower or b"unattended" in lower or b"nosey bugger" in lower


def probe_public(url: str, timeout: float = 2.0) -> str | None:
    if not url:
        return None
    target = url.rstrip("/") + "/?unattended"
    req = urllib.request.Request(target, headers={"User-Agent": "omanosey/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) >= 400:
                return None
            body = resp.read(8000)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    return target if looks_like_nosey(body) else None


def health_ok(host: str, port: int, timeout: float = 0.4) -> bool:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{HEALTH_PATH}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return getattr(resp, "status", 200) == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


class NoseyHandler(BaseHTTPRequestHandler):
    server_version = "omanosey/1.0"
    files: dict[str, Path]
    strings: dict[str, str]
    spline_scene: str
    public_base: str
    bind_host: str
    port: int

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cookie(self) -> str:
        raw = self.headers.get("Cookie", "")
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:
            return ""
        morsel = jar.get(COOKIE_NAME)
        return morsel.value if morsel else ""

    def _ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def _ua(self) -> str:
        return (self.headers.get("User-Agent") or "")[:512]

    def _secure(self) -> bool:
        proto = (self.headers.get("X-Forwarded-Proto") or "").lower()
        return proto == "https"

    def _base_url(self) -> str:
        if self.public_base:
            return self.public_base.rstrip("/") + "/"
        host = self.headers.get("Host") or f"{lan_ip()}:{self.port}"
        # Prefer a LAN address in QR codes so a phone can scan the unattended view.
        if host.startswith("127.0.0.1") or host.startswith("localhost"):
            host = f"{lan_ip()}:{self.port}"
        https = self._secure()
        scheme = "https" if https else "http"
        return f"{scheme}://{host}/"

    def _send(
        self,
        code: int,
        body: str | bytes,
        content_type: str = "text/html; charset=utf-8",
        extra: list[tuple[str, str]] | None = None,
    ) -> None:
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        if extra:
            for key, value in extra:
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def _set_ban_cookie(self, value: str) -> list[tuple[str, str]]:
        flags = ["Path=/", "HttpOnly", "SameSite=Lax", f"Max-Age={COOKIE_TTL}"]
        if self._secure():
            flags.append("Secure")
        return [("Set-Cookie", f"{COOKIE_NAME}={value}; " + "; ".join(flags))]

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/ws":
            self._websocket()
            return
        if parsed.path == "/ticket":
            nonce = nonce_new(self.files)
            url = self._base_url() + "?rand=" + nonce
            self._send(200, json.dumps({"url": url, "ttl": NONCE_TTL}), "application/json; charset=utf-8")
            return
        if parsed.path == "/replies":
            self._send(
                200,
                json.dumps({"replies": recent_replies(self.files)}),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path == "/desk-state":
            state = LIVE.desk_state()
            scan = state.get("scan") or {}
            nonce = str(scan.get("nonce") or "")
            path = snap_path(nonce) if nonce else None
            state["snap"] = bool(path)
            if path:
                state["snap_url"] = f"/snap/{nonce}.jpg"
            self._send(200, json.dumps(state), "application/json; charset=utf-8")
            return
        if parsed.path == "/screen-lead":
            qs = parse_qs(parsed.query, keep_blank_values=True)
            monitor = (qs.get("monitor") or [""])[0]
            self._send(
                200,
                json.dumps(SCREENS.ping(monitor)),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path.startswith("/snap/"):
            token = parsed.path[len("/snap/") :].split(".")[0]
            path = snap_path(token)
            if not path:
                self._send(404, "missing\n", "text/plain; charset=utf-8")
                return
            self._send(200, path.read_bytes(), "image/jpeg")
            return
        if parsed.path == HEALTH_PATH:
            self._send(200, "ok\n", "text/plain; charset=utf-8")
            return
        if parsed.path.startswith("/public/"):
            self._static(parsed.path)
            return
        if parsed.path not in ("/", "/index.php", "/index.html"):
            self._send(404, render_expired(self.strings))
            return
        qs = parse_qs(parsed.query, keep_blank_values=True)
        if "unattended" in qs or parsed.query == "unattended":
            nonce = nonce_new(self.files)
            url = self._base_url() + "?rand=" + nonce
            monitor = (qs.get("monitor") or [""])[0]
            self._send(200, render_unattended(url, monitor=monitor))
            return
        if "desk" in qs or parsed.query == "desk":
            self._send(200, render_desk())
            return
        rand = (qs.get("rand") or [""])[0]
        if rand:
            banned = is_banned(self._ip(), self._cookie(), self.files)
            if nonce_valid(rand, self.files):
                LIVE.announce_scan(rand)
                threading.Thread(
                    target=camera_snap,
                    args=(rand,),
                    name="omanosey-snap",
                    daemon=True,
                ).start()
                if banned:
                    line = again_line(self._ip(), self.files, self.strings)
                    self._send(
                        200,
                        render_oi(
                            self.strings,
                            self.spline_scene,
                            line=line,
                            nonce=rand,
                        ),
                    )
                    return
                self._send(200, render_form(rand, self.strings))
                return
            if banned:
                line = again_line(self._ip(), self.files, self.strings)
                self._send(200, render_oi(self.strings, self.spline_scene, line=line))
                return
            self._send(404, render_expired(self.strings))
            return
        if is_banned(self._ip(), self._cookie(), self.files):
            line = again_line(self._ip(), self.files, self.strings)
            self._send(200, render_oi(self.strings, self.spline_scene, line=line))
            return
        self._send(404, render_expired(self.strings))

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length > 8192:
            self._send(413, render_expired(self.strings))
            return
        raw = self.rfile.read(length) if length else b""
        form = parse_qs(raw.decode("utf-8", errors="replace"))
        nonce = (form.get("nonce") or [""])[0]
        comment = (form.get("comment") or [""])[0].strip()
        if not nonce_valid(nonce, self.files):
            self._send(404, render_expired(self.strings))
            return
        if comment == "":
            if is_banned(self._ip(), self._cookie(), self.files):
                line = again_line(self._ip(), self.files, self.strings)
                self._send(
                    200,
                    render_oi(self.strings, self.spline_scene, line=line, nonce=nonce),
                )
            else:
                self._send(200, render_form(nonce, self.strings, nudge=True))
            return
        row = save_reply(comment, nonce, self._ip(), self._ua(), self.files)
        nonce_burn(nonce, self.files)
        value = ban_visitor(self._ip(), self._ua(), self.files, self._secure())
        LIVE.announce_reply(row["comment"], ts=row["ts"], ip=row["ip"], nonce=nonce)
        self._send(200, render_thanks(self.strings), extra=self._set_ban_cookie(value))

    def _static(self, path: str) -> None:
        rel = path[len("/public/") :]
        if not rel or ".." in Path(rel).parts:
            self._send(404, "not found\n", "text/plain; charset=utf-8")
            return
        target = (web_root() / "public" / rel).resolve()
        public = (web_root() / "public").resolve()
        if public not in target.parents and target != public:
            self._send(404, "not found\n", "text/plain; charset=utf-8")
            return
        if not target.is_file():
            self._send(404, "not found\n", "text/plain; charset=utf-8")
            return
        data = target.read_bytes()
        self._send(200, data, MIME.get(target.suffix, "application/octet-stream"))

    def _websocket(self) -> None:
        key = self.headers.get("Sec-WebSocket-Key", "")
        if not key:
            self._send(400, "websocket required\n", "text/plain; charset=utf-8")
            return
        self.close_connection = True
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept_key(key))
        self.end_headers()
        sock = self.connection
        write_lock = threading.Lock()

        def send_raw(frame: bytes) -> None:
            with write_lock:
                sock.sendall(frame)

        def send(text: str) -> None:
            send_raw(encode_frame(text))

        def read_exact(n: int) -> bytes:
            buf = b""
            while len(buf) < n:
                chunk = sock.recv(n - len(buf))
                if not chunk:
                    return b""
                buf += chunk
            return buf

        client = None
        try:
            first = read_frame(read_exact)
            if first is None or first[0] != "text":
                return
            message = json.loads(first[1] or "{}")
            role = message.get("role") if isinstance(message, dict) else ""
            if role not in ("screen", "desk", "visitor"):
                return
            ticket = str(message.get("nonce") or "") if role == "visitor" else ""
            client = LIVE.add(role, ticket, send)
            while True:
                incoming = read_frame(read_exact)
                if incoming is None:
                    break
                kind, payload = incoming
                if kind == "ping":
                    send_raw(encode_pong(payload if isinstance(payload, bytes) else b""))
                    continue
                if kind != "text" or not payload:
                    continue
                try:
                    body = json.loads(str(payload))
                except json.JSONDecodeError:
                    continue
                if isinstance(body, dict) and body.get("type") == "audio":
                    LIVE.relay_audio(client, str(body.get("mime") or ""), str(body.get("data") or ""))
        except Exception:
            return
        finally:
            if client is not None:
                LIVE.remove(client)


def make_server(bind: str, port: int, public_base: str = "", spline: str = "") -> ThreadingHTTPServer:
    files = _ensure_private()
    handler = type(
        "BoundNoseyHandler",
        (NoseyHandler,),
        {
            "files": files,
            "strings": load_strings(),
            "spline_scene": spline,
            "public_base": public_base,
            "bind_host": bind,
            "port": port,
        },
    )
    httpd = ThreadingHTTPServer((bind, port), handler)
    return httpd


def serve_forever(bind: str, port: int, public_base: str = "", spline: str = "") -> None:
    if health_ok("127.0.0.1", port):
        print(f"omanosey already serving on port {port}", flush=True)
        return
    try:
        httpd = make_server(bind, port, public_base=public_base, spline=spline)
    except OSError as exc:
        if health_ok("127.0.0.1", port):
            print(f"omanosey already serving on port {port}", flush=True)
            return
        raise SystemExit(f"omanosey: bind failed: {exc}") from exc
    print(f"omanosey listening on {bind}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def start_background(bind: str, port: int, public_base: str = "", spline: str = "") -> None:
    if health_ok("127.0.0.1", port):
        return
    log = state_dir() / "server.log"
    state_dir().mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "serve",
        "--bind",
        bind,
        "--port",
        str(port),
    ]
    if public_base:
        cmd.extend(["--public-base", public_base])
    if spline:
        cmd.extend(["--spline", spline])
    log_fh = log.open("a", encoding="utf-8")
    subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        cwd=str(plugin_root()),
    )
    deadline = time.time() + 3
    while time.time() < deadline:
        if health_ok("127.0.0.1", port):
            return
        time.sleep(0.05)
    raise SystemExit(f"omanosey: local server did not become healthy on :{port}")


def kiosk_url() -> str:
    cfg = load_config()
    public = probe_public(cfg["public_url"])
    if public:
        return public
    start_background(
        cfg["bind"],
        int(cfg["port"]),
        public_base=str(cfg.get("phone_base") or ""),
        spline=cfg.get("spline_scene") or "",
    )
    return f"http://127.0.0.1:{int(cfg['port'])}/?unattended"


def status_payload() -> dict[str, Any]:
    cfg = load_config()
    public = probe_public(cfg["public_url"])
    local = health_ok("127.0.0.1", int(cfg["port"]))
    return {
        "ok": True,
        "idle": bool(cfg["idle"]),
        "public_url": cfg["public_url"],
        "phone_base": cfg.get("phone_base") or "",
        "public_live": bool(public),
        "kiosk_url": public or (f"http://127.0.0.1:{int(cfg['port'])}/?unattended" if local else ""),
        "local": local,
        "port": int(cfg["port"]),
        "lan_ip": lan_ip(),
        "plugin_root": str(plugin_root()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="omanosey")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve_p = sub.add_parser("serve", help="run the honeypot HTTP server")
    serve_p.add_argument("--bind", default="")
    serve_p.add_argument("--port", type=int, default=0)
    serve_p.add_argument("--public-base", default="")
    serve_p.add_argument("--spline", default="")

    sub.add_parser("url", help="print the screensaver kiosk URL (starts local server if needed)")
    sub.add_parser("status", help="JSON status")
    set_p = sub.add_parser("set", help="write config keys")
    set_p.add_argument("--idle", choices=["true", "false"], default=None)
    set_p.add_argument("--public-url", default=None)
    set_p.add_argument(
        "--phone-base",
        default=None,
        help="phone-facing origin for QR burn links (e.g. Tailscale Serve HTTPS)",
    )
    set_p.add_argument("--port", type=int, default=None)

    args = parser.parse_args(argv)
    cfg = load_config()
    if args.cmd == "serve":
        bind = args.bind or cfg["bind"]
        port = args.port or int(cfg["port"])
        serve_forever(
            bind,
            port,
            public_base=args.public_base or str(cfg.get("phone_base") or ""),
            spline=args.spline or cfg.get("spline_scene") or "",
        )
        return 0
    if args.cmd == "url":
        print(kiosk_url())
        return 0
    if args.cmd == "status":
        print(json.dumps(status_payload()))
        return 0
    if args.cmd == "set":
        update: dict[str, Any] = {}
        if args.idle is not None:
            update["idle"] = args.idle == "true"
        if args.public_url is not None:
            update["public_url"] = args.public_url
        if args.phone_base is not None:
            update["phone_base"] = args.phone_base
        if args.port is not None:
            update["port"] = args.port
        print(json.dumps(save_config(update)))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
