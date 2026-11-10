import hashlib
import io
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from quadra import core
from quadra.rebuild import (
    RebuildError,
    appimage,
    flatpak,
    handoff,
    native,
    prompt,
)
from quadra.rebuild import fetch, releases


def entry(tag, draft=False, assets=("AppImage", "flatpak", "sums")):
    names = {
        "AppImage": f"Quadra-{tag}-x86_64.AppImage",
        "flatpak": f"Quadra-{tag}-x86_64.flatpak",
        "sums": "SHA256SUMS",
    }
    return {
        "tag_name": tag,
        "draft": draft,
        "assets": [
            {"name": names[kind], "browser_download_url": f"https://example/{names[kind]}"}
            for kind in assets
        ],
    }


class FakeResponse(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *arguments):
        self.close()


def network(files):
    def opener(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else request
        if url not in files:
            raise OSError("offline")
        return FakeResponse(files[url])

    return opener


class VersionTests(unittest.TestCase):
    def test_orders_alphas_and_releases_like_semver(self):
        ascending = [
            "v0.50.0-alpha.1",
            "v0.50.0-alpha.2",
            "v0.50.0-alpha.10",
            "v0.50.0-beta",
            "v0.50.0",
            "v0.50.1",
            "v1.0.0",
        ]
        keys = [releases.version_key(tag) for tag in ascending]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(set(keys)), len(keys))

    def test_rejects_things_that_are_not_versions(self):
        for tag in ("", "latest", "1.2", "v1.2.3.4", "nightly-2026"):
            self.assertIsNone(releases.version_key(tag), tag)


class ReleaseTests(unittest.TestCase):
    def test_picks_the_highest_version_not_the_first_listed(self):
        found = releases.newest(
            [entry("v0.50.0-alpha.1"), entry("v0.50.0-alpha.10"), entry("v0.50.0-alpha.2")]
        )
        self.assertEqual(found.tag, "v0.50.0-alpha.10")
        self.assertEqual(found.version, "0.50.0-alpha.10")
        self.assertEqual(found.appimage.name, "Quadra-v0.50.0-alpha.10-x86_64.AppImage")
        self.assertEqual(found.checksums.name, "SHA256SUMS")

    def test_skips_drafts_and_odd_entries(self):
        found = releases.newest(
            [entry("v0.51.0", draft=True), "junk", {"tag_name": 3}, entry("v0.50.0-alpha.2")]
        )
        self.assertEqual(found.tag, "v0.50.0-alpha.2")

    def test_a_release_may_lack_assets(self):
        found = releases.newest([entry("v0.50.0-alpha.2", assets=())])
        self.assertIsNone(found.appimage)
        self.assertIsNone(found.flatpak)
        self.assertIsNone(found.checksums)

    def test_nothing_found_and_network_failures_are_reported(self):
        self.assertIsNone(releases.newest([]))
        with self.assertRaises(RebuildError):
            releases.fetch_newest(opener=network({}))
        with self.assertRaises(RebuildError):
            releases.fetch_newest(opener=network({releases.RELEASES_URL: b"[]"}))

    def test_fetches_through_the_api(self):
        body = b'[{"tag_name": "v0.50.0-alpha.2", "assets": []}]'
        found = releases.fetch_newest(opener=network({releases.RELEASES_URL: body}))
        self.assertEqual(found.tag, "v0.50.0-alpha.2")


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.directory)]))
        self.content = b"appimage bytes" * 5000
        self.asset = releases.Asset("Quadra-v1-x86_64.AppImage", "https://example/app")
        self.sums = releases.Asset("SHA256SUMS", "https://example/sums")

    def checksum_file(self, content=None, name=None):
        digest = hashlib.sha256(content or self.content).hexdigest()
        return f"{digest}  {name or self.asset.name}\n".encode()

    def test_expected_checksum_reads_both_styles(self):
        text = "AAA  plain\nBBB *binary\n"
        self.assertEqual(fetch.expected_checksum(text, "plain"), "aaa")
        self.assertEqual(fetch.expected_checksum(text, "binary"), "bbb")
        self.assertIsNone(fetch.expected_checksum(text, "other"))

    def test_installs_a_verified_download_and_reports_progress(self):
        target = self.directory / "Quadra.AppImage"
        steps = []
        fetch.download_verified(
            self.asset,
            self.sums,
            target,
            progress=steps.append,
            opener=network({self.asset.url: self.content, self.sums.url: self.checksum_file()}),
        )
        self.assertEqual(target.read_bytes(), self.content)
        self.assertEqual(steps[-1], 1.0)
        self.assertEqual(list(self.directory.glob("*.partial")), [])

    def test_a_wrong_checksum_installs_nothing_and_keeps_the_old_file(self):
        target = self.directory / "Quadra.AppImage"
        target.write_bytes(b"old")
        with self.assertRaises(RebuildError):
            fetch.download_verified(
                self.asset,
                self.sums,
                target,
                opener=network(
                    {self.asset.url: b"tampered", self.sums.url: self.checksum_file()}
                ),
            )
        self.assertEqual(target.read_bytes(), b"old")
        self.assertEqual(list(self.directory.glob("*.partial")), [])

    def test_missing_checksums_refuse_to_install(self):
        target = self.directory / "Quadra.AppImage"
        with self.assertRaises(RebuildError):
            fetch.download_verified(self.asset, None, target, opener=network({}))
        with self.assertRaises(RebuildError):
            fetch.download_verified(
                self.asset,
                self.sums,
                target,
                opener=network(
                    {self.asset.url: self.content, self.sums.url: b"abc  other-file\n"}
                ),
            )
        self.assertFalse(target.exists())

    def test_cancelling_stops_the_download(self):
        target = self.directory / "Quadra.AppImage"
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(RebuildError):
            fetch.download_verified(
                self.asset,
                self.sums,
                target,
                cancelled=cancelled,
                opener=network(
                    {self.asset.url: self.content, self.sums.url: self.checksum_file()}
                ),
            )
        self.assertFalse(target.exists())

    def test_the_appimage_is_installed_executable_under_home(self):
        release = releases.Release("v1", self.asset, None, self.sums)
        with mock.patch.object(appimage.Path, "home", return_value=self.directory), mock.patch.object(
            fetch.urllib.request,
            "urlopen",
            network({self.asset.url: self.content, self.sums.url: self.checksum_file()}),
        ):
            installed = appimage.install(release)
        self.assertEqual(installed, self.directory / ".local" / "bin" / "Quadra.AppImage")
        self.assertEqual(installed.stat().st_mode & 0o777, 0o755)
        with self.assertRaises(RebuildError):
            appimage.install(releases.Release("v1", None, None, self.sums))


