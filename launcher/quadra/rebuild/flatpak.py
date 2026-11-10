import shlex
import shutil

from .. import core
from ..i18n import _
from .errors import RebuildError
from .fetch import download_verified
from .handoff import write_script

__all__ = ["available", "download", "prepare"]

APP_ID = "org.quadrahq.Quadra"
FLATHUB_REPOSITORY = "https://dl.flathub.org/repo/flathub.flatpakrepo"
BODY = """echo "Installing Quadra as a Flatpak."
echo "The first install also downloads the GNOME runtime, which is large."
flatpak remote-add --user --if-not-exists flathub "$flathub" || fail "Could not add Flathub."
flatpak install --user --bundle -y --noninteractive "$bundle" || fail "The Flatpak did not install."
echo "Installed. Quadra will close and the Rust version will open."
stop_quadra
setsid -f flatpak run "$app_id" >/dev/null 2>&1
"""


def available():
    return shutil.which("flatpak") is not None


def download(release, progress=None, cancelled=None):
    if release.flatpak is None:
        raise RebuildError(_("This release has no Flatpak."))
    bundle = core.CACHE_DIR / "rust-rebuild" / release.flatpak.name
    return download_verified(
        release.flatpak, release.checksums, bundle, progress, cancelled
    )


def prepare(bundle, old_pid):
    return write_script(
        "install-flatpak.sh",
        old_pid,
        {"bundle": bundle, "flathub": FLATHUB_REPOSITORY, "app_id": APP_ID},
        BODY,
    )
