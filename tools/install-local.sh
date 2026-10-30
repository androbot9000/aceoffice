#!/usr/bin/env bash
# Add AceOffice (from this checkout) to your app grid. Undo with: tools/install-local.sh --uninstall
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
ID=io.github.androbot9000.AceOffice
if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$APPS/$ID.desktop" "$ICONS/$ID.svg"
    echo "Removed AceOffice from the app grid."
    exit 0
fi
mkdir -p "$APPS" "$ICONS"
sed "s#@EXEC@#$ROOT/run.sh#" "$ROOT/data/$ID.desktop.in" > "$APPS/$ID.desktop"
cp "$ROOT/data/$ID.svg" "$ICONS/$ID.svg"
update-desktop-database "$APPS" 2>/dev/null || true
echo "AceOffice is in your app grid. It runs from $ROOT."
