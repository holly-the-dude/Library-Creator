"""Run targeted Clone setup with every host mutation mocked."""
from pathlib import Path
import contextlib
import io
import json
import re
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

BOOTSTRAP = Path(__file__).resolve().parents[2] / 'bootstrap'


class CloneSetupTests(unittest.TestCase):
    def run_setup(self, missing_file=None, **settings):
        function = re.search(r'^install_clone_service\(\) \{\n.*?^\}',
                             BOOTSTRAP.read_text(), re.M | re.S).group()
        function = function.replace('ansible=/root/.local/bin/ansible-playbook', 'ansible="$TEST_ANSIBLE"')
        stubs = r'''
trace() { printf 'CALL'; printf '\t%s' "$@"; printf '\n'; }
msg_error() { printf 'ERROR:%s\n' "$1"; }
msg_step() { :; }
msg_ok() { printf 'OK:%s\n' "$1"; }
resolve_repository() { printf '%s\n' "$TEST_REPOSITORY"; }
podman() {
    trace podman "$@"
    if [[ "$1" == image ]]; then return "$IMAGE_STATUS"; fi
    if [[ "$1" == exec ]]; then return "$SOCKET_STATUS"; fi
    return 99
}
mountpoint() { trace mountpoint "$@"; return "$MOUNT_STATUS"; }
CHECKS=0
check_clone_setup_idle() {
    CHECKS=$((CHECKS + 1)); trace idle "$CHECKS"
    if [[ "$CHECKS" == 1 ]]; then return "$FIRST_IDLE_STATUS"; fi
    return "$SECOND_IDLE_STATUS"
}
systemctl() { trace systemctl "$@"; return "$SYSTEMCTL_STATUS"; }
install() { trace install "$@"; return "$COPY_STATUS"; }
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / 'source with spaces'
            for relative in ('setup_library/01_install_ansible.yml', 'setup_library/files/start_library.yml',
                             'setup_library/files/library-clone.socket', 'setup_library/files/library-clone.service',
                             'setup_library/files/containers/data_download/clone_host.py'):
                if relative == missing_file:
                    continue
                file = repository / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.touch()
            ansible = root / 'ansible test'
            ansible.write_text('''#!/bin/bash
