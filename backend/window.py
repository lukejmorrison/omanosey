#!/usr/bin/env python3
"""Fullscreen WebKit window with class org.omarchy.screensaver."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from typing import Any

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from debuglog import dismiss_action, write_event  # noqa: E402

# GTK3 WebKit on native Wayland hits Error 71 (protocol error) on this Hyprland
# setup. Force XWayland unless the user overrides GDK_BACKEND.
if not os.environ.get("OMANOSEY_GDK_BACKEND"):
    os.environ["GDK_BACKEND"] = "x11"
else:
    os.environ["GDK_BACKEND"] = os.environ["OMANOSEY_GDK_BACKEND"]
if os.environ.get("GDK_BACKEND") == "x11":
    os.environ.pop("WAYLAND_DISPLAY", None)
    # XWayland + WebKit HW compositing often paints a blank white view even when
    # the DOM (and QR probe) succeed. Software rendering keeps pixels on screen.
    os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, GLib, Gtk, WebKit2  # noqa: E402

APP_CLASS = "org.omarchy.screensaver"
GRACE_MS = 1500


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def hide_cursor(hidden: bool) -> None:
    flag = "true" if hidden else "false"
    _run(["hyprctl", "eval", f"hl.config({{ cursor = {{ invisible = {flag} }} }})"])
    _run(["hyprctl", "keyword", "cursor:invisible", flag])


def kill_all() -> None:
    hide_cursor(False)
    try:
        from camera import stop as camera_stop

        camera_stop()
    except Exception:
        pass
    # Match window.py argv only — a bare class string also hits launchers/shells that
    # mention org.omarchy.screensaver in their command line.
    _run(["pkill", "-f", "backend/window.py .*--class=org.omarchy.screensaver"])


def _load_event_name(event: object) -> str:
    try:
        value = int(event)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(event)
    names = {
        int(WebKit2.LoadEvent.STARTED): "started",
        int(WebKit2.LoadEvent.REDIRECTED): "redirected",
        int(WebKit2.LoadEvent.COMMITTED): "committed",
        int(WebKit2.LoadEvent.FINISHED): "finished",
    }
    return names.get(value, str(value))


class ScreensaverWindow(Gtk.Window):
    def __init__(self, url: str, *, debug: bool = False, monitor: str = "", wm_class: str = APP_CLASS) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title(wm_class)
        # XWayland ignores Gdk.set_program_class for WM_CLASS; without this Hypr
        # sees class "Window.py" and skips the screensaver fullscreen rules.
        try:
            self.set_wmclass(wm_class, wm_class)
        except Exception:
            pass
        self.set_decorated(False)
        # Hypr windowrules already force fullscreen for org.omarchy.screensaver.
        self.set_keep_above(True)
        self.fullscreen()
        self._url = url
        self.debug = debug
        self._monitor = monitor
        self.armed = False
        self._closed = False
        self._motion_count = 0
        self._last_motion_log = 0.0
        self._load_state = "idle"
        self._qr_state = "pending"
        self._recent: list[str] = []
        self._hud: Gtk.Label | None = None
        self.connect("destroy", self._on_destroy)
        self.connect("key-press-event", self._on_key)
        self.connect("button-press-event", self._on_button)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("focus-out-event", self._on_focus_out)
        self.connect("map-event", self._on_map)
        self.add_events(
            Gdk.EventMask.KEY_PRESS_MASK
            | Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.FOCUS_CHANGE_MASK
        )

        view = WebKit2.WebView()
        self.view = view
        settings = view.get_settings()
        settings.set_enable_javascript(True)
        settings.set_allow_file_access_from_file_urls(True)
        try:
            settings.set_hardware_acceleration_policy(
                WebKit2.HardwareAccelerationPolicy.NEVER
            )
        except Exception:
            pass
        try:
            view.set_background_color(Gdk.RGBA(red=0.04, green=0.06, blue=0.12, alpha=1.0))
        except Exception:
            pass
        view.set_hexpand(True)
        view.set_vexpand(True)
        view.connect("load-changed", self._on_load_changed)
        view.connect("load-failed", self._on_load_failed)
        self._connect_optional(view, "load-failed-with-tls-errors", self._on_tls_failed)
        self._connect_optional(view, "console-message", self._on_console)
        view.load_uri(url)

        if debug:
            overlay = Gtk.Overlay()
            overlay.add(view)
            self._hud = self._build_hud()
            overlay.add_overlay(self._hud)
            self.add(overlay)
        else:
            self.add(view)
        self._record("start", action="ignore", url=url, grace_ms=GRACE_MS)
        GLib.timeout_add(GRACE_MS, self._arm)

    def _connect_optional(self, obj: object, signal_name: str, handler: object) -> None:
        try:
            obj.connect(signal_name, handler)  # type: ignore[attr-defined]
        except Exception as exc:
            self._record("signal-skip", action="ignore", signal=signal_name, error=type(exc).__name__)

    def _build_hud(self) -> Gtk.Label:
        label = Gtk.Label()
        label.set_name("nosey-debug")
        label.set_halign(Gtk.Align.START)
        label.set_valign(Gtk.Align.END)
        label.set_margin_start(16)
        label.set_margin_end(16)
        label.set_margin_bottom(16)
        label.set_xalign(0)
        label.set_line_wrap(True)
        label.set_max_width_chars(96)
        label.set_selectable(False)
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b"label#nosey-debug {"
            b" background-color: rgba(0, 0, 0, 0.82);"
            b" color: #d6ffe1;"
            b" font-family: monospace;"
            b" font-size: 12pt;"
            b" padding: 10px 12px;"
            b"}"
        )
        screen = Gdk.Screen.get_default()
        if screen is not None:
            Gtk.StyleContext.add_provider_for_screen(
                screen,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
        self._refresh_hud(label)
        return label

    def _refresh_hud(self, label: Gtk.Label | None = None) -> None:
        hud = label if label is not None else self._hud
        if hud is None:
            return
        lines = [
            "OmaNosey debug — Esc dismisses; other input is held",
            f"url {self._url}",
            f"load {self._load_state}  qr {self._qr_state}  armed {self.armed}  motions {self._motion_count}",
        ]
        lines.extend(self._recent[-8:])
        hud.set_text("\n".join(lines))

    def _record(self, kind: str, **fields: Any) -> None:
        fields.setdefault("armed", self.armed)
        fields.setdefault("debug", self.debug)
        if self._monitor:
            fields.setdefault("monitor", self._monitor)
        line = write_event(kind, **fields)
        self._recent.append(line)
        del self._recent[:-12]
        self._refresh_hud()

    def _consider(self, kind: str, **fields: Any) -> None:
        key = str(fields.get("key") or "")
        action = dismiss_action(kind=kind, armed=self.armed, debug=self.debug, key=key)
        self._record(kind, action=action, **fields)
        if action == "quit":
            self._quit()

    def _arm(self) -> bool:
        self.armed = True
        self._record("armed", action="ignore", grace_ms=GRACE_MS, motions=self._motion_count)
        return False

    def _on_map(self, *_args: object) -> bool:
        self._record("mapped", action="ignore")
        return False

    def _on_key(self, _widget: object, event: object) -> bool:
        keyval = getattr(event, "keyval", 0)
        name = Gdk.keyval_name(keyval) or str(int(keyval))
        self._consider("key", key=name)
        return True

    def _on_button(self, _widget: object, event: object) -> bool:
        button = int(getattr(event, "button", 0))
        self._consider("button", button=button)
        return True

    def _on_motion(self, _widget: object, event: object) -> bool:
        self._motion_count += 1
        action = dismiss_action(kind="motion", armed=self.armed, debug=self.debug)
        now = time.monotonic()
        should_log = action == "quit" or self._motion_count == 1 or now - self._last_motion_log >= 0.5
        if should_log:
            self._last_motion_log = now
            x = round(float(getattr(event, "x", 0.0)), 1)
            y = round(float(getattr(event, "y", 0.0)), 1)
            self._record("motion", action=action, x=x, y=y, count=self._motion_count)
        elif self.debug:
            self._refresh_hud()
        if action == "quit":
            self._quit()
        return False

    def _active_window_class(self) -> tuple[str, str]:
        try:
            raw = subprocess.check_output(
                ["hyprctl", "activewindow", "-j"],
                text=True,
                timeout=0.4,
            )
            data = json.loads(raw)
            return str(data.get("class") or ""), ""
        except Exception as exc:
            return "", type(exc).__name__

    def _on_focus_out(self, *_args: object) -> bool:
        active, error = self._active_window_class()
        if active == APP_CLASS:
            self._record("focus-out", action="ignore", active=active)
            return False
        fields: dict[str, Any] = {"active": active}
        if error:
            fields["error"] = error
        self._consider("focus-out", **fields)
        return False

    def _on_load_changed(self, webview: WebKit2.WebView, event: object) -> None:
        name = _load_event_name(event)
        self._load_state = name
        try:
            uri = webview.get_uri() or ""
        except Exception:
            uri = ""
        self._record("load", action="ignore", state=name, uri=uri)
        if name == "finished":
            self._probe_qr()

    def _on_load_failed(self, _webview: object, event: object, uri: object, error: object) -> bool:
        self._load_state = "failed"
        message = getattr(error, "message", None) or str(error)
        self._record(
            "load-failed",
            action="ignore",
            state=_load_event_name(event),
            uri=str(uri),
            error=str(message),
        )
        return False

    def _on_tls_failed(self, _webview: object, uri: object, _certificate: object, errors: object) -> bool:
        self._load_state = "tls-error"
        self._record("tls-error", action="ignore", uri=str(uri), errors=str(errors))
        return False

    def _on_console(self, _webview: object, message: object) -> bool:
        text = getattr(message, "get_text", None)
        body = text() if callable(text) else str(message)
        self._record("console", action="ignore", text=str(body)[:300])
        return False

    def _probe_qr(self) -> None:
        script = (
            "(function(){"
            "var el=document.getElementById('qr');"
            "var text=document.body?document.body.innerText.slice(0,180):'';"
            "if(!el) return JSON.stringify({qr:false,title:document.title,text:text});"
            "return JSON.stringify({qr:true,svg:!!el.querySelector('svg'),bytes:el.innerHTML.length,title:document.title,text:text});"
            "})()"
        )
        try:
            self.view.run_javascript(script, None, self._on_qr_probe, None)
        except Exception as exc:
            self._qr_state = "probe-failed"
            self._record("qr-probe-failed", action="ignore", error=str(exc))

    def _on_qr_probe(self, webview: object, result: object, *_args: object) -> None:
        try:
            js_result = webview.run_javascript_finish(result)  # type: ignore[attr-defined]
            raw = js_result.get_js_value().to_string()
        except Exception as exc:
            self._qr_state = "probe-failed"
            self._record("qr-probe-failed", action="ignore", error=str(exc))
            return
        self._qr_state = raw
        self._record("qr", action="ignore", detail=raw)

    def _on_destroy(self, *_args: object) -> None:
        if not self._closed:
            self._record("destroy", action="quit")
        self._quit()

    def _quit(self, *_args: object) -> None:
        if self._closed:
            return
        self._closed = True
        # Debug hold: close only this window so a bad monitor cannot wipe the
        # others via kill_all while we are diagnosing.
        if self.debug:
            hide_cursor(False)
            try:
                Gtk.Window.destroy(self)
            except Exception:
                pass
            Gtk.main_quit()
            return
        kill_all()
        Gtk.main_quit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--class", dest="wm_class", default=APP_CLASS)
    parser.add_argument("--monitor", default="")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="hold the screensaver open, log dismiss causes, and show them on screen; Esc closes",
    )
    args = parser.parse_args(argv)

    GLib.set_prgname(args.wm_class)
    Gdk.set_program_class(args.wm_class)

    hide_cursor(not args.debug)
    win = ScreensaverWindow(
        args.url, debug=args.debug, monitor=args.monitor, wm_class=args.wm_class
    )
    win.show_all()

    def _signal(signum: int, _frame: object) -> None:
        if not win._closed:
            win._record("signal", action="quit", signum=int(signum))
        win._quit()

    signal.signal(signal.SIGINT, _signal)
    signal.signal(signal.SIGTERM, _signal)
    signal.signal(signal.SIGHUP, _signal)

    # Give Hyprland a beat to map us onto the focused monitor.
    time.sleep(0.05)
    Gtk.main()
    hide_cursor(False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
