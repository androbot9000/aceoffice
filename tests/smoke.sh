#!/usr/bin/env bash
# Run the end-to-end smoke test inside a private, headless GNOME Shell
# (its own D-Bus session, Wayland display and throwaway home folder), so
# nothing appears on screen and your recent files and settings are untouched.
#   tests/smoke.sh [OUTDIR]       screenshots land in OUTDIR
#   SMOKE_FLATPAK=1 tests/smoke.sh   test the installed Flatpak instead of this checkout
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="$(realpath -m "${1:-$(mktemp -d)}")"
mkdir -p "$OUT"

OFFICIAL="${XDG_DATA_HOME:-$HOME/.local/share}/aceoffice/runtime-official/program"
RT="${XDG_DATA_HOME:-$HOME/.local/share}/aceoffice/runtime"
if [ -z "${ACEOFFICE_LO_PATH:-}" ] && [ -d "$OFFICIAL" ]; then
    export ACEOFFICE_LO_PATH="$OFFICIAL"
elif [ -z "${ACEOFFICE_LO_PATH:-}" ] && [ ! -e /usr/lib/libreoffice/program/libmergedlo.so ]; then
    export ACEOFFICE_LO_PATH="$RT/usr/lib/libreoffice/program"
    export LD_LIBRARY_PATH="$ACEOFFICE_LO_PATH:$RT/usr/lib/x86_64-linux-gnu"
fi

FAKE_HOME="$(mktemp -d)"
# A private runtime folder too: the test session starts its own portals, and one sharing
# /run/user/UID would mount over (and, on exit, unmount) your desktop's document portal,
# after which no Flatpak app starts until you log in again.
RUN_DIR="$(mktemp -d)"
chmod 700 "$RUN_DIR"
trap 'fusermount3 -u "$RUN_DIR/doc" 2>/dev/null; rm -rf "$FAKE_HOME" "$RUN_DIR"' EXIT
export XDG_RUNTIME_DIR="$RUN_DIR"
mkdir -p "$FAKE_HOME/Documents" "$FAKE_HOME/.config"
# SMOKE_THEME=1: render with your own GTK 4 theme (e.g. WhiteSur in ~/.config/gtk-4.0).
if [ -n "${SMOKE_THEME:-}" ] && [ -d "$HOME/.config/gtk-4.0" ]; then
    cp -rL "$HOME/.config/gtk-4.0" "$FAKE_HOME/.config/gtk-4.0"
fi
# Flatpak finds per-user installs under $HOME; keep pointing it at the real one.
export FLATPAK_USER_DIR="${FLATPAK_USER_DIR:-$HOME/.local/share/flatpak}"
export OUT HOME="$FAKE_HOME" XDG_DATA_HOME="$FAKE_HOME/.local/share" \
       XDG_CONFIG_HOME="$FAKE_HOME/.config" XDG_CACHE_HOME="$FAKE_HOME/.cache"
export PYTHONPATH="$PWD"

dbus-run-session -- bash -c '
    gnome-shell --headless --wayland --no-x11 --virtual-monitor 1280x860 \
        --wayland-display aceoffice-smoke >"$OUT/shell.log" 2>&1 &
    SHELL_PID=$!
    trap "kill $SHELL_PID 2>/dev/null" EXIT
    for _ in $(seq 50); do [ -S "$XDG_RUNTIME_DIR/aceoffice-smoke" ] && break; sleep 0.2; done
    sleep 1  # the socket appears a moment before the compositor accepts clients
    export WAYLAND_DISPLAY=aceoffice-smoke GDK_BACKEND=wayland
    if [ -n "${SMOKE_FLATPAK:-}" ]; then
        # The installed Flatpak: its own Python, GTK and LibreOffice, running the test from here.
        timeout 240 flatpak run --command=python3 --filesystem="$PWD" --filesystem="$OUT" \
            --filesystem="$HOME" --env=HOME="$HOME" --env=PYTHONPATH="$PWD" \
            --env=XDG_DATA_HOME="$XDG_DATA_HOME" --env=XDG_CONFIG_HOME="$XDG_CONFIG_HOME" \
            --env=XDG_CACHE_HOME="$XDG_CACHE_HOME" --env=ACEOFFICE_LO_PATH=/app/libreoffice/program \
            io.github.androbot9000.AceOffice "${SMOKE_SCRIPT:-tests/smoke.py}" "$OUT"
    else
        timeout 180 python3 "${SMOKE_SCRIPT:-tests/smoke.py}" "$OUT"
    fi
'
