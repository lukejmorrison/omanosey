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

import gi

gi.require_version("Gtk", "3.0")
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
    # Same pattern as stock omarchy-screensaver: one dismiss tears down every monitor.
    _run(["pkill", "-f", f"[o]rg.omarchy.screensaver"])


class ScreensaverWindow(Gtk.Window):
    def __init__(self, url: str) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title(APP_CLASS)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.fullscreen()
        self.armed = False
        self.connect("destroy", self._quit)
        self.connect("key-press-event", self._on_input)
        self.connect("button-press-event", self._on_input)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("focus-out-event", self._on_focus_out)
        self.add_events(
            Gdk.EventMask.KEY_PRESS_MASK
            | Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.FOCUS_CHANGE_MASK
        )

        view = WebKit2.WebView()
        settings = view.get_settings()
        settings.set_enable_javascript(True)
        settings.set_allow_file_access_from_file_urls(True)
        view.load_uri(url)
        self.add(view)
        GLib.timeout_add(GRACE_MS, self._arm)

    def _arm(self) -> bool:
        self.armed = True
        return False

    def _on_input(self, *_args) -> bool:
        if self.armed:
            self._quit()
        return True

    def _on_motion(self, *_args) -> bool:
        if self.armed:
            self._quit()
        return False

    def _on_focus_out(self, *_args) -> bool:
        if not self.armed:
            return False
        try:
            raw = subprocess.check_output(
                ["hyprctl", "activewindow", "-j"],
                text=True,
                timeout=0.4,
            )
            data = json.loads(raw)
            if str(data.get("class") or "") == APP_CLASS:
                return False
        except Exception:
            pass
        self._quit()
        return False

    def _quit(self, *_args) -> None:
        kill_all()
        Gtk.main_quit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--class", dest="wm_class", default=APP_CLASS)
    parser.add_argument("--monitor", default="")
    args = parser.parse_args(argv)

    GLib.set_prgname(args.wm_class)
    Gdk.set_program_class(args.wm_class)
    os.environ["GDK_BACKEND"] = os.environ.get("GDK_BACKEND", "wayland")

    hide_cursor(True)
    win = ScreensaverWindow(args.url)
    win.show_all()

    def _signal(_signum, _frame) -> None:
        kill_all()
        Gtk.main_quit()

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
