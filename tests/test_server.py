#!/usr/bin/env python3
"""HTTP-level tests for the Nosey honeypot."""

from __future__ import annotations

import http.client
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


class NoseyServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        os.environ["XDG_STATE_HOME"] = cls.tmpdir.name
        os.environ["XDG_CONFIG_HOME"] = cls.tmpdir.name
        import sys

        sys.path.insert(0, str(BACKEND))
        import server as nosey

        cls.nosey = nosey
        cls.httpd = nosey.make_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        deadline = time.time() + 2
        while time.time() < deadline:
            if nosey.health_ok("127.0.0.1", cls.port):
                break
            time.sleep(0.02)
        else:
            raise RuntimeError("test server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmpdir.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        hdrs = headers or {}
        if body is not None:
            payload = body.encode("utf-8") if isinstance(body, str) else body
            hdrs = dict(hdrs)
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
            hdrs["Content-Length"] = str(len(payload))
            conn.request(method, path, body=payload, headers=hdrs)
        else:
            conn.request(method, path, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data, dict(resp.getheaders())

    def test_healthz(self):
        status, body, _ = self.request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertIn(b"ok", body)

    def test_css_is_served(self):
        status, body, headers = self.request("GET", "/public/nosey.css")
        self.assertEqual(status, 200)
        self.assertIn(b".owner", body)
        self.assertIn("text/css", headers.get("Content-Type", ""))

    def test_unattended_qr_page(self):
        status, body, _ = self.request("GET", "/?unattended")
        self.assertEqual(status, 200)
        self.assertIn(b'id="qr"', body)
        self.assertIn(b"?rand=", body)
        self.assertIn(b"Leave this on screen", body)

    def test_expired_rand(self):
        status, body, _ = self.request("GET", "/?rand=" + ("a" * 32))
        self.assertEqual(status, 404)
        self.assertIn(b"Nothing to see here", body)

    def test_form_nudge_then_thanks_then_oi(self):
        _, unattended, _ = self.request("GET", "/?unattended")
        text = unattended.decode("utf-8")
        marker = "?rand="
        start = text.find(marker)
        self.assertGreater(start, 0)
        nonce = text[start + len(marker) : start + len(marker) + 32]
        self.assertEqual(len(nonce), 32)

        status, body, _ = self.request("GET", "/?rand=" + nonce)
        self.assertEqual(status, 200)
        self.assertIn(b"Nosey Bugger", body)

        status, body, _ = self.request(
            "POST",
            "/?rand=" + nonce,
            body=urlencode({"nonce": nonce, "comment": ""}),
        )
        self.assertEqual(status, 200)
        self.assertIn(b"nosey enough", body)

        status, body, headers = self.request(
            "POST",
            "/?rand=" + nonce,
            body=urlencode({"nonce": nonce, "comment": "hello from tests"}),
        )
        self.assertEqual(status, 200)
        self.assertIn(b"Thanks!", body)
        set_cookie = headers.get("Set-Cookie") or headers.get("set-cookie") or ""
        self.assertIn("seen=", set_cookie)

        cookie = set_cookie.split(";", 1)[0]
        status, body, _ = self.request("GET", "/?rand=" + nonce, headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn(b"once enough", body)
        self.assertIn(b"screen-oi", body)

    def test_looks_like_nosey(self):
        self.assertTrue(self.nosey.looks_like_nosey(b'<div id="qr"></div>'))
        self.assertFalse(self.nosey.looks_like_nosey(b"<hr>Smashing<hr>"))

    def test_static_traversal_rejected(self):
        status, _, _ = self.request("GET", "/public/../backend/server.py")
        self.assertEqual(status, 404)


class ConfigTests(unittest.TestCase):
    def test_save_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["XDG_CONFIG_HOME"] = tmp
            os.environ["XDG_STATE_HOME"] = tmp
            import importlib
            import sys

            sys.path.insert(0, str(BACKEND))
            import config as cfg

            importlib.reload(cfg)
            saved = cfg.save_config({"idle": False, "port": 9001, "public_url": "https://example.test"})
            self.assertFalse(saved["idle"])
            self.assertEqual(saved["port"], 9001)
            loaded = cfg.load_config()
            self.assertEqual(loaded["public_url"], "https://example.test")
            self.assertEqual(loaded["port"], 9001)


if __name__ == "__main__":
    unittest.main()
