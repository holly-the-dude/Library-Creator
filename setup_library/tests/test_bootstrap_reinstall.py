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
    def run_reinstall(self, **settings):
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
exec 3>&1
'''
        shell += match.group() + '\ndo_reinstall\nprintf "RETURN=%s\\n" "$?"\n'
        environment = {"PATH": "/nonexistent", "CONFIRM_STATUS": "0", "GIT_MISSING": "0",
                       "CHECKOUT_STATUS": "0", "PULL_STATUS": "0", **settings}
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c", shell],
                                    cwd=directory, env=environment, capture_output=True,
                                    text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        calls = [line.split("\t")[1:] for line in result.stdout.splitlines() if line.startswith("CALL\t")]
        return calls, result.stdout

    def test_pull_precedes_the_existing_cleanup_from_any_working_directory(self):
        calls, output = self.run_reinstall()
        self.assertEqual(calls, [
            ["git", "-C", "/root/Library-Creator", "rev-parse", "--is-inside-work-tree"],
            ["git", "-C", "/root/Library-Creator", "pull", "--ff-only"],
            ["rm", "-f", "/root/.0boot", "/root/.firstboot", "/root/.secondboot", "/root/.thirdboot", "/root/start_library"],
            ["rm", "-rf", "/root/install", "/root/display"],
            ["podman", "stop", "--all"],
            ["podman", "stop", "--all"],
            ["podman", "rmi", "--all", "--force"],
        ])
        self.assertIn("Run /root/Library-Creator/bootstrap again", output)
        self.assertNotIn("RETURN=", output)  # Successful cleanup still exits.

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
