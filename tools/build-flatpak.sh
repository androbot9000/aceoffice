#!/usr/bin/env bash
# Build the AceOffice Flatpak and install it for you (no root needed once flatpak and
# flatpak-builder are installed: sudo apt install flatpak flatpak-builder).
#   tools/build-flatpak.sh            build and install for this user
#   tools/build-flatpak.sh --bundle   also write aceoffice.flatpak, a single file to copy elsewhere
set -euo pipefail
cd "$(dirname "$0")/.."
MANIFEST=flatpak/io.github.androbot9000.AceOffice.yml
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user --noninteractive flathub org.gnome.Platform//50 org.gnome.Sdk//50
flatpak-builder --user --install --force-clean --repo=build/repo build/app "$MANIFEST"
if [ "${1:-}" = "--bundle" ]; then
    flatpak build-bundle build/repo aceoffice.flatpak io.github.androbot9000.AceOffice
    echo "Wrote aceoffice.flatpak"
fi
echo "Installed. Run it from the app grid, or: flatpak run io.github.androbot9000.AceOffice"
