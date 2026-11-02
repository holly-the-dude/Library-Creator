#!/usr/bin/env bash
set -euo pipefail
# Rootful Podman matches the appliance's start_library.yml.
if [[ $EUID -ne 0 ]]; then
    echo 'Run with sudo: sudo bash start.sh' >&2
    exit 1
fi
documents=${CRAFT_DOCUMENTS:-/Library/documents}
config=${CRAFT_CONFIG:-craft-apps-config}
if podman image exists localhost/craft_apps:dontrun; then
    echo 'Office is disabled. Enable the add-on with set-enabled.sh yes first.' >&2
    exit 1
else
    status=$?
    [[ $status == 1 ]] || exit "$status"
fi
podman image exists localhost/craft_apps:latest
# exFAT cannot store Unix ownership or desktop symlinks. Leave document ownership
# intact and keep settings in a native Podman volume by default.
mkdir -p "$documents"
craft_uid=${PUID:-$(stat -c %u "$documents")}
craft_gid=${PGID:-$(stat -c %g "$documents")}
if [[ "$config" == /* ]]; then
    mkdir -p "$config"
fi
exec podman run -d --name craft_apps --replace --restart unless-stopped \
    --network=podman --ip=10.88.0.218 --shm-size=1g \
    -p "${CRAFT_PORT:-3001}:3001" \
    -e "PUID=$craft_uid" -e "PGID=$craft_gid" \
    -e "TZ=${TZ:-America/Denver}" \
    -v "$documents:/documents:rw" -v "$config:/config:rw" \
    localhost/craft_apps:latest
