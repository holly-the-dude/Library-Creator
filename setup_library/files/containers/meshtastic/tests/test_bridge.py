"""Exercise the real protobuf/HTTP boundary without a physical radio."""

import http.client
import os
from pathlib import Path
import select
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bridge
from meshtastic.protobuf import mesh_pb2


def frame(payload):
    return bridge.MAGIC + len(payload).to_bytes(2, "big") + payload


def node_packet(number, name):
    message = mesh_pb2.FromRadio()
    message.node_info.num = number
    message.node_info.user.long_name = name
    return message.SerializeToString()


class SerialCapture:
    def __init__(self, incomplete=False):
        self.writes = []
        self.incomplete = incomplete
        self.closed = False

    def write(self, payload):
        self.writes.append(payload)
        return len(payload) - int(self.incomplete)

    def close(self):
        self.closed = True


class FrameDecoderTests(unittest.TestCase):
    def test_every_split_boundary_with_debug_noise_and_multiple_packets(self):
        packets = [node_packet(123, "library0001"), node_packet(456, "other")]
        wire = b"boot: ready\r\n" + frame(packets[0]) + b"debug\n" + frame(packets[1])
        for split in range(len(wire) + 1):
            with self.subTest(split=split):
                decoder = bridge.FrameDecoder()
                self.assertEqual(decoder.feed(wire[:split]) + decoder.feed(wire[split:]), packets)

    def test_single_byte_reads_and_invalid_lengths_resynchronize(self):
        payload = node_packet(123, "library0001")
        wire = b"\x94\x94\xc3\xff\xffbad\x94\xc3\x00\x00" + frame(payload)
        decoder = bridge.FrameDecoder()
        packets = []
        for value in wire:
            packets.extend(decoder.feed(bytes([value])))
        self.assertEqual(packets, [payload])
        self.assertEqual(decoder.buffer, b"")

    def test_abandons_incomplete_frame_after_serial_idle(self):
        payload = node_packet(123, "library0001")
        with mock.patch.object(bridge.time, "monotonic", side_effect=[0, 0, 3]):
            decoder = bridge.FrameDecoder()
            self.assertEqual(decoder.feed(b"\x94\xc3\x01\xffpartial"), [])
            self.assertEqual(decoder.feed(frame(payload)), [payload])


class RadioBridgeTests(unittest.TestCase):
    def setUp(self):
        self.radio = bridge.RadioBridge("/dev/fake", "/unused", 0)
        self.capture = SerialCapture()
        self.radio.stream = self.capture

    def test_configuration_request_discards_previous_session_queue(self):
        self.radio.packets.append(node_packet(123, "stale"))
        message = mesh_pb2.ToRadio(want_config_id=4321)
        self.radio.send(message.SerializeToString())
        self.assertEqual(self.capture.writes, [frame(message.SerializeToString())])
        self.assertEqual(self.radio.receive(), b"")

    def test_heartbeat_does_not_discard_received_packets(self):
        incoming = node_packet(123, "library0001")
        self.radio.packets.append(incoming)
        message = mesh_pb2.ToRadio()
        message.heartbeat.nonce = 2
        self.radio.send(message.SerializeToString())
        self.assertEqual(self.radio.receive(), incoming)

    def test_rejects_invalid_protobuf_without_writing_serial(self):
        for payload in (b"", b"\xff", b"x" * 513, b"\x80\x01\x01"):
            with self.subTest(payload=payload[:8]):
                with self.assertRaises(ValueError):
                    self.radio.send(payload)
        self.assertEqual(self.capture.writes, [])

    def test_partial_serial_write_marks_radio_disconnected(self):
        self.capture.incomplete = True
        payload = mesh_pb2.ToRadio(want_config_id=1).SerializeToString()
        with self.assertRaises(ConnectionError):
            self.radio.send(payload)
        self.assertTrue(self.capture.closed)
        self.assertFalse(self.radio.status()["ready"])
        with self.assertRaises(ConnectionError):
            self.radio.receive()


class HttpApiTests(unittest.TestCase):
    def setUp(self):
        self.radio = bridge.RadioBridge("/dev/fake", "/unused", 0)
        self.radio.stream = SerialCapture()
        self.radio.error = None
        self.server = bridge.BridgeServer(("127.0.0.1", 0), self.radio)
        self.worker = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_official_client_probe_put_and_poll_until_empty(self):
        self.assertEqual(self.request("OPTIONS", "/api/v1/toradio")[0], 204)
        outgoing = mesh_pb2.ToRadio(want_config_id=12345).SerializeToString()
        status, _, _ = self.request("PUT", "/api/v1/toradio", outgoing,
                                    {"Content-Type": "application/x-protobuf"})
        self.assertEqual(status, 200)
        self.assertEqual(self.radio.stream.writes, [frame(outgoing)])
        incoming = node_packet(123, "library0001")
        self.radio.packets.append(incoming)
        status, headers, body = self.request("GET", "/api/v1/fromradio?all=false")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/x-protobuf")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(body, incoming)
        self.assertEqual(mesh_pb2.FromRadio.FromString(body).node_info.user.long_name,
                         "library0001")
        self.assertEqual(self.request("GET", "/api/v1/fromradio?all=false")[2], b"")

    def test_all_true_returns_firmware_style_raw_concatenation(self):
        first = node_packet(123, "library0001")
        second = node_packet(456, "library0002")
        self.radio.packets.extend([first, second])
        self.assertEqual(self.request("GET", "/api/v1/fromradio?all=true")[2], first + second)
        self.assertEqual(self.request("GET", "/api/v1/fromradio")[2], b"")

    def test_invalid_requests_do_not_reach_serial(self):
        for payload in (b"\xff", b"x" * 513, b""):
            with self.subTest(length=len(payload)):
                self.assertEqual(self.request("PUT", "/api/v1/toradio", payload)[0], 400)
        self.assertEqual(self.request("PUT", "/wrong", b"hello")[0], 404)
        self.assertEqual(self.request("GET", "/wrong")[0], 404)
        self.assertEqual(self.radio.stream.writes, [])

    def test_disconnected_radio_returns_503_while_health_remains_available(self):
        self.radio.stream = None
        self.radio.error = "USB disconnected"
        for method, path, body in (
            ("OPTIONS", "/api/v1/toradio", None),
            ("GET", "/api/v1/fromradio", None),
            ("PUT", "/api/v1/toradio", mesh_pb2.ToRadio(want_config_id=1).SerializeToString()),
        ):
            self.assertEqual(self.request(method, path, body)[0], 503)
        for path in ("/health", "/bridge/status"):
            status, headers, body = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "application/json")
            self.assertFalse(bridge.json.loads(body)["ready"])


