#!/usr/bin/env bash
set -euo pipefail

INSTALLER_URL=${QUADRA_INSTALLER_URL:-https://raw.githubusercontent.com/QuadraHQ/quadra-rewrite/main/install.sh}

main() {
    command -v curl >/dev/null 2>&1 || {
        printf 'error: curl is needed.\n' >&2
        exit 1
    }
    local installer
    installer=$(curl -fsSL "$INSTALLER_URL") || {
        printf 'error: could not download the installer from %s\n' "$INSTALLER_URL" >&2
        exit 1
    }
    [ -n "$installer" ] || {
        printf 'error: the installer at %s was empty.\n' "$INSTALLER_URL" >&2
        exit 1
    }
    exec bash -c "$installer" quadra-install "$@"
}

main "$@"
exit
