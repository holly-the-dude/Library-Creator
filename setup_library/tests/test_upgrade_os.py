"""Host upgrade tests: all OS files are temporary and package commands are mocked."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'upgrade_os.py'
spec = importlib.util.spec_from_file_location('upgrade_os', SCRIPT)
upgrade_os = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade_os)


class SourceTests(unittest.TestCase):
    def test_list_only_changes_active_suite_and_keeps_options_and_comments(self):
        original = ('# bookworm backup\n'
                    'deb [signed-by=/keys/bookworm.gpg] https://deb.debian.org/debian bookworm main non-free-firmware\n'
                    'deb http://security.debian.org/debian-security bookworm-security main\n'
                    'deb https://archive.raspberrypi.com/debian/ bookworm main\n')
        actual, count = upgrade_os.rewrite_sources(original)
        self.assertEqual(count, 3)
        self.assertIn('# bookworm backup', actual)
        self.assertIn('signed-by=/keys/bookworm.gpg', actual)
        self.assertIn('trixie-security main', actual)
        self.assertIn('/debian/ trixie main', actual)

    def test_deb822_multiline_suites_and_disabled_third_party_source(self):
        original = ('Types: deb deb-src\nURIs: https://deb.debian.org/debian\n'
                    'Suites: bookworm\n bookworm-updates\nComponents: main\nSigned-By: /key.gpg\n\n'
                    'Enabled: no\nTypes: deb\nURIs: https://example.com\nSuites: stable\n')
        actual, count = upgrade_os.rewrite_sources(original, deb822=True)
        self.assertEqual(count, 1)
        self.assertIn('Suites: trixie trixie-updates\nComponents:', actual)
        self.assertIn('Signed-By: /key.gpg', actual)
        self.assertIn('Suites: stable', actual)

    def test_unsupported_sources_fail_before_changes(self):
        for line in ('deb https://example.com/debian bookworm main',
                     'deb https://deb.debian.org/debian stable main',
                     'deb https://deb.debian.org/debian bookworm-backports main',
                     'deb https://deb.debian.org/debian trixie main'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                upgrade_os.rewrite_sources(line)

    def test_partial_source_transition_can_resume(self):
        actual, count = upgrade_os.rewrite_sources(
            'deb https://deb.debian.org/debian trixie main\n'
            'deb https://archive.raspberrypi.org/debian bookworm main\n', resuming=True)
        self.assertEqual(count, 2)
        self.assertNotIn('bookworm', actual)


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        paths = {'APT_DIR': root / 'apt', 'BACKUP_DIR': root / 'backups',
                 'STATE_DIR': root / 'state', 'STATE_FILE': root / 'state' / 'os-upgrade.json',
                 'OS_RELEASE_FILE': root / 'os-release', 'BOOT_ID_FILE': root / 'boot-id'}
        for key in ('APT_DIR', 'BACKUP_DIR', 'STATE_DIR'):
            paths[key].mkdir()
        for key, value in paths.items():
            patcher = patch.object(upgrade_os, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.source = paths['APT_DIR'] / 'sources.list'
        self.source.write_text('deb https://deb.debian.org/debian bookworm main\n')
        paths['BOOT_ID_FILE'].write_text('boot-before-upgrade')
        self.set_release('bookworm')
        self.calls = []
        self.fail_target_upgrade = False
        runner = patch.object(upgrade_os, 'run', side_effect=self.run_command)
        runner.start()
        self.addCleanup(runner.stop)

    def set_release(self, codename, os_id='debian'):
        upgrade_os.OS_RELEASE_FILE.write_text(f'ID={os_id}\nVERSION_CODENAME={codename}\n')

    def run_command(self, *args, capture=False):
        self.calls.append(args)
        if args == ('dpkg', '--print-architecture'):
            return 'arm64\n'
        if args[0] == 'apt-get' and args[-1] == 'full-upgrade' and 'trixie' in self.source.read_text():
            self.set_release('trixie')
            if self.fail_target_upgrade:
                raise subprocess.CalledProcessError(100, args)
        return ''

    def test_trixie_is_noop(self):
        self.set_release('trixie')
        self.assertEqual(upgrade_os.upgrade(), 0)
        self.assertEqual(self.calls, [])

    def test_older_newer_and_other_distros_stop_without_package_changes(self):
        for codename, os_id in [('bullseye', 'debian'), ('forky', 'debian'), ('noble', 'ubuntu')]:
            with self.subTest(codename=codename):
                self.set_release(codename, os_id)
                with self.assertRaises(ValueError):
                    upgrade_os.upgrade()
                self.assertEqual(self.calls, [])
                self.assertFalse(upgrade_os.STATE_FILE.exists())

    def test_upgrade_backs_up_sources_and_requires_reboot_before_install(self):
        self.assertEqual(upgrade_os.upgrade(), 10)
        state = json.loads(upgrade_os.STATE_FILE.read_text())
        self.assertEqual(state['phase'], 'complete')
        self.assertIn('bookworm', (Path(state['backup']) / 'apt' / 'sources.list').read_text())
        self.assertIn('trixie', self.source.read_text())
        commands = [call[4:] for call in self.calls if call[0] == 'apt-get']
        self.assertEqual(commands, [('update',), ('full-upgrade',), ('update',),
                                   ('--fix-broken', 'install'), ('upgrade', '--without-new-pkgs'), ('full-upgrade',)])
        self.calls.clear()
        self.assertEqual(upgrade_os.upgrade(), 10)
        self.assertEqual(self.calls, [])
        upgrade_os.BOOT_ID_FILE.write_text('boot-after-upgrade')
        self.assertEqual(upgrade_os.upgrade(), 0)
        self.assertFalse(upgrade_os.STATE_FILE.exists())

    def test_failed_target_upgrade_is_retried_even_if_os_reports_trixie(self):
        self.fail_target_upgrade = True
        with self.assertRaises(subprocess.CalledProcessError):
            upgrade_os.upgrade()
        self.assertEqual(upgrade_os.os_release()['VERSION_CODENAME'], 'trixie')
        self.assertEqual(json.loads(upgrade_os.STATE_FILE.read_text())['phase'], 'upgrading')
        self.calls.clear()
        self.fail_target_upgrade = False
        self.assertEqual(upgrade_os.upgrade(), 10)
        full_upgrades = [call for call in self.calls if call[-1] == 'full-upgrade']
        self.assertEqual(len(full_upgrades), 1)

    def test_third_party_source_prevents_backup_or_package_changes(self):
        self.source.write_text('deb https://example.com bookworm main\n')
        with self.assertRaisesRegex(ValueError, 'Nonstandard'):
            upgrade_os.upgrade()
        self.assertFalse(upgrade_os.STATE_FILE.exists())
        self.assertFalse(any(call[0] == 'apt-get' for call in self.calls))


if __name__ == '__main__':
    unittest.main()
