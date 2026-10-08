"""Run the routing activation playbook block against fake Podman commands.

No real containers or /Library files are changed. Requires Ansible and PyYAML.
"""
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


@unittest.skipUnless(shutil.which("ansible-playbook"), "Ansible is required")
class RoutingStartupTests(unittest.TestCase):
    def exercise(self, pending=True, failure=""):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = yaml.safe_load(PLAYBOOK.read_text())[0]["tasks"]
            block = copy.deepcopy(next(t for t in tasks if t.get("tags") == ["routing_activation"]))
            block["become"] = False
            play = [{"hosts": "localhost", "gather_facts": False,
                     "vars": {"routing_pending": {"stat": {"exists": pending, "isreg": True}}},
                     "tasks": [block]}]
            (root / "play.yml").write_text(yaml.safe_dump(play))
            (root / "podman").write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["ROUTING_TEST_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
fail = os.environ["ROUTING_TEST_FAILURE"]
sys.exit(1 if (fail == "image" and args[:2] == ["image", "exists"]) or (fail == "activation" and args[0] == "run") else 0)
''')
            (root / "podman").chmod(0o755)
            log = root / "calls"
            environment = {**os.environ, "PATH": directory + os.pathsep + os.environ["PATH"],
                           "ANSIBLE_LOCAL_TEMP": str(root / "ansible"), "ANSIBLE_NOCOLOR": "1",
                           "ROUTING_TEST_LOG": str(log), "ROUTING_TEST_FAILURE": failure}
            result = subprocess.run(["ansible-playbook", "-i", "localhost,", "-c", "local", str(root / "play.yml")],
                                    env=environment, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else [], result.stdout

    def test_no_selection_does_not_touch_running_routing(self):
        calls, _ = self.exercise(pending=False)
        self.assertEqual(calls, [])

    def test_stops_routing_before_offline_activation(self):
        calls, _ = self.exercise()
        stop = calls.index(["stop", "--ignore", "graphhopper"])
        activation = next(i for i, call in enumerate(calls) if call[0] == "run")
        self.assertLess(stop, activation)
        self.assertIn("--network=none", calls[activation])
        self.assertEqual(calls[activation][-1], "/opt/data_download/routing.py")

    def test_missing_image_keeps_running_engine_untouched(self):
        calls, output = self.exercise(failure="image")
        self.assertFalse(any(call[0] in {"stop", "run"} for call in calls))
        self.assertIn("Routing selection could not be activated", output)

    def test_activation_failure_does_not_abort_appliance_startup(self):
        calls, output = self.exercise(failure="activation")
        self.assertTrue(any(call[0] == "run" for call in calls))
        self.assertIn("Routing selection could not be activated", output)


if __name__ == "__main__":
    unittest.main()
