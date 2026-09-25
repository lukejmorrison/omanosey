#!/usr/bin/env python3
"""Local webcam helper for the unattended honeypot.

Opens the PC camera while the screensaver is up (LED on), and freezes a JPEG
when a QR link is scanned so the visitor can see themselves.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from config import private_dir, state_dir  # noqa: E402

DEFAULT_DEVICE = os.environ.get("OMANOSEY_CAMERA", "/dev/video0")
FFMPEG = os.environ.get("OMANOSEY_FFMPEG", "ffmpeg")


def camera_dir() -> Path:
    path = state_dir() / "camera"
    path.mkdir(parents=True, exist_ok=True)
    return path


def snaps_dir() -> Path:
    path = private_dir() / "snaps"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pid_path() -> Path:
    return camera_dir() / "warm.pid"


def latest_path() -> Path:
    return camera_dir() / "latest.jpg"


def log_path() -> Path:
    return camera_dir() / "camera.log"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def status() -> dict[str, object]:
    pid = 0
    if pid_path().is_file():
        try:
            pid = int(pid_path().read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            pid = 0
    alive = _pid_alive(pid)
    latest = latest_path()
    return {
        "running": alive,
        "pid": pid if alive else 0,
        "device": DEFAULT_DEVICE,
        "latest": str(latest) if latest.is_file() else "",
        "latest_age_s": round(time.time() - latest.stat().st_mtime, 1) if latest.is_file() else None,
    }


def stop() -> None:
    if not pid_path().is_file():
        return
    try:
        pid = int(pid_path().read_text(encoding="utf-8").strip() or "0")
    except ValueError:
        pid = 0
    if _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        deadline = time.time() + 2
        while time.time() < deadline and _pid_alive(pid):
            time.sleep(0.05)
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    try:
        pid_path().unlink()
    except OSError:
        pass


def start(device: str = DEFAULT_DEVICE) -> int:
    st = status()
    if st["running"]:
        return int(st["pid"] or 0)
    if not Path(device).exists():
        sys.stderr.write(f"omanosey-camera: missing device {device}\n")
        return 0
    stop()
    latest = latest_path()
    try:
        latest.unlink()
    except OSError:
        pass
    log_fh = log_path().open("a", encoding="utf-8")
    # Keep the device open and refresh latest.jpg ~1 fps so the LED stays on.
    cmd = [
        FFMPEG,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "v4l2",
        "-video_size",
        "1280x720",
        "-i",
        device,
        "-vf",
        "fps=1",
        "-q:v",
        "3",
        "-update",
        "1",
        "-y",
        str(latest),
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        cwd=str(camera_dir()),
    )
    pid_path().write_text(str(proc.pid), encoding="utf-8")
    # Wait briefly for first frame so a fast scan still has something.
    deadline = time.time() + 4
    while time.time() < deadline:
        if latest.is_file() and latest.stat().st_size > 1000:
            break
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    return proc.pid


def _capture_fresh(dest: Path, device: str = DEFAULT_DEVICE) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "v4l2",
        "-video_size",
        "1280x720",
        "-i",
        device,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-update",
        "1",
        "-y",
        str(dest),
    ]
    # Warm process may own the device; stop it briefly for a still, then restart.
    was_running = bool(status()["running"])
    if was_running:
        stop()
        time.sleep(0.15)
    try:
        completed = subprocess.run(cmd, capture_output=True, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired):
        if was_running:
            start(device)
        return False
    ok = completed.returncode == 0 and dest.is_file() and dest.stat().st_size > 1000
    if was_running:
        start(device)
    return ok


def snap(nonce: str, device: str = DEFAULT_DEVICE) -> Path | None:
    token = "".join(ch for ch in nonce.lower() if ch in "0123456789abcdef")
    if len(token) != 32:
        return None
    dest = snaps_dir() / f"{token}.jpg"
    latest = latest_path()
    # Prefer a brand-new frame; fall back to the warm preview if needed.
    if _capture_fresh(dest, device=device):
        return dest
    if latest.is_file() and latest.stat().st_size > 1000:
        dest.write_bytes(latest.read_bytes())
        return dest
    return None


def snap_path(nonce: str) -> Path | None:
    token = "".join(ch for ch in nonce.lower() if ch in "0123456789abcdef")
    if len(token) != 32:
        return None
    path = snaps_dir() / f"{token}.jpg"
    return path if path.is_file() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="omanosey-camera")
    sub = parser.add_subparsers(dest="cmd", required=True)
    start_p = sub.add_parser("start", help="open the camera while the screensaver is up")
    start_p.add_argument("--device", default=DEFAULT_DEVICE)
    sub.add_parser("stop", help="release the camera")
    sub.add_parser("status", help="print camera helper status")
    snap_p = sub.add_parser("snap", help="freeze a JPEG for a scan nonce")
    snap_p.add_argument("nonce")
    snap_p.add_argument("--device", default=DEFAULT_DEVICE)
    args = parser.parse_args(argv)
    if args.cmd == "start":
        pid = start(args.device)
        print(pid)
        return 0 if pid else 1
    if args.cmd == "stop":
        stop()
        return 0
    if args.cmd == "status":
        import json

        print(json.dumps(status()))
        return 0
    if args.cmd == "snap":
        path = snap(args.nonce, device=args.device)
        if not path:
            return 1
        print(path)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
