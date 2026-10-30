#!/usr/bin/env bash
# Run AceOffice from a source checkout.
set -euo pipefail
cd "$(dirname "$0")"

RT="${XDG_DATA_HOME:-$HOME/.local/share}/aceoffice/runtime"
if [ -z "${ACEOFFICE_LO_PATH:-}" ] && [ ! -e /usr/lib/libreoffice/program/libmergedlo.so ] \
   && [ -d "$RT/usr/lib/libreoffice/program" ]; then
    export ACEOFFICE_LO_PATH="$RT/usr/lib/libreoffice/program"
    export LD_LIBRARY_PATH="$ACEOFFICE_LO_PATH:$RT/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
exec python3 -m aceoffice "$@"
