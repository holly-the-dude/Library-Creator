#!/bin/bash
set -euo pipefail

umask 077
mkdir -p "${DATA_DIR:-/var/lib/meshtastic}" /run
nginx -t

bridge_pid=
nginx_pid=
stop_services() {
    trap - TERM INT
    [ -z "$bridge_pid" ] || kill -TERM "$bridge_pid" 2>/dev/null || true
    [ -z "$nginx_pid" ] || kill -QUIT "$nginx_pid" 2>/dev/null || true
    wait || true
}
trap 'stop_services; exit 0' TERM INT

python3 -u /opt/meshtastic/bridge.py &
bridge_pid=$!
nginx -g 'daemon off;' &
nginx_pid=$!

status=0
wait -n "$bridge_pid" "$nginx_pid" || status=$?
echo "A Meshtastic service exited (status $status); stopping container."
stop_services
if [ "$status" -eq 0 ]; then status=1; fi
exit "$status"
