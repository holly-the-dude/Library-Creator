#!/usr/bin/env python3
"""Expose one read-only serial GPS reader to nginx at 127.0.0.1:8765/api/gps.

GPS_PORT selects a receiver explicitly; otherwise read_gps auto-detection is used.
GPS_BAUD defaults to 9600. No commands are sent to the receiver. This service is
intended to be proxied by the maps container, rather than exposed directly.

Data flow: GPSMonitor owns the serial port and updates GPSState; HTTP request
threads only read snapshots. This lets every browser share the same receiver
without competing for serial bytes. No coordinates are saved to disk.

API coordinates are decimal degrees and may describe the last known position.
Clients must check fix_valid before treating them as current. Detection, an open
serial connection, and receipt of supported NMEA data are reported separately:
a generic USB serial device can be present without actually being a GPS.
"""

import argparse
import json
import math
import os
import re
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from read_gps import available_ports, detect_port, parse_nmea, parse_position, parse_satellite_status


# Keep the browser's FRESH_FIX_SECONDS in gps-control.js aligned with this limit.
FIX_MAX_AGE = 10.0
# Cap incomplete/binary input while leaving room for extended NMEA sentences.
MAX_SENTENCE_BYTES = 1024
# Avoid busy rescanning when no receiver is attached; Event.wait makes this
# delay interruptible so container shutdown does not wait for the next scan.
RETRY_SECONDS = 2.0


def _number(fields, index):
    """Read an optional, finite numeric diagnostic without breaking the reader."""
    try:
        value = float(fields[index])
        return value if math.isfinite(value) else None
    except (IndexError, ValueError):
        return None


