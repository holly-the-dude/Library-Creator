"""Behavior checks for naming, verified writes, and private persistent backups."""

import json
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import yaml
from meshtastic.protobuf import config_pb2, localonly_pb2, mesh_pb2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bootstrap


def node(name, short="", **extra):
    return {"user": {"longName": name, "shortName": short, **extra}}


class FakeRadio:
    def __init__(self, name="Heltec", short="HT", number=42, neighbors=None):
        self.nodesByNum = {number: node(name, short, id=f"!{number:08x}")}
        self.nodesByNum.update(neighbors or {})
        config = localonly_pb2.LocalConfig()
        config.lora.region = config_pb2.Config.LoRaConfig.US
        config.security.private_key = b"private-test-value"
        # Default to an already-provisioned radio so tests that only exercise
        # naming/backup do not trip the region/serial provisioning writes.
        config.device.serial_enabled = True
        self.localNode = SimpleNamespace(
            nodeNum=number,
            localConfig=config,
            moduleConfig=localonly_pb2.LocalModuleConfig(),
            channels=[],
            cannedPluginMessage=None,
            ringtone=None,
            getURL=lambda: "https://meshtastic.org/e/#channel-test-secret",
            setOwner=Mock(),
            writeConfig=Mock(),
        )
        self.metadata = mesh_pb2.DeviceMetadata(firmware_version="test-version")
        self.connect = Mock()
        self.waitForConfig = Mock()
        self.close = Mock()
        self.stream = None
        self.heartbeatTimer = None

    def getMyNodeInfo(self):
        return self.nodesByNum[self.localNode.nodeNum]

    def getLongName(self):
        return self.getMyNodeInfo()["user"]["longName"]

    def getShortName(self):
        return self.getMyNodeInfo()["user"]["shortName"]

    def getCannedMessage(self):
        raise AssertionError("Bootstrap must not make optional blocking queries")

    def getRingtone(self):
        raise AssertionError("Bootstrap must not make optional blocking queries")


