#!/usr/bin/env python3
"""Find a USB radio that completes the Meshtastic configuration handshake.

Run as a one-shot container with /dev mounted at /host-dev. Outputs only JSON
with host paths and firmware versions; never outputs radio configuration/keys.
No esptool probe, firmware write, owner change or configuration write is made.
"""

import argparse
from contextlib import suppress
import json
import os
from pathlib import Path
import signal
import subprocess
import sys


def candidates(root, device="", exclude=""):
    def inside(host_path):
        relative = Path(host_path).relative_to("/dev")
        if ".." in relative.parts:
            raise ValueError("Device path must be within /dev")
        target = (root / relative).resolve()
        return target

    excluded = {inside(exclude)} if exclude else set()
    aliases = {}
    for link in sorted((root / "serial/by-id").glob("*")):
        target = link.resolve()
        # A GPS often shares the ttyACM namespace with ESP32 radios.
        if any(word in link.name.lower() for word in ("gps", "gnss", "u-blox", "ublox")):
            excluded.add(target)
        aliases.setdefault(target, "/dev/serial/by-id/" + link.name)
    ports = [inside(device)] if device else sorted(
        {p.resolve() for pattern in ("ttyUSB*", "ttyACM*") for p in root.glob(pattern)})
    return [(p, device or aliases.get(p, "/dev/" + p.name)) for p in ports
            if p not in excluded and p.parent == root.resolve()
            and p.name.startswith(("ttyUSB", "ttyACM")) and p.is_char_device()]


def probe(device, timeout):
    # Import only in the child: each failed probe gets its own bounded process,
    # including cleanup of upstream reader threads and heartbeat timers.
    from meshtastic.serial_interface import SerialInterface

    interface = SerialInterface(devPath=device, connectNow=False, timeout=timeout)
    try:
        interface.connect()
        interface.waitForConfig()
        version = interface.metadata.firmware_version
        if not version or not interface.myInfo.my_node_num:
            raise ValueError("Incomplete Meshtastic identity")
        return {"firmware": version}
    finally:
        with suppress(Exception):
            interface.close()
        stream = getattr(interface, "stream", None)
        if stream is not None:
            with suppress(Exception):
                stream.close()
        timer = getattr(interface, "heartbeatTimer", None)
        if timer is not None:
            timer.cancel()


def scan(root, device="", exclude="", timeout=12):
    found = []
    for path, host_path in candidates(root, device, exclude):
        try:
            result = subprocess.run(
                [sys.executable, __file__, "--probe", str(path), "--timeout", str(timeout)],
                capture_output=True, text=True, timeout=timeout + 5,
            )
            if result.returncode == 0:
                info = json.loads(result.stdout)
                if not isinstance(info.get("firmware"), str) or not info["firmware"]:
                    raise ValueError("Missing firmware version")
                found.append({"device": host_path, "firmware": info["firmware"]})
        except (subprocess.TimeoutExpired, ValueError):
            print(f"No Meshtastic handshake on {host_path}", file=sys.stderr)
    if len(found) == 1:
        return {"status": "found", **found[0]}
    return {"status": "ambiguous" if found else "not_found", "devices": found}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/host-dev"))
    parser.add_argument("--device", default="")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--probe", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 60:
        parser.error("timeout must be between 1 and 60 seconds")
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    if args.probe:
        # Upstream may print connection messages. Keep stdout machine-readable.
        with open(os.devnull, "w") as quiet:
            from contextlib import redirect_stdout
            with redirect_stdout(quiet):
                try:
                    result = probe(args.probe, args.timeout)
                except Exception:
                    sys.exit(1)
        print(json.dumps(result))
    else:
        if not args.root.is_dir():
            parser.error("USB mount missing: run with -v /dev:/host-dev:ro and serial cgroup rules")
        print(json.dumps(scan(args.root, args.device, args.exclude, args.timeout)))


if __name__ == "__main__":
    main()
