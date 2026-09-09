#!/usr/bin/env bash
# Download (or link) the OSM extract GraphHopper routes on, normalized to the
# fixed name region.osm.pbf inside the routing data directory.
#
# Usage:
#   ./scripts/get-osm.sh colorado                 # download Colorado from Geofabrik
#   ./scripts/get-osm.sh us                        # download whole US (very large)
#   ./scripts/get-osm.sh /path/to/existing.osm.pbf # use a local file you already have
set -euo pipefail

# OSM_DIR must match compose.yaml's graphhopper OSM mount source. It lives
# under the maps volume so it rides the same USB mount as the PMTiles.
OSM_DIR="${OSM_DIR:-/Library/maps/osm}"
OUT="${OSM_DIR}/region.osm.pbf"
mkdir -p "$OSM_DIR"

ARG="${1:-colorado}"

# Case 1: an existing local .osm.pbf path was given -> link/copy it into place.
if [[ -f "$ARG" ]]; then
  echo "Using local extract: $ARG"
  rm -f "$OUT"
  if ln "$ARG" "$OUT" 2>/dev/null; then
    echo "Hardlinked -> $OUT"
  else
    cp -f "$ARG" "$OUT"
    echo "Copied -> $OUT"
  fi
  echo "Routing PBF ready: $OUT"
  echo "If GraphHopper imported older data, run: ./scripts/reset-routing-cache.sh"
  exit 0
fi

# Case 2: a region name -> download from Geofabrik.
slug="$(printf '%s' "$ARG" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')"
if [[ "$slug" == "us" || "$slug" == "usa" || "$slug" == "united-states" ]]; then
  URL="https://download.geofabrik.de/north-america/us-latest.osm.pbf"
else
  URL="https://download.geofabrik.de/north-america/us/${slug}-latest.osm.pbf"
fi

echo "Downloading routing data:"
echo "  $URL"
echo "  -> $OUT"
echo "curl uses resume + retries, so re-running after an interruption is safe."

curl -fL -C - \
  --retry 999 \
  --retry-delay 5 \
  --retry-all-errors \
  --output "$OUT" \
  "$URL"

echo
echo "Routing PBF ready: $OUT"
echo "If GraphHopper already imported older data, run:"
echo "  ./scripts/reset-routing-cache.sh"