class GPSState:
    """Share receiver data safely between the serial reader and HTTP threads.

    All state mutations and snapshot copies hold the same lock. Freshness is
    derived when a snapshot is requested, so a silent receiver cannot leave a
    previously valid position marked current forever.
    """

    def __init__(self, baud=9600, clock=time.monotonic):
        # Monotonic time measures age independently of wall-clock corrections.
        # An injected clock also lets tests advance time without sleeping.
        self.clock = clock
        self.lock = threading.Lock()
        self.data = {
            # Discovery can find multiple candidates, even if none is opened.
            "detected": False,
            "connected": False,
            # Set only after checksum-valid GGA, RMC or GSV input is received.
            "gps_detected": False,
            "status": "no_device",
            "message": "No USB GPS/serial receiver found. Connect a receiver to begin.",
            "port": None,
            "baud": baud,
            # None means no accepted position yet; loss of fix retains these.
            "latitude": None,
            "longitude": None,
            # None means unreported, whereas zero is a receiver-reported count.
            "satellites_used": None,
            "satellites_in_view": {},
            "hdop": None,
            "altitude_m": None,
            "last_sentence": None,
            "ports": [],
        }
        self.last_fix = None
        self.last_data = None
        # None: no position report in this connection; False: latest GGA/RMC
        # rejected; True: latest GGA/RMC accepted (its age is checked separately).
        self.position_valid = None

    def scanned(self, ports, detected, port):
        """Publish a discovery result without opening or validating a receiver."""
        with self.lock:
            self.data.update(
                detected=detected,
                port=port,
                ports=[{"device": device, "description": description}
                       for device, description, _ in ports],
            )

    def connected(self):
        """Begin a new serial session, clearing diagnostics from the old one."""
        with self.lock:
            self.data.update(connected=True, gps_detected=False, status="waiting",
                             message="Serial receiver opened. Waiting for NMEA GPS data.",
                             satellites_used=None, satellites_in_view={}, hdop=None,
                             altitude_m=None, last_sentence=None)
            self.last_data = None
            # Retain the last known coordinates, but require a new fix after open.
            self.position_valid = None

    def unavailable(self, status, message):
        """Invalidate a connection while retaining its last position for display."""
        with self.lock:
            self.data.update(connected=False, status=status, message=message)
            self.position_valid = None

    def received_data(self):
        """Record serial activity, including bytes that are not usable NMEA.

        Recent bytes help diagnose baud/output problems; they are not evidence
        of a recent position, so this must never refresh last_fix.
        """
        with self.lock:
            self.last_data = self.clock()

    def sentence(self, sentence):
        """Apply one complete line; bad checksums never alter fix state."""
        # A line can contain a binary prefix or an incomplete previous sentence.
        sentence = sentence[sentence.rfind(b"$"):] if b"$" in sentence else sentence
        if len(sentence) > MAX_SENTENCE_BYTES:
            return
        fields = parse_nmea(sentence)
        if fields is None:
            return
        supported = re.fullmatch(r"[A-Z]{2}(GGA|RMC|GSV)", fields[0])
        with self.lock:
            # Other checksummed sentence types remain useful in diagnostics,
            # but only the supported GPS types confirm gps_detected.
            self.data["last_sentence"] = sentence.strip().decode("ascii")
            if not supported:
                return
            self.data["gps_detected"] = True
            satellite_status = parse_satellite_status(sentence)
            if satellite_status is not None:
                _, count = satellite_status
                if fields[0].endswith("GSV"):
                    # Each multipart GSV sentence repeats its talker's total.
                    # Replace that total rather than adding parts or summing
                    # overlapping GN (combined) and GP/GL constellation counts.
                    self.data["satellites_in_view"][fields[0][:2]] = count
                else:
                    self.data["satellites_used"] = count
            if fields[0].endswith("GGA"):
                # NMEA GGA fields 8/9/10 are HDOP, altitude, and altitude units.
                # Only expose altitude as metres when the receiver declares M.
                self.data["hdop"] = _number(fields, 8)
                self.data["altitude_m"] = (_number(fields, 9)
                                           if len(fields) > 10 and fields[10] == "M" else None)
            if fields[0].endswith(("GGA", "RMC")):
                position = parse_position(sentence)
                # A checksummed no-fix (or malformed position) immediately
                # invalidates the previous fix, even if it arrived recently.
                self.position_valid = position is not None
                if position is not None:
                    self.data["latitude"], self.data["longitude"] = position
                    self.last_fix = self.clock()

    def snapshot(self):
        """Return a detached JSON-ready snapshot with ages measured in seconds."""
        with self.lock:
            now = self.clock()
            result = dict(self.data)
            # Copy nested containers too: JSON encoding happens after releasing
            # the lock, while the reader may be publishing another sentence.
            result["satellites_in_view"] = dict(self.data["satellites_in_view"])
            result["ports"] = [dict(port) for port in self.data["ports"]]
            age = None if self.last_fix is None else max(0.0, now - self.last_fix)
            result["fix_age_seconds"] = age
            result["last_data_age_seconds"] = (None if self.last_data is None
                                                 else max(0.0, now - self.last_data))
            result["fix_valid"] = bool(result["connected"] and self.position_valid
                                       and age is not None and age <= FIX_MAX_AGE)
            # Preserve discovery/open errors when disconnected. While connected,
            # distinguish stale coordinates from explicitly rejected fixes and
            # a serial stream that has not produced recognizable GPS sentences.
            if result["connected"]:
                if result["fix_valid"]:
                    result.update(status="fix", message="GPS position is current.")
                elif self.position_valid:
                    result.update(status="stale", message="GPS position is over 10 seconds old. "
                                  "Waiting for a fresh GGA or RMC position.")
                elif result["gps_detected"]:
                    result.update(status="no_fix", message="GPS data received, but no current "
                                  "position fix. Give the receiver a clear view of the sky.")
                else:
                    result.update(status="waiting", message="Serial receiver opened. Waiting "
                                  "for NMEA GGA, RMC or GSV data. Check GPS_BAUD and receiver output.")
            return result