class NamingTests(unittest.TestCase):
    def test_skips_case_insensitive_neighbors_but_excludes_own_number(self):
        nodes = {42: node("library0003"), 1: node("LIBRARY0001"),
                 2: node("library0002"), 3: node("unrelated")}
        self.assertEqual(bootstrap.choose_name(nodes, 42, "Heltec", {}),
                         "library0003")

    def test_saved_name_has_priority_and_collision_selects_lowest_free(self):
        state = {"node_num": 42, "long_name": "library0050"}
        self.assertEqual(bootstrap.choose_name({}, 42, "library0009", state),
                         "library0050")
        self.assertEqual(bootstrap.choose_name({1: node("library0050")}, 42,
                                              "library0009", state),
                         "library0001")

    def test_other_radio_state_does_not_transfer_and_current_name_survives(self):
        state = {"node_num": 41, "long_name": "library0050"}
        self.assertEqual(bootstrap.choose_name({}, 42, "Heltec", state),
                         "library0001")
        self.assertEqual(bootstrap.choose_name({}, 42, "library0042", state),
                         "library0042")

    def test_invalid_names_and_exhaustion(self):
        for value in (None, 123, "library0000", "library1", "library10000",
                      "library0001extra"):
            self.assertIsNone(bootstrap.valid_name(value))
        occupied = {i: node(f"library{i:04d}") for i in range(1, 10000)}
        with self.assertRaisesRegex(RuntimeError, "All library"):
            bootstrap.choose_name(occupied, 10000, "Heltec", {})


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_dir = Path(self.temporary.name)

    def run_bootstrap(self, radios, seconds=0):
        with patch.object(bootstrap, "SerialInterface", side_effect=radios), \
                patch.object(bootstrap.time, "sleep"):
            return bootstrap.bootstrap_radio("/dev/meshtastic", self.data_dir, seconds)

    def test_writes_then_rereads_preserves_flags_and_saves_private_backup(self):
        first = FakeRadio(neighbors={1: node("LIBRARY0001")})
        first.getMyNodeInfo()["user"].update(isLicensed=True, isUnmessagable=True)
        # This secret is present in the raw API node DB but must not be copied.
        first.nodesByNum[1]["adminSessionPassKey"] = b"node-admin-secret"
        second = FakeRadio("library0002", "0002")
        status = self.run_bootstrap([first, second], seconds=30)
        first.localNode.setOwner.assert_called_once_with(
            long_name="library0002", short_name="0002",
            is_licensed=True, is_unmessagable=True,
        )
        self.assertTrue(status["name_changed"])
        self.assertEqual(status["region"], "US")
        self.assertEqual(status["discovered_nodes"], 1)
        for radio in (first, second):
            radio.close.assert_called_once()
        config = yaml.safe_load((self.data_dir / "config.yaml").read_text())
        self.assertEqual(config["owner"], "library0002")
        self.assertEqual(config["owner_short"], "0002")
        self.assertTrue(config["config"]["security"]["privateKey"].startswith("base64:"))
        state = json.loads((self.data_dir / "state.json").read_text())
        self.assertEqual(state["node_num"], 42)
        self.assertEqual(state["long_name"], "library0002")
        for name in ("config.yaml", "state.json", "nodes.json"):
            self.assertEqual(stat.S_IMODE((self.data_dir / name).stat().st_mode), 0o600)
        self.assertNotIn("secret", json.dumps(status))
        self.assertNotIn("adminSessionPassKey", (self.data_dir / "nodes.json").read_text())

    def test_correct_name_has_no_write_or_reconnect(self):
        radio = FakeRadio("library0042", "0042")
        status = self.run_bootstrap([radio])
        radio.localNode.setOwner.assert_not_called()
        self.assertFalse(status["name_changed"])
        self.assertEqual(status["long_name"], "library0042")
        radio.close.assert_called_once()

    def test_restart_reuses_saved_name_then_resolves_new_collision(self):
        first = FakeRadio(neighbors={1: node("library0001")})
        confirmed = FakeRadio("library0002", "0002")
        self.run_bootstrap([first, confirmed])
        # Even if library0001 is no longer seen, keep this radio's saved name.
        restart = FakeRadio("library0002", "0002")
        self.assertEqual(self.run_bootstrap([restart])["long_name"], "library0002")
        restart.localNode.setOwner.assert_not_called()
        collision = FakeRadio("library0002", "0002", neighbors={3: node("LIBRARY0002")})
        confirmed = FakeRadio("library0001", "0001")
        self.assertEqual(self.run_bootstrap([collision, confirmed])["long_name"],
                         "library0001")
        self.assertEqual(json.loads((self.data_dir / "state.json").read_text())["long_name"],
                         "library0001")

    def test_replacement_radio_cannot_reuse_other_radios_saved_identity(self):
        self.run_bootstrap([FakeRadio("library0099", "0099")])
        new_radio = FakeRadio(number=43)
        confirmed = FakeRadio("library0001", "0001", number=43)
        status = self.run_bootstrap([new_radio, confirmed])
        self.assertEqual(status["node_num"], 43)
        self.assertEqual(status["long_name"], "library0001")

    def test_unset_region_is_provisioned_to_us_and_serial_enabled(self):
        # A freshly-flashed radio comes up UNSET; provisioning sets US + serial.
        first = FakeRadio("library0001", "0001")
        first.localNode.localConfig.lora.region = config_pb2.Config.LoRaConfig.UNSET
        first.localNode.localConfig.device.serial_enabled = False
        # After the writes + reconnect, the radio reports the applied region.
        second = FakeRadio("library0001", "0001")
        status = self.run_bootstrap([first, second])
        # Region was written on the first connection, serial too.
        self.assertEqual(first.localNode.localConfig.lora.region,
                         config_pb2.Config.LoRaConfig.US)
        self.assertTrue(first.localNode.localConfig.device.serial_enabled)
        written = [c.args[0] for c in first.localNode.writeConfig.call_args_list]
        self.assertIn("lora", written)
        self.assertIn("device", written)
        # Name was already correct, so the owner is never rewritten.
        first.localNode.setOwner.assert_not_called()
        self.assertEqual(status["region"], "US")

    def test_existing_region_is_never_overridden(self):
        # A radio already set to EU_868 must keep it; only serial may change.
        radio = FakeRadio("library0001", "0001")
        radio.localNode.localConfig.lora.region = config_pb2.Config.LoRaConfig.EU_868
        radio.localNode.localConfig.device.serial_enabled = True
        status = self.run_bootstrap([radio])
        self.assertEqual(radio.localNode.localConfig.lora.region,
                         config_pb2.Config.LoRaConfig.EU_868)
        # Nothing needed writing: no region write, no serial write, no reconnect.
        radio.localNode.writeConfig.assert_not_called()
        radio.localNode.setOwner.assert_not_called()
        self.assertEqual(status["region"], "EU_868")

    def test_serial_enabled_when_off_even_if_region_already_set(self):
        first = FakeRadio("library0001", "0001")  # region US already
        first.localNode.localConfig.device.serial_enabled = False
        second = FakeRadio("library0001", "0001")
        self.run_bootstrap([first, second])
        self.assertTrue(first.localNode.localConfig.device.serial_enabled)
        written = [c.args[0] for c in first.localNode.writeConfig.call_args_list]
        self.assertEqual(written, ["device"])  # only serial, not region

    def test_provisioning_respects_env_overrides(self):
        first = FakeRadio("library0001", "0001")
        first.localNode.localConfig.lora.region = config_pb2.Config.LoRaConfig.UNSET
        first.localNode.localConfig.device.serial_enabled = False
        with patch.dict(bootstrap.os.environ,
                        {"LORA_REGION": "", "ENSURE_SERIAL_ENABLED": "0"}):
            self.run_bootstrap([first])
        # With region disabled (empty) and serial disabled, nothing is written.
        first.localNode.writeConfig.assert_not_called()
        self.assertEqual(first.localNode.localConfig.lora.region,
                         config_pb2.Config.LoRaConfig.UNSET)
        self.assertFalse(first.localNode.localConfig.device.serial_enabled)

    def test_rejected_write_does_not_persist_unverified_state(self):
        first, second = FakeRadio(), FakeRadio()
        with self.assertRaisesRegex(RuntimeError, "did not confirm"):
            self.run_bootstrap([first, second])
        self.assertFalse((self.data_dir / "state.json").exists())
        for radio in (first, second):
            radio.close.assert_called_once()

    def test_handshake_failure_closes_connection(self):
        radio = FakeRadio()
        radio.waitForConfig.side_effect = RuntimeError("handshake failed")
        with self.assertRaisesRegex(RuntimeError, "handshake failed"):
            self.run_bootstrap([radio])
        radio.close.assert_called_once()

    def test_export_failure_closes_connection_and_preserves_previous_backup(self):
        radio = FakeRadio("library0001", "0001")
        backup = self.data_dir / "config.yaml"
        backup.write_text("previous valid backup")
        with patch.object(bootstrap, "export_config", side_effect=RuntimeError("export failed")):
            with self.assertRaisesRegex(RuntimeError, "export failed"):
                self.run_bootstrap([radio])
        self.assertEqual(backup.read_text(), "previous valid backup")
        radio.close.assert_called_once()

    def test_failed_atomic_replace_leaves_old_file_and_removes_temporary(self):
        target = self.data_dir / "state.json"
        target.write_text("old state")
        with patch.object(bootstrap.os, "replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                bootstrap.atomic_write(target, "new state")
        self.assertEqual(target.read_text(), "old state")
        self.assertEqual(list(self.data_dir.iterdir()), [target])


if __name__ == "__main__":
    unittest.main()
