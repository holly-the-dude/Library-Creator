#!/usr/bin/env python3
"""Expose the Meshtastic HTTP protobuf API for one USB serial radio.

Bootstrap uses the official Python API for naming and a configuration backup.
After that, raw serial frames belong exclusively to the web client: running a
second Python protocol client would interfere with its configuration download.
"""

import collections
from contextlib import suppress
import json
import logging
import math
import os
from pathlib import Path
import signal
import termios
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from google.protobuf.message import DecodeError
from meshtastic.protobuf import mesh_pb2
import serial

from bootstrap import bootstrap_radio
import flash

LOG = logging.getLogger("meshtastic.bridge")
MAGIC = b"\x94\xc3"
MAX_PACKET = 512


class FrameDecoder:
    """Extract protobuf frames, ignoring interspersed device debug output."""

    def __init__(self):
        self.buffer = bytearray()
        self.last_data = time.monotonic()

    def feed(self, data):
        now = time.monotonic()
        if now - self.last_data > 2:
            self.buffer.clear()  # abandon an interrupted frame after unplug/reboot
        if data:
            self.last_data = now
        self.buffer.extend(data)
        packets = []
        while self.buffer:
            start = self.buffer.find(MAGIC)
            if start < 0:
                self.buffer[:] = b"\x94" if self.buffer[-1] == 0x94 else b""
                break
            del self.buffer[:start]
            if len(self.buffer) < 4:
                break
            size = int.from_bytes(self.buffer[2:4], "big")
            if not 0 < size <= MAX_PACKET:
                del self.buffer[0]
                continue
            if len(self.buffer) < size + 4:
                break
            packets.append(bytes(self.buffer[4:4 + size]))
            del self.buffer[:4 + size]
        return packets


def open_serial(device):
    # Match Meshtastic SerialInterface: prevent close from resetting the ESP32.
    # Do not adopt the radio as our controlling terminal when running as PID 1.
    descriptor = os.open(device, os.O_RDONLY | os.O_NOCTTY)
    try:
        attrs = termios.tcgetattr(descriptor)
        attrs[2] &= ~termios.HUPCL
        termios.tcsetattr(descriptor, termios.TCSAFLUSH, attrs)
    finally:
        os.close(descriptor)
    stream = serial.Serial(device, 115200, exclusive=True,
                           timeout=0.5, write_timeout=3)
    try:
        stream.reset_input_buffer()
        stream.write(b"\xc3" * 32)  # official wake/resynchronization sequence
        stream.flush()
        time.sleep(0.1)
    except Exception:
        stream.close()
        raise
    return stream


