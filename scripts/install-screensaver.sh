#!/usr/bin/env bash
# Point ~/.local/bin/omarchy-launch-screensaver at OmaNosey's dispatcher.
# Saves the previous launcher so idle=false restores Kingdom Age / stock.
set -euo pipefail

here=$(CDPATH= cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd)
plugin=$(CDPATH= cd -- "$here/.." && pwd)
dispatcher="$plugin/scripts/omarchy-launch-screensaver"
bin="${HOME}/.local/bin/omarchy-launch-screensaver"
state="${XDG_STATE_HOME:-$HOME/.local/state}/omarchy/omanosey"
prev="$state/previous-launch"

mkdir -p "$HOME/.local/bin" "$state"

if [[ -e $bin || -L $bin ]]; then
  current=$(readlink -f -- "$bin" 2>/dev/null || true)
  if [[ -n $current && $current != "$dispatcher" && ! -f $prev ]]; then
    printf '%s\n' "$current" > "$prev"
  fi
fi

ln -sfn "$dispatcher" "$bin"
echo "Screensaver dispatcher: $bin -> $dispatcher"
if [[ -f $prev ]]; then
  echo "Previous launcher saved at $prev: $(tr -d '\n' < "$prev")"
fi
