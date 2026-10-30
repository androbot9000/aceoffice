#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Unpack LibreOffice from the distro archive into ~/.local/share/aceoffice/runtime
# without root, for developing AceOffice on a machine without LibreOffice installed.
# Debian/Ubuntu only. If you can, just: sudo apt install libreoffice-writer libreoffice-calc libreoffice-impress
set -euo pipefail

DEST="${XDG_DATA_HOME:-$HOME/.local/share}/aceoffice/runtime"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PKGS=(libreoffice-core libreoffice-common libreoffice-writer libreoffice-calc
      libreoffice-impress libreoffice-base-core libreoffice-style-colibre
      ure uno-libs-private)

cd "$WORK"
echo "Downloading LibreOffice packages…"
# Everything LibreOffice needs that this system doesn't already have, minus
# alternative toolkits (Qt, KF6, GTK2, Xfce) that LibreOfficeKit never loads.
deps=$(apt-cache depends --recurse --no-recommends --no-suggests --no-conflicts \
         --no-breaks --no-replaces --no-enhances "${PKGS[@]}" 2>/dev/null \
       | grep -v '^[ <]' | sort -u \
       | grep -E '^(lib|libreoffice-|ure$|uno-|fonts-opensymbol$)' \
       | grep -vE 'qt6|kf6|gtk2|xfce|xfconf|fltk|heif|libopengl|libts0|xcb-cursor|debian-installer|textwrap' \
       | while read -r p; do
           dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed' || echo "$p"
         done)
apt-get download $deps >/dev/null

rm -rf "$DEST"; mkdir -p "$DEST"
for f in *.deb; do dpkg -x "$f" "$DEST"; done

# Debian packaging links some files into /etc and /var; point them inside the runtime.
find "$DEST" -xtype l -lname '/*' | while read -r link; do
    target="$(readlink "$link")"
    if [ -e "$DEST$target" ]; then ln -sfn "$DEST$target" "$link"; else rm -f "$link"; fi
done

# The registry's main.xcd is normally linked into place by a postinst trigger.
ln -sfn ../.registry/main.xcd "$DEST/usr/lib/libreoffice/share/registry/main.xcd"

P="$DEST/usr/lib/libreoffice/program"
missing=$(LD_LIBRARY_PATH="$P:$DEST/usr/lib/x86_64-linux-gnu" \
          bash -c 'for so in "$0"/*.so; do ldd "$so" 2>/dev/null; done' "$P" | grep 'not found' | sort -u || true)
if [ -n "$missing" ]; then
    echo "Warning: some libraries are still missing:"; echo "$missing"
fi
echo "LibreOffice runtime ready in $DEST"
echo "Run AceOffice with:  ./run.sh"