class RadioBridge:
    def __init__(self, device, data_dir, discovery_seconds=60,
                 firmware_dir=None, auto_flash=True, flash_probe_after=3):
        self.device = device
        self.data_dir = Path(data_dir)
        self.discovery_seconds = discovery_seconds
        self.firmware_dir = firmware_dir
        self.auto_flash = auto_flash
        # Only probe/flash after this many consecutive handshake failures on a
        # first-seen board, so a transient boot-timing miss never resets it.
        self.flash_probe_after = max(1, int(flash_probe_after))
        # A "known good" radio (state.json/flash.json present) is normally never
        # probed. But its record can be stale -- e.g. the board was wiped or
        # swapped for a blank one, or the volume persisted across a reinstall.
        # After this many consecutive failures we run a READ-ONLY blank-app
        # probe; only a board confirmed to have no valid app image is reflashed.
        # This is deliberately higher than flash_probe_after so a working radio
        # riding out a long transient (contention, slow boot) is left alone.
        self.reprovision_after = max(self.flash_probe_after,
                                     int(flash_probe_after) * 4)
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.stream = None
        self.packets = collections.deque(maxlen=4096)
        self.metadata = {}
        self.error = "Waiting for the radio configuration and node discovery"
        self.dropped_packets = 0
        # Guard against a reflash loop: attempt an automatic flash at most once
        # per detected unflashed board until a Meshtastic handshake succeeds.
        self._flash_attempted = False
        self._consecutive_failures = 0
        # A known-good radio is blank-probed at most once per session. Without
        # this, a merely-unreachable (not blank) known-good radio would be
        # RTS-reset by the probe every reprovision_after cycles.
        self._reprovision_probed = False

    def status(self):
        with self.lock:
            return {**self.metadata, "ready": self.stream is not None,
                    "serial_device": self.device, "error": self.error,
                    "queued_packets": len(self.packets),
                    "dropped_packets": self.dropped_packets}

    def send(self, payload):
        if not 0 < len(payload) <= MAX_PACKET:
            raise ValueError("ToRadio packet must contain 1 to 512 bytes")
        message = mesh_pb2.ToRadio()
        try:
            message.ParseFromString(payload)
        except DecodeError as exc:
            raise ValueError("Invalid ToRadio protobuf") from exc
        if message.WhichOneof("payload_variant") is None:
            raise ValueError("ToRadio payload is missing or unsupported")
        with self.lock:
            if self.stream is None:
                raise ConnectionError(self.error)
            if message.HasField("want_config_id"):
                # A fresh client handshake must not consume a previous session.
                self.packets.clear()
            frame = MAGIC + len(payload).to_bytes(2, "big") + payload
            try:
                if self.stream.write(frame) != len(frame):
                    raise serial.SerialTimeoutException("Incomplete serial write")
            except (serial.SerialException, OSError) as exc:
                self.error = f"Serial write failed: {exc}"
                self.stream.close()  # reader will reconnect and repeat bootstrap
                self.stream = None
                raise ConnectionError(self.error) from exc

    def receive(self, all_packets=False):
        with self.lock:
            if self.stream is None:
                raise ConnectionError(self.error)
            if all_packets:
                # Firmware's HTTP API concatenates protobufs without framing.
                payload = b"".join(self.packets)
                self.packets.clear()
                return payload
            return self.packets.popleft() if self.packets else b""

    def _radio_known_good(self):
        """True when this setup has ever completed a handshake or been flashed.

        ``state.json`` is written only after a successful configuration/backup,
        and ``flash.json`` only after a successful flash. Either means a real
        Meshtastic radio has answered here before, so a later handshake timeout
        is a transient boot/timing issue -- never a reason to reset or reflash
        the board. Probing would hard-reset a working radio via RTS and can
        knock it offline, so we must not probe once a radio is known good.
        """
        for name in ("state.json", "flash.json"):
            if (self.data_dir / name).exists():
                return True
        return False

    def _clear_known_good(self):
        """Remove the stale working/flashed record so the board is first-seen.

        Called only after a read-only probe confirmed the board is blank, so we
        are not discarding the record of a healthy radio.
        """
        for name in ("state.json", "flash.json", "nodes.json", "config.yaml"):
            with suppress(OSError):
                (self.data_dir / name).unlink()

    def _bootstrap_with_autoflash(self):
        """Bootstrap the radio; flash a genuinely unflashed or wiped board.

        The esptool probe hard-resets the ESP32-S3, so it must never run against
        a radio that already works. Two paths reach a flash:

        * First-seen board (no state/flash record): after ``flash_probe_after``
          consecutive failures, probe and flash a matching unflashed board.
        * Known-good board (record present) that keeps failing: normally left
          alone, because a timeout is usually transient. But after the higher
          ``reprovision_after`` threshold we run a READ-ONLY blank-app probe;
          only if the board is confirmed to have no valid app image (wiped or
          swapped for a blank one) do we clear the stale record and reflash.

        A single flash is attempted per session; a successful handshake re-arms
        everything.
        """
        try:
            metadata = bootstrap_radio(self.device, self.data_dir,
                                       self.discovery_seconds)
            self._flash_attempted = False   # a working radio re-arms the guard
            self._consecutive_failures = 0
            self._reprovision_probed = False
            return metadata
        except Exception as exc:
            self._consecutive_failures += 1
            if not self.auto_flash or self._flash_attempted or self.stop.is_set():
                raise
            known_good = self._radio_known_good()
            if known_good:
                # Only reconsider a known-good radio after a long, sustained
                # failure, and only reflash if a read-only probe proves it is
                # genuinely blank. A working radio never reaches this state.
                if (self._consecutive_failures < self.reprovision_after
                        or self._reprovision_probed):
                    raise
                self._reprovision_probed = True  # probe at most once per session
                LOG.warning("Known-good radio has failed %d times; running a "
                            "read-only blank-app probe to check the flash",
                            self._consecutive_failures)
                if not flash.app_is_blank(self.device):
                    LOG.info("Board is not blank (or is unreachable); leaving it "
                             "untouched and continuing to retry")
                    raise
                LOG.warning("Board reports a blank/invalid app image; the stored "
                            "record is stale. Reprovisioning firmware.")
                self._clear_known_good()
            elif self._consecutive_failures < self.flash_probe_after:
                # Give a first-seen board a few cycles to boot before resetting.
                LOG.info("Handshake failed (%s); attempt %d of %d before probing "
                         "for an unflashed board", exc, self._consecutive_failures,
                         self.flash_probe_after)
                raise
            else:
                LOG.warning("Handshake failed %d times (%s); checking for an "
                            "unflashed supported board",
                            self._consecutive_failures, exc)
            self._flash_attempted = True
            with self.lock:
                self.error = "Checking for an unflashed board to install firmware"
            flashed = flash.auto_flash(self.device, self.firmware_dir,
                                       self.data_dir, self.auto_flash)
            if not flashed or self.stop.is_set():
                raise
            LOG.info("Firmware installed; retrying the Meshtastic handshake")
            metadata = bootstrap_radio(self.device, self.data_dir,
                                       self.discovery_seconds)
            self._flash_attempted = False
            self._consecutive_failures = 0
            self._reprovision_probed = False
            return metadata

    def run(self):
        while not self.stop.is_set():
            stream = None
            try:
                metadata = self._bootstrap_with_autoflash()
                if self.stop.is_set():
                    break
                stream = open_serial(self.device)
                decoder = FrameDecoder()
                with self.lock:
                    self.metadata = metadata
                    self.packets.clear()
                    self.stream = stream
                    self.error = None
                LOG.info("Radio ready; web client may connect over HTTP")
                while not self.stop.is_set():
                    data = stream.read(max(1, min(stream.in_waiting, 4096)))
                    for payload in decoder.feed(data):
                        # Do not queue noise that happened to resemble a header.
                        try:
                            message = mesh_pb2.FromRadio.FromString(payload)
                        except DecodeError:
                            continue
                        if message.WhichOneof("payload_variant") is None:
                            continue
                        with self.lock:
                            if len(self.packets) == self.packets.maxlen:
                                self.dropped_packets += 1
                            self.packets.append(payload)
            except Exception as exc:
                # Keep nginx/status available during unplugged or unflashed USB.
                with self.lock:
                    self.error = f"{type(exc).__name__}: {exc}"
                LOG.warning("Radio unavailable: %s; retrying in 10 seconds", exc)
            finally:
                with self.lock:
                    self.stream = None
                    self.packets.clear()
                if stream is not None:
                    stream.close()
            self.stop.wait(10)


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, bridge):
        super().__init__(address, Handler)
        self.bridge = bridge

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(5)
        return sock, address


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass  # nginx logs requests; never log protobuf/configuration contents

    def reply(self, status, body=b"", content_type="application/x-protobuf"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path in ("/health", "/bridge/status"):
            status = self.server.bridge.status()
            self.reply(200, json.dumps(status).encode(), "application/json")
        elif url.path == "/api/v1/fromradio":
            try:
                payload = self.server.bridge.receive(
                    parse_qs(url.query).get("all", ["false"])[0] == "true")
                self.reply(200, payload)
            except ConnectionError as exc:
                self.reply(503, str(exc).encode(), "text/plain")
        else:
            self.reply(404)

    def do_OPTIONS(self):
        if urlsplit(self.path).path != "/api/v1/toradio":
            self.reply(404)
        elif not self.server.bridge.status()["ready"]:
            self.reply(503, b"Radio is initializing or disconnected", "text/plain")
        else:
            self.reply(204)

    def do_PUT(self):
        if urlsplit(self.path).path != "/api/v1/toradio":
            self.reply(404)
            return
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Use Content-Length, not chunked transfer")
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_PACKET:
                raise ValueError("ToRadio packet must contain 1 to 512 bytes")
            payload = self.rfile.read(size)
            if len(payload) != size:
                raise ValueError("Incomplete request body")
            self.server.bridge.send(payload)
            self.reply(200)
        except ValueError as exc:
            self.reply(400, str(exc).encode(), "text/plain")
        except ConnectionError as exc:
            self.reply(503, str(exc).encode(), "text/plain")


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # Upstream SerialInterface briefly opens the TTY without O_NOCTTY during
    # bootstrap. An unplug must reach the retry loop, not terminate this daemon.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    discovery = float(os.environ.get("DISCOVERY_SECONDS", "60"))
    if not math.isfinite(discovery) or not 0 <= discovery <= 3600:
        raise ValueError("DISCOVERY_SECONDS must be between 0 and 3600")
    auto_flash = os.environ.get("AUTO_FLASH", "1").strip().lower() not in (
        "0", "false", "no", "off", "")
    try:
        probe_after = int(os.environ.get("FLASH_PROBE_AFTER", "3"))
    except ValueError:
        probe_after = 3
    bridge = RadioBridge(os.environ.get("SERIAL_DEVICE", "/dev/meshtastic"),
                         os.environ.get("DATA_DIR", "/var/lib/meshtastic"),
                         discovery,
                         os.environ.get("FIRMWARE_DIR", "/opt/meshtastic/firmware"),
                         auto_flash, probe_after)
    worker = threading.Thread(target=bridge.run, daemon=True, name="radio")
    worker.start()
    server = BridgeServer(("127.0.0.1", 8766), bridge)
    server.timeout = 0.5
    signal.signal(signal.SIGTERM, lambda *_: bridge.stop.set())
    signal.signal(signal.SIGINT, lambda *_: bridge.stop.set())
    try:
        while not bridge.stop.is_set() and worker.is_alive():
            server.handle_request()
    finally:
        bridge.stop.set()
        server.server_close()
        worker.join(timeout=5)


if __name__ == "__main__":
    main()
