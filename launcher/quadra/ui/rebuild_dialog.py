import os
import signal
import threading
import time

from gi.repository import Adw, GLib, Gtk

from .. import rebuild
from ..i18n import _
from . import dialogs, system

__all__ = [
    "REBUILD_APPIMAGE",
    "REBUILD_FLATPAK",
    "REBUILD_FLATPAK_SANDBOX_FILE",
    "REBUILD_NATIVE",
    "_rebuild_build_natively",
    "_rebuild_choices",
    "_rebuild_download",
    "_rebuild_fail",
    "_rebuild_hand_over_to_terminal",
    "_rebuild_in_background",
    "_rebuild_install_flatpak",
    "_rebuild_lookup_failed",
    "_rebuild_show_choices",
    "_rebuild_start",
    "_rebuild_switch_to_appimage",
    "offer_rust_version",
]

REBUILD_APPIMAGE = "appimage"
REBUILD_FLATPAK = "flatpak"
REBUILD_NATIVE = "native"
REBUILD_FLATPAK_SANDBOX_FILE = "/.flatpak-info"


def offer_rust_version(window, forced=False):
    if forced and os.path.exists(REBUILD_FLATPAK_SANDBOX_FILE):
        system._open_uri(window, rebuild.RELEASES_PAGE)
        return

    def look_up():
        try:
            release = rebuild.fetch_newest()
        except rebuild.RebuildError as error:
            GLib.idle_add(_rebuild_lookup_failed, window, str(error), forced)
            return
        GLib.idle_add(_rebuild_show_choices, window, release)

    threading.Thread(target=look_up, daemon=True).start()


def _rebuild_lookup_failed(window, message, forced):
    if forced:
        dialogs._toast(window.toasts, message)


