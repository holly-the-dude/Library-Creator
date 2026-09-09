#!/usr/bin/env bash
#
# update_rasbase.sh
#
# 1. Ensures the source "localhost/rasbase" podman image exists. If it is
#    missing, it is loaded from ./rasbase.tar.
# 2. Determines the target Debian release from the official Raspberry Pi OS
#    image download index (the codename in the newest published image name).
# 3. Boots a container from the source image and upgrades it release-by-
#    release (e.g. bullseye -> bookworm -> trixie) up to that target release,
#    committing the result to the "rasbase_master" image.
# 4. Flattens the accumulated upgrade layers into a single layer to reclaim
#    the disk space wasted by superseded files, then removes the now-unused
#    intermediate images from the upgrade chain.
# 5. Verifies the resulting image reports the target codename.
#
# The script is safe to run repeatedly: already-current releases are skipped
# and it leaves an updated "rasbase_master" image in place.

set -uo pipefail

# --------------------------------------------------------------------------
# Colors (only when attached to a terminal)
# --------------------------------------------------------------------------
if [[ -t 1 ]]; then
    RED=$'\033[0;31m'
    GREEN=$'\033[0;32m'
    YELLOW=$'\033[1;33m'
    BLUE=$'\033[0;34m'
    CYAN=$'\033[0;36m'
    BOLD=$'\033[1m'
    RESET=$'\033[0m'
else
    RED="" GREEN="" YELLOW="" BLUE="" CYAN="" BOLD="" RESET=""
fi

log()   { echo "${BOLD}${BLUE}==>${RESET} ${*}"; }
info()  { echo "${CYAN}  •${RESET} ${*}"; }
ok()    { echo "${GREEN}  ✓${RESET} ${*}"; }
warn()  { echo "${YELLOW}  ➜${RESET} ${*}"; }
err()   { echo "${RED}  ✗${RESET} ${*}" >&2; }

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
# Work from the directory this script lives in so tar files are found.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source image: this is what we start from. It is loaded from SOURCE_TAR when
# not already present locally.
SOURCE_IMAGE="localhost/rasbase"
SOURCE_TAR="rasbase.tar"

# Target image: the (updated) result is committed/tagged as this image,
# regardless of which Debian release it ends up on.
BASE_IMAGE="rasbase_master"

# Ordered Debian release codenames, oldest to newest. The script upgrades
# from the source image's current release forward, one hop at a time, up to
# the target release. Extend this list as new releases are named.
DEBIAN_ORDER=(buster bullseye bookworm trixie forky duke)

# Raspberry Pi OS image download index (sorted newest-first by mtime). The
# newest dated directory contains an image file named like
# "YYYY-MM-DD-raspios-<codename>-arm64-full.img.xz"; that <codename> is used
# as the upgrade target so we track whatever Raspberry Pi ships as stable
# (and never overshoot into testing).
RPIOS_IMAGES_URL="https://downloads.raspberrypi.com/raspios_full_arm64/images/"

# --------------------------------------------------------------------------
# Pre-flight checks
# --------------------------------------------------------------------------
if ! command -v podman >/dev/null 2>&1; then
    err "podman is not installed or not on PATH."
    exit 1
fi

# --------------------------------------------------------------------------
# Helper: does an image exist locally?
# --------------------------------------------------------------------------
image_exists() {
    podman image exists "$1"
}

# Helper: index of a codename in DEBIAN_ORDER (-1 if unknown).
codename_index() {
    local target="$1" i
    for i in "${!DEBIAN_ORDER[@]}"; do
        if [[ "${DEBIAN_ORDER[$i]}" == "$target" ]]; then
            echo "$i"
            return 0
        fi
    done
    echo "-1"
}

# Helper: fetch a URL to stdout using curl or wget. Returns non-zero on
# failure or empty body.
http_get() {
    local url="$1" body=""
    if command -v curl >/dev/null 2>&1; then
        body="$(curl -fsSL --max-time 30 "$url" 2>/dev/null)"
    elif command -v wget >/dev/null 2>&1; then
        body="$(wget -qO- --timeout=30 "$url" 2>/dev/null)"
    else
        return 1
    fi
    [[ -z "$body" ]] && return 1
    printf '%s' "$body"
}

