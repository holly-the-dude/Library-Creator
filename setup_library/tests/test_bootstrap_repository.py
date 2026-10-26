"""Exercise checkout discovery without running the installer or writing root files."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

BOOTSTRAP = Path(__file__).resolve().parents[2] / 'bootstrap'


def function(name):
    return re.search(r'^' + name + r'\(\) \{\n.*?^\}', BOOTSTRAP.read_text(), re.M | re.S).group()


class RepositoryTests(unittest.TestCase):
    def test_copy_without_git_is_discovered_from_launch_saved_path_or_cwd(self):
        for source in ('launch', 'saved', 'cwd'):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                copied = root / 'my test copy'
                (copied / 'setup_library').mkdir(parents=True)
                (copied / 'bootstrap').touch()
                old = root / 'old-clone'
                (old / '.git').mkdir(parents=True)
                (old / 'setup_library').mkdir()
                (old / 'bootstrap').touch()
                saved = root / 'saved'
                if source != 'cwd':
                    saved.write_text(str(old if source == 'launch' else copied) + '\n')
                result = subprocess.run(['/bin/bash', '-c',
                    function('is_library_checkout') + '\n' + function('resolve_repository') + '\nresolve_repository'],
                    env={**os.environ, 'BOOTSTRAP_DIR': str(copied if source == 'launch' else root),
                         'REPOSITORY_FILE': str(saved)},
                    cwd=copied if source == 'cwd' else root, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), str(copied))

    def test_incomplete_source_folder_is_rejected(self):
        for missing in ('bootstrap', 'setup_library'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                if missing != 'bootstrap':
                    (root / 'bootstrap').touch()
                if missing != 'setup_library':
                    (root / 'setup_library').mkdir()
                result = subprocess.run(['/bin/bash', '-c',
                    function('is_library_checkout') + '\nis_library_checkout "$1"', 'bash', str(root)],
                    text=True, capture_output=True)
                self.assertEqual(result.returncode, 1, result.stderr)

    def test_discovery_from_clone_or_remembered_path_with_any_name(self):
        for name in ('Library-Creator', 'library-creator', 'my library checkout'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                clone = root / name
                (clone / '.git').mkdir(parents=True)
                (clone / 'setup_library').mkdir()
                (clone / 'bootstrap').touch()
                remembered = root / 'saved-path'
                for from_clone in (True, False):
                    remembered.write_text(str(clone) + '\n')
                    result = subprocess.run(['/bin/bash', '-c',
                        function('is_library_checkout') + '\n' + function('resolve_repository') + '\nresolve_repository'],
                        env={**os.environ, 'BOOTSTRAP_DIR': str(clone if from_clone else root),
                             'REPOSITORY_FILE': str(remembered)}, cwd=root, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), str(clone))

    def test_launched_checkout_wins_over_saved_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('old', 'new'):
                (root / name / '.git').mkdir(parents=True)
                (root / name / 'setup_library').mkdir()
                (root / name / 'bootstrap').touch()
            saved = root / 'saved'
            saved.write_text(str(root / 'old') + '\n')
            result = subprocess.run(['/bin/bash', '-c', function('is_library_checkout') + '\n' +
                                     function('resolve_repository') + '\nresolve_repository'],
                                    env={**os.environ, 'BOOTSTRAP_DIR': str(root / 'new'),
                                         'REPOSITORY_FILE': str(saved)}, cwd=root,
                                    capture_output=True, text=True)
            self.assertEqual(result.stdout.strip(), str(root / 'new'))

    def test_first_boot_os_failure_stops_before_any_disk_or_flag_work(self):
        shell = r'''
resolve_repository() { echo '/tmp/library-creator'; }
ensure_trixie() { echo OS-CHECK-STOPPED; return 1; }
test() { return 1; }
msg_error() { echo "$1"; }
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', shell + function('do_first_boot') + '\ndo_first_boot'],
                                    env={'PATH': '/nonexistent', 'REPOSITORY_FILE': directory + '/saved'},
                                    cwd=directory, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout.strip(), 'OS-CHECK-STOPPED')
            self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
