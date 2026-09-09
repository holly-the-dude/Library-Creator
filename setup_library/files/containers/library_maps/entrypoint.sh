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

echo "Starting nginx on port 8080..."
exec nginx -g "daemon off;"
