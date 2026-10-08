"""Check power-page routing with all host commands mocked; never reboot."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "library_shutdown", Path(__file__).resolve().parents[1] / "files/library_shutdown.py")
power = importlib.util.module_from_spec(spec)
spec.loader.exec_module(power)


class PowerPageTests(unittest.TestCase):
    def setUp(self):
        self.client = power.app.test_client()
        self.command = patch.object(power.subprocess, "run").start()
        self.addCleanup(patch.stopall)

    def test_page_renders_distinct_forms_without_power_action(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'action="/shutdown"', response.data)
        self.assertIn(b'action="/reboot"', response.data)
        self.command.assert_not_called()

    def test_power_actions_reject_get(self):
        for route in ("/shutdown", "/reboot"):
            self.assertEqual(self.client.get(route).status_code, 405)
        self.command.assert_not_called()

    def test_shutdown_only_calls_poweroff_helper(self):
        self.assertEqual(self.client.post("/shutdown").status_code, 200)
        self.command.assert_called_once_with(['/usr/local/bin/library_shutdown'], check=True)

    def test_restart_only_schedules_graceful_service(self):
        self.assertEqual(self.client.post("/reboot").status_code, 202)
        self.command.assert_called_once_with(
            ['/usr/bin/systemctl', '--no-block', 'start', 'library-restart.service'],
            check=True, timeout=10)

    def test_command_failures_return_error_instead_of_success(self):
        for route in ("/shutdown", "/reboot"):
            for error in (FileNotFoundError("missing helper"),
                          subprocess.CalledProcessError(1, "helper")):
                with self.subTest(route=route, error=error), patch.object(power.app.logger, "exception"):
                    self.command.side_effect = error
                    self.assertEqual(self.client.post(route).status_code, 503)


if __name__ == '__main__':
    unittest.main()
