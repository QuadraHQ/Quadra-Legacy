import shlex
import subprocess

from .. import core, terminal
from ..i18n import _
from .errors import RebuildError

__all__ = ["open_in_terminal", "start_after_exit", "write_script"]

FRAME = """#!/usr/bin/env bash
set -u
stop_quadra() {
    kill -TERM "$old_pid" 2>/dev/null
    while kill -0 "$old_pid" 2>/dev/null; do sleep 0.5; done
}
fail() {
    printf '\\n%s\\nQuadra has not been changed.\\n\\n' "$1"
    read -r -p "Press Enter to close this window. " answer
    exit 1
}
"""
WAIT_THEN_START = 'while kill -0 "$0" 2>/dev/null; do sleep 0.5; done; exec "$@"'


def write_script(name, old_pid, variables, body):
    header = "".join(
        f"{variable}={shlex.quote(str(value))}\n"
        for variable, value in {"old_pid": old_pid, **variables}.items()
    )
    path = core.CACHE_DIR / "rust-rebuild" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{header}{FRAME}{body}")
    path.chmod(0o700)
    return path


def open_in_terminal(script):
    argv = terminal.command(["bash", str(script)])
    if argv is None:
        raise RebuildError(
            _(
                "No terminal application was found. Install one (for example xterm), "
                "or set the TERMINAL environment variable to your terminal's command, "
                "then try again."
            )
        )
    try:
        subprocess.Popen(argv, start_new_session=True)
    except OSError as error:
        raise RebuildError(
            _("Could not open a terminal: {error}", error=error)
        ) from error


def start_after_exit(argv, old_pid):
    subprocess.Popen(
        ["sh", "-c", WAIT_THEN_START, str(old_pid), *map(str, argv)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
