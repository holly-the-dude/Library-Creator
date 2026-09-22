#!/usr/bin/env bash
#
# build_pods.sh
# Iterates over each subfolder that contains a Containerfile, removes the
# existing image (podman rmi --force), then rebuilds localhost/<folder>:latest.
# Meshtastic and meshflash are both required by start_library.yml.
#
set -uo pipefail

# ----- colors -----
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

# Work from the directory this script lives in.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Startup needs the radio bridge AND the firmware setup fallback. Fail before
# removing images if either build context is missing from this checkout.
for required in meshtastic meshflash; do
    if [[ ! -f "${required}/Containerfile" ]]; then
        echo "${RED}Missing required container: ${required}/Containerfile${RESET}" >&2
        exit 1
    fi
done

built=()
failed=()

echo "${BOLD}${BLUE}==> Scanning for containers in ${SCRIPT_DIR}${RESET}"
echo

for dir in */; do
    name="${dir%/}"
    tag="localhost/${name}:latest"

    # Only process folders that have a Containerfile (or Dockerfile).
    if [[ -f "${dir}Containerfile" ]]; then
        containerfile="Containerfile"
    elif [[ -f "${dir}Dockerfile" ]]; then
        containerfile="Dockerfile"
    else
        continue
    fi

    echo "${BOLD}${CYAN}────────────────────────────────────────────${RESET}"
    echo "${BOLD}${CYAN}📦 Container: ${name}${RESET}"
    echo "${BOLD}${CYAN}────────────────────────────────────────────${RESET}"

    # Remove existing image (ignore errors if it doesn't exist).
    echo "${YELLOW}➜ Removing existing image '${tag}'...${RESET}"
    if podman rmi --force "${tag}" >/dev/null 2>&1; then
        echo "${GREEN}  ✓ Removed existing image${RESET}"
    else
        echo "${BLUE}  • No existing image to remove${RESET}"
    fi

    # Build the container.
    echo "${YELLOW}➜ Building '${tag}'...${RESET}"
    if podman build -t "${tag}" -f "${dir}${containerfile}" "${dir}"; then
        echo "${GREEN}  ✓ Successfully built '${tag}'${RESET}"
        built+=("${tag}")
    else
        echo "${RED}  ✗ Failed to build '${tag}'${RESET}"
        failed+=("${tag}")
    fi
    echo
done

# ----- nested routing subimages -----
# Some pods (e.g. library_maps) ship a routing engine in a "graphhopper"
# subfolder with its own Containerfile. The top-level loop above does not
# descend into subfolders, so build these explicitly and tag them
# "<parent>-graphhopper:11" (matching compose.yaml / start_library.yml).
for ghfile in */graphhopper/Containerfile; do
    [[ -e "$ghfile" ]] || continue              # no matches -> skip
    ghdir="$(dirname "$ghfile")"                # e.g. library_maps/graphhopper
    parent="$(basename "$(dirname "$ghdir")")"  # e.g. library_maps
    tag="${parent}-graphhopper:11"

    echo "${BOLD}${CYAN}────────────────────────────────────────────${RESET}"
    echo "${BOLD}${CYAN}📦 Routing subimage: ${tag} (from ${ghdir})${RESET}"
    echo "${BOLD}${CYAN}────────────────────────────────────────────${RESET}"

    podman rmi --force "${tag}" >/dev/null 2>&1 || true

    echo "${YELLOW}➜ Building '${tag}'...${RESET}"
    if podman build -t "${tag}" -f "${ghdir}/Containerfile" "${ghdir}"; then
        echo "${GREEN}  ✓ Successfully built '${tag}'${RESET}"
        built+=("${tag}")
    else
        echo "${RED}  ✗ Failed to build '${tag}'${RESET}"
        failed+=("${tag}")
    fi
    echo
done

# ----- summary -----
echo "${BOLD}${BLUE}==> Build summary${RESET}"
if ((${#built[@]})); then
    echo "${GREEN}  Built (${#built[@]}):${RESET} ${built[*]}"
fi
if ((${#failed[@]})); then
    echo "${RED}  Failed (${#failed[@]}):${RESET} ${failed[*]}"
    exit 1
fi

if ((${#built[@]} == 0)); then
    echo "${YELLOW}  No containers found to build.${RESET}"
fi