def _rebuild_show_choices(window, release):
    body = _(
        "Quadra has been rewritten in Rust ({version}, an early test version). "
        "It runs Roblox through Rosemary only, and it does not carry over your "
        "settings or your Roblox sign-in. This Quadra stays installed and keeps working.",
        version=release.version,
    )
    if window.settings.get("runtime_backend") == "darling":
        body += "\n\n" + _(
            "You run Roblox on Darling now, which the Rust version does not support yet."
        )
    dialog = Adw.AlertDialog(heading=_("Try the Rust version of Quadra?"), body=body)

    group = Adw.PreferencesGroup()
    buttons = {}
    first_button = None
    for key, title, subtitle, available in _rebuild_choices(release):
        button = Gtk.CheckButton(sensitive=available)
        if first_button is None:
            first_button = button
        else:
            button.set_group(first_button)
        row = Adw.ActionRow(
            title=title,
            subtitle=subtitle,
            activatable_widget=button,
            sensitive=available,
        )
        row.add_prefix(button)
        group.add(row)
        buttons[key] = button
    next(
        button for key, button in buttons.items() if button.get_sensitive()
    ).set_active(True)
    dialog.set_extra_child(group)

    dialog.add_response("never", _("Don't ask again"))
    dialog.add_response("later", _("Not now"))
    dialog.add_response("continue", _("Continue"))
    dialog.set_response_appearance("continue", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("continue")
    dialog.set_close_response("later")

    def response(_dialog, result):
        if result == "never":
            window.set_setting("rust_rebuild_dismissed", True)
        elif result == "later":
            window.set_setting(
                "rust_rebuild_snoozed_until",
                time.time() + rebuild.prompt.SNOOZE_SECONDS,
            )
        elif result == "continue":
            chosen = next(key for key, button in buttons.items() if button.get_active())
            _rebuild_start(window, release, chosen)

    dialog.connect("response", response)
    dialog.present(window)


def _rebuild_choices(release):
    has_checksums = release.checksums is not None
    if release.appimage is None or not has_checksums:
        appimage_note = _("This release has no AppImage with checksums yet.")
    else:
        appimage_note = _(
            "One file in ~/.local/bin that updates itself. The simplest choice."
        )
    if not rebuild.flatpak.available():
        flatpak_note = _("Flatpak is not installed.")
    elif release.flatpak is None or not has_checksums:
        flatpak_note = _("This release has no Flatpak with checksums yet.")
    else:
        flatpak_note = _(
            "Sandboxed. VR may not work inside the sandbox, and updates stay "
            "manual until it is on Flathub."
        )
    return [
        (
            REBUILD_APPIMAGE,
            _("AppImage"),
            appimage_note,
            release.appimage is not None and has_checksums,
        ),
        (
            REBUILD_FLATPAK,
            _("Flatpak"),
            flatpak_note,
            release.flatpak is not None
            and has_checksums
            and rebuild.flatpak.available(),
        ),
        (
            REBUILD_NATIVE,
            _("Build on this computer"),
            _(
                "Compiles Quadra here, like the old version. Needs Rust and the GTK "
                "development packages, takes a few minutes and does not update itself."
            ),
            True,
        ),
    ]


def _rebuild_start(window, release, choice):
    if not window.begin("moving_to_rust"):
        return
    if choice == REBUILD_NATIVE:
        _rebuild_in_background(
            rebuild.native.problems, lambda found: _rebuild_build_natively(window, release, found)
        )
    else:
        _rebuild_download(window, release, choice)


def _rebuild_build_natively(window, release, found_problems):
    try:
        if found_problems:
            raise rebuild.RebuildError(
                _("This computer cannot build Quadra yet:")
                + "\n\n"
                + "\n".join(f"• {problem}" for problem in found_problems)
                + "\n\n"
                + _("The AppImage and the Flatpak need none of this.")
            )
        rebuild.handoff.open_in_terminal(rebuild.native.prepare(release, os.getpid()))
    except rebuild.RebuildError as error:
        _rebuild_fail(window, error)
        return
    _rebuild_hand_over_to_terminal(window)


def _rebuild_download(window, release, choice):
    cancelled = threading.Event()
    bar = Gtk.ProgressBar(show_text=True)
    dialog = Adw.AlertDialog(
        heading=_("Downloading Quadra {version}…", version=release.version)
    )
    dialog.set_extra_child(bar)
    dialog.add_response("cancel", _("Cancel"))
    dialog.connect("response", lambda *_args: cancelled.set())
    dialog.present(window)

    def report(fraction):
        GLib.idle_add(bar.set_fraction, fraction)

    def work():
        if choice == REBUILD_APPIMAGE:
            return rebuild.appimage.install(release, report, cancelled)
        return rebuild.flatpak.download(release, report, cancelled)

    def finished(result, error):
        dialog.force_close()
        if error is not None:
            _rebuild_fail(window, error, quiet=cancelled.is_set())
        elif choice == REBUILD_APPIMAGE:
            _rebuild_switch_to_appimage(window, result)
        else:
            _rebuild_install_flatpak(window, result)

    _rebuild_in_background(work, finished, catch=rebuild.RebuildError)


def _rebuild_switch_to_appimage(window, appimage):
    rebuild.handoff.start_after_exit([appimage], os.getpid())
    window.end(resume_pending=False)
    window.get_application().stop_from_signal(signal.SIGTERM)


def _rebuild_install_flatpak(window, bundle):
    try:
        rebuild.handoff.open_in_terminal(rebuild.flatpak.prepare(bundle, os.getpid()))
    except rebuild.RebuildError as error:
        _rebuild_fail(window, error)
        return
    _rebuild_hand_over_to_terminal(window)


def _rebuild_hand_over_to_terminal(window):
    window.end(resume_pending=False)
    dialogs._toast(
        window.toasts,
        _(
            "Installing in a terminal window. This Quadra stays open until it is done."
        ),
    )


def _rebuild_fail(window, error, quiet=False):
    window.end(resume_pending=False)
    if not quiet:
        dialogs._error_dialog(
            window, _("Could not move to the Rust version"), str(error)
        )


def _rebuild_in_background(work, finished, catch=None):
    def run():
        try:
            result, error = work(), None
        except catch or () as caught:
            result, error = None, caught
        if catch is None:
            GLib.idle_add(finished, result)
        else:
            GLib.idle_add(finished, result, error)

    threading.Thread(target=run, daemon=True).start()
