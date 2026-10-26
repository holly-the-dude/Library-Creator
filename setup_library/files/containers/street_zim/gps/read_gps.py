#!/usr/bin/env python3
"""Print latitude/longitude and satellite status from a serial NMEA GPS.

Install: sudo apt install python3-serial
Run:     python3 scripts/read_gps.py
One fix: python3 scripts/read_gps.py --once
Port:    python3 scripts/read_gps.py --port /dev/ttyACM0
Devices: python3 scripts/read_gps.py --list-ports
Baud:    python3 scripts/read_gps.py --port /dev/ttyUSB0 --baud 4800

Supports VK-172, u-blox, and other USB/serial GPS receivers that output standard
NMEA sentences. Defaults to 9600 baud; use --baud for a different receiver setting.
Auto-detection prefers a GPS-labelled device, then a single USB serial device.
If several candidates are connected, use --list-ports and select one with --port.
Other serial connections (such as /dev/serial0) can also be selected with --port.

The receiver must output NMEA GGA or RMC sentences for coordinates. Binary-only
output is not supported; configure the receiver to output NMEA first. GSV reports
satellites in view; GGA reports satellites used for a fix, even before a valid
position is available. Enable GSV output to see the in-view count. Coordinates
are decimal degrees, with negative values for south/west. Satellite status goes
to stderr when counts change, and every 10 seconds while reports keep arriving.
Protocol: https://content.u-blox.com/sites/default/files/products/documents/
          u-blox6_ReceiverDescrProtSpec_(GPS.G6-SW-10018)_Public.pdf
"""

import argparse
import glob
import os
import re
import sys
import time
from typing import List, Optional, Tuple


def coordinate(value: str, hemisphere: str, latitude: bool) -> float:
    """Convert NMEA degrees/minutes into signed decimal degrees."""
    digits = 2 if latitude else 3
    directions = "NS" if latitude else "EW"
    limit = 90 if latitude else 180
    if hemisphere not in tuple(directions) or not re.fullmatch(
        rf"[0-9]{{{digits + 2}}}(?:\.[0-9]+)?", value
    ):
        raise ValueError("Invalid coordinate")
    degrees = int(value[:digits])
    minutes = float(value[digits:])
    if minutes >= 60 or degrees > limit or (degrees == limit and minutes != 0):
        raise ValueError("Coordinate out of range")
    result = degrees + minutes / 60
    return -result if hemisphere in ("S", "W") else result


def parse_nmea(sentence: bytes) -> Optional[List[str]]:
    """Return checksum-validated NMEA fields, or None for unusable input."""
    try:
        # Resynchronize if opening the port caught a partial/binary message.
        sentence = sentence[sentence.rindex(b"$") :].strip()
        body, checksum = sentence[1:].split(b"*")
        if not re.fullmatch(b"[0-9A-Fa-f]{2}", checksum):
            return None
        actual_checksum = 0
        for byte in body:
            actual_checksum ^= byte
        if actual_checksum != int(checksum, 16):
            return None

        return body.decode("ascii").split(",")
    except (ValueError, UnicodeError):
        return None


def parse_position(sentence: bytes) -> Optional[Tuple[float, float]]:
    """Return a valid (latitude, longitude), or None for unusable input."""
    fields = parse_nmea(sentence)
    if fields is None:
        return None
    try:
        if not re.fullmatch(r"[A-Z]{2}(GGA|RMC)", fields[0]):
            return None
        if fields[0].endswith("GGA"):
            # Reject no fix (0), estimated/dead reckoning (6), and simulation.
            if fields[6] not in ("1", "2", "4", "5"):
                return None
            lat, ns, lon, ew = fields[2:6]
        else:
            if fields[2] != "A":
                return None
            # Older NMEA versions omit the optional positioning mode.
            if len(fields) > 12 and fields[12] in ("N", "E", "M", "S"):
                return None
            lat, ns, lon, ew = fields[3:7]
        return coordinate(lat, ns, True), coordinate(lon, ew, False)
    except (ValueError, IndexError, UnicodeError):
        return None


def parse_satellite_status(sentence: bytes) -> Optional[Tuple[str, int]]:
    """Read satellite counts independently of whether a position fix exists."""
    fields = parse_nmea(sentence)
    if fields is None or not re.fullmatch(r"[A-Z]{2}(GGA|GSV)", fields[0]):
        return None
    try:
        if fields[0].endswith("GSV"):
            if not all(re.fullmatch(r"[0-9]+", value) for value in fields[1:3]):
                return None
            if not 1 <= int(fields[2]) <= int(fields[1]):
                return None
            # Every part repeats the total; do not add the parts together.
            # Keep talkers separate so different constellations do not overwrite
            # one another (GP is GPS; GN is combined GNSS).
            label, count = f"Satellites in view ({fields[0][:2]})", fields[3]
        else:
            label, count = "Satellites used for fix", fields[7]
        if not re.fullmatch(r"[0-9]{1,2}", count):
            return None
        return label, int(count)
    except (ValueError, IndexError):
        return None


