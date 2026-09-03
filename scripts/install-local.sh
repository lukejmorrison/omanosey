#!/usr/bin/env bash
set -euo pipefail

source_root=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
section=right
plugin_id=wizwam.omanosey
reinstall=0

usage() {
  cat <<'EOF'
Usage: scripts/install-local.sh [--section left|center|right] [--reinstall]

Validate this checkout, link it into ~/.config/omarchy/plugins/wizwam.omanosey,
enable the bar widget, and install the idle screensaver dispatcher.
EOF
}

while (( $# > 0 )); do
  case $1 in
    --section)
      [[ $# -ge 2 ]] || { echo "install-local.sh: --section requires a value" >&2; exit 2; }
      section=$2
      shift 2
      ;;
    --reinstall)
      reinstall=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "install-local.sh: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ $section =~ ^(left|center|right)$ ]] || {
  echo "install-local.sh: section must be left, center, or right" >&2
  exit 2
}

command -v omarchy >/dev/null 2>&1 || {
  echo "install-local.sh: Omarchy is required" >&2
  exit 1
}

chmod +x "$source_root"/scripts/*.sh "$source_root"/scripts/omarchy-launch-screensaver "$source_root"/scripts/omarchy-launch-screensaver-omanosey
omarchy plugin validate "$source_root"

plugins_root="${XDG_CONFIG_HOME:-"$HOME/.config"}/omarchy/plugins"
target="$plugins_root/$plugin_id"
install -d -m 700 -- "$plugins_root"

if [[ $reinstall -eq 1 && ( -e $target || -L $target ) ]]; then
  echo "Removing $target (--reinstall)"
  rm -rf -- "$target"
fi

if [[ -L $target && $(readlink -f -- "$target") == "$source_root" ]]; then
  echo "Local plugin link already points at this checkout."
elif [[ -e $target || -L $target ]]; then
  echo "install-local.sh: refusing to replace existing path: $target (pass --reinstall)" >&2
  exit 1
else
  ln -s -- "$source_root" "$target"
  echo "Linked local plugin: $target -> $source_root"
fi

"$source_root/scripts/install-screensaver.sh"

omarchy-shell shell rescanPlugins >/dev/null || true
discovered=0
for (( attempt = 0; attempt < 40; attempt++ )); do
  if omarchy plugin list --json | python3 -c 'import json,sys; data=json.load(sys.stdin); raise SystemExit(0 if any(item.get("id")=="wizwam.omanosey" for item in data) else 1)'; then
    discovered=1
    break
  fi
  sleep 0.05
done
(( discovered )) || {
  echo "install-local.sh: Omarchy did not discover $plugin_id" >&2
  exit 1
}

if [[ $section == right ]]; then
  omarchy plugin enable "$plugin_id" --section right --before omarchy.tray
elif [[ $section == center ]]; then
  omarchy plugin enable "$plugin_id" --section center --before omarchy.clock
else
  omarchy plugin enable "$plugin_id" --section left --after omarchy.workspaces
fi

echo "Installed. Click the OmaNosey QR chip. Right-click previews the screensaver."
