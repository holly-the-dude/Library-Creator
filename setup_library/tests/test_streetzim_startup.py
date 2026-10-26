"""Exercise GPS ownership transitions with Ansible and a fake Podman executable."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

PLAYBOOK = Path(__file__).resolve().parents[1] / "files/start_library.yml"


def find_task(tasks, name):
    for task in tasks:
        for key in ("block", "rescue"):
            found = find_task(task.get(key, []), name)
            if found:
                return found
        if task.get("name") == name:
            return task


@unittest.skipUnless(shutil.which("ansible-playbook"), "Ansible is required")
class StreetZimStartupTests(unittest.TestCase):
    def exercise(self, enabled=True, failure=""):
        original = yaml.safe_load(PLAYBOOK.read_text())[0]
        names = ["check optional StreetZim image", "initialize StreetZim GPS ownership",
                 "release GPS from a disabled StreetZim service",
                 "start StreetZim and its shared GPS feed", "start maps"]
        tasks = [copy.deepcopy(find_task(original["tasks"], name)) for name in names]
        # The temporary service has no real HTTP endpoint. Successful fake run
        # is sufficient here; actual health and proxy behavior have a runtime check.
        health = find_task(tasks, "wait for StreetZim reader (GPS fix is not required)")
        health.clear()
        health.update({"name": "test health result", "ansible.builtin.assert":
                       {"that": ["test_failure != 'health'"]}})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            play = [{"hosts": "localhost", "gather_facts": False,
                     "vars": {"street_zim_enabled": enabled, "gps_port": "/dev/serial/by-id/test GPS",
                              "gps_baud": 4800, "test_failure": failure}, "tasks": tasks}]
            (root / "play.yml").write_text(yaml.safe_dump(play))
            (root / "podman").write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['GPS_TEST_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
sys.exit(1 if os.environ['GPS_TEST_FAILURE'] == 'image' and args[:2] == ['image', 'exists'] else 0)
''')
            (root / "podman").chmod(0o755)
            log = root / "calls"
            env = {**os.environ, "PATH": directory + os.pathsep + os.environ["PATH"],
                   "ANSIBLE_LOCAL_TEMP": str(root / "ansible"), "ANSIBLE_NOCOLOR": "1",
                   "GPS_TEST_LOG": str(log), "GPS_TEST_FAILURE": failure}
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local',
                                     str(root / 'play.yml')], env=env, text=True,
                                    capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return [json.loads(line) for line in log.read_text().splitlines()]

    def test_streetzim_owns_usb_and_maps_only_relays(self):
        calls = self.exercise()
        street = next(c for c in calls if '--name=street_zim' in c)
        maps = next(c for c in calls if '--name=library_maps' in c)
        self.assertLess(calls.index(['stop', '--ignore', 'library_maps']), calls.index(street))
        self.assertIn('/dev:/dev', street)
        self.assertIn('GPS_MODE=serial', street)
        self.assertIn('GPS_PORT=/dev/serial/by-id/test GPS', street)
        self.assertIn('GPS_BAUD=4800', street)
        self.assertIn('GPS_UPSTREAM=http://10.88.0.216:8093', maps)
        self.assertNotIn('/dev:/dev', maps)
        self.assertNotIn('--privileged', maps)

    def assert_fallback(self, calls):
        maps = next(c for c in calls if '--name=library_maps' in c)
        self.assertLess(calls.index(['stop', '--ignore', 'street_zim']), calls.index(maps))
        self.assertIn('/dev:/dev', maps)
        self.assertIn('GPS_PORT=/dev/serial/by-id/test GPS', maps)
        self.assertFalse(any('GPS_UPSTREAM=' in arg for arg in maps))

    def test_missing_image_preserves_maps_gps(self):
        calls = self.exercise(failure='image')
        self.assertFalse(any('--name=street_zim' in c for c in calls))
        self.assert_fallback(calls)

    def test_disabled_streetzim_releases_receiver(self):
        self.assert_fallback(self.exercise(enabled=False))

    def test_failed_health_stops_streetzim_before_fallback(self):
        self.assert_fallback(self.exercise(failure='health'))


if __name__ == '__main__':
    unittest.main()
