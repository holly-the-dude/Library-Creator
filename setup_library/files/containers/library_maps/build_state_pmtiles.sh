#!/bin/bash
#
# build_state_pmtiles.sh
#
# Downloads OSM PBF extracts for all US states from Geofabrik and converts
# each to PMTiles format using Planetiler.
#
# Output naming convention: statename_YYYY-MM.pmtiles
# (e.g., alabama_2025-08.pmtiles)
#
# Prerequisites:
#   - Java 21+ (for Planetiler)
#   - wget or curl
#   - ~100GB+ free disk space (PBFs are large, especially California/Texas)
#
# Usage:
#   ./build_state_pmtiles.sh [OPTIONS]
#
#   Options:
#     --output-dir=PATH     Directory for output .pmtiles files (default: ./pmtiles)
#     --work-dir=PATH       Working directory for downloads and temp files (default: ./work)
#     --planetiler=PATH     Path to planetiler.jar (will download if not found)
#     --keep-pbf            Keep .osm.pbf files after conversion (default: delete)
#     --states=s1,s2,...    Comma-separated list of states to process (default: all)
#     --ram=NUM             RAM in GB to allocate to Planetiler (default: auto)
#     -h, --help            Show this help message
#
set -euo pipefail

# --- Configuration ---
OUTPUT_DIR="./pmtiles"
WORK_DIR="./work"
PLANETILER_JAR=""
KEEP_PBF=false
FILTER_STATES=""
RAM_GB=""
DATE_STAMP=$(date +%Y-%m)
GEOFABRIK_BASE="https://download.geofabrik.de/north-america/us"
PLANETILER_VERSION="0.8.2"
PLANETILER_URL="https://github.com/onthegomap/planetiler/releases/download/v${PLANETILER_VERSION}/planetiler.jar"

# --- State definitions ---
# Maps: state_name -> geofabrik slug
# Geofabrik uses hyphenated names; our output uses underscores
declare -A STATES=(
    ["alabama"]="alabama"
    ["alaska"]="alaska"
    ["arizona"]="arizona"
    ["arkansas"]="arkansas"
    ["california"]="california"
    ["colorado"]="colorado"
    ["connecticut"]="connecticut"
    ["delaware"]="delaware"
    ["florida"]="florida"
    ["georgia"]="georgia"
    ["hawaii"]="hawaii"
    ["idaho"]="idaho"
    ["illinois"]="illinois"
    ["indiana"]="indiana"
    ["iowa"]="iowa"
    ["kansas"]="kansas"
    ["kentucky"]="kentucky"
    ["louisiana"]="louisiana"
    ["maine"]="maine"
    ["maryland"]="maryland"
    ["massachusetts"]="massachusetts"
    ["michigan"]="michigan"
    ["minnesota"]="minnesota"
    ["mississippi"]="mississippi"
    ["missouri"]="missouri"
    ["montana"]="montana"
    ["nebraska"]="nebraska"
    ["nevada"]="nevada"
    ["new_hampshire"]="new-hampshire"
    ["new_jersey"]="new-jersey"
    ["new_mexico"]="new-mexico"
    ["new_york"]="new-york"
    ["north_carolina"]="north-carolina"
    ["north_dakota"]="north-dakota"
    ["ohio"]="ohio"
    ["oklahoma"]="oklahoma"
    ["oregon"]="oregon"
    ["pennsylvania"]="pennsylvania"
    ["rhode_island"]="rhode-island"
    ["south_carolina"]="south-carolina"
    ["south_dakota"]="south-dakota"
    ["tennessee"]="tennessee"
    ["texas"]="texas"
    ["utah"]="utah"
    ["vermont"]="vermont"
    ["virginia"]="virginia"
    ["washington"]="washington"
    ["west_virginia"]="west-virginia"
    ["wisconsin"]="wisconsin"
    ["wyoming"]="wyoming"
)

