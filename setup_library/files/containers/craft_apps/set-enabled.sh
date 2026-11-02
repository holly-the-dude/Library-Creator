#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
    echo 'Run this script with sudo on the Library appliance.' >&2
    exit 1
fi
case "${1:-}" in yes|no) ;; *) echo 'Usage: set-enabled.sh yes|no' >&2; exit 1 ;; esac
# Distinguish a missing image from an error accessing Podman storage.
image_exists() {
    local status
    if podman image exists "$1"; then return 0; else status=$?; fi
    if [[ $status == 1 ]]; then return 1; fi
    exit "$status"
}
latest=localhost/craft_apps:latest
disabled=localhost/craft_apps:dontrun
if [[ "$1" == yes ]]; then
    if ! image_exists "$latest"; then
        if ! image_exists "$disabled"; then
            echo 'Build or load the craft_apps image before enabling Office.' >&2
            exit 1
        fi
        podman tag "$disabled" "$latest"
    fi
    if image_exists "$disabled"; then podman untag "$disabled" "$disabled"; fi
    echo 'Office enabled (:latest). Start Office or restart the Library to use it.'
else
    # Tag first, then remove only the alias; never remove the image or documents.
    if image_exists "$latest"; then
        podman tag "$latest" "$disabled"
        podman untag "$latest" "$latest"
    fi
    podman stop --ignore craft_apps
    echo 'Office disabled (:dontrun). Documents and settings are retained.'
fi
