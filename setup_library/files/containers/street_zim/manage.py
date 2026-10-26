#!/usr/bin/env python3
"""Build/start StreetZim with Podman, without requiring Compose."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
IMAGE = "localhost/street_zim:latest"


def check_network(network, address):
    data = json.loads(subprocess.check_output(["podman", "network", "inspect", network]))[0]
    ip = ipaddress.ip_address(address)
    subnets = [ipaddress.ip_network(item["subnet"]) for item in data.get("subnets", [])]
    if not any(ip in subnet and ip not in (subnet.network_address, subnet.broadcast_address)
               for subnet in subnets):
        raise ValueError(f"{address} is not a usable address on network {network}")
    if any(address == item.get("gateway") for item in data.get("subnets", [])):
        raise ValueError(f"{address} is the network gateway")
    # Include stopped containers: their configured addresses remain reserved.
    ids = subprocess.check_output(["podman", "ps", "-aq"], text=True).split()
    if ids:
        containers = json.loads(subprocess.check_output(["podman", "inspect", *ids]))
        for container in containers:
            for name, settings in container.get("NetworkSettings", {}).get("Networks", {}).items():
                candidates = (settings.get("IPAddress"), (settings.get("IPAMConfig") or {}).get("IPv4Address"))
                if name == network and address in candidates:
                    raise ValueError(f"{address} is already assigned to {container.get('Name', 'a container')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "start"))
    parser.add_argument("--gps-device", help="Direct USB mode: persistent receiver path; it must not be read by Maps")
    args = parser.parse_args()
    if args.command == "build":
        return subprocess.call(["podman", "build", "--format", "docker", "-t", IMAGE,
                                "-f", str(ROOT / "Containerfile"), str(ROOT)])
    port = int(os.environ.get("STREET_ZIM_PORT", "8093"))
    if not 1 <= port <= 65535:
        raise ValueError("STREET_ZIM_PORT must be between 1 and 65535")
    address = os.environ.get("STREET_ZIM_IP", "10.88.0.216")
    network = os.environ.get("STREET_ZIM_NETWORK", "podman")
    directory = Path(os.environ.get("STREET_ZIM_DIR", "/Library/wiki")).resolve()
    if not directory.is_dir():
        raise ValueError(f"ZIM folder does not exist: {directory}. Set STREET_ZIM_DIR to the shared ZIM folder on this host.")
    if subprocess.run(["podman", "container", "exists", "street_zim"]).returncode == 0:
        raise ValueError("Container street_zim already exists. Use podman start/restart street_zim, or remove that container explicitly before recreating it.")
    check_network(network, address)
    with socket.socket() as probe:
        probe.bind(("0.0.0.0", port))
    command = ["podman", "run", "-d", "--name", "street_zim", "--restart", "unless-stopped",
               "--network", network, "--ip", address, "-p", f"{port}:8093",
               "-v", f"{directory}:/data:ro"]
    if args.gps_device:
        device = Path(args.gps_device)
        if not device.is_char_device():
            raise ValueError(f"GPS device is not a character device: {device}")
        command.extend(["--device", f"{device}:/dev/streetzim-gps", "-e", "GPS_MODE=serial",
                        "-e", "GPS_PORT=/dev/streetzim-gps", "-e", f"GPS_BAUD={os.environ.get('GPS_BAUD', '9600')}"])
    else:
        command.extend(["-e", "GPS_MODE=relay", "-e", f"GPS_UPSTREAM={os.environ.get('GPS_UPSTREAM', 'http://10.88.0.212:8080')}"])
    command.append(IMAGE)
    subprocess.run(command, check=True)
    print(f"StreetZim: http://localhost:{port} (hotspot: http://10.1.1.1:{port})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"StreetZim: {error}", file=sys.stderr)
        sys.exit(1)