# Ordered list for consistent processing
STATE_ORDER=(
    alabama alaska arizona arkansas california colorado connecticut delaware
    florida georgia hawaii idaho illinois indiana iowa kansas kentucky louisiana
    maine maryland massachusetts michigan minnesota mississippi missouri montana
    nebraska nevada new_hampshire new_jersey new_mexico new_york north_carolina
    north_dakota ohio oklahoma oregon pennsylvania rhode_island south_carolina
    south_dakota tennessee texas utah vermont virginia washington west_virginia
    wisconsin wyoming
)

# --- Functions ---

usage() {
    sed -n '/^# Usage:/,/^#$/p' "$0" | sed 's/^# \?//'
    exit 0
}

log() {
    echo "[$(date '+%H:%M:%S')] $*"
}

error() {
    echo "[$(date '+%H:%M:%S')] ERROR: $*" >&2
}

die() {
    error "$@"
    exit 1
}

check_java() {
    if ! command -v java &>/dev/null; then
        die "Java not found. Planetiler requires Java 21+. Install with: apt install openjdk-21-jre-headless"
    fi
    local java_version
    java_version=$(java -version 2>&1 | head -1 | awk -F '"' '{print $2}' | cut -d. -f1)
    if [ "$java_version" -lt 21 ] 2>/dev/null; then
        log "WARNING: Java $java_version detected. Planetiler works best with Java 21+."
    fi
}

download_planetiler() {
    local jar_path="$WORK_DIR/planetiler.jar"
    if [ -f "$jar_path" ]; then
        log "Planetiler already downloaded at $jar_path"
        PLANETILER_JAR="$(realpath "$jar_path")"
        return
    fi
    log "Downloading Planetiler v${PLANETILER_VERSION}..."
    wget -q --show-progress -O "$jar_path" "$PLANETILER_URL" || \
        curl -fSL -o "$jar_path" "$PLANETILER_URL" || \
        die "Failed to download Planetiler"
    PLANETILER_JAR="$(realpath "$jar_path")"
    log "Planetiler downloaded to $PLANETILER_JAR"
}

get_ram_flag() {
    if [ -n "$RAM_GB" ]; then
        echo "-Xmx${RAM_GB}g"
        return
    fi
    # Auto-detect: use 75% of available RAM, min 2GB
    local total_mb
    if [ -f /proc/meminfo ]; then
        total_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
    elif command -v sysctl &>/dev/null; then
        total_mb=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1024 / 1024 ))
    else
        total_mb=4096
    fi
    local alloc_mb=$(( total_mb * 75 / 100 ))
    [ "$alloc_mb" -lt 2048 ] && alloc_mb=2048
    echo "-Xmx${alloc_mb}m"
}

download_pbf() {
    local state_name="$1"
    local geofabrik_slug="${STATES[$state_name]}"
    local pbf_url="${GEOFABRIK_BASE}/${geofabrik_slug}-latest.osm.pbf"
    local pbf_path="$WORK_DIR/${state_name}.osm.pbf"

    if [ -f "$pbf_path" ]; then
        log "  PBF already exists: $pbf_path (skipping download)" >&2
        echo "$pbf_path"
        return
    fi

    log "  Downloading ${geofabrik_slug}-latest.osm.pbf..." >&2
    if command -v wget &>/dev/null; then
        wget -q --show-progress -O "$pbf_path" "$pbf_url" >&2
    else
        curl -fSL --progress-bar -o "$pbf_path" "$pbf_url" >&2
    fi

    if [ ! -f "$pbf_path" ] || [ ! -s "$pbf_path" ]; then
        error "  Download failed for $state_name"
        rm -f "$pbf_path"
        return 1
    fi

    echo "$pbf_path"
}

