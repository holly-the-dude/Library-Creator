#!/usr/bin/env bash
#
# create_tar_pods.sh
# Iterates over each subfolder that contains a Containerfile (matching the
# discovery logic of build_pods.sh), then runs `podman save -o <name>.tar <name>`
# to export the built image, replacing any existing saved tar.
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
cd "$SCRIPT_DIR"

saved=()
failed=()

echo "${BOLD}${BLUE}==> Scanning for containers in ${SCRIPT_DIR}${RESET}"
echo

for dir in */; do
    name="${dir%/}"

    # Only process folders that have a Containerfile (or Dockerfile),
    # mirroring build_pods.sh discovery.
    if [[ -f "${dir}Containerfile" ]]; then
        :
    elif [[ -f "${dir}Dockerfile" ]]; then
        :
    else
        continue
    fi

    tarfile="${name}.tar"

    echo "${BOLD}${CYAN}────────────────────────────────────────────${RESET}"
    echo "${BOLD}${CYAN}📦 Container: ${name}${RESET}"
    echo "${BOLD}${CYAN}────────────────────────────────────────────${RESET}"

    # Make sure the image actually exists before trying to save it.
    if ! podman image exists "${name}"; then
        echo "${RED}  ✗ No image '${name}' found — did you run build_pods.sh?${RESET}"
        failed+=("${name}")
        echo
        continue
    fi

    # Remove the existing tar (podman save -o overwrites, but this makes the
    # replacement explicit and avoids leaving a stale file on failure).
    if [[ -f "${tarfile}" ]]; then
        echo "${YELLOW}➜ Removing existing '${tarfile}'...${RESET}"
        rm -f "${tarfile}"
        echo "${GREEN}  ✓ Removed existing tar${RESET}"
    else
        echo "${BLUE}  • No existing tar to remove${RESET}"
    fi

    # Save the image to a tar.
    echo "${YELLOW}➜ Saving '${name}' -> '${tarfile}'...${RESET}"
    if podman save -o "${tarfile}" "${name}"; then
        echo "${GREEN}  ✓ Successfully saved '${tarfile}'${RESET}"
        saved+=("${name}")
    else
        echo "${RED}  ✗ Failed to save '${name}'${RESET}"
        failed+=("${name}")
    fi
    echo
done

# ----- summary -----
echo "${BOLD}${BLUE}==> Save summary${RESET}"
if ((${#saved[@]})); then
    echo "${GREEN}  Saved (${#saved[@]}):${RESET} ${saved[*]}"
fi
if ((${#failed[@]})); then
    echo "${RED}  Failed (${#failed[@]}):${RESET} ${failed[*]}"
    exit 1
fi

if ((${#saved[@]} == 0)); then
    echo "${YELLOW}  No containers found to save.${RESET}"
fi
