import hashlib
import os
import urllib.request

from ..i18n import _
from .errors import RebuildError
from .releases import TIMEOUT_SECONDS

__all__ = ["download_verified", "expected_checksum"]

CHUNK_BYTES = 64 * 1024
MAXIMUM_CHECKSUMS_BYTES = 1024 * 1024


def expected_checksum(text, name):
    for line in text.splitlines():
        checksum, _separator, listed = line.strip().partition(" ")
        if checksum and listed.strip().lstrip("*") == name:
            return checksum.lower()
    return None


def download_verified(
    asset,
    checksums,
    destination,
    progress=None,
    cancelled=None,
    opener=None,
):
    opener = opener or urllib.request.urlopen
    if checksums is None:
        raise RebuildError(
            _("This release has no checksums, so Quadra will not install it.")
        )
    expected = expected_checksum(_read_text(checksums.url, opener), asset.name)
    if expected is None:
        raise RebuildError(
            _("The release's checksums do not list {name}.", name=asset.name)
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    digest = hashlib.sha256()
    try:
        with opener(_request(asset.url), timeout=TIMEOUT_SECONDS) as response:
            total = int(response.headers.get("Content-Length") or 0)
            received = 0
            with open(partial, "wb") as file:
                while chunk := response.read(CHUNK_BYTES):
                    if cancelled is not None and cancelled.is_set():
                        raise RebuildError(_("Cancelled."))
                    file.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    if progress is not None and total:
                        progress(min(received / total, 1.0))
        if digest.hexdigest() != expected:
            raise RebuildError(
                _(
                    "The download of {name} does not match its checksum, so it was not installed.",
                    name=asset.name,
                )
            )
        os.replace(partial, destination)
    except OSError as error:
        raise RebuildError(
            _("Could not download {name}: {error}", name=asset.name, error=error)
        ) from error
    finally:
        partial.unlink(missing_ok=True)
    return destination


def _request(url):
    return urllib.request.Request(url, headers={"User-Agent": "Quadra"})


def _read_text(url, opener):
    try:
        with opener(_request(url), timeout=TIMEOUT_SECONDS) as response:
            return response.read(MAXIMUM_CHECKSUMS_BYTES).decode(errors="replace")
    except OSError as error:
        raise RebuildError(
            _("Could not download the release's checksums: {error}", error=error)
        ) from error
