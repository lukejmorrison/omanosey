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
- **Debug preview** in the panel, or `omarchy-launch-screensaver force debug`, holds the screensaver open so you can see the QR. Mouse, focus, and keys other than Esc are logged and ignored. Esc dismisses.

If `https://e1.yahvehyireh.com/?unattended` is actually serving Nosey, the
screensaver kiosks that so phone scans work off your LAN. Otherwise OmaNosey
runs a local honeypot on port **8765** and the QR uses your LAN address.

Replies, bans, and cookie keys live in `~/.local/state/omarchy/omanosey/private/`
(mode 0700), outside the plugin tree.

## Debug a screensaver that vanishes

Every launch appends start, page-load, QR probe, and dismiss lines to
`~/.local/state/omarchy/omanosey/screensaver.log`, including the normal idle
path that closes before you can read the QR. The panel shows the latest lines
after you open it. From a checkout:

```bash
/usr/bin/python3 backend/debuglog.py tail
```

`action=quit` is what closed the window (`motion`, `key`, `button`, `focus-out`, `signal`). `action=ignore` during the 1.5s grace period did not. `qr` records whether the page actually drew the code.

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
