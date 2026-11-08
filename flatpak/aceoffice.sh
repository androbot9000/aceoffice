#!/bin/sh
# Launcher inside the Flatpak: AceOffice's code is in /app/share/aceoffice and its
# LibreOffice in /app/libreoffice (found by aceoffice/lok.py).
export PYTHONPATH=/app/share/aceoffice
export ACEOFFICE_LO_PATH=/app/libreoffice/program
exec python3 -m aceoffice "$@"
