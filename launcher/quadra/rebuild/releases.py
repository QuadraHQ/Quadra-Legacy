import json
import re
import urllib.request
from typing import NamedTuple

from ..i18n import _
from .errors import RebuildError

__all__ = [
    "RELEASES_PAGE",
    "REPOSITORY_URL",
    "Asset",
    "Release",
    "fetch_newest",
    "newest",
    "version_key",
]

RELEASES_URL = (
    "https://api.github.com/repos/QuadraHQ/quadra-rewrite/releases?per_page=30"
)
RELEASES_PAGE = "https://github.com/QuadraHQ/quadra-rewrite/releases"
REPOSITORY_URL = "https://github.com/QuadraHQ/quadra-rewrite.git"
TIMEOUT_SECONDS = 10
APPIMAGE_SUFFIX = "-x86_64.AppImage"
FLATPAK_SUFFIX = "-x86_64.flatpak"
CHECKSUMS_NAME = "SHA256SUMS"
VERSION_PATTERN = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+.*)?$"
)


class Asset(NamedTuple):
    name: str
    url: str


class Release(NamedTuple):
    tag: str
    appimage: Asset | None
    flatpak: Asset | None
    checksums: Asset | None

    @property
    def version(self):
        return self.tag.lstrip("v")


def version_key(tag):
    match = VERSION_PATTERN.match(tag)
    if match is None:
        return None
    core = tuple(int(part) for part in match.group(1, 2, 3))
    prerelease = match.group(4)
    if prerelease is None:
        return (core, 1, ())
    identifiers = tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in prerelease.split(".")
    )
    return (core, 0, identifiers)


def newest(entries):
    candidates = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("draft"):
            continue
        tag = entry.get("tag_name")
        key = version_key(tag) if isinstance(tag, str) else None
        if key is not None:
            candidates.append((key, _release_of(entry, tag)))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[0])[1]


def fetch_newest(opener=None):
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(RELEASES_URL, headers={"User-Agent": "Quadra"})
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            entries = json.loads(response.read())
    except (OSError, ValueError) as error:
        raise RebuildError(
            _("Could not look up the Rust version: {error}", error=error)
        ) from error
    release = newest(entries if isinstance(entries, list) else [])
    if release is None:
        raise RebuildError(_("No release of the Rust version was found."))
    return release


def _release_of(entry, tag):
    assets = [
        Asset(asset["name"], asset["browser_download_url"])
        for asset in entry.get("assets") or []
        if isinstance(asset, dict)
        and isinstance(asset.get("name"), str)
        and isinstance(asset.get("browser_download_url"), str)
    ]

    def find(matches):
        return next((asset for asset in assets if matches(asset.name)), None)

    return Release(
        tag,
        find(lambda name: name.endswith(APPIMAGE_SUFFIX)),
        find(lambda name: name.endswith(FLATPAK_SUFFIX)),
        find(lambda name: name == CHECKSUMS_NAME),
    )
