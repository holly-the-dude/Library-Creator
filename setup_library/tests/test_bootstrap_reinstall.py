"""Run only the reinstall function with Git and destructive commands mocked.

No root files, containers, network, or real Git checkout are touched.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


BOOTSTRAP = Path(__file__).resolve().parents[2] / "bootstrap"


class BootstrapReinstallTests(unittest.TestCase):
    def run_reinstall(self, expected_exit=0, **settings):
        match = re.search(r"^do_reinstall\(\) \{\n.*?^\}", BOOTSTRAP.read_text(), re.M | re.S)
        self.assertIsNotNone(match)
        shell = r'''
trace() { printf 'CALL'; printf '\t%s' "$@"; printf '\n'; }
msg_info() { printf '%s\n' "$1"; }
msg_warn() { printf '%s\n' "$1"; }
msg_error() { printf '%s\n' "$1"; }
msg_ok() { printf '%s\n' "$1"; }
msg_step() { printf '%s\n' "$1"; }
separator() { :; }
pause() { :; }
confirm() { return "$CONFIRM_STATUS"; }
resolve_repository() { printf '%s\n' "$CHECKOUT_PATH"; }
ensure_trixie() { trace os-check "$@"; return "$OS_STATUS"; }
REPOSITORY_FILE=./repository-path
command() {
    if [[ "$1" == -v && "$2" == git ]]; then
        return "$GIT_MISSING"
    fi
    builtin command "$@"
}
git() {
    # rev-parse output is redirected by the installer; record calls separately.
    trace git "$@" >&3
    if [[ "$3" == rev-parse ]]; then return "$CHECKOUT_STATUS"; fi
    if [[ "$3" == pull ]]; then return "$PULL_STATUS"; fi
    return 99
}
rm() { trace rm "$@"; }
podman() { trace podman "$@"; }
clear() { :; }
sleep() { :; }
cd() {
    trace cd "$@"
    [[ $# == 1 ]] || return 1
    if [[ "$1" == /root ]]; then
        return "$ROOT_CD_STATUS"
    fi
    [[ "$1" == "$CHECKOUT_PATH" ]] || return 1
    [[ "$CHECKOUT_CD_STATUS" == 0 ]] || return "$CHECKOUT_CD_STATUS"
    builtin cd "$TEST_CHECKOUT"
}
exec 3>&1
'''
        shell += match.group() + '\ndo_reinstall\nprintf "RETURN=%s\\n" "$?"\n'
        environment = {"PATH": "/nonexistent", "CONFIRM_STATUS": "0", "GIT_MISSING": "0",
                       "CHECKOUT_STATUS": "0", "PULL_STATUS": "0", "OS_STATUS": "0",
                       "CHECKOUT_PATH": "/root/Library-Creator", "ROOT_CD_STATUS": "0",
                       "CHECKOUT_CD_STATUS": "0", "BOOTSTRAP_STATUS": "0", **settings}
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory) / 'source with spaces'
            checkout.mkdir()
            launcher = checkout / 'bootstrap'
            launcher.write_text('#!/bin/bash\nprintf "CALL\\tbootstrap\\n"\nexit "$BOOTSTRAP_STATUS"\n')
            launcher.chmod(0o755)
            environment['TEST_CHECKOUT'] = str(checkout)
            result = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c", shell],
                                    cwd=directory, env=environment, capture_output=True,
                                    text=True, timeout=5)
        self.assertEqual(result.returncode, expected_exit, result.stderr)
        self.assertEqual(result.stderr, "")
        calls = [line.split("\t")[1:] for line in result.stdout.splitlines() if line.startswith("CALL\t")]
        return calls, result.stdout

    def test_pull_precedes_the_existing_cleanup_from_any_working_directory(self):
        calls, output = self.run_reinstall()
        self.assertEqual(calls, [
            ["git", "-C", "/root/Library-Creator", "rev-parse", "--is-inside-work-tree"],
            ["git", "-C", "/root/Library-Creator", "pull", "--ff-only"],
            ["os-check", "/root/Library-Creator"],
            ["cd", "/root"],
            ["rm", "-frv", ".0boot", "bootstrap", "display", "file_me_invert.jpg",
             ".firstboot", "install", "install.log", "installplay.log", ".secondboot",
             "start_library.yml", ".thirdboot", "touchtest.py"],
            ["podman", "stop", "--all"],
            ["podman", "stop", "--all"],
            ["podman", "rmi", "--all", "--force"],
            ["cd", "/root/Library-Creator"],
            ["bootstrap"],
        ])
        self.assertNotIn("RETURN=", output)  # Successful cleanup still exits.

    def test_lowercase_checkout_is_used_for_pull_and_relaunch(self):
        calls, output = self.run_reinstall(CHECKOUT_PATH="/root/library-creator")
        self.assertEqual(calls[1], ["git", "-C", "/root/library-creator", "pull", "--ff-only"])
        self.assertEqual(calls[-2:], [["cd", "/root/library-creator"], ["bootstrap"]])

    def test_checkout_with_spaces_is_used_for_relaunch(self):
        calls, output = self.run_reinstall(CHECKOUT_PATH="/root/my library copy")
        self.assertEqual(calls[-2:], [["cd", "/root/my library copy"], ["bootstrap"]])

    def test_failed_root_cd_prevents_relative_cleanup(self):
        calls, output = self.run_reinstall(ROOT_CD_STATUS="1")
        self.assertEqual([call[0] for call in calls], ["git", "git", "os-check", "cd"])
        self.assertIn("RETURN=1", output)

    def test_failed_checkout_cd_prevents_relaunch(self):
        calls, output = self.run_reinstall(CHECKOUT_CD_STATUS="1")
        self.assertEqual(calls[-1], ["cd", "/root/Library-Creator"])
        self.assertNotIn(["bootstrap"], calls)
        self.assertIn("RETURN=1", output)

    def test_relaunch_failure_is_propagated(self):
        calls, output = self.run_reinstall(BOOTSTRAP_STATUS="7", expected_exit=7)
        self.assertEqual(calls[-1], ["bootstrap"])
        self.assertNotIn("RETURN=", output)

    def test_failed_or_reboot_pending_os_preflight_prevents_cleanup(self):
        calls, output = self.run_reinstall(OS_STATUS="1")
        self.assertEqual([call[0] for call in calls], ["git", "git", "os-check"])
        self.assertIn("RETURN=1", output)

    def test_failed_pull_does_not_start_cleanup(self):
        calls, output = self.run_reinstall(PULL_STATUS="1")
        self.assertEqual([call[0] for call in calls], ["git", "git"])
        self.assertIn("Git pull failed. Reinstall cleanup was not started.", output)
        self.assertIn("RETURN=1", output)

    def test_missing_checkout_does_not_pull_or_clean_up(self):
        calls, output = self.run_reinstall(CHECKOUT_STATUS="128")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][3], "rev-parse")
        self.assertIn("not an accessible Git checkout", output)
        self.assertIn("RETURN=1", output)

    def test_missing_git_does_not_clean_up(self):
        calls, output = self.run_reinstall(GIT_MISSING="1")
        self.assertEqual(calls, [])
        self.assertIn("Git is not installed", output)
        self.assertIn("RETURN=1", output)

    def test_cancellation_does_not_pull_or_clean_up(self):
        calls, output = self.run_reinstall(CONFIRM_STATUS="1")
        self.assertEqual(calls, [])
        self.assertIn("Reinstall / upgrade cancelled", output)


if __name__ == "__main__":
    unittest.main()
