#!/usr/bin/env bash
# Run the end-to-end smoke test inside a private, headless GNOME Shell
# (its own D-Bus session, Wayland display and throwaway home folder), so
# nothing appears on screen and your recent files and settings are untouched.
#   tests/smoke.sh [OUTDIR]       screenshots land in OUTDIR
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="$(realpath -m "${1:-$(mktemp -d)}")"
mkdir -p "$OUT"

RT="${XDG_DATA_HOME:-$HOME/.local/share}/aceoffice/runtime"
if [ -z "${ACEOFFICE_LO_PATH:-}" ] && [ ! -e /usr/lib/libreoffice/program/libmergedlo.so ]; then
    export ACEOFFICE_LO_PATH="$RT/usr/lib/libreoffice/program"
    export LD_LIBRARY_PATH="$ACEOFFICE_LO_PATH:$RT/usr/lib/x86_64-linux-gnu"
fi

FAKE_HOME="$(mktemp -d)"
trap 'rm -rf "$FAKE_HOME"' EXIT
mkdir -p "$FAKE_HOME/Documents" "$FAKE_HOME/.config"
# SMOKE_THEME=1: render with your own GTK 4 theme (e.g. WhiteSur in ~/.config/gtk-4.0).
if [ -n "${SMOKE_THEME:-}" ] && [ -d "$HOME/.config/gtk-4.0" ]; then
    cp -rL "$HOME/.config/gtk-4.0" "$FAKE_HOME/.config/gtk-4.0"
fi
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
    WAYLAND_DISPLAY=aceoffice-smoke GDK_BACKEND=wayland \
        timeout 180 python3 "${SMOKE_SCRIPT:-tests/smoke.py}" "$OUT"
'
