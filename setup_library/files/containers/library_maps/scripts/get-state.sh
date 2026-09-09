#!/usr/bin/env bash
#
# get-state.sh
#
# Download everything needed for one (or more) US state(s):
#   * PMTiles map tiles   -> ../maps/pmtiles/<state>_2025-12.pmtiles   (display)
#   * OSM .pbf extract     -> ../maps/osm/<state>.osm.pbf              (routing)
#
# The map viewer auto-discovers the PMTiles. GraphHopper routes on a single
# extract named region.osm.pbf, so when you request EXACTLY ONE state this
# script also activates that state for routing (copies/links it to
# region.osm.pbf and clears the stale routing graph so it re-imports).
#
# Usage:
#   ./scripts/get-state.sh georgia                 # tiles + pbf, activate routing
#   ./scripts/get-state.sh georgia florida         # tiles + pbf for both (no auto-activate)
#   ./scripts/get-state.sh --route georgia         # also (re)activate georgia for routing
#   ./scripts/get-state.sh --no-pbf georgia        # tiles only (no routing data)
#   ./scripts/get-state.sh --no-pmtiles georgia    # routing pbf only (no tiles)
#
# Notes:
#   * On a 2 GB Raspberry Pi, GraphHopper can only IMPORT state-sized extracts.
#     Multi-state / regional PBFs will run out of memory during import.
#   * Downloads resume on re-run (curl -C -), and existing files are skipped.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# library_maps root is one level up from scripts/. Maps live in ../maps
# relative to that root (i.e. /Library/maps on the Pi via the mounted volume).
MAPS_DIR="${MAPS_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)/../maps}"
PMTILES_DIR="${PMTILES_DIR:-$MAPS_DIR/pmtiles}"
OSM_DIR="${OSM_DIR:-$MAPS_DIR/osm}"
GRAPH_CACHE_DIR="${GRAPH_CACHE_DIR:-$MAPS_DIR/graph-cache}"

PMTILES_DATE="${PMTILES_DATE:-2025-12}"
PMTILES_BASE="https://github.com/Crosstalk-Solutions/project-nomad-maps/raw/refs/heads/master/pmtiles"
GEOFABRIK_BASE="https://download.geofabrik.de/north-america/us"

# ---- colors ----
if [[ -t 1 ]]; then
  RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
  CYAN=$'\033[0;36m'; BOLD=$'\033[1m'; NC=$'\033[0m'
else
  RED="" GREEN="" YELLOW="" CYAN="" BOLD="" NC=""
fi
info() { echo "${CYAN}[INFO]${NC} $*"; }
ok()   { echo "${GREEN}[ OK ]${NC} $*"; }
warn() { echo "${YELLOW}[WARN]${NC} $*"; }
err()  { echo "${RED}[FAIL]${NC} $*" >&2; }

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

# ---- parse args ----
DO_PMTILES=1
DO_PBF=1
ROUTE_STATE=""
STATES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-pmtiles) DO_PMTILES=0 ;;
    --no-pbf)     DO_PBF=0 ;;
    --route)      shift; ROUTE_STATE="${1:-}";;
    -h|--help)    usage 0 ;;
    -*)           err "unknown option: $1"; usage 1 ;;
    *)            STATES+=("$1") ;;
  esac
  shift
done

