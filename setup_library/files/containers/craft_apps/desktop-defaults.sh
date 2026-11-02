#!/usr/bin/env bash
set -euo pipefail
for icon in home filesystem trash removable; do
    xfconf-query --channel xfce4-desktop \
        --property "/desktop-icons/file-icons/show-$icon" \
        --create --type bool --set false
done
