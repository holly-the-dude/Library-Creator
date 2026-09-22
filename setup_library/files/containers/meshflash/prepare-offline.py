#!/usr/bin/env python3
"""Snapshot official ESP32 manifests and verified binaries for offline flashing."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import quote

from flasher import load_manifest, safe_name, verify_file

API = "https://api.meshtastic.org/github/firmware/list"
RELEASES = "https://release.meshtastic.org"


def download(url, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "curl", "--fail", "--location", "--silent", "--show-error",
        "--retry", "5", "--retry-all-errors", "--connect-timeout", "30",
        "--max-time", "900", "--output", str(destination), url,
    ], check=True)


def remote_json(url):
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "response.json"
        download(url, path)
        return json.loads(path.read_text())


def mirror_board(root, version, target):
    board = safe_name(target["board"])
    destination = root / version / board
    name = f"firmware-{board}-{version}.mt.json"
    path = destination / name
    download(f"{RELEASES}/{quote(version)}/{quote(name)}", path)
    metadata = json.loads(path.read_text())
    if metadata["mcu"] != target["platform"] or metadata["version"] != version:
        raise ValueError(f"Unexpected firmware metadata: {name}")
    # Separate directories avoid collisions between board-specific OTA images.
    for entry in metadata["files"]:
        filename = safe_name(entry["name"])
        if filename.endswith(".bin"):
            binary = destination / filename
            download(f"{RELEASES}/{quote(version)}/{quote(filename)}", binary)
            verify_file(binary, entry)
    manifest = load_manifest(path)
    manifest.plan("install")
    manifest.plan("update")
    print(f"Bundled {version}: {board}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--stable-count", type=int, default=1)
    parser.add_argument("--alpha-count", type=int, default=1)
    parser.add_argument("--boards", default="", help="comma-separated targets; empty means all ESP32 boards")
    args = parser.parse_args()
    if not all(0 <= n <= 4 for n in (args.stable_count, args.alpha_count)):
        parser.error("release counts must be between 0 and 4")
    if args.stable_count + args.alpha_count == 0:
        parser.error("bundle at least one release")
    requested = {safe_name(b.strip()) for b in args.boards.split(",") if b.strip()}
    catalog = remote_json(API)
    snapshot = []
    for channel, count in (("stable", args.stable_count), ("alpha", args.alpha_count)):
        candidates = [r for r in catalog["releases"][channel] if "Preview" not in r["title"]]
        if len(candidates) < count:
            raise ValueError(f"Only {len(candidates)} {channel} releases available")
        for release in candidates[:count]:
            version = safe_name(release["id"].removeprefix("v"))
            # Require metadata: never guess offsets for old bare binaries.
            manifest = remote_json(f"{RELEASES}/{quote(version)}/firmware-{quote(version)}.json")
            targets = [t for t in manifest["targets"] if t["platform"].startswith("esp32")
                       and (not requested or t["board"] in requested)]
            missing = requested - {t["board"] for t in targets}
            if not targets or missing:
                raise ValueError(f"Missing ESP32 targets in {version}: {sorted(missing)}")
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda t: mirror_board(args.destination, version, t), targets))
            notes = args.destination / version / "release_notes.md"
            notes.write_text(release.get("release_notes", ""))
            snapshot.append({"version": version, "channel": channel, "title": release["title"]})
    (args.destination / "releases.json").write_text(json.dumps(snapshot, indent=2) + "\n")


if __name__ == "__main__":
    main()
