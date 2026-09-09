#!/bin/bash
set -euo pipefail

# --- Configuration (overridable via environment) -----------------------------
# Debian release codename and architecture for the base image. Default to the
# values of the system this script runs on, so on a Raspberry Pi running
# Debian 13 (trixie)/arm64 you get a matching minimal base.
SUITE="${SUITE:-$( . /etc/os-release 2>/dev/null; echo "${VERSION_CODENAME:-bookworm}" )}"
ARCH="${ARCH:-$(dpkg --print-architecture 2>/dev/null || echo arm64)}"
MIRROR="${MIRROR:-http://deb.debian.org/debian}"

# Detect whether we are running on a Raspberry Pi.
# /proc/device-tree/model is the most reliable source across Pi models/OSes;
# fall back to /proc/cpuinfo if it is not present.
is_raspberry_pi() {
    if [ -r /proc/device-tree/model ] && grep -qi "raspberry pi" /proc/device-tree/model; then
        return 0
    fi
    if [ -r /proc/cpuinfo ] && grep -qi "raspberry pi" /proc/cpuinfo; then
        return 0
    fi
    return 1
}

# Build a small minimal base image using debootstrap.
# Produces a clean base rootfs (variant=minbase: no recommended extras, no
# machine-specific state/logs/caches) that can be built upon. The rootfs is
# written directly into the container's mounted storage, so it never copies the
# host's running filesystem.
build_base_image() {
    local container="$1"
    local image="$2"
    local mount_path

    echo "Building minimal base: suite=${SUITE} arch=${ARCH} -> image '${image}'"

    # Ensure debootstrap is available.
    if ! command -v debootstrap >/dev/null 2>&1; then
        sudo apt-get update -qq
        sudo apt-get install -y debootstrap
    fi

    # Remove any stale container of the same name from a previous run.
    buildah rm "$container" >/dev/null 2>&1 || true

    buildah from --name "$container" scratch
    mount_path=$(buildah mount "$container")
    echo "Mounted '$container' at: $mount_path"

    # minbase keeps the image small (only Essential + apt). Drop apt lists and
    # caches afterwards to trim it further.
    debootstrap --variant=minbase --arch="$ARCH" "$SUITE" "$mount_path" "$MIRROR"
    rm -rf "$mount_path/var/lib/apt/lists/"* \
           "$mount_path/var/cache/apt/archives/"*.deb \
           "$mount_path/var/log/"*

    buildah unmount "$container"
    buildah commit "$container" "$image"

    buildah images
    buildah push "localhost/${image}" "oci-archive:/root/${image}.tar:${image}"
}

main() {
    if is_raspberry_pi; then
        # On a Raspberry Pi: create the rasbase_master base image.
        build_base_image "rasbase_master" "rasbase_master"
    else
        # Otherwise: build a base image named from $1 (default 'rasbase').
        build_base_image "${1:-rasbase}" "rasbase"
    fi
}

main "$@"

# Ctrl+p, Ctrl+q will now turn interactive mode into daemon mode.
# buildah pull oci-archive:ee_ccd.tar