# Helper: determine the current stable Raspberry Pi OS Debian codename from
# the image download index. Prints the codename on success, empty on failure.
#
# Strategy:
#   1. List RPIOS_IMAGES_URL; the newest dated subdirectory is
#      "raspios_full_arm64-YYYY-MM-DD/".
#   2. List that subdirectory; an image file is named like
#      "YYYY-MM-DD-raspios-<codename>-arm64-full.img.xz".
#   3. Extract <codename>.
fetch_target_codename() {
    local index newest sub codename

    index="$(http_get "${RPIOS_IMAGES_URL}?C=M;O=D")" || return 1

    # Newest dated directory (first "raspios_full_arm64-YYYY-MM-DD/" href).
    newest="$(
        printf '%s' "$index" \
        | grep -oE 'raspios_full_arm64-[0-9]{4}-[0-9]{2}-[0-9]{2}/' \
        | head -n1
    )"
    [[ -z "$newest" ]] && return 1

    sub="$(http_get "${RPIOS_IMAGES_URL}${newest}")" || return 1

    # Codename from "raspios-<codename>-arm64" in an image filename.
    codename="$(
        printf '%s' "$sub" \
        | grep -oE 'raspios-[a-z]+-arm64' \
        | head -n1 \
        | sed -E 's/^raspios-([a-z]+)-arm64$/\1/'
    )"
    printf '%s' "$codename"
}

# --------------------------------------------------------------------------
# Step 1: Ensure the source image is present, then tag it as the base image
# --------------------------------------------------------------------------
log "Checking for source '${SOURCE_IMAGE}' image"
if image_exists "$SOURCE_IMAGE"; then
    ok "Image '${SOURCE_IMAGE}' is already loaded."
else
    warn "Image '${SOURCE_IMAGE}' not found."
    if [[ -f "$SOURCE_TAR" ]]; then
        info "Loading from '${SOURCE_TAR}' ..."
        if podman load -i "$SOURCE_TAR"; then
            ok "Loaded from '${SOURCE_TAR}'."
        else
            err "Failed to load '${SOURCE_TAR}'."
            exit 1
        fi
    else
        err "'${SOURCE_TAR}' does not exist; cannot load source image."
        exit 1
    fi

    # After load, confirm the expected source tag exists.
    if ! image_exists "$SOURCE_IMAGE"; then
        err "Loaded tar but image '${SOURCE_IMAGE}' still not present."
        err "Check the tags with: podman images"
        exit 1
    fi
fi

# Tag the source image as the target base image so the rest of the pipeline
# operates on '${BASE_IMAGE}'.
log "Tagging '${SOURCE_IMAGE}' as '${BASE_IMAGE}'"
if podman tag "$SOURCE_IMAGE" "$BASE_IMAGE"; then
    ok "Tagged '${SOURCE_IMAGE}' -> '${BASE_IMAGE}'."
else
    err "Failed to tag '${SOURCE_IMAGE}' as '${BASE_IMAGE}'."
    exit 1
fi

# The image we operate on.
CURRENT_IMAGE="$BASE_IMAGE"

# --------------------------------------------------------------------------
# Step 2: Upgrade release-by-release up to the target release
# --------------------------------------------------------------------------

# Determine the image's current codename.
CURRENT_CODENAME="$(
    podman run --rm "$CURRENT_IMAGE" /bin/bash -c \
        '. /etc/os-release 2>/dev/null; echo "${VERSION_CODENAME:-}"' 2>/dev/null \
        | tr -d "[:space:]"
)"
if [[ -z "$CURRENT_CODENAME" ]]; then
    err "Could not read the current codename from '${CURRENT_IMAGE}'."
    exit 1
fi
info "Source image reports codename: '${CURRENT_CODENAME}'."

CUR_IDX="$(codename_index "$CURRENT_CODENAME")"
if [[ "$CUR_IDX" == "-1" ]]; then
    err "Current codename '${CURRENT_CODENAME}' is not in the known release order."
    err "Add it to DEBIAN_ORDER and re-run."
    exit 1
fi

# Determine the upgrade target from the Raspberry Pi OS image index.
log "Determining target release from Raspberry Pi OS image index"
TARGET_CODENAME="$(fetch_target_codename)"

if [[ -n "$TARGET_CODENAME" ]] && [[ "$(codename_index "$TARGET_CODENAME")" != "-1" ]]; then
    ok "Latest stable Raspberry Pi OS is Debian '${TARGET_CODENAME}'."
else
    # Fall back to the newest codename we know about.
    TARGET_CODENAME="${DEBIAN_ORDER[-1]}"
    warn "Could not detect target from the web; falling back to '${TARGET_CODENAME}'."
fi

TARGET_IDX="$(codename_index "$TARGET_CODENAME")"

if (( CUR_IDX > TARGET_IDX )); then
    warn "Image release '${CURRENT_CODENAME}' is newer than target '${TARGET_CODENAME}'."
    warn "Will only refresh packages; no release change."
    TARGET_IDX="$CUR_IDX"
    TARGET_CODENAME="$CURRENT_CODENAME"
fi
info "Upgrade target: '${TARGET_CODENAME}'."

