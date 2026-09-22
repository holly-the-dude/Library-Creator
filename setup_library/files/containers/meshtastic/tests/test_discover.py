"""Device selection must identify the protocol, not the USB bridge vendor."""

import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import discover


class SerialProtocolTests(unittest.TestCase):
    def test_real_client_recognizes_meshtastic_over_a_pseudo_terminal(self):
        from bridge import FrameDecoder
        from meshtastic.protobuf import mesh_pb2

        master, slave = os.openpty()
        stop = threading.Event()
        outgoing = []

        def radio():
            decoder = FrameDecoder()
            while not stop.is_set():
                if not select.select([master], [], [], 0.1)[0]:
                    continue
                for payload in decoder.feed(os.read(master, 4096)):
                    request = mesh_pb2.ToRadio.FromString(payload)
                    outgoing.append(request.WhichOneof("payload_variant"))
                    if not request.HasField("want_config_id"):
                        continue
                    identity = mesh_pb2.FromRadio()
                    identity.my_info.my_node_num = 123
                    metadata = mesh_pb2.FromRadio()
                    metadata.metadata.firmware_version = "2.7.serial-test"
                    node = mesh_pb2.FromRadio()
                    node.node_info.num = 123
                    node.node_info.user.id = "!0000007b"
                    complete = mesh_pb2.FromRadio(config_complete_id=request.want_config_id)
                    for message in (identity, metadata, node, complete):
                        data = message.SerializeToString()
                        os.write(master, b"\x94\xc3" + len(data).to_bytes(2, "big") + data)

        worker = threading.Thread(target=radio, daemon=True)
        worker.start()
        try:
            result = subprocess.run([sys.executable, discover.__file__, "--probe",
                                     os.ttyname(slave), "--timeout", "3"],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"firmware": "2.7.serial-test"})
            self.assertIn("want_config_id", outgoing)
            self.assertNotIn("packet", outgoing)  # No admin/configuration writes.
        finally:
            stop.set()
            worker.join(timeout=2)
            os.close(master)
            os.close(slave)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "serial/by-id").mkdir(parents=True)

    def device(self, tty, name=None):
        path = self.root / tty
        path.touch()
        if name:
            (self.root / "serial/by-id" / name).symlink_to("../../" + tty)
        return path

    def test_excludes_gps_and_returns_radio_by_id(self):
        self.device("ttyACM0", "usb-u-blox_GPS_Receiver")
        radio = self.device("ttyACM1", "usb-1a86_USB_Single_Serial_test-if00")
        with patch.object(Path, "is_char_device", return_value=True):
            self.assertEqual(discover.candidates(self.root), [
                (radio, "/dev/serial/by-id/usb-1a86_USB_Single_Serial_test-if00")])

    def test_explicit_gps_exclusion_and_no_alias_fallback(self):
        self.device("ttyACM0")
        radio = self.device("ttyUSB0")
        with patch.object(Path, "is_char_device", return_value=True):
            self.assertEqual(discover.candidates(self.root, exclude="/dev/ttyACM0"),
                             [(radio, "/dev/ttyUSB0")])

    def test_override_deduplicates_and_selects_only_requested_radio(self):
        radio = self.device("ttyACM1", "usb-radio")
        self.device("ttyUSB0")
        with patch.object(Path, "is_char_device", return_value=True):
            self.assertEqual(discover.candidates(self.root, device="/dev/serial/by-id/usb-radio"),
                             [(radio, "/dev/serial/by-id/usb-radio")])

    def test_missing_override_returns_no_devices(self):
        self.assertEqual(discover.candidates(self.root, device="/dev/serial/by-id/unplugged"), [])

    def test_non_device_and_path_escape_are_not_probed(self):
        self.device("ttyACM0")
        self.assertEqual(discover.candidates(self.root), [])
        with self.assertRaises(ValueError):
            discover.candidates(self.root, device="/dev/../etc/passwd")

    def scan_with(self, responses):
        ports = [(self.root / f"ttyACM{i}", f"/dev/ttyACM{i}") for i in range(len(responses))]
        with patch.object(discover, "candidates", return_value=ports), \
                patch.object(discover.subprocess, "run", side_effect=responses):
            return discover.scan(self.root)

    @staticmethod
    def reply(info=None, code=0):
        return subprocess.CompletedProcess([], code, json.dumps(info or {"firmware": "2.7.test"}))

    def test_no_devices_offers_setup(self):
        self.assertEqual(self.scan_with([]), {"status": "not_found", "devices": []})

    def test_blank_or_unresponsive_adapter_does_not_count_as_meshtastic(self):
        self.assertEqual(self.scan_with([self.reply(code=1)])["status"], "not_found")

    def test_timeout_on_first_port_does_not_hide_second_radio(self):
        result = self.scan_with([subprocess.TimeoutExpired("probe", 17), self.reply()])
        self.assertEqual(result, {"status": "found", "device": "/dev/ttyACM1", "firmware": "2.7.test"})

    def test_multiple_radios_require_explicit_selection(self):
        result = self.scan_with([self.reply(), self.reply()])
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(len(result["devices"]), 2)

    def test_missing_protocol_identity_is_not_a_radio(self):
        self.assertEqual(self.scan_with([self.reply({"firmware": ""})])["status"], "not_found")

    def test_probe_reads_identity_without_bootstrap_configuration(self):
        interface = Mock()
        interface.metadata = SimpleNamespace(firmware_version="2.7.test")
        interface.myInfo = SimpleNamespace(my_node_num=123)
        with patch("meshtastic.serial_interface.SerialInterface", return_value=interface):
            self.assertEqual(discover.probe("/dev/fake", 12), {"firmware": "2.7.test"})
        interface.connect.assert_called_once()
        interface.waitForConfig.assert_called_once()
        interface.close.assert_called_once()
        interface.localNode.writeConfig.assert_not_called()
        interface.localNode.setOwner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
