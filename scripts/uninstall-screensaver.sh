#!/usr/bin/env bash
set -euo pipefail

here=$(CDPATH= cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd)
plugin=$(CDPATH= cd -- "$here/.." && pwd)
bin="${HOME}/.local/bin/omarchy-launch-screensaver"
dispatcher="$plugin/scripts/omarchy-launch-screensaver"
prev="${XDG_STATE_HOME:-$HOME/.local/state}/omarchy/omanosey/previous-launch"

if [[ -L $bin ]]; then
  current=$(readlink -f -- "$bin" 2>/dev/null || true)
  if [[ $current == "$dispatcher" ]]; then
    rm -f -- "$bin"
    if [[ -f $prev ]]; then
      target=$(tr -d '\n' < "$prev")
      if [[ -x $target ]]; then
        ln -sfn "$target" "$bin"
        echo "Restored previous screensaver launcher: $bin -> $target"
        exit 0
      fi
    fi
    echo "Removed OmaNosey screensaver dispatcher."
  fi
fi
