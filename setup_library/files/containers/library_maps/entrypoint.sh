#!/bin/bash
set -e

echo "=== library_maps starting ==="
echo "PMTiles version: $(pmtiles version)"
echo "Map storage: /storage/maps"

# List available .pmtiles files
PMTILES_DIR="/storage/maps/pmtiles"
if [ -d "$PMTILES_DIR" ] && [ "$(ls -A $PMTILES_DIR/*.pmtiles 2>/dev/null)" ]; then
    echo "Available map files:"
    ls -lh "$PMTILES_DIR"/*.pmtiles | awk '{print "  " $NF " (" $5 ")"}'
else
    echo "No .pmtiles files found in $PMTILES_DIR"
    echo "Mount your pmtiles files to /storage/maps/pmtiles/"
fi

# Ensure nginx pid directory exists
mkdir -p /run

# Keep both processes under this entrypoint so container stop reaches the serial
# reader, and an unexpected process exit lets the restart policy recover it.
gps_pid=
nginx_pid=
stop_services() {
    # Prevent another stop signal from recursively entering this cleanup.
    trap - TERM INT
    # Python handles TERM to close its reader; QUIT gracefully drains nginx.
    # A child may already have exited, so missing-process errors are expected.
    [ -z "$gps_pid" ] || kill -TERM "$gps_pid" 2>/dev/null || true
    [ -z "$nginx_pid" ] || kill -QUIT "$nginx_pid" 2>/dev/null || true
    # Reap both children before the entrypoint (container PID 1) exits.
    wait || true
}
# An operator-requested stop is successful, unlike an unexpected child exit.
trap 'stop_services; exit 0' TERM INT

echo "Starting serial GPS status service..."
# Unbuffered Python output makes connection/startup messages visible in logs.
python3 -u /usr/local/lib/library_maps/gps_service.py &
gps_pid=$!

echo "Starting nginx on port 8080..."
# Keep nginx attached to this PID; daemonizing would defeat child supervision.
nginx -g "daemon off;" &
nginx_pid=$!

status=0
# Capture the first child's exit even under set -e, then shut down its sibling.
wait -n "$gps_pid" "$nginx_pid" || status=$?
echo "A maps service exited (status $status); stopping container."
stop_services
# A clean but unexpected child exit is still a failure of the running service.
if [ "$status" -eq 0 ]; then status=1; fi
exit "$status"
