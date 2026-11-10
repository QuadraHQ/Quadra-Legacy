from pathlib import Path

from ..i18n import _
from .errors import RebuildError
from .fetch import download_verified

__all__ = ["destination", "install"]

FILE_NAME = "Quadra.AppImage"
EXECUTABLE_MODE = 0o755


def destination():
    return Path.home() / ".local" / "bin" / FILE_NAME


def install(release, progress=None, cancelled=None):
    if release.appimage is None:
        raise RebuildError(_("This release has no AppImage."))
    target = destination()
    download_verified(release.appimage, release.checksums, target, progress, cancelled)
    target.chmod(EXECUTABLE_MODE)
    return target
