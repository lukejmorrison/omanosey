#!/usr/bin/env bash
set -euo pipefail

source_root=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$source_root"

command -v omarchy >/dev/null 2>&1 || {
  echo "test.sh: omarchy is required" >&2
  exit 1
}

omarchy plugin validate .

python3 -m py_compile backend/config.py backend/server.py
/usr/bin/python3 -m py_compile backend/window.py

python3 -m unittest discover -s tests -v

for script in scripts/omarchy-launch-screensaver scripts/omarchy-launch-screensaver-omanosey scripts/install-screensaver.sh scripts/uninstall-screensaver.sh scripts/install-local.sh; do
  [[ -x $script ]] || chmod +x "$script"
  bash -n "$script"
done

if command -v qmllint >/dev/null 2>&1 || [[ -x /usr/lib/qt6/bin/qmllint ]]; then
  qmlint_bin=$(command -v qmllint 2>/dev/null || true)
  [[ -n $qmlint_bin ]] || qmlint_bin=/usr/lib/qt6/bin/qmllint
  "$qmlint_bin" -I /usr/share/omarchy/shell Model.js Service.qml Panel.qml || true
fi

echo "All validation and tests passed."
