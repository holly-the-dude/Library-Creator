"""Safety behavior with synthetic firmware; never opens a real serial device."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flasher


class FlashTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = {
            "mcu": "esp32s3", "version": "2.7.test", "platformioTarget": "test-board",
            "part": [
                {"name": "app0", "subtype": "ota_0", "offset": "0x10000", "size": "0x330000"},
                {"name": "app1", "subtype": "ota_1", "offset": "0x340000", "size": "0x330000"},
                {"name": "spiffs", "subtype": "spiffs", "offset": "0x670000", "size": "0x180000"},
            ], "files": [],
        }
        for name, part in [("firmware.factory.bin", None), ("firmware.bin", "app0"),
                           ("ota.bin", "app1"), ("littlefs.bin", "spiffs")]:
            content = name.encode() * 3
            (self.root / name).write_bytes(content)
            entry = {"name": name, "bytes": len(content), "md5": hashlib.md5(content).hexdigest()}
            if part:
                entry["part_name"] = part
            self.data["files"].append(entry)
        self.path = self.root / "firmware.mt.json"
        self.manifest = flasher.Manifest(self.path, self.data)

    def test_clean_install_uses_factory_and_metadata_offsets(self):
        self.assertEqual([(offset, p.name) for offset, p in self.manifest.plan("install")], [
            (0, "firmware.factory.bin"), (0x340000, "ota.bin"), (0x670000, "littlefs.bin")])

    def test_update_writes_only_application(self):
        self.assertEqual(self.manifest.plan("update"), [(0x10000, self.root / "firmware.bin")])

    def test_legacy_partition_names_resolve_by_subtype(self):
        self.data["part"][0]["name"] = "app"
        self.data["part"][1]["name"] = "flashApp"
        self.assertEqual([offset for offset, _ in self.manifest.plan("install")],
                         [0, 0x340000, 0x670000])
        self.assertEqual(self.manifest.plan("update")[0][0], 0x10000)

    def test_corruption_blocks_all_serial_activity(self):
        (self.root / "littlefs.bin").write_bytes(b"corrupt")
        with patch.object(flasher, "esptool") as esp:
            with self.assertRaisesRegex(ValueError, "checksum"):
                flasher.flash(self.manifest, "install", Path("/dev/fake"), "115200")
        esp.assert_not_called()

    def test_missing_image_rejected(self):
        self.data["files"] = [e for e in self.data["files"] if e["name"] != "ota.bin"]
        with self.assertRaisesRegex(ValueError, "Missing image"):
            self.manifest.plan("install")

    def test_oversized_app_rejected(self):
        self.data["part"][0]["size"] = "0x1"
        with self.assertRaisesRegex(ValueError, "Invalid image size"):
            self.manifest.plan("update")

    def test_path_traversal_rejected(self):
        self.data["files"][0]["name"] = "../escape.factory.bin"
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.manifest.plan("install")

    def test_wrong_chip_or_small_flash_rejected(self):
        writes = self.manifest.plan("install")
        for chip, capacity in [("esp32", 8 * 1048576), ("esp32s3", 4 * 1048576)]:
            with self.assertRaises(ValueError):
                flasher.check_device(self.manifest, chip, capacity, writes)

    def test_probe_supports_esptool_4_and_5_formats(self):
        for line in ["Chip is ESP32-S3 (revision v0.2)", "Chip type:          ESP32-S3 (QFN56)"]:
            self.assertEqual(flasher.parse_probe(line + "\nDetected flash size: 8MB"),
                             ("esp32s3", 8 * 1048576))
        with self.assertRaises(ValueError):
            flasher.parse_probe("Connection failed")

    def run_flash(self, mode, confirmation="", fail_erase=False):
        def fake_esptool(port, baud, *args, **kwargs):
            if fail_erase and args[0] == "erase-flash":
                raise subprocess.CalledProcessError(2, ["esptool"])
            return subprocess.CompletedProcess([], 0, "Chip type: ESP32-S3\nDetected flash size: 8MB")
        with patch.object(flasher, "esptool", side_effect=fake_esptool) as esp, \
                patch.object(flasher, "dialog", return_value=confirmation), \
                patch.object(flasher, "pause"), patch.object(flasher.subprocess, "run"):
            try:
                flasher.flash(self.manifest, mode, Path("/dev/fake"), "115200")
            except subprocess.CalledProcessError:
                if not fail_erase:
                    raise
        return [call.args[2:] for call in esp.call_args_list]

    def test_cancel_does_not_erase_or_write(self):
        self.assertEqual(self.run_flash("install", confirmation=None), [("flash-id",)])

    def test_update_never_erases(self):
        calls = self.run_flash("update")
        self.assertEqual([c[0] for c in calls], ["flash-id", "write-flash"])
        self.assertEqual(calls[1][1:], ("0x10000", str(self.root / "firmware.bin")))

    def test_clean_install_erases_then_writes(self):
        self.assertEqual([c[0] for c in self.run_flash("install")],
                         ["flash-id", "erase-flash", "write-flash"])

    def test_failed_erase_never_starts_write(self):
        self.assertEqual([c[0] for c in self.run_flash("install", fail_erase=True)],
                         ["flash-id", "erase-flash"])

    def test_unsupported_mcu_rejected(self):
        self.data["mcu"] = "nrf52840"
        self.path.write_text(json.dumps(self.data))
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            flasher.load_manifest(self.path)


if __name__ == "__main__":
    unittest.main()