@unittest.skipUnless(hasattr(os, "openpty"), "Requires a POSIX pseudo-terminal")
class PtyWorkerIntegrationTests(unittest.TestCase):
    def wait_until(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if predicate():
                return
            threading.Event().wait(0.01)
        self.fail("Serial worker did not reach the expected state within 3 seconds")

    def read_exact(self, descriptor, size):
        result = bytearray()
        deadline = time.monotonic() + 3
        while len(result) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([descriptor], [], [], remaining)[0]:
                self.fail("Timed out waiting for serial bytes")
            result.extend(os.read(descriptor, size - len(result)))
        return bytes(result)

    def test_http_serial_roundtrip_and_unplug_cleanup(self):
        master, slave = os.openpty()
        radio = bridge.RadioBridge(os.ttyname(slave), "/unused", 0)
        server = bridge.BridgeServer(("127.0.0.1", 0), radio)
        http_worker = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        serial_worker = threading.Thread(target=radio.run, daemon=True)
        connection = http.client.HTTPConnection(*server.server_address, timeout=2)
        http_worker.start()
        try:
            with mock.patch.object(bridge, "bootstrap_radio", return_value={"long_name": "library0001"}):
                serial_worker.start()
                self.wait_until(lambda: radio.status()["ready"])
                serial_port = radio.stream
                self.assertEqual(self.read_exact(master, 32), b"\xc3" * 32)

                outgoing = mesh_pb2.ToRadio(want_config_id=9876).SerializeToString()
                connection.request("PUT", "/api/v1/toradio", body=outgoing,
                                   headers={"Content-Type": "application/x-protobuf"})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
                self.assertEqual(self.read_exact(master, len(outgoing) + 4), frame(outgoing))

                incoming = node_packet(123, "library0001")
                # Real pyserial reads must discard malformed protobufs and debug text.
                os.write(master, b"boot log\r\n" + frame(b"\xff") + frame(b"\x08\x01")
                         + frame(incoming)[:2])
                os.write(master, frame(incoming)[2:])
                self.wait_until(lambda: radio.status()["queued_packets"] == 1)
                connection.request("GET", "/api/v1/fromradio?all=false")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), incoming)

                # Closing the fake device produces the same reader failure as unplugging USB.
                os.close(master)
                master = None
                self.wait_until(lambda: not radio.status()["ready"])
                self.assertFalse(serial_port.is_open)
                self.assertTrue(radio.status()["error"])
                connection.request("GET", "/api/v1/fromradio")
                response = connection.getresponse()
                self.assertEqual(response.status, 503)
                response.read()
                radio.stop.set()  # Interrupt the reconnect delay and stop the worker.
                serial_worker.join(timeout=3)
                self.assertFalse(serial_worker.is_alive())
        finally:
            radio.stop.set()
            serial_worker.join(timeout=3)
            connection.close()
            server.shutdown()
            server.server_close()
            http_worker.join(timeout=2)
            if master is not None:
                os.close(master)
            os.close(slave)


class BootstrapFailureTests(unittest.TestCase):
    def test_repeated_failure_preserves_backups_and_only_retries_bootstrap(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("state.json", "config.yaml", "nodes.json", "flash.json"):
                (root / name).write_text("preserve-me")
            radio = bridge.RadioBridge("/dev/fake", root, 0)
            attempts = 0

            def failed_bootstrap(*args):
                nonlocal attempts
                attempts += 1
                if attempts == 6:
                    radio.stop.set()
                raise RuntimeError("Timed out")

            with mock.patch.object(bridge, "bootstrap_radio", side_effect=failed_bootstrap), \
                    mock.patch.object(radio.stop, "wait"), \
                    mock.patch.object(bridge, "open_serial") as opened:
                radio.run()
            self.assertEqual(attempts, 6)
            opened.assert_not_called()
            self.assertFalse(radio.status()["ready"])
            self.assertIn("Timed out", radio.status()["error"])
            for path in root.iterdir():
                self.assertEqual(path.read_text(), "preserve-me")


if __name__ == "__main__":
    unittest.main()
