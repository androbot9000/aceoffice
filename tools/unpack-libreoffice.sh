#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Unpack The Document Foundation's LibreOffice (the Linux "deb" tarball from
# libreoffice.org) into DEST, keeping only what AceOffice uses: writer, calc,
# impress and draw, filters, fonts and English dictionaries. DEST/program is
# then a LibreOffice "program" directory for ACEOFFICE_LO_PATH.
#
#   tools/unpack-libreoffice.sh LibreOffice_26.2.7_Linux_x86-64_deb.tar.gz DEST
#
# Needs only ar and tar, so it also runs inside flatpak-builder (see flatpak/).
# Why TDF's build: Ubuntu's LibreOffice paints slides blank through
# LibreOfficeKit (issue #1); TDF's renders them.
set -euo pipefail

TARBALL="$(realpath "$1")"
DEST="$(realpath -m "$2")"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Package name stems (after "libobasisNN.N-" or "libreofficeNN.N-") to keep.
KEEP='^(core|ure|writer|calc|impress|draw|math|graphicfilter|images|en-us|ooofonts|ooolinguistic|libreofficekit-data|xsltfilter|extension-pdf-import|dict-en|)$'

tar -xzf "$TARBALL" -C "$WORK"
mkdir -p "$WORK/root"
n=0
for deb in "$WORK"/*/DEBS/*.deb; do
    name="$(basename "$deb")"
    stem="$(sed -E 's/^(libobasis|libreoffice)[0-9.]+-?//; s/_.*$//' <<<"$name")"
    [[ "$stem" =~ $KEEP ]] || continue
    member="$(ar t "$deb" | grep '^data\.tar')"
    (cd "$WORK" && ar x "$deb" "$member")
    tar -xf "$WORK/$member" -C "$WORK/root"
    rm -f "$WORK/$member"
    n=$((n + 1))
done

src="$(ls -d "$WORK"/root/opt/libreoffice*/ | head -n1)"
rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
mv "$src" "$DEST"
echo "Unpacked $n packages of $(basename "$TARBALL") into $DEST"
