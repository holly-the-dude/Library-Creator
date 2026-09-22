#!/usr/bin/env python3
"""Expose the Meshtastic HTTP protobuf API for one USB serial radio.

Bootstrap uses the official Python API for naming and a configuration backup.
After that, raw serial frames belong exclusively to the web client: running a
second Python protocol client would interfere with its configuration download.
"""

import collections
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
    def __init__(self, device, data_dir, discovery_seconds=60):
        self.device = device
        self.data_dir = Path(data_dir)
        self.discovery_seconds = discovery_seconds
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.stream = None
        self.packets = collections.deque(maxlen=4096)
        self.metadata = {}
        self.error = "Waiting for the radio configuration and node discovery"
        self.dropped_packets = 0

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

    def run(self):
        while not self.stop.is_set():
            stream = None
            try:
                metadata = bootstrap_radio(self.device, self.data_dir,
                                           self.discovery_seconds)
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
    bridge = RadioBridge(os.environ.get("SERIAL_DEVICE", "/dev/meshtastic"),
                         os.environ.get("DATA_DIR", "/var/lib/meshtastic"),
                         discovery)
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
