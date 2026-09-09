#!/usr/bin/env bash
# Clear GraphHopper's imported routing graph so it re-imports region.osm.pbf on
# next start. Run this after replacing the OSM extract.
set -euo pipefail

CACHE_DIR="${GRAPH_CACHE_DIR:-./data/graph-cache}"

echo "Stopping GraphHopper if running..."
podman compose stop graphhopper 2>/dev/null || true

echo "Removing imported GraphHopper graph cache in ${CACHE_DIR} ..."
rm -rf "${CACHE_DIR:?}/"* 2>/dev/null || true

echo "Done. Start the stack again with:"
echo "  podman compose up -d"