# Helper: run apt work inside a fresh container built from CURRENT_IMAGE.
# Args: 1=container name, 2=from codename, 3=to codename ("" = stay, just
# update packages), 4=probe-only ("probe" = don't upgrade, just apt update).
run_apt_hop() {
    local ctr="$1" from="$2" to="$3" mode="${4:-}"
    podman rm -f "$ctr" >/dev/null 2>&1 || true
    podman run --name "$ctr" "$CURRENT_IMAGE" /bin/bash -c "
        set -e
        export DEBIAN_FRONTEND=noninteractive

        # Tell apt to retry failed downloads itself (handles transient
        # mirror timeouts like 'Connection timed out' without aborting).
        echo 'Acquire::Retries \"5\";' > /etc/apt/apt.conf.d/80-retries

        # Retry wrapper: run an apt command up to N times with a backoff,
        # so a temporary network failure does not kill the whole hop.
        apt_retry() {
            local tries=5 n=1 delay=15
            while true; do
                if \"\$@\"; then
                    return 0
                fi
                if [ \"\$n\" -ge \"\$tries\" ]; then
                    echo \"apt command failed after \$tries attempts: \$*\" >&2
                    return 1
                fi
                echo \"apt command failed (attempt \$n/\$tries), retrying in \${delay}s: \$*\" >&2
                sleep \"\$delay\"
                n=\$(( n + 1 ))
                delay=\$(( delay * 2 ))
            done
        }

        if [ -n \"${to}\" ] && [ \"${from}\" != \"${to}\" ]; then
            if [ -f /etc/apt/sources.list ]; then
                sed -i 's/${from}/${to}/g' /etc/apt/sources.list
            fi
            for f in /etc/apt/sources.list.d/*.list; do
                [ -e \"\$f\" ] && sed -i 's/${from}/${to}/g' \"\$f\"
            done
            for f in /etc/apt/sources.list.d/*.sources; do
                [ -e \"\$f\" ] && sed -i 's/${from}/${to}/g' \"\$f\"
            done
        fi
        apt_retry apt-get update
        if [ \"${mode}\" != \"probe\" ]; then
            apt_retry apt-get -y --fix-missing upgrade
            apt_retry apt-get -y --fix-missing full-upgrade
            apt-get -y autoremove
            apt-get clean
        fi
    "
}

# Retry wrapper for an entire apt hop. Because the container name is fixed
# per call, a failed attempt is removed before the next try. This recovers
# from broader failures (e.g. the mirror being unreachable for a stretch)
# on top of the per-command retries inside the container.
run_apt_hop_retry() {
    local ctr="$1"
    local tries=3 n=1 delay=30
    while true; do
        if run_apt_hop "$@"; then
            return 0
        fi
        podman rm -f "$ctr" >/dev/null 2>&1 || true
        if (( n >= tries )); then
            err "Hop failed after ${tries} attempts."
            return 1
        fi
        warn "Hop attempt ${n}/${tries} failed; retrying in ${delay}s ..."
        sleep "$delay"
        n=$(( n + 1 ))
        delay=$(( delay * 2 ))
    done
}

# First, refresh packages on the current release and commit.
log "Updating packages on '${CURRENT_CODENAME}'"
UPDATE_CTR="rasbase_update_$$"
if run_apt_hop_retry "$UPDATE_CTR" "$CURRENT_CODENAME" "" ""; then
    info "Committing '${CURRENT_CODENAME}' package updates back to '${CURRENT_IMAGE}' ..."
    podman commit "$UPDATE_CTR" "$CURRENT_IMAGE" >/dev/null
    ok "'${CURRENT_CODENAME}' package update complete."
else
    err "Package update on '${CURRENT_CODENAME}' failed."
    podman rm -f "$UPDATE_CTR" >/dev/null 2>&1 || true
    exit 1
fi
podman rm -f "$UPDATE_CTR" >/dev/null 2>&1 || true

# Now advance release-by-release up to the target release, provided each
# next release is actually published (probe as a safety net).
FROM_CODENAME="$CURRENT_CODENAME"
IDX="$CUR_IDX"
while (( IDX < TARGET_IDX )); do
    NEXT_CODENAME="${DEBIAN_ORDER[$(( IDX + 1 ))]}"

    # Probe: does the next release resolve in apt?
    log "Checking whether release '${NEXT_CODENAME}' is published"
    PROBE_CTR="rasbase_probe_$$"
    if run_apt_hop "$PROBE_CTR" "$FROM_CODENAME" "$NEXT_CODENAME" "probe"; then
        ok "Release '${NEXT_CODENAME}' is available."
        podman rm -f "$PROBE_CTR" >/dev/null 2>&1 || true
    else
        warn "Release '${NEXT_CODENAME}' is not published yet. Stopping at '${FROM_CODENAME}'."
        podman rm -f "$PROBE_CTR" >/dev/null 2>&1 || true
        break
    fi

    # Real dist-upgrade to the next release.
    log "Upgrading release '${FROM_CODENAME}' -> '${NEXT_CODENAME}'"
    HOP_CTR="rasbase_hop_$$"
    if run_apt_hop_retry "$HOP_CTR" "$FROM_CODENAME" "$NEXT_CODENAME" ""; then
        info "Committing '${NEXT_CODENAME}' state back to '${CURRENT_IMAGE}' ..."
        podman commit "$HOP_CTR" "$CURRENT_IMAGE" >/dev/null
        ok "'${NEXT_CODENAME}' upgrade complete."
        podman rm -f "$HOP_CTR" >/dev/null 2>&1 || true
    else
        err "Upgrade to '${NEXT_CODENAME}' failed inside the container."
        podman rm -f "$HOP_CTR" >/dev/null 2>&1 || true
        exit 1
    fi

    FROM_CODENAME="$NEXT_CODENAME"
    IDX=$(( IDX + 1 ))
done

REACHED_CODENAME="$FROM_CODENAME"

# --------------------------------------------------------------------------
# Step 3: Flatten accumulated layers to reclaim space from superseded files
# --------------------------------------------------------------------------
# Each per-hop commit adds a layer; deleted/replaced files from earlier
# releases still occupy space in lower layers. Exporting the container's
# rootfs and re-importing collapses everything into a single layer, which
# physically drops those superseded files.
log "Flattening '${CURRENT_IMAGE}' to reclaim space from upgrade layers"

# Remember the pre-flatten image ID (the tip of the intermediate commit
# chain). After flattening re-tags CURRENT_IMAGE to a fresh image, this old
# ID becomes an untagged leftover; removing it cascades to its now-unused
# parent layers while podman refuses to touch still-tagged images.
PRE_FLATTEN_ID="$(podman image inspect "$CURRENT_IMAGE" --format '{{.Id}}' 2>/dev/null)"

FLATTEN_CTR="rasbase_flatten_$$"
podman rm -f "$FLATTEN_CTR" >/dev/null 2>&1 || true

if podman create --name "$FLATTEN_CTR" "$CURRENT_IMAGE" >/dev/null 2>&1 \
   && podman export "$FLATTEN_CTR" \
        | podman import \
            --change 'CMD ["/bin/bash"]' \
            - "$CURRENT_IMAGE" >/dev/null; then
    ok "Flattened '${CURRENT_IMAGE}' into a single layer."
else
    err "Failed to flatten '${CURRENT_IMAGE}'."
    podman rm -f "$FLATTEN_CTR" >/dev/null 2>&1 || true
    exit 1
fi
podman rm -f "$FLATTEN_CTR" >/dev/null 2>&1 || true

# --------------------------------------------------------------------------
# Step 4: Clean up the intermediate images this run produced
# --------------------------------------------------------------------------
NEW_ID="$(podman image inspect "$CURRENT_IMAGE" --format '{{.Id}}' 2>/dev/null)"

if [[ -n "$PRE_FLATTEN_ID" ]] && [[ "$PRE_FLATTEN_ID" != "$NEW_ID" ]]; then
    log "Cleaning up intermediate upgrade images"
    if podman rmi "$PRE_FLATTEN_ID" >/dev/null 2>&1; then
        ok "Removed intermediate image layers from the upgrade chain."
    else
        # Not fatal: the ID may still be referenced by something else, or a
        # concurrent process may hold it. Leave it and let the user prune.
        warn "Could not remove intermediate image '${PRE_FLATTEN_ID:0:12}';"
        warn "you can reclaim space later with: podman image prune"
    fi
else
    info "No intermediate images to clean up."
fi

# Also drop any remaining dangling images left by earlier interrupted runs.
if podman image prune -f >/dev/null 2>&1; then
    ok "Pruned dangling images."
fi

# --------------------------------------------------------------------------
# Step 5: Verify the resulting image reports the target release
# --------------------------------------------------------------------------
log "Verifying '${CURRENT_IMAGE}' reports codename '${REACHED_CODENAME}'"

IMAGE_CODENAME="$(
    podman run --rm "$CURRENT_IMAGE" /bin/bash -c \
        '. /etc/os-release 2>/dev/null; echo "${VERSION_CODENAME:-}"' 2>/dev/null \
        | tr -d "[:space:]"
)"

if [[ "$IMAGE_CODENAME" == "$REACHED_CODENAME" ]]; then
    ok "Verified: '${CURRENT_IMAGE}' reports codename '${IMAGE_CODENAME}'."
else
    err "Verification failed: expected '${REACHED_CODENAME}' but image reports '${IMAGE_CODENAME:-<unknown>}'."
    exit 1
fi

log "Done. '${CURRENT_IMAGE}' is updated to the latest reachable release: '${REACHED_CODENAME}'."

