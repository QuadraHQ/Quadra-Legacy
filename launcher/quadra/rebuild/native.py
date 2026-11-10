import re
import shutil
import subprocess
from pathlib import Path

from .. import paths
from ..i18n import _
from .handoff import write_script
from .releases import REPOSITORY_URL

__all__ = ["binary_path", "prepare", "problems", "source_directory"]

MINIMUM_GTK = "4.18"
MINIMUM_LIBADWAITA = "1.7"
MINIMUM_RUST = (1, 85)
CARGO_VERSION = re.compile(r"cargo (\d+)\.(\d+)")
BINARY_NAME = "quadra-rewrite"
BODY = """mkdir -p "$(dirname "$source")"
if [ -d "$source/.git" ]; then
    git -C "$source" fetch --depth 1 origin "refs/tags/$tag:refs/tags/$tag" \\
        && git -C "$source" checkout -q "$tag" || fail "Could not fetch Quadra $tag."
else
    git clone --depth 1 --branch "$tag" "$repository" "$source" || fail "Could not download Quadra $tag."
fi
cd "$source" || fail "Could not open the source folder."
echo "Building Quadra $tag. This takes a few minutes."
cargo build --release --locked || fail "The build failed."
install -Dm755 "target/release/$binary_name" "$binary" || fail "Could not install the program."
echo "Built. Quadra will close and the Rust version will open."
stop_quadra
setsid -f "$binary" >/dev/null 2>&1
"""


def source_directory():
    return paths.user_directory("DATA") / "rust-rebuild" / "quadra-rewrite"


def binary_path():
    return Path.home() / ".local" / "bin" / BINARY_NAME


def problems(run=subprocess.run, which=shutil.which):
    found = [
        _("{program} is not installed.", program=program)
        for program in ("git", "cargo", "pkg-config")
        if which(program) is None
    ]
    if which("cc") is None and which("gcc") is None and which("clang") is None:
        found.append(_("A C compiler (gcc or clang) is not installed."))
    if which("cargo") is not None and not _rust_is_new_enough(run):
        found.append(
            _(
                "Rust {version} or newer is needed. Update it with rustup.",
                version=".".join(map(str, MINIMUM_RUST)),
            )
        )
    if which("pkg-config") is not None:
        for library, minimum, name in (
            ("gtk4", MINIMUM_GTK, "GTK"),
            ("libadwaita-1", MINIMUM_LIBADWAITA, "libadwaita"),
        ):
            if not _library_is_new_enough(run, library, minimum):
                found.append(
                    _(
                        "{name} {version} or newer, with its development files, is needed.",
                        name=name,
                        version=minimum,
                    )
                )
    return found


def prepare(release, old_pid):
    return write_script(
        "build-native.sh",
        old_pid,
        {
            "tag": release.tag,
            "repository": REPOSITORY_URL,
            "source": source_directory(),
            "binary": binary_path(),
            "binary_name": BINARY_NAME,
        },
        BODY,
    )


def _rust_is_new_enough(run):
    try:
        output = run(
            ["cargo", "--version"], capture_output=True, text=True, timeout=20
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    match = CARGO_VERSION.match(output)
    return match is not None and tuple(map(int, match.groups())) >= MINIMUM_RUST


def _library_is_new_enough(run, library, minimum):
    try:
        return (
            run(
                ["pkg-config", f"--atleast-version={minimum}", library],
                capture_output=True,
                timeout=20,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False