class GPSMonitor:
    """Own the serial connection and retry scans after errors or unplugging."""

    def __init__(self, state, serial_factory, port=None, baud=9600,
                 port_lister=available_ports, stop=None, retry_seconds=RETRY_SECONDS):
        # Inject discovery and serial access so tests need neither USB hardware
        # nor pySerial; production passes serial.Serial and available_ports.
        self.state = state
        self.serial_factory = serial_factory
        self.port = port
        self.baud = baud
        self.port_lister = port_lister
        self.stop = stop if stop is not None else threading.Event()
        self.retry_seconds = retry_seconds
        self.pending = b""

    def consume(self, data):
        """Assemble newline-delimited sentences across arbitrary serial reads."""
        if not data:
            return
        self.state.received_data()
        self.pending += data
        while b"\n" in self.pending:
            sentence, self.pending = self.pending.split(b"\n", 1)
            self.state.sentence(sentence)
        # Binary output, bad baud rates and missing newlines cannot grow memory.
        self.pending = self.pending[-MAX_SENTENCE_BYTES:]

    def scan(self):
        """Select a port or publish a retryable no-device/ambiguity status."""
        ports = self.port_lister()
        if self.port:
            # Explicit paths may be UARTs omitted by USB enumeration. Resolve
            # aliases when comparing them with the same device's discovered name.
            exists = (os.path.exists(self.port) or any(
                os.path.realpath(device) == os.path.realpath(self.port)
                for device, _, _ in ports))
            self.state.scanned(ports, exists, self.port)
            if not exists:
                self.state.unavailable("no_device", "Configured GPS device is not present: "
                                       + self.port)
                return None
            return self.port
        try:
            # Use one scan for both selection and the diagnostics device list,
            # avoiding inconsistent lists if USB devices change between scans.
            port = detect_port(ports)
        except ValueError as exc:
            ambiguous = str(exc).startswith("Multiple possible GPS devices")
            self.state.scanned(ports, ambiguous, None)
            self.state.unavailable("ambiguous" if ambiguous else "no_device",
                                   str(exc).replace("--port DEVICE", "GPS_PORT=DEVICE")
                                   .replace("; --list-ports shows descriptions", "")
                                   .replace("--list-ports and ", ""))
            return None
        self.state.scanned(ports, True, port)
        return port

    def run(self):
        """Read one receiver until shutdown, reopening after connection errors."""
        while not self.stop.is_set():
            opened = False
            try:
                port = self.scan()
                if port is not None:
                    with self.serial_factory(port, baudrate=self.baud, timeout=1) as receiver:
                        opened = True
                        # Never combine an old connection's partial line with
                        # the first bytes from a newly opened receiver.
                        self.pending = b""
                        self.state.connected()
                        while not self.stop.is_set():
                            # Drain available bytes in bounded chunks. With no
                            # queued bytes, wait for one byte (up to one second)
                            # instead of spinning on empty reads.
                            self.consume(receiver.read(min(receiver.in_waiting or 1, 4096)))
            except Exception as exc:
                # Include unexpected reader errors: HTTP must never retain a
                # green fix because its only reader thread stopped running.
                self.state.unavailable("disconnected" if opened else "error",
                                       "GPS connection lost: " + str(exc) if opened else
                                       "Unable to read GPS: " + str(exc)
                                       + ". Check the device, GPS_BAUD and serial permissions.")
            finally:
                if self.stop.is_set():
                    self.state.unavailable("disconnected", "GPS reader stopped.")
            self.stop.wait(self.retry_seconds)


def create_server(state, port=8765):
    """Build the loopback status API; requests never touch the serial port.

    Port zero is supported for tests that need an OS-assigned temporary port.
    The production listener is reached through nginx's same-origin /api/gps.
    """
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Absence of a GPS is a successful status query (200), not an HTTP
            # failure. The browser uses payload.status to explain the receiver.
            if urlsplit(self.path).path == "/api/gps":
                status, payload = 200, state.snapshot()
            else:
                status, payload = 404, {"error": "Not found"}
            body = json.dumps(payload, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # Cached coordinates could look current after a receiver disconnects.
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            # Every browser polls frequently; omit repetitive access-log lines.
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    # A slow client must not keep the process alive after container shutdown.
    server.daemon_threads = True
    return server


def main():
    """Load receiver settings, start the reader, and serve until SIGINT/SIGTERM."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=os.environ.get("GPS_PORT") or None)
    parser.add_argument("--baud", type=int, default=os.environ.get("GPS_BAUD", "9600"))
    args = parser.parse_args()
    if args.baud <= 0:
        parser.error("--baud / GPS_BAUD must be positive")
    try:
        import serial
    except ImportError:
        print("Install pySerial first: sudo apt install python3-serial", file=sys.stderr)
        return 1

    state = GPSState(args.baud)
    stop = threading.Event()
    monitor = GPSMonitor(state, serial.Serial, args.port, args.baud, stop=stop)
    server = create_server(state)
    # handle_request returns periodically even with no HTTP traffic, allowing
    # this main thread to notice the stop event set by the signal handler.
    server.timeout = 0.5
    print(f"GPS API listening at http://127.0.0.1:8765/api/gps; "
          f"receiver={args.port or 'auto-detect'}, baud={args.baud}", flush=True)
    reader = threading.Thread(target=monitor.run, name="serial-gps-reader", daemon=True)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    reader.start()
    try:
        while not stop.is_set():
            server.handle_request()
    finally:
        stop.set()
        # Serial reads time out after one second. Bound the join as an extra
        # safeguard against a device/driver that does not return normally.
        reader.join(timeout=2)
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