def available_ports() -> List[Tuple[str, str, bool]]:
    """List (device, description, is_usb), preferring persistent Linux names."""
    from serial.tools import list_ports

    aliases = {}
    for path in sorted(glob.glob("/dev/serial/by-id/*")):
        if os.path.exists(path):
            aliases.setdefault(os.path.realpath(path), path)

    ports = {}
    for info in list_ports.comports():
        real_path = os.path.realpath(info.device)
        device = aliases.get(real_path, info.device)
        description = " / ".join(dict.fromkeys(
            value for value in (info.description, info.manufacturer, info.product)
            if value and value != "n/a"
        )) or "Unknown serial device"
        is_usb = (info.vid is not None or real_path in aliases
                  or real_path.startswith(("/dev/ttyACM", "/dev/ttyUSB")))
        ports[real_path] = (device, description, is_usb)

    # Some systems omit USB ports from enumeration but still expose by-id links.
    for real_path, alias in aliases.items():
        ports.setdefault(real_path, (alias, "USB serial device", True))
    return sorted(ports.values())


def detect_port(ports: Optional[List[Tuple[str, str, bool]]] = None) -> str:
    """Choose an unambiguous GPS or USB serial device without opening ports.

    Supply an existing available_ports() result to reuse the service's discovery
    snapshot. None performs a fresh scan; an empty list means that scan found no
    devices and must not trigger another scan. Selection identifies a candidate,
    not proof of NMEA output; the reader validates the incoming sentences.
    """
    if ports is None:
        ports = available_ports()
    gps_names = r"gps|gnss|u[ -]?blox|vk[ -]?172|g[ -]?mouse"
    candidates = [device for device, description, _ in ports
                  if re.search(gps_names, f"{device} {description}", re.IGNORECASE)]
    if not candidates:
        candidates = [device for device, _, is_usb in ports if is_usb]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError("No USB GPS/serial device found. Connect the receiver or use "
                         "--list-ports and --port DEVICE.")
    raise ValueError("Multiple possible GPS devices found: " + ", ".join(candidates)
                     + ". Choose one with --port DEVICE; --list-ports shows descriptions.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", help="Serial device (default: auto-detect GPS/USB serial)")
    parser.add_argument("--list-ports", action="store_true", help="List serial devices and exit")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--once", action="store_true", help="Exit after the first valid position")
    args = parser.parse_args()
    if args.baud <= 0:
        parser.error("--baud must be positive")

    try:
        import serial
    except ImportError:
        print("Install pySerial first: sudo apt install python3-serial", file=sys.stderr)
        return 1

    try:
        if args.list_ports:
            ports = available_ports()
            for device, description, _ in ports:
                print(f"{device}  |  {description}")
            if not ports:
                print("No serial devices found.")
            return 0
        port = args.port or detect_port()
        with serial.Serial(port, baudrate=args.baud, timeout=1) as gps:
            print(f"Reading {port} at {args.baud} baud. "
                  "Waiting for satellite data and a GPS fix; Ctrl-C to stop.",
                  file=sys.stderr)
            pending = b""
            satellite_reports = {}
            last_fix = last_notice = time.monotonic()
            while True:
                # Keep partial sentences across read timeouts and bound memory
                # if the device outputs binary data or data without newlines.
                pending += gps.read(min(gps.in_waiting or 1, 4096))
                while b"\n" in pending:
                    sentence, pending = pending.split(b"\n", 1)
                    satellite_status = parse_satellite_status(sentence)
                    if satellite_status is not None:
                        label, count = satellite_status
                        now = time.monotonic()
                        previous = satellite_reports.get(label)
                        if previous is None or count != previous[0] or now - previous[1] >= 10:
                            print(f"{label}: {count}", file=sys.stderr, flush=True)
                            satellite_reports[label] = (count, now)
                    position = parse_position(sentence)
                    if position is None:
                        continue
                    lat, lon = position
                    print(f"Lat Long: {lat:.6f}, {lon:.6f}", flush=True)
                    last_fix = time.monotonic()
                    if args.once:
                        return 0
                pending = pending[-1024:]
                now = time.monotonic()
                if now - max(last_fix, last_notice) >= 10:
                    print("No valid position in the last 10 seconds. Give the GPS a clear "
                          "view of the sky; check --baud and that NMEA GGA/RMC output is enabled.",
                          file=sys.stderr)
                    last_notice = now
    except (serial.SerialException, OSError, ValueError) as exc:
        print(f"GPS error: {exc}", file=sys.stderr)
        print("Check --port and device permissions. For permission denied on Raspberry Pi OS, "
              "run: sudo usermod -aG dialout \"$USER\" then log out and back in.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
