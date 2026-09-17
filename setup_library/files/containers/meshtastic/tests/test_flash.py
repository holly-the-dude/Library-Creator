"""Behavior checks for automatic firmware detection and flashing.

These tests never touch real hardware or esptool: the subprocess boundary and
the esptool probe are patched. They verify the safety guards (only a matching
unflashed chip is flashed), the exact esptool command sequence and offsets, and
that a working radio re-arms the one-shot guard in the bridge.
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flash


VERSION = "2.7.26.54e0d8d"
PROG = f"firmware-heltec-wsl-v3-{VERSION}"

METADATA = {
    "version": VERSION,
    "mcu": "esp32s3",
    "hwModelSlug": "HELTEC_WSL_V3",
    "partitionScheme": "8MB",
    "part": [
        {"subtype": "ota_1", "offset": "0x340000"},
        {"subtype": "spiffs", "offset": "0x670000"},
    ],
}

PROBE_OUTPUT = """esptool.py v5.4.0
Serial port /dev/meshtastic
Connecting....
Detecting chip type... ESP32-S3
Chip is ESP32-S3 (QFN56) (revision v0.2)
Features: WiFi, BLE
Crystal is 40MHz
Manufacturer: 20
Device: 4016
Detected flash size: 8MB
Hard resetting via RTS pin...
"""


def make_firmware(directory, mcu="esp32s3", with_ota=True, with_littlefs=True):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{PROG}.mt.json").write_text(json.dumps({**METADATA, "mcu": mcu}))
    (directory / f"{PROG}.factory.bin").write_bytes(b"factory")
    if with_ota:
        (directory / f"mt-{mcu}-ota.bin").write_bytes(b"ota")
    if with_littlefs:
        (directory / f"littlefs-heltec-wsl-v3-{VERSION}.bin").write_bytes(b"lfs")
    return directory


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_none_when_no_firmware_bundled(self):
        self.assertIsNone(flash.read_manifest(self.dir))

    def test_resolves_files_and_metadata_offsets(self):
        make_firmware(self.dir)
        manifest = flash.read_manifest(self.dir)
        self.assertEqual(manifest["mcu"], "esp32s3")
        self.assertEqual(manifest["slug"], "HELTEC_WSL_V3")
        self.assertEqual(manifest["version"], VERSION)
        self.assertEqual(manifest["flash_size"], "8MB")
        offsets = [offset for offset, _ in manifest["writes"]]
        self.assertEqual(offsets, ["0x0", "0x340000", "0x670000"])
        names = [path.name for _, path in manifest["writes"]]
        self.assertEqual(names, [
            f"{PROG}.factory.bin", "mt-esp32s3-ota.bin",
            f"littlefs-heltec-wsl-v3-{VERSION}.bin",
        ])

    def test_missing_factory_bin_raises(self):
        make_firmware(self.dir)
        (self.dir / f"{PROG}.factory.bin").unlink()
        with self.assertRaisesRegex(flash.FlashError, "missing"):
            flash.read_manifest(self.dir)

    def test_optional_images_absent_are_skipped(self):
        make_firmware(self.dir, with_ota=False, with_littlefs=False)
        manifest = flash.read_manifest(self.dir)
        self.assertEqual([offset for offset, _ in manifest["writes"]], ["0x0"])


class DetectTests(unittest.TestCase):
    def _probe(self, returncode=0, stdout=PROBE_OUTPUT):
        completed = subprocess.CompletedProcess([], returncode, stdout=stdout)
        with patch.object(flash.subprocess, "run", return_value=completed) as run:
            return flash.detect_chip("/dev/meshtastic"), run

    def test_parses_chip_and_flash_size_from_flash_id(self):
        (chip, size), run = self._probe()
        self.assertEqual(chip, "ESP32-S3")
        self.assertEqual(size, "8MB")
        command = run.call_args.args[0]
        self.assertIn("flash-id", command)
        self.assertIn("/dev/meshtastic", command)

    def test_nonzero_return_is_none(self):
        (chip, size), _ = self._probe(returncode=2, stdout="A fatal error occurred")
        self.assertIsNone(chip)
        self.assertIsNone(size)

    def test_timeout_is_none(self):
        with patch.object(flash.subprocess, "run",
                          side_effect=subprocess.TimeoutExpired("esptool", 60)):
            self.assertEqual(flash.detect_chip("/dev/meshtastic"), (None, None))

    def test_chip_matches_family(self):
        self.assertTrue(flash.chip_matches("ESP32-S3", "esp32s3"))
        self.assertTrue(flash.chip_matches("ESP32-S3 (QFN56)", "esp32s3"))
        self.assertFalse(flash.chip_matches("ESP32-C3", "esp32s3"))
        self.assertFalse(flash.chip_matches("ESP32", "esp32s3"))
        self.assertFalse(flash.chip_matches(None, "esp32s3"))

    def test_normalize_size(self):
        self.assertEqual(flash._normalize_size("8MB"), "8mb")
        self.assertEqual(flash._normalize_size("8 MB"), "8mb")
        self.assertEqual(flash._normalize_size("16MB"), "16mb")
        self.assertIsNone(flash._normalize_size(None))


class _FakeSerial:
    """Minimal serial.Serial stand-in that returns a fixed byte payload once."""

    def __init__(self, payload):
        self._payload = payload
        self.port = None
        self.baudrate = None
        self.timeout = None
        self.dtr = None
        self.rts = None

    def open(self):
        pass

    def read(self, _n):
        data, self._payload = self._payload, b""
        return data

    def close(self):
        pass


class BlankAppTests(unittest.TestCase):
    def _run_probe(self, payload, reset_ok=True):
        import sys as _sys
        import types
        fake_serial = types.SimpleNamespace(Serial=lambda: _FakeSerial(payload))
        reset = (subprocess.CompletedProcess([], 0, stdout="Hard resetting")
                 if reset_ok else None)
        with patch.dict(_sys.modules, {"serial": fake_serial}), \
                patch.object(flash.subprocess, "run", return_value=reset), \
                patch.object(flash, "BLANK_PROBE_SECONDS", 0.2):
            return flash.app_is_blank("/dev/meshtastic")

    def test_blank_marker_is_detected(self):
        payload = b"ESP-ROM\r\ninvalid header: 0xffffffff\r\ninvalid header: 0xffffffff\r\n"
        self.assertTrue(self._run_probe(payload))

    def test_running_radio_with_frames_is_not_blank(self):
        # Even if noise resembles the marker, a real Meshtastic frame wins.
        payload = b"\x94\xc3\x00\x02\x08\x01invalid header: 0xffffffff"
        self.assertFalse(self._run_probe(payload))

    def test_silent_or_unreachable_board_is_not_blank(self):
        self.assertFalse(self._run_probe(b""))

    def test_reset_failure_returns_not_blank(self):
        with patch.object(flash.subprocess, "run",
                          side_effect=OSError("no device")):
            self.assertFalse(flash.app_is_blank("/dev/meshtastic"))


class AutoFlashTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.fw = make_firmware(self.dir / "fw")
        self.data = self.dir / "data"

    def test_flashes_matching_unflashed_board_and_records(self):
        calls = []

        def fake_run(command, timeout, **_):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="")

        with patch.object(flash, "detect_chip", return_value=("ESP32-S3", "8MB")), \
                patch.object(flash.subprocess, "run", side_effect=fake_run):
            flashed = flash.auto_flash("/dev/meshtastic", self.fw, self.data)
        self.assertTrue(flashed)
        # erase-flash first, then three write-flash calls at the right offsets.
        self.assertIn("erase-flash", calls[0])
        writes = [c for c in calls if "write-flash" in c]
        self.assertEqual(len(writes), 3)
        offsets = [c[c.index("write-flash") + 1] for c in writes]
        self.assertEqual(offsets, ["0x0", "0x340000", "0x670000"])
        record = json.loads((self.data / "flash.json").read_text())
        self.assertEqual(record["version"], VERSION)
        self.assertEqual(record["board"], "HELTEC_WSL_V3")
        self.assertEqual(record["chip"], "ESP32-S3")
        self.assertEqual(record["flash_size"], "8MB")

    def test_disabled_does_not_probe_or_flash(self):
        with patch.object(flash, "detect_chip") as probe, \
                patch.object(flash.subprocess, "run") as run:
            self.assertFalse(
                flash.auto_flash("/dev/meshtastic", self.fw, self.data, enabled=False))
        probe.assert_not_called()
        run.assert_not_called()

    def test_no_firmware_declines(self):
        empty = self.dir / "empty"
        empty.mkdir()
        with patch.object(flash, "detect_chip") as probe:
            self.assertFalse(flash.auto_flash("/dev/meshtastic", empty, self.data))
        probe.assert_not_called()

    def test_no_chip_declines_without_flashing(self):
        with patch.object(flash, "detect_chip", return_value=(None, None)), \
                patch.object(flash.subprocess, "run") as run:
            self.assertFalse(flash.auto_flash("/dev/meshtastic", self.fw, self.data))
        run.assert_not_called()

    def test_wrong_chip_refuses_to_flash(self):
        with patch.object(flash, "detect_chip", return_value=("ESP32-C3", "4MB")), \
                patch.object(flash.subprocess, "run") as run:
            self.assertFalse(flash.auto_flash("/dev/meshtastic", self.fw, self.data))
        run.assert_not_called()
        self.assertFalse((self.data / "flash.json").exists())

    def test_matching_chip_but_wrong_flash_size_refuses_to_flash(self):
        # A 16MB ESP32-S3 LilyGo must not receive the 8MB Heltec firmware.
        with patch.object(flash, "detect_chip", return_value=("ESP32-S3", "16MB")), \
                patch.object(flash.subprocess, "run") as run:
            self.assertFalse(flash.auto_flash("/dev/meshtastic", self.fw, self.data))
        run.assert_not_called()
        self.assertFalse((self.data / "flash.json").exists())

    def test_esptool_failure_raises_flasherror(self):
        error = subprocess.CalledProcessError(1, ["esptool"], output="boom")
        with patch.object(flash, "detect_chip", return_value=("ESP32-S3", "8MB")), \
                patch.object(flash.subprocess, "run", side_effect=error):
            with self.assertRaisesRegex(flash.FlashError, "esptool failed"):
                flash.auto_flash("/dev/meshtastic", self.fw, self.data)
        self.assertFalse((self.data / "flash.json").exists())


if __name__ == "__main__":
    unittest.main()
