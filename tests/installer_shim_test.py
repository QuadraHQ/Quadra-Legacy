import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIM = ROOT / "install.sh"


def run(installer_body, *arguments, url=None, feed_script_on_stdin=False):
    with tempfile.TemporaryDirectory() as directory:
        installer = Path(directory) / "installer.sh"
        installer.write_text(installer_body)
        environment = dict(
            os.environ, QUADRA_INSTALLER_URL=url or installer.as_uri()
        )
        if feed_script_on_stdin:
            return subprocess.run(
                ["bash", "-s", "--", *arguments],
                input=SHIM.read_text(),
                capture_output=True,
                text=True,
                env=environment,
            )
        return subprocess.run(
            ["bash", str(SHIM), *arguments],
            capture_output=True,
            text=True,
            env=environment,
            stdin=subprocess.DEVNULL,
        )


class InstallerShimTests(unittest.TestCase):
    def test_syntax_and_identical_copy_for_the_website(self):
        subprocess.run(["bash", "-n", str(SHIM)], check=True)
        self.assertEqual(SHIM.read_text(), (ROOT / "website/dist/install.sh").read_text())

    def test_runs_the_downloaded_installer_with_every_argument_intact(self):
        result = run('printf "%s|" "$0" "$@"', "--version", "v1 2", "--flatpak")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "quadra-install|--version|v1 2|--flatpak|")

    def test_works_when_the_shim_itself_is_piped_into_bash(self):
        result = run('echo "ran with $#: $*"', "--help", feed_script_on_stdin=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ran with 1: --help")

    def test_the_installers_exit_status_is_passed_on(self):
        self.assertEqual(run("exit 7").returncode, 7)

    def test_an_unreachable_installer_is_a_clear_failure_that_runs_nothing(self):
        result = run("echo SHOULD-NOT-RUN", url="http://127.0.0.1:1/install.sh")
        self.assertEqual(result.returncode, 1)
        self.assertIn("could not download the installer", result.stderr)
        self.assertNotIn("SHOULD-NOT-RUN", result.stdout)

    def test_an_empty_installer_is_refused(self):
        result = run("")
        self.assertEqual(result.returncode, 1)
        self.assertIn("was empty", result.stderr)

    def test_it_points_at_the_rewrite_by_default(self):
        self.assertIn(
            "https://raw.githubusercontent.com/QuadraHQ/quadra-rewrite/main/install.sh",
            SHIM.read_text(),
        )


if __name__ == "__main__":
    unittest.main()