printf 'CALL\\tansible'; printf '\\t%s' "$@"; printf '\\n'
if [[ "$3" == clone_service ]]; then exit "$INSTALL_STATUS"; fi
exit "$RECREATE_STATUS"
''')
            ansible.chmod(0o755)
            environment = {'PATH': '/nonexistent', 'TEST_REPOSITORY': str(repository),
                           'TEST_ANSIBLE': str(ansible), 'IMAGE_STATUS': '0', 'SOCKET_STATUS': '0',
                           'MOUNT_STATUS': '0', 'FIRST_IDLE_STATUS': '0', 'SECOND_IDLE_STATUS': '0',
                           'SYSTEMCTL_STATUS': '0', 'COPY_STATUS': '0', 'INSTALL_STATUS': '0',
                           'RECREATE_STATUS': '0', **settings}
            result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c',
                                     stubs + function + '\ninstall_clone_service'],
                                    env=environment, cwd=root, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.stderr, '')
            calls = [line.split('\t')[1:] for line in result.stdout.splitlines() if line.startswith('CALL\t')]
            # Normalize only the test fixture path to keep assertions readable.
            calls = [[part.replace(str(repository), 'SOURCE') for part in call] for call in calls]
            return result.returncode, calls, result.stdout

    def test_targeted_install_recreates_only_downloader_and_checks_socket(self):
        status, calls, output = self.run_setup()
        self.assertEqual(status, 0)
        self.assertEqual(calls, [
            ['podman', 'image', 'exists', 'localhost/data_download:latest'],
            ['mountpoint', '-q', '/Library'], ['idle', '1'],
            ['ansible', 'SOURCE/setup_library/01_install_ansible.yml', '--tags', 'clone_service', '-i', 'localhost,', '-c', 'local'],
            ['idle', '2'], ['systemctl', 'try-restart', 'library-clone.service'],
            ['systemctl', 'is-active', '--quiet', 'library-clone.socket'],
            ['install', '-m', '0755', 'SOURCE/setup_library/files/start_library.yml', '/root/start_library.yml'],
            ['ansible', '/root/start_library.yml', '--tags', 'data_download', '-i', 'localhost,', '-c', 'local'],
            ['podman', 'exec', 'data_download', 'test', '-S', '/run/library-clone/clone.sock'],
        ])
        self.assertIn('OK:Clone is enabled', output)

    def test_preflight_failures_do_not_install(self):
        for setting in ('IMAGE_STATUS', 'MOUNT_STATUS', 'FIRST_IDLE_STATUS'):
            with self.subTest(setting=setting):
                status, calls, output = self.run_setup(**{setting: '1'})
                self.assertEqual(status, 1)
                self.assertFalse(any(c[0] in ('ansible', 'systemctl', 'install') for c in calls))
                self.assertNotIn('OK:', output)
        status, calls, output = self.run_setup(missing_file='setup_library/files/containers/data_download/clone_host.py')
        self.assertEqual(status, 1)
        self.assertEqual(calls, [])

    def test_install_failure_or_work_started_during_install_prevents_restart(self):
        for setting in ('INSTALL_STATUS', 'SECOND_IDLE_STATUS'):
            with self.subTest(setting=setting):
                status, calls, output = self.run_setup(**{setting: '1'})
                self.assertEqual(status, 1)
                self.assertFalse(any(c[0] in ('systemctl', 'install') for c in calls))
                self.assertNotIn('OK:', output)

    def test_restart_copy_recreation_or_mount_failures_do_not_report_success(self):
        for setting in ('SYSTEMCTL_STATUS', 'COPY_STATUS', 'RECREATE_STATUS', 'SOCKET_STATUS'):
            with self.subTest(setting=setting):
                status, calls, output = self.run_setup(**{setting: '1'})
                self.assertEqual(status, 1)
                self.assertNotIn('OK:', output)


class ClonePreflightTests(unittest.TestCase):
    def preflight(self, host_status='idle', state=None, running=True, host_present=True, broken=False):
        source = BOOTSTRAP.read_text().split("<<'PYCLONE'\n", 1)[1].split('\nPYCLONE', 1)[0]
        bridge = MagicMock()
        bridge.return_value.__enter__.return_value.makefile.return_value = io.BytesIO(
            json.dumps({'ok': True, 'result': {'status': host_status}}).encode() + b'\n')
        http = MagicMock(return_value=io.BytesIO(json.dumps(state or {'jobs': []}).encode()))
        if broken:
            http.side_effect = OSError('connection refused')
        with patch('socket.socket', bridge), patch('os.path.exists', return_value=host_present), \
             patch('urllib.request.urlopen', http), patch('sys.argv', ['-', 'true' if running else 'false']), \
             contextlib.redirect_stderr(io.StringIO()):
            try:
                exec(compile(source, 'bootstrap clone preflight', 'exec'), {})
                result = 0
            except SystemExit as exc:
                result = exc.code
        return result, http

    def test_idle_and_new_installation_are_allowed(self):
        self.assertEqual(self.preflight()[0], 0)
        self.assertEqual(self.preflight(host_present=False)[0], 0)
        status, http = self.preflight(running=False, host_present=False)
        self.assertEqual(status, 0)
        http.assert_not_called()

    def test_running_clone_and_unknown_host_state_block_setup(self):
        for status in ('running', 'unknown'):
            with self.subTest(status=status):
                result, http = self.preflight(host_status=status)
                self.assertEqual(result, 1)
                http.assert_not_called()

    def test_transfers_refresh_restart_and_unreachable_downloader_block_setup(self):
        cases = [{'jobs': [{'status': status}]} for status in ('queued', 'downloading', 'verifying', 'extracting')]
        cases += [{'jobs': [], 'upload_active': True}, {'jobs': [], 'refreshing': True},
                  {'jobs': [], 'restart': {'requested': True}},
                  {'jobs': [], 'clone': {'status': 'running'}}]
        for state in cases:
            with self.subTest(state=state):
                self.assertEqual(self.preflight(state=state)[0], 1)
        self.assertEqual(self.preflight(broken=True)[0], 1)
        self.assertEqual(self.preflight(state={'jobs': [{'status': 'complete'}, {'status': 'failed'}]})[0], 0)


if __name__ == '__main__':
    unittest.main()
