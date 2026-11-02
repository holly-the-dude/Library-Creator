#!/usr/bin/env bash
set -euo pipefail
app=$(basename "$0")
case "$app" in wordcraft|deckcraft|gridcraft) ;; *) exit 1 ;; esac
# Keep preferences on native storage while file pickers start in shared documents.
export XDG_CONFIG_HOME=/config/.config XDG_CACHE_HOME=/config/.cache
export XDG_DATA_HOME=/config/.local/share XDG_STATE_HOME=/config/.local/state
export HOME=/documents
cd /documents
exec "/usr/bin/$app" "$@"
