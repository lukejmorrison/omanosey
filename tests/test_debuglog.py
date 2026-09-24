#!/usr/bin/env python3
"""Diagnostics for a screensaver that closes before the QR is visible."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import debuglog  # noqa: E402


class DismissActionTests(unittest.TestCase):
    def test_grace_ignores_input(self):
        self.assertEqual(debuglog.dismiss_action(kind="motion", armed=False, debug=False), "ignore")
        self.assertEqual(debuglog.dismiss_action(kind="key", armed=False, debug=False, key="a"), "ignore")
        self.assertEqual(debuglog.dismiss_action(kind="focus-out", armed=False, debug=False), "ignore")

    def test_armed_input_quits(self):
        self.assertEqual(debuglog.dismiss_action(kind="motion", armed=True, debug=False), "quit")
        self.assertEqual(debuglog.dismiss_action(kind="button", armed=True, debug=False), "quit")
        self.assertEqual(debuglog.dismiss_action(kind="key", armed=True, debug=False, key="space"), "quit")
        self.assertEqual(debuglog.dismiss_action(kind="focus-out", armed=True, debug=False), "quit")

    def test_debug_holds_until_escape(self):
        self.assertEqual(debuglog.dismiss_action(kind="motion", armed=True, debug=True), "hold")
        self.assertEqual(debuglog.dismiss_action(kind="focus-out", armed=True, debug=True), "hold")
        self.assertEqual(debuglog.dismiss_action(kind="key", armed=True, debug=True, key="space"), "hold")
        self.assertEqual(debuglog.dismiss_action(kind="key", armed=True, debug=True, key="Escape"), "quit")
        self.assertEqual(debuglog.dismiss_action(kind="key", armed=False, debug=True, key="ESC"), "quit")

    def test_signal_always_quits(self):
        self.assertEqual(debuglog.dismiss_action(kind="signal", armed=False, debug=True), "quit")
        self.assertEqual(debuglog.dismiss_action(kind="signal", armed=True, debug=False), "quit")


class DebugLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["XDG_STATE_HOME"] = self.tmp.name
        os.environ["XDG_CONFIG_HOME"] = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_event_line_quotes_spaces(self):
        line = debuglog.format_event("load-failed", error="timed out", uri="http://127.0.0.1/?unattended")
        self.assertIn("load-failed", line)
        self.assertIn('error="timed out"', line)
        self.assertIn("uri=http://127.0.0.1/?unattended", line)

    def test_write_and_tail(self):
        line = debuglog.write_event("armed", grace_ms=1500, motions=4)
        self.assertIn("armed", line)
        self.assertIn("motions=4", line)
        recent = debuglog.recent_events(5)
        self.assertEqual(recent, [line])
        self.assertTrue(str(debuglog.log_path()).endswith("screensaver.log"))

    def test_trim_keeps_newest(self):
        last = ""
        for i in range(10):
            last = debuglog.write_event("tick", n=i, max_bytes=40, keep_lines=3)
        recent = debuglog.recent_events(20)
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent[-1], last)
        self.assertIn("n=9", recent[-1])

    def test_cli_event(self):
        code = debuglog.main(["event", "spawn", "monitor=DP-1", "url=http://127.0.0.1:8765/?unattended"])
        self.assertEqual(code, 0)
        recent = debuglog.recent_events(5)
        self.assertEqual(len(recent), 1)
        self.assertIn("spawn", recent[0])
        self.assertIn("monitor=DP-1", recent[0])
        self.assertIn("url=http://127.0.0.1:8765/?unattended", recent[0])

    def test_missing_log_is_empty(self):
        self.assertEqual(debuglog.recent_events(8), [])


if __name__ == "__main__":
    unittest.main()
