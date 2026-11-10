# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Keep unsaved work safe: a copy of every document with unsaved changes is written
to ~/.cache/aceoffice/recovery shortly after you pause, and removed when you save or
close it. If AceOffice (or the computer) stops unexpectedly, the next start offers
those copies back.
"""

import json
import os
import time
import uuid

from gi.repository import GLib

INTERVAL = 20            # seconds between checks
FORMAT = {"text": "odt", "spreadsheet": "ods", "presentation": "odp"}   # LibreOffice's own: nothing is lost


def folder():
    path = os.path.join(GLib.get_user_cache_dir(), "aceoffice", "recovery")
    os.makedirs(path, exist_ok=True)
    return path


class Keeper:
    """One per open document."""

    def __init__(self, win):
        self.win = win
        self.stem = os.path.join(folder(), uuid.uuid4().hex)
        self.stale = False           # edited since the last copy
        self._source = GLib.timeout_add_seconds(INTERVAL, self._tick)

    def touched(self):
        self.stale = True

    def _tick(self):
        if not self.win.doc:
            self._source = 0
            return False
        if self.stale and self.win.modified:
            self.write()
        return True

    def write(self):
        win = self.win
        ext = FORMAT[win.kind]
        try:
            if win.notes:
                win.notes.commit(wait=True)
            win.doc.export(f"{self.stem}.part.{ext}", ext)
            os.replace(f"{self.stem}.part.{ext}", f"{self.stem}.{ext}")
            with open(self.stem + ".json", "w", encoding="utf-8") as f:
                json.dump({"file": f"{self.stem}.{ext}", "original": win.path, "name": win._display_name(),
                           "kind": win.kind, "saved": time.time(), "pid": os.getpid()}, f)
            self.stale = False
        except Exception:  # noqa: BLE001 - recovery must never get in the way of editing
            pass

    def clear(self):
        """The document was saved or closed on purpose."""
        self.stale = False
        for name in (self.stem + ".json", *(f"{self.stem}.{e}" for e in FORMAT.values())):
            try:
                os.unlink(name)
            except OSError:
                pass

    def stop(self):
        if self._source:
            GLib.source_remove(self._source)
            self._source = 0
        self.clear()


def pending():
    """Copies left by an AceOffice that didn't close its documents: [{file, original, name, …}]."""
    found = []
    for name in sorted(os.listdir(folder())):
        if not name.endswith(".json"):
            continue
        path = os.path.join(folder(), name)
        try:
            with open(path, encoding="utf-8") as f:
                entry = json.load(f)
        except (OSError, ValueError):
            continue
        if entry.get("pid") == os.getpid() or not os.path.exists(entry.get("file", "")):
            continue
        entry["json"] = path
        found.append(entry)
    return found


def discard(entries):
    for entry in entries:
        for path in (entry.get("json"), entry.get("file")):
            try:
                os.unlink(path)
            except (OSError, TypeError):
                pass
