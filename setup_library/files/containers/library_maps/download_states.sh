#!/bin/bash
#
# download_states.sh
#
# Downloads all US state PMTiles files from project-nomad-maps.
# Files are stored in ../maps/pmtiles/ relative to this script.
#
# Usage:
#   ./download_states.sh              # Download all states
#   ./download_states.sh alabama oregon  # Download specific states
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/../maps/pmtiles"
BASE_URL="https://github.com/Crosstalk-Solutions/project-nomad-maps/raw/refs/heads/master/pmtiles"

ALL_STATES=(
  alabama
  alaska
  arizona
  arkansas
  california
  colorado
  connecticut
  delaware
  florida
  georgia
  hawaii
  idaho
  illinois
  indiana
  iowa
  kansas
  kentucky
  louisiana
  maine
  maryland
  massachusetts
  michigan
  minnesota
  mississippi
  missouri
  montana
  nebraska
  nevada
  new_hampshire
  new_jersey
  new_mexico
  new_york
  north_carolina
  north_dakota
  ohio
  oklahoma
  oregon
  pennsylvania
  rhode_island
  south_carolina
  south_dakota
  tennessee
  texas
  utah
  vermont
  virginia
  washington
  west_virginia
  wisconsin
  wyoming
)

# Use command-line args if provided, otherwise download all
if [ $# -gt 0 ]; then
  STATES=("$@")
else
  STATES=("${ALL_STATES[@]}")
fi

mkdir -p "$OUTPUT_DIR"

echo "=== Downloading ${#STATES[@]} state PMTiles files ==="
echo "Output directory: $OUTPUT_DIR"
echo ""

DOWNLOADED=0
FAILED=0

for state in "${STATES[@]}"; do
  FILENAME="${state}_2025-12.pmtiles"
  OUTPUT_FILE="${OUTPUT_DIR}/${FILENAME}"

  if [ -f "$OUTPUT_FILE" ] && [ "$(stat -f%z "$OUTPUT_FILE" 2>/dev/null || stat -c%s "$OUTPUT_FILE" 2>/dev/null)" -gt 1000 ]; then
    echo "[SKIP] ${FILENAME} (already exists)"
    DOWNLOADED=$((DOWNLOADED + 1))
    continue
  fi

  echo "[DOWN] ${FILENAME}..."
  if curl -L -f --progress-bar -o "$OUTPUT_FILE" "${BASE_URL}/${FILENAME}"; then
    SIZE=$(ls -lh "$OUTPUT_FILE" | awk '{print $5}')
    echo "       Done (${SIZE})"
    DOWNLOADED=$((DOWNLOADED + 1))
  else
    echo "       FAILED"
    rm -f "$OUTPUT_FILE"
    FAILED=$((FAILED + 1))
  fi
done

echo ""
echo "=== Complete ==="
echo "Downloaded: ${DOWNLOADED}"
echo "Failed: ${FAILED}"
echo "Location: ${OUTPUT_DIR}"
