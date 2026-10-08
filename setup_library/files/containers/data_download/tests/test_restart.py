"""Exercise the real Unix bridge with systemctl mocked; never reboot a host."""
import importlib.util
from pathlib import Path
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app

spec = importlib.util.spec_from_file_location("library_control", ROOT / "../../library_control.py")
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.socket = str(Path(self.temp.name) / "control.sock")
        self.server = socketserver.UnixStreamServer(self.socket, control.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(patch.stopall)
        patch.object(app, "CONTROL_SOCKET", self.socket).start()
        self.run = patch.object(control.subprocess, "run").start()
        self.application = app.Application(app.Storage(self.temp.name, require_mount=False, reserve=0))

    def test_idle_request_schedules_once_and_blocks_new_downloads(self):
        self.application.restart()
        self.application.restart()
        self.run.assert_called_once_with(
            ["/usr/bin/systemctl", "--no-block", "start", "library-restart.service"],
            check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.assertEqual(self.application.snapshot()["restart"], {"available": True, "requested": True})
        self.application.internet["status"] = "online"
        with self.assertRaisesRegex(ValueError, "restarting"):
            self.application.enqueue(["anything"])

    def test_all_active_job_states_block_restart(self):
        for state in app.ACTIVE:
            self.application.jobs = {"one": {"status": state}}
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, "Wait for"):
                self.application.restart()
        self.run.assert_not_called()

    def test_failed_and_completed_jobs_allow_restart(self):
        self.application.jobs = {state: {"status": state} for state in ("failed", "cancelled", "complete")}
        self.application.restart()
        self.run.assert_called_once()

    def test_missing_bridge_keeps_downloads_enabled(self):
        with patch.object(app, "CONTROL_SOCKET", self.socket + "-missing"):
            with self.assertRaisesRegex(ValueError, "not installed"):
                self.application.restart()
            self.assertFalse(self.application.snapshot()["restart"]["available"])
        self.assertFalse(self.application.restart_requested)
        self.run.assert_not_called()

    def test_host_failure_is_reported_and_retry_allowed(self):
        self.run.side_effect = subprocess.CalledProcessError(1, "systemctl")
        with self.assertRaisesRegex(ValueError, "did not confirm"):
            self.application.restart()
        self.assertFalse(self.application.restart_requested)
        self.run.side_effect = None
        self.application.restart()
        self.assertTrue(self.application.restart_requested)

    def test_bridge_rejects_arbitrary_commands(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(self.socket)
            client.sendall(b"restart; shutdown -r now\n")
            self.assertEqual(client.recv(128), b"ERROR Invalid request\n")
        self.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
