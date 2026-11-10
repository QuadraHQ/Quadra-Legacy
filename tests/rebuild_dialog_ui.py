"""Optional UI regression for the offer to move to the Rust version of Quadra.

GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a -s "-screen 0 1280x900x24" python3 tests/rebuild_dialog_ui.py

Settings are never read from or written to disk: load_settings and save_settings are replaced.
"""
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
threading.Thread.start = lambda self: None
from quadra import core, rebuild, ui
from quadra.rebuild.releases import Asset, Release
from gi.repository import Adw, Gio, Gtk

saved, shown, terminals = [], [], []
application = Adw.Application(application_id="org.quadrahq.Quadra.RebuildTest",
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
application.register(None)


def walk(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from walk(child)
        child = child.get_next_sibling()


def capture(dialog, parent=None):
    shown.append(dialog)


def build(settings):
    with patch.object(core, "load_settings", return_value=dict(settings)):
        return ui.LauncherWindow(application)


def buttons_of(dialog):
    return [w for w in walk(dialog.get_extra_child()) if isinstance(w, Gtk.CheckButton)]


def complete(**missing):
    assets = {"appimage": Asset("a-x86_64.AppImage", "u"), "flatpak": Asset("f-x86_64.flatpak", "u"),
              "checksums": Asset("SHA256SUMS", "u")}
    assets.update(missing)
    return Release("v0.50.0-alpha.2", **assets)


def run_now(work, finished, catch=None):
    try:
        result, error = work(), None
    except catch or () as caught:
        result, error = None, caught
    finished(result) if catch is None else finished(result, error)


with patch.object(core, "save_settings", side_effect=lambda value: saved.append(dict(value))), \
        patch.object(Adw.AlertDialog, "present", capture), \
        patch.object(rebuild.flatpak, "available", return_value=True), \
        patch.object(ui, "_rebuild_in_background", run_now), \
        patch.object(rebuild.handoff, "open_in_terminal", side_effect=terminals.append):
    window = build(core.DEFAULT_SETTINGS)

    ui._rebuild_show_choices(window, complete())
    dialog = shown[-1]
    assert dialog.get_heading() == "Try the Rust version of Quadra?"
    assert "0.50.0-alpha.2" in dialog.get_body() and "Darling" not in dialog.get_body()
    appimage, flatpak, native = buttons_of(dialog)
    assert appimage.get_active() and not flatpak.get_active() and not native.get_active()
    assert all(button.get_sensitive() for button in (appimage, flatpak, native))
    flatpak.set_active(True)
    assert not appimage.get_active()

    dialog.emit("response", "never")
    assert window.settings["rust_rebuild_dismissed"] is True

    window.settings["rust_rebuild_dismissed"] = False
    ui._rebuild_show_choices(window, complete())
    before = time.time()
    shown[-1].emit("response", "later")
    snoozed = window.settings["rust_rebuild_snoozed_until"]
    assert before + rebuild.prompt.SNOOZE_SECONDS - 1 <= snoozed <= time.time() + rebuild.prompt.SNOOZE_SECONDS
    assert not rebuild.prompt.should_offer(window.settings, time.time(), in_flatpak=False)
    assert window.busy is None

    ui._rebuild_show_choices(window, complete(appimage=None))
    appimage, flatpak, native = buttons_of(shown[-1])
    assert not appimage.get_sensitive() and flatpak.get_sensitive() and flatpak.get_active()

    ui._rebuild_show_choices(window, complete(checksums=None))
    appimage, flatpak, native = buttons_of(shown[-1])
    assert not appimage.get_sensitive() and not flatpak.get_sensitive()
    assert native.get_sensitive() and native.get_active()

    with patch.object(rebuild.flatpak, "available", return_value=False):
        ui._rebuild_show_choices(window, complete())
    appimage, flatpak, native = buttons_of(shown[-1])
    assert appimage.get_active() and not flatpak.get_sensitive()

    darling = build({**core.DEFAULT_SETTINGS, "runtime_backend": "darling"})
    ui._rebuild_show_choices(darling, complete())
    assert "Darling" in shown[-1].get_body()

    shown.clear()
    with patch.object(rebuild.native, "problems", return_value=["git is not installed."]):
        ui._rebuild_show_choices(window, complete())
        dialog = shown[-1]
        buttons_of(dialog)[2].set_active(True)
        dialog.emit("response", "continue")
    assert terminals == [] and window.busy is None
    assert shown[-1].get_heading() == "Could not move to the Rust version"

    script_release = complete()
    with patch.object(rebuild.native, "problems", return_value=[]), \
            patch.object(rebuild.native, "prepare", return_value=Path("/tmp/build.sh")) as prepare:
        ui._rebuild_show_choices(window, script_release)
        dialog = shown[-1]
        buttons_of(dialog)[2].set_active(True)
        dialog.emit("response", "continue")
    assert terminals == [Path("/tmp/build.sh")] and window.busy is None
    assert prepare.call_args.args[0] is script_release

    window.session = object()
    ui._rebuild_show_choices(window, complete())
    shown[-1].emit("response", "continue")
    assert terminals == [Path("/tmp/build.sh")]
    window.session = None

print("rebuild dialog UI checks passed")