convert_to_pmtiles() {
    local state_name="$1"
    local pbf_path
    pbf_path="$(realpath "$2")"
    local output_path
    output_path="$(realpath "$OUTPUT_DIR")/${state_name}_${DATE_STAMP}.pmtiles"
    local tmp_dir
    tmp_dir="$(realpath "$WORK_DIR")/planetiler_tmp_${state_name}"

    if [ -f "$output_path" ]; then
        log "  Output already exists: $output_path (skipping conversion)"
        return 0
    fi

    mkdir -p "$tmp_dir"

    local ram_flag
    ram_flag=$(get_ram_flag)

    log "  Converting to PMTiles (${ram_flag})..."
    java "$ram_flag" \
        -jar "$PLANETILER_JAR" \
        --osm-path="$pbf_path" \
        --output="$output_path" \
        --tmpdir="$tmp_dir" \
        --nodemap-type=array \
        --download \
        --force

    local exit_code=$?

    # Clean up temp directory
    rm -rf "$tmp_dir"

    if [ $exit_code -ne 0 ]; then
        error "  Planetiler failed for $state_name (exit code: $exit_code)"
        rm -f "$output_path"
        return 1
    fi

    local size
    size=$(du -h "$output_path" | cut -f1)
    log "  ✓ Created $output_path ($size)"
    return 0
}

# --- Parse arguments ---

for arg in "$@"; do
    case $arg in
        --output-dir=*)
            OUTPUT_DIR="${arg#*=}"
            ;;
        --work-dir=*)
            WORK_DIR="${arg#*=}"
            ;;
        --planetiler=*)
            PLANETILER_JAR="${arg#*=}"
            ;;
        --keep-pbf)
            KEEP_PBF=true
            ;;
        --states=*)
            FILTER_STATES="${arg#*=}"
            ;;
        --ram=*)
            RAM_GB="${arg#*=}"
            ;;
        -h|--help)
            usage
            ;;
        *)
            die "Unknown argument: $arg"
            ;;
    esac
done

# --- Main ---

log "=== US State PBF → PMTiles Builder ==="
log "Date stamp: $DATE_STAMP"
log "Output dir: $OUTPUT_DIR"
log "Work dir:   $WORK_DIR"
echo ""

# Create directories
mkdir -p "$OUTPUT_DIR" "$WORK_DIR"

# Check prerequisites
check_java

# Get Planetiler
if [ -n "$PLANETILER_JAR" ] && [ -f "$PLANETILER_JAR" ]; then
    log "Using Planetiler at: $PLANETILER_JAR"
else
    download_planetiler
fi

# Determine which states to process
declare -a states_to_process=()
if [ -n "$FILTER_STATES" ]; then
    IFS=',' read -ra states_to_process <<< "$FILTER_STATES"
else
    states_to_process=("${STATE_ORDER[@]}")
fi

total=${#states_to_process[@]}
log "Processing $total state(s)..."
echo ""

# Process each state
success=0
failed=0
skipped=0

for i in "${!states_to_process[@]}"; do
    state="${states_to_process[$i]}"
    num=$((i + 1))

    # Validate state name
    if [ -z "${STATES[$state]+x}" ]; then
        error "Unknown state: $state (skipping)"
        ((skipped++))
        continue
    fi

    log "[$num/$total] Processing: $state"

    # Check if output already exists
    if [ -f "$OUTPUT_DIR/${state}_${DATE_STAMP}.pmtiles" ]; then
        log "  ✓ Already exists, skipping"
        ((success++))
        continue
    fi

    # Download PBF
    pbf_path=""
    pbf_path=$(download_pbf "$state") || {
        ((failed++))
        echo ""
        continue
    }

    # Convert to PMTiles
    if convert_to_pmtiles "$state" "$pbf_path"; then
        ((success++))
    else
        ((failed++))
    fi

    # Optionally remove PBF to save disk space
    if [ "$KEEP_PBF" = false ] && [ -f "$pbf_path" ]; then
        log "  Removing PBF to save space..."
        rm -f "$pbf_path"
    fi

    echo ""
done

# --- Summary ---
echo ""
log "=== Complete ==="
log "  Successful: $success"
log "  Failed:     $failed"
log "  Skipped:    $skipped"
log "  Output dir: $OUTPUT_DIR"

if [ $failed -gt 0 ]; then
    exit 1
fi
