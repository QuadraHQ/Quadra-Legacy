import os

from .. import backends

__all__ = ["SNOOZE_SECONDS", "should_offer"]

SNOOZE_SECONDS = 7 * 24 * 60 * 60


def should_offer(settings, now, in_flatpak=None):
    if in_flatpak is None:
        in_flatpak = os.path.exists("/.flatpak-info")
    return not (
        in_flatpak
        or settings.get("rust_rebuild_dismissed", False)
        or now < settings.get("rust_rebuild_snoozed_until", 0.0)
        or settings.get("runtime_backend") == backends.DARLING
    )