class NativeTests(unittest.TestCase):
    def runner(self, cargo="cargo 1.90.0 (abc 2026-01-01)", libraries=("gtk4", "libadwaita-1")):
        def run(argv, **keywords):
            if argv[0] == "cargo":
                return subprocess.CompletedProcess(argv, 0, stdout=cargo)
            library = argv[-1]
            return subprocess.CompletedProcess(argv, 0 if library in libraries else 1)

        return run

    def which(self, missing=()):
        return lambda name: None if name in missing else f"/usr/bin/{name}"

    def test_a_ready_machine_has_no_problems(self):
        self.assertEqual(native.problems(self.runner(), self.which()), [])

    def test_missing_tools_are_listed(self):
        found = native.problems(self.runner(), self.which(missing=("git", "cargo")))
        self.assertEqual(len(found), 2)

    def test_a_compiler_of_any_kind_is_enough(self):
        self.assertEqual(
            native.problems(self.runner(), self.which(missing=("cc", "gcc"))), []
        )
        self.assertEqual(
            len(native.problems(self.runner(), self.which(missing=("cc", "gcc", "clang")))), 1
        )

    def test_old_rust_and_old_gtk_are_caught(self):
        found = native.problems(
            self.runner(cargo="cargo 1.80.1 (x)", libraries=("libadwaita-1",)), self.which()
        )
        self.assertEqual(len(found), 2)
        self.assertTrue(any("Rust" in message for message in found))
        self.assertTrue(any("GTK" in message for message in found))


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.directory)]))
        patcher = mock.patch.object(core, "CACHE_DIR", self.directory)
        patcher.start()
        self.addCleanup(patcher.stop)

    def assert_valid_bash(self, script):
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(script.stat().st_mode & 0o777, 0o700)

    def test_the_flatpak_script_is_valid_and_quotes_awkward_paths(self):
        bundle = self.directory / "it's a $(bundle).flatpak"
        script = flatpak.prepare(bundle, 4242)
        self.assert_valid_bash(script)
        self.assertIn("old_pid=4242", script.read_text())

    def test_values_reach_a_script_exactly_as_given(self):
        awkward = "it's a $(touch pwned) `id` \"quoted\" path"
        script = handoff.write_script("quote.sh", 1, {"value": awkward}, 'printf %s "$value"\n')
        result = subprocess.run(["bash", str(script)], capture_output=True, text=True, cwd=self.directory)
        self.assertEqual(result.stdout, awkward)
        self.assertFalse((self.directory / "pwned").exists())

    def test_the_native_script_is_valid(self):
        release = releases.Release("v0.50.0-alpha.2", None, None, None)
        script = native.prepare(release, 1)
        self.assert_valid_bash(script)
        self.assertIn("tag=v0.50.0-alpha.2", script.read_text())
        self.assertIn("cargo build --release --locked", script.read_text())

    def test_a_script_sees_the_values_it_was_given(self):
        script = handoff.write_script("check.sh", 7, {"greeting": "hello world"}, 'echo "$old_pid $greeting"\n')
        result = subprocess.run(["bash", str(script)], capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), "7 hello world")

    def test_a_failing_step_reports_and_stops_before_closing_quadra(self):
        script = handoff.write_script(
            "fail.sh", 999999, {}, 'false || fail "It broke."\nstop_quadra\necho reached\n'
        )
        result = subprocess.run(
            ["bash", str(script)], capture_output=True, text=True, input="\n"
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("It broke.", result.stdout)
        self.assertNotIn("reached", result.stdout)

    def test_no_terminal_is_an_error_the_user_can_read(self):
        with mock.patch.object(handoff.terminal, "command", return_value=None):
            with self.assertRaises(RebuildError):
                handoff.open_in_terminal(self.directory / "x.sh")


class PromptTests(unittest.TestCase):
    def test_offers_by_default(self):
        self.assertTrue(prompt.should_offer({}, 1000.0, in_flatpak=False))

    def test_respects_never_and_the_snooze(self):
        self.assertFalse(prompt.should_offer({"rust_rebuild_dismissed": True}, 1000.0, False))
        snoozed = {"rust_rebuild_snoozed_until": 2000.0}
        self.assertFalse(prompt.should_offer(snoozed, 1000.0, False))
        self.assertTrue(prompt.should_offer(snoozed, 2000.5, False))

    def test_not_offered_to_darling_or_flatpak_installs(self):
        self.assertFalse(prompt.should_offer({"runtime_backend": "darling"}, 1.0, False))
        self.assertFalse(prompt.should_offer({}, 1.0, in_flatpak=True))
        self.assertTrue(prompt.should_offer({"runtime_backend": "rosemary"}, 1.0, False))


if __name__ == "__main__":
    unittest.main()
