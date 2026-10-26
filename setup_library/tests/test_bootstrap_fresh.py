"""Check fresh-install routing and flag cleanup without running installation."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


BOOTSTRAP = Path(__file__).resolve().parents[2] / "bootstrap"


class FreshInstallTests(unittest.TestCase):
    def run_shell(self, shell, inputs="", **settings):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                ["/bin/bash", "--noprofile", "--norc", "-c", shell],
                input=inputs, text=True, capture_output=True, timeout=5,
                cwd=directory,
                env={"PATH": "/nonexistent", "CONFIRM_STATUS": "0",
                     "OS_STATUS": "0", "RM_STATUS": "0", **settings},
            )
        self.assertEqual(result.stderr, "")
        return result

    def run_menu(self, inputs, **settings):
        menu = BOOTSTRAP.read_text().split('\nwhile true; do\n', 1)[1]
        stubs = r'''
show_main_menu() { :; }
show_display_menu() { :; }
separator() { :; }
msg_info() { :; }
msg_warn() { :; }
msg_ok() { :; }
msg_error() { printf 'ERROR:%s\n' "$1"; }
pause() { echo PAUSED; }
confirm() { return "$CONFIRM_STATUS"; }
do_first_boot() { printf 'FIRST:%s:%s\n' "$1" "$DISP"; return "${FIRST_STATUS:-0}"; }
'''
        if settings.pop("real_confirm", False):
            stubs += re.search(r'^confirm\(\) \{\n.*?^\}',
                               BOOTSTRAP.read_text(), re.M | re.S).group() + '\n'
        return self.run_shell(stubs + '\nwhile true; do\n' + menu, inputs, **settings)

    def test_yes_variants_reach_installation_and_exit_without_another_menu(self):
        for reply in ('y', 'Y', 'yes', 'Yes', 'YES', 'yEs', ' yes '):
            with self.subTest(reply=reply):
                result = self.run_menu(f'1\n2\n{reply}\n', real_confirm=True)
                self.assertEqual(result.returncode, 0)
                self.assertIn('FIRST:--fresh:0', result.stdout)
                self.assertNotIn('PAUSED', result.stdout)

    def test_negative_empty_and_invalid_answers_do_not_install(self):
        for reply in ('n', 'no', 'NO', '', 'maybe', 'yesterday'):
            with self.subTest(reply=reply):
                result = self.run_menu(f'1\n2\n{reply}\nq\n', real_confirm=True)
                self.assertEqual(result.returncode, 0)
                self.assertNotIn('FIRST:', result.stdout)

    def test_failed_first_boot_preserves_error_until_acknowledged(self):
        result = self.run_menu('1\n2\nyes\nq\n', real_confirm=True, FIRST_STATUS='1')
        self.assertIn('ERROR:First Boot stopped.', result.stdout)
        self.assertIn('PAUSED', result.stdout)
        self.assertLess(result.stdout.index('ERROR:'), result.stdout.index('PAUSED'))

    def test_fresh_and_restart_both_restart_first_boot(self):
        for choice in ("1", "3"):
            with self.subTest(choice=choice):
                result = self.run_menu(f"{choice}\n2\nq\n")
                self.assertEqual(result.returncode, 0)
                self.assertIn("FIRST:--fresh:0", result.stdout)

    def test_cancel_or_back_does_not_start_installation(self):
        for inputs, status in (("3\nb\nq\n", "0"), ("3\n1\nq\n", "1")):
            with self.subTest(inputs=inputs):
                result = self.run_menu(inputs, CONFIRM_STATUS=status)
                self.assertEqual(result.returncode, 0)
                self.assertNotIn("FIRST:", result.stdout)

    def run_first_boot(self, **settings):
        function = re.search(r'^do_first_boot\(\) \{\n.*?^\}',
                             BOOTSTRAP.read_text(), re.M | re.S).group()
        stubs = r'''
REPOSITORY_FILE=./saved-repository
BOOTSTRAP_DIR=/root
resolve_repository() { echo /example/checkout; }
ensure_trixie() { echo OS-CHECK; return "$OS_STATUS"; }
msg_step() { :; }
separator() { :; }
rm() { printf 'REMOVE'; printf ' %s' "$@"; printf '\n'; return "$RM_STATUS"; }
# Stop before any real install work, including creating boot markers.
touch() { echo START-INSTALL; exit 0; }
'''
        return self.run_shell(stubs + function + '\ndo_first_boot --fresh', **settings)

    def test_flags_are_cleared_after_preflight_before_installation(self):
        result = self.run_first_boot()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.splitlines(), [
            "OS-CHECK",
            "REMOVE -f /root/.0boot /root/.firstboot /root/.secondboot /root/.thirdboot",
            "START-INSTALL",
        ])

    def test_os_failure_preserves_flags(self):
        result = self.run_first_boot(OS_STATUS="1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "OS-CHECK\n")

    def test_cleanup_failure_stops_installation(self):
        result = self.run_first_boot(RM_STATUS="1")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("START-INSTALL", result.stdout)


if __name__ == "__main__":
    unittest.main()