if [[ ${#STATES[@]} -eq 0 && -z "$ROUTE_STATE" ]]; then
  err "no state given"
  usage 1
fi

# Normalize a state name: viewer/pmtiles use underscores (new_york); Geofabrik
# uses hyphens (new-york). Accept either form on input.
norm_under() { printf '%s' "$1" | tr '[:upper:] ' '[:lower:]_' | tr '-' '_'; }
geo_slug()   { printf '%s' "$1" | tr '[:upper:] ' '[:lower:]-' | tr '_' '-'; }

# Download with resume + retries; skip if a non-trivial file already exists.
fetch() {
  local url="$1" out="$2" label="$3"
  if [[ -f "$out" ]] && [[ "$(stat -c%s "$out" 2>/dev/null || stat -f%z "$out" 2>/dev/null || echo 0)" -gt 100000 ]]; then
    ok "$label already present ($(du -h "$out" | cut -f1)) — skipping"
    return 0
  fi
  info "downloading $label"
  info "  $url"
  if curl -fL -C - --retry 20 --retry-delay 5 --retry-all-errors \
       --progress-bar -o "$out" "$url"; then
    ok "$label -> $out ($(du -h "$out" | cut -f1))"
    return 0
  else
    err "failed to download $label"
    # leave a partial file for resume unless it is empty
    [[ -s "$out" ]] || rm -f "$out"
    return 1
  fi
}

mkdir -p "$PMTILES_DIR" "$OSM_DIR"

FAILS=0

for state in "${STATES[@]}"; do
  us="$(norm_under "$state")"
  gs="$(geo_slug "$state")"
  echo
  echo "${BOLD}${CYAN}==> $us${NC}"

  if [[ "$DO_PMTILES" -eq 1 ]]; then
    fetch "${PMTILES_BASE}/${us}_${PMTILES_DATE}.pmtiles" \
          "${PMTILES_DIR}/${us}_${PMTILES_DATE}.pmtiles" \
          "PMTiles ${us}" || FAILS=$((FAILS+1))
  fi

  if [[ "$DO_PBF" -eq 1 ]]; then
    fetch "${GEOFABRIK_BASE}/${gs}-latest.osm.pbf" \
          "${OSM_DIR}/${us}.osm.pbf" \
          "OSM extract ${us}" || FAILS=$((FAILS+1))
  fi
done

# Decide which state becomes the active routing extract (region.osm.pbf).
# Explicit --route wins; otherwise auto-activate when exactly one state was
# requested and its pbf was downloaded.
if [[ -z "$ROUTE_STATE" && "$DO_PBF" -eq 1 && ${#STATES[@]} -eq 1 ]]; then
  ROUTE_STATE="${STATES[0]}"
fi

if [[ -n "$ROUTE_STATE" ]]; then
  rus="$(norm_under "$ROUTE_STATE")"
  src="${OSM_DIR}/${rus}.osm.pbf"
  active="${OSM_DIR}/region.osm.pbf"
  if [[ ! -f "$src" ]]; then
    err "cannot activate routing: ${src} not found (download it first)"
    FAILS=$((FAILS+1))
  else
    # Size sanity check for small-RAM devices.
    bytes="$(stat -c%s "$src" 2>/dev/null || stat -f%z "$src" 2>/dev/null || echo 0)"
    if [[ "$bytes" -gt 1500000000 ]]; then
      warn "${rus}.osm.pbf is $(du -h "$src" | cut -f1). Extracts over ~1.5 GB"
      warn "may fail to import on a 2 GB Raspberry Pi (out of memory)."
    fi
    info "activating ${rus} for routing -> region.osm.pbf"
    rm -f "$active"
    if ln "$src" "$active" 2>/dev/null; then
      ok "linked region.osm.pbf -> ${rus}.osm.pbf"
    else
      cp -f "$src" "$active"
      ok "copied region.osm.pbf from ${rus}.osm.pbf"
    fi
    # Force a re-import: clear the old routing graph so GraphHopper rebuilds
    # from the newly-activated extract on next start.
    if [[ -d "$GRAPH_CACHE_DIR" ]]; then
      info "clearing routing graph cache so it re-imports (${GRAPH_CACHE_DIR})"
      rm -rf "${GRAPH_CACHE_DIR:?}/"* 2>/dev/null || true
    fi
    ok "routing set to ${rus}. Restart the stack to import:"
    echo "     podman restart graphhopper   # or: podman compose up -d"
  fi
fi

echo
if [[ "$FAILS" -eq 0 ]]; then
  ok "done"
else
  err "$FAILS item(s) failed"
  exit 1
fi
