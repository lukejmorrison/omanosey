# OmaNosey

Omarchy screensaver plugin that puts **Nosey Bugger** on the idle screen: a
fullscreen QR so anyone who peeks at an unattended Omarchy box can leave a
note, then get told off if they come back.

Plugin id `wizwam.omanosey`.

Idle still uses Omarchy's contract: windows with class `org.omarchy.screensaver`,
one per monitor, dismissed by a key or mouse move. Kingdom Age / stock ASCII
is saved and restored when you turn OmaNosey idle off.

## Install

```bash
omarchy plugin add https://github.com/lukejmorrison/omanosey.git --enable --yes
```

From a checkout:

```bash
./scripts/install-local.sh --section right
```

That also points `~/.local/bin/omarchy-launch-screensaver` at OmaNosey's
dispatcher (the previous launcher is remembered).

## Use

- Left-click the **QR** chip: panel
- Right-click: preview the screensaver now (`force`)
- Middle-click: toggle idle Nosey vs the previous screensaver
- Any key or mouse movement dismisses, same as stock Omarchy

If `https://e1.yahvehyireh.com/?unattended` is actually serving Nosey, the
screensaver kiosks that so phone scans work off your LAN. Otherwise OmaNosey
runs a local honeypot on port **8765** and the QR uses your LAN address.

Replies, bans, and cookie keys live in `~/.local/state/omarchy/omanosey/private/`
(mode 0700), outside the plugin tree.

## Verify

```bash
./scripts/test.sh
omarchy plugin list | awk '$1 == "wizwam.omanosey"'
/usr/bin/python3 backend/server.py status
```

## Remove

```bash
./scripts/uninstall-screensaver.sh
omarchy plugin disable wizwam.omanosey
omarchy plugin remove wizwam.omanosey --yes
```

## License

MIT. See [LICENSE](LICENSE).

Nosey Bugger UI and the unattended QR flow are a Python port of Matt's original
PHP honeypot. `web/public/qrcode.min.js` is Kazuhiko Arase's QR library.
