## Learned User Preferences

- Screensaver dismissal should be key press or mouse click only; pointer motion must not dismiss it.
- Keep honeypot state file-backed (short-lived burnable links with expiry); do not introduce a database.
- Prefer a live scan alarm on the laptop plus phone talk-back (WebSocket / voice notes) over a form-only honeypot.

## Learned Workspace Facts

- OmaNosey is Omarchy plugin `wizwam.omanosey`: a Python honeypot plus GTK/WebKit fullscreen windows with class `org.omarchy.screensaver` (one per monitor; cursor hidden while up).
- Local honeypot defaults to port 8765; private state lives under `~/.local/state/omarchy/omanosey/private/` (mode 0700).
- QR links expire after about two minutes and burn after one use; phone desk UI is `/?desk` with hold-to-talk over `/ws`.
- Prefer the wireless LAN IP for phone-facing URLs over the default-route/wired address; when LAN cannot reach the phone, Tailscale HTTPS to the local honeypot is an acceptable path.
- Phone QR burn links use config `phone_base` when set (currently Tailscale Serve `https://ytomarchy1.tailbec7fd.ts.net:9443`). Desk talk-back needs WebSockets: use `http://ytomarchy1.tailbec7fd.ts.net:8765/?desk` — Serve on `:9443` returns HTML but `/ws` is 502.
- Screensaver launch warms the local USB webcam (`backend/camera.py`, default `/dev/video0`); a QR scan freezes a JPEG under `private/snaps/` and the visitor page polls `/snap/<nonce>.jpg` to show them.
- Local installs often symlink this checkout as `~/.config/omarchy/plugins/wizwam.omanosey` and may point `~/.local/bin/omarchy-launch-screensaver` at OmaNosey's dispatcher.
- Screensaver diagnostics: `omarchy-launch-screensaver force debug` (or panel **Debug preview**) holds the QR open until Esc; mouse/focus/other keys are logged and ignored. Lifecycle lines go to `~/.local/state/omarchy/omanosey/screensaver.log` — after a flash-and-gone idle close, `tail -n 40` that file (or `/usr/bin/python3 backend/debuglog.py tail`) and look for `action=quit` (`motion`/`key`/`button`/`focus-out`/`signal`). Pulling the plugin checkout picks this up without reinstall; rescan plugins or restart the shell if Panel.qml has no debug row.
