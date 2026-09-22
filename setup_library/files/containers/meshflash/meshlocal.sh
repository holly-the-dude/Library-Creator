#!/bin/sh
# Build and launch the local TUI container. Run as root for USB hotplug support.
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run with sudo: USB hotplug cgroup rules require rootful Podman.' >&2
    exit 1
fi
cd "$(dirname "$0")"
podman build -t localhost/meshflash:latest -f Containerfile .
exec podman run -d --name meshflash --restart unless-stopped \
  -p 8086:8086 -v /dev:/host-dev:ro \
  --device-cgroup-rule='c 188:* rw' --device-cgroup-rule='c 166:* rw' \
  -e TTYD_CREDENTIAL="${TTYD_CREDENTIAL:-}" localhost/meshflash:latest
