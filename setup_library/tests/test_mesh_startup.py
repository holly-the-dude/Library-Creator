"""Run the real radio playbook block against fake Podman and an HTTP fixture.

No containers, USB devices, or /Library data are changed. Requires Ansible and
PyYAML. Run: python3 -m unittest discover -s setup_library/tests -v
"""

import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

import yaml

PLAYBOOK = Path(__file__).resolve().parents[1] / "files/start_library.yml"


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ready": true}')

    def log_message(self, *_):
        pass


@unittest.skipUnless(shutil.which("ansible-playbook"), "Ansible is required")
class StartupTests(unittest.TestCase):
    def exercise(self, detection, missing_image=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            config = yaml.safe_load(PLAYBOOK.read_text())[0]
            block = copy.deepcopy(next(t for t in config["tasks"] if t.get("tags") == ["mesh"]))
            block["become"] = False

            def fixtures(tasks):
                for task in tasks:
                    if "ansible.builtin.uri" in task:
                        task["ansible.builtin.uri"]["url"] = f"http://127.0.0.1:{server.server_port}/"
                    if "ansible.builtin.file" in task:
                        task["ansible.builtin.file"]["path"] = str(root / "data")
                    fixtures(task.get("block", []))
            fixtures([block])
            playbook = [{"name": "Test mesh selection", "hosts": "localhost", "gather_facts": False,
                         "vars": {"meshtastic_device": "", "gps_port": "", "meshtastic_probe_timeout": 1},
                         "tasks": [block]}]
            (root / "play.yml").write_text(yaml.safe_dump(playbook, sort_keys=False))
            (root / "podman").write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["MESH_TEST_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:2] == ["image", "exists"] and os.environ["MESH_TEST_MISSING"] == "1":
    sys.exit(1)
if "--entrypoint" in args:
    print(os.environ["MESH_TEST_DETECTION"])
''')
            (root / "displayit").write_text("#!/bin/sh\nexit 0\n")
            for name in ("podman", "displayit"):
                (root / name).chmod(0o755)
            environment = {**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"],
                           "ANSIBLE_LOCAL_TEMP": str(root / "ansible"),
                           "ANSIBLE_NOCOLOR": "1", "MESH_TEST_LOG": str(root / "calls.jsonl"),
                           "MESH_TEST_DETECTION": json.dumps(detection),
                           "MESH_TEST_MISSING": str(int(missing_image))}
            result = subprocess.run(["ansible-playbook", "-i", "localhost,", "-c", "local",
                                     str(root / "play.yml"), "--tags", "mesh"],
                                    env=environment, capture_output=True, text=True, timeout=90)
            calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
            return result, calls

    def test_radio_starts_only_meshtastic_with_detected_mapping(self):
        device = "/dev/serial/by-id/usb-1a86-radio"
        result, calls = self.exercise({"status": "found", "device": device})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        starts = [c for c in calls if c[:2] == ["run", "-d"]]
        self.assertEqual(len(starts), 1)
        self.assertIn("--name=meshtastic", starts[0])
        self.assertIn(device + ":/dev/meshtastic:rwm", starts[0])
        self.assertIn("8086:8086", starts[0])
        stop = ["stop", "--ignore", "meshtastic", "meshflash"]
        self.assertLess(calls.index(stop), calls.index(starts[0]))

    def test_no_radio_starts_only_setup_with_hotplug_on_8086(self):
        result, calls = self.exercise({"status": "not_found", "devices": []})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        starts = [c for c in calls if c[:2] == ["run", "-d"]]
        self.assertEqual(len(starts), 1)
        for expected in ("--name=meshflash", "8086:8086", "/dev:/host-dev:ro",
                         "--device-cgroup-rule=c 188:* rw", "--device-cgroup-rule=c 166:* rw"):
            self.assertIn(expected, starts[0])

    def test_multiple_radios_do_not_start_arbitrary_device_or_flasher(self):
        result, calls = self.exercise({"status": "ambiguous", "devices": [{"device": "/dev/ttyACM1"}]})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Multiple Meshtastic radios", result.stdout)
        self.assertFalse(any(c[:2] == ["run", "-d"] for c in calls))

    def test_missing_image_does_not_stop_existing_service(self):
        result, calls = self.exercise({"status": "not_found"}, missing_image=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(all(c[:2] == ["image", "exists"] for c in calls))


if __name__ == "__main__":
    unittest.main()
