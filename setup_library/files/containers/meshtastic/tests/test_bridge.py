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


class AutoFlashIntegrationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        # flash_probe_after=1 lets a single failure trigger the probe in tests
        # that specifically exercise flashing; the threshold has its own test.
        self.radio = bridge.RadioBridge("/dev/fake", self.data_dir, 0,
                                        firmware_dir="/fw", auto_flash=True,
                                        flash_probe_after=1)

    def test_handshake_success_returns_metadata_and_keeps_guard_armed(self):
        with mock.patch.object(bridge, "bootstrap_radio",
                               return_value={"long_name": "library0001"}) as boot, \
                mock.patch.object(bridge.flash, "auto_flash") as auto:
            result = self.radio._bootstrap_with_autoflash()
        self.assertEqual(result["long_name"], "library0001")
        auto.assert_not_called()
        self.assertFalse(self.radio._flash_attempted)
        self.assertEqual(self.radio._consecutive_failures, 0)
        boot.assert_called_once()

    def test_handshake_failure_triggers_flash_then_retries_handshake(self):
        boot = mock.Mock(side_effect=[RuntimeError("Timed out"),
                                      {"long_name": "library0002"}])
        with mock.patch.object(bridge, "bootstrap_radio", boot), \
                mock.patch.object(bridge.flash, "auto_flash", return_value=True) as auto:
            result = self.radio._bootstrap_with_autoflash()
        self.assertEqual(result["long_name"], "library0002")
        auto.assert_called_once_with("/dev/fake", "/fw", self.radio.data_dir, True)
        self.assertEqual(boot.call_count, 2)
        # A confirmed handshake re-arms the one-shot guard for future replacements.
        self.assertFalse(self.radio._flash_attempted)
        self.assertEqual(self.radio._consecutive_failures, 0)

    def test_no_flashable_board_reraises_and_does_not_retry(self):
        boot = mock.Mock(side_effect=RuntimeError("Timed out"))
        with mock.patch.object(bridge, "bootstrap_radio", boot), \
                mock.patch.object(bridge.flash, "auto_flash", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "Timed out"):
                self.radio._bootstrap_with_autoflash()
        self.assertEqual(boot.call_count, 1)
        self.assertTrue(self.radio._flash_attempted)

    def test_flash_attempted_once_until_a_working_handshake(self):
        boot = mock.Mock(side_effect=RuntimeError("Timed out"))
        with mock.patch.object(bridge, "bootstrap_radio", boot), \
                mock.patch.object(bridge.flash, "auto_flash", return_value=False) as auto:
            with self.assertRaises(RuntimeError):
                self.radio._bootstrap_with_autoflash()
            # Second cycle must not probe/flash again after a single attempt.
            with self.assertRaises(RuntimeError):
                self.radio._bootstrap_with_autoflash()
        auto.assert_called_once()

    def test_disabled_auto_flash_never_probes(self):
        self.radio.auto_flash = False
        boot = mock.Mock(side_effect=RuntimeError("Timed out"))
        with mock.patch.object(bridge, "bootstrap_radio", boot), \
                mock.patch.object(bridge.flash, "auto_flash") as auto:
            with self.assertRaises(RuntimeError):
                self.radio._bootstrap_with_autoflash()
        auto.assert_not_called()

    def test_known_good_radio_from_state_json_is_never_probed(self):
        # A prior successful init wrote state.json: a timeout now is transient.
        (self.data_dir / "state.json").write_text("{}")
        boot = mock.Mock(side_effect=RuntimeError("Timed out"))
        with mock.patch.object(bridge, "bootstrap_radio", boot), \
                mock.patch.object(bridge.flash, "auto_flash") as auto:
            with self.assertRaisesRegex(RuntimeError, "Timed out"):
                self.radio._bootstrap_with_autoflash()
        auto.assert_not_called()
        self.assertFalse(self.radio._flash_attempted)

    def test_known_good_radio_from_flash_json_is_never_probed(self):
        (self.data_dir / "flash.json").write_text("{}")
        boot = mock.Mock(side_effect=RuntimeError("Timed out"))
        with mock.patch.object(bridge, "bootstrap_radio", boot), \
                mock.patch.object(bridge.flash, "auto_flash") as auto:
            with self.assertRaises(RuntimeError):
                self.radio._bootstrap_with_autoflash()
        auto.assert_not_called()

    def test_first_seen_board_is_not_probed_until_threshold_reached(self):
        self.radio.flash_probe_after = 3
        boot = mock.Mock(side_effect=RuntimeError("Timed out"))
        with mock.patch.object(bridge, "bootstrap_radio", boot), \
                mock.patch.object(bridge.flash, "auto_flash", return_value=False) as auto:
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    self.radio._bootstrap_with_autoflash()
            auto.assert_not_called()  # first two failures must not probe/reset
            with self.assertRaises(RuntimeError):
                self.radio._bootstrap_with_autoflash()  # third failure probes
            auto.assert_called_once()

    def test_known_good_not_probed_below_reprovision_threshold(self):
        # reprovision_after = max(fp, fp*4). With flash_probe_after=1 -> 4.
        (self.data_dir / "state.json").write_text("{}")
        self.assertEqual(self.radio.reprovision_after, 4)
        boot = mock.Mock(side_effect=RuntimeError("Timed out"))
        with mock.patch.object(bridge, "bootstrap_radio", boot), \
                mock.patch.object(bridge.flash, "app_is_blank") as blank, \
                mock.patch.object(bridge.flash, "auto_flash") as auto:
            for _ in range(3):  # below the threshold of 4
                with self.assertRaises(RuntimeError):
                    self.radio._bootstrap_with_autoflash()
        blank.assert_not_called()  # never even probe a known-good radio yet
        auto.assert_not_called()

    def test_known_good_blank_board_is_reprovisioned_and_record_cleared(self):
        (self.data_dir / "state.json").write_text("{}")
        (self.data_dir / "flash.json").write_text("{}")
        (self.data_dir / "config.yaml").write_text("x")
        # bootstrap_radio times out until a flash happens, then succeeds. Track
        # flashing via a mutable flag so ordering of internal calls cannot break
        # the test regardless of how many probe cycles run.
        state = {"flashed": False}

        def fake_bootstrap(*_a, **_k):
            if state["flashed"]:
                return {"long_name": "library0001"}
            raise RuntimeError("Timed out")

        def fake_flash(*_a, **_k):
            state["flashed"] = True
            return True

        with mock.patch.object(bridge, "bootstrap_radio", side_effect=fake_bootstrap), \
                mock.patch.object(bridge.flash, "app_is_blank", return_value=True) as blank, \
                mock.patch.object(bridge.flash, "auto_flash", side_effect=fake_flash) as auto:
            for _ in range(3):  # below threshold: just retries, no probe
                with self.assertRaises(RuntimeError):
                    self.radio._bootstrap_with_autoflash()
            blank.assert_not_called()
            # 4th failure reaches reprovision_after: probe -> blank -> flash -> retry
            result = self.radio._bootstrap_with_autoflash()
        self.assertEqual(result["long_name"], "library0001")
        blank.assert_called_once_with("/dev/fake")
        auto.assert_called_once()
        # The stale record must have been cleared before flashing.
        self.assertFalse((self.data_dir / "state.json").exists())
        self.assertFalse((self.data_dir / "flash.json").exists())
        self.assertFalse((self.data_dir / "config.yaml").exists())

    def test_known_good_nonblank_board_is_left_untouched(self):
        (self.data_dir / "state.json").write_text("{}")
        boot = mock.Mock(side_effect=RuntimeError("Timed out"))
        with mock.patch.object(bridge, "bootstrap_radio", boot), \
                mock.patch.object(bridge.flash, "app_is_blank", return_value=False) as blank, \
                mock.patch.object(bridge.flash, "auto_flash") as auto:
            for _ in range(6):  # well past the reprovision threshold
                with self.assertRaises(RuntimeError):
                    self.radio._bootstrap_with_autoflash()
        # Probed at most once (one-shot), never flashed, record intact.
        blank.assert_called_once()
        auto.assert_not_called()
        self.assertTrue((self.data_dir / "state.json").exists())


if __name__ == "__main__":
    unittest.main()
