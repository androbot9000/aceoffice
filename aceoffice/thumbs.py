# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Page thumbnails for the document manager and the template chooser.

LibreOffice renders the first page (or the top of the first sheet) on a worker
thread; the PNG is cached under ~/.cache/aceoffice/thumbnails, keyed by the
file's path, size and modification time, so each file is rendered once.
"""

import hashlib
import os
import queue
import threading

from gi.repository import Gdk, GLib

from . import lok

WIDTH = 360          # pixels; shown at half size, so it stays sharp on HiDPI screens
_queue = queue.Queue()
_waiting = {}        # cache path -> [callbacks]
_lock = threading.Lock()
_worker = None


def cache_dir():
    return os.path.join(GLib.get_user_cache_dir(), "aceoffice", "thumbnails")


def cache_path(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = f"{os.path.abspath(path)}\0{st.st_size}\0{st.st_mtime_ns}".encode()
    return os.path.join(cache_dir(), hashlib.sha1(key).hexdigest() + ".png")


def request(office, path, callback):
    """Call callback(png_path or None) on the main loop once a thumbnail of path exists."""
    out = cache_path(path)
    if out is None:
        GLib.idle_add(callback, None)
        return
    if os.path.exists(out):
        GLib.idle_add(callback, out)
        return
    with _lock:
        if out in _waiting:
            _waiting[out].append(callback)
            return
        _waiting[out] = [callback]
    _queue.put((office, path, out))
    _ensure_worker()


def _ensure_worker():
    global _worker
    with _lock:
        if _worker is None:
            _worker = threading.Thread(target=_work, name="aceoffice-thumbnails", daemon=True)
            _worker.start()


def _work():
    while True:
        office, path, out = _queue.get()
        try:
            ok = render(office, path, out)
        except Exception:  # noqa: BLE001 - a file we can't render just gets an icon
            ok = False
        with _lock:
            callbacks = _waiting.pop(out, [])
        for cb in callbacks:
            GLib.idle_add(cb, out if ok else None)


def _first_page(doc):
    """The region to render, in twips: Writer's first page, or the top-left of a sheet."""
    kind = doc.doc_type()
    w, h = doc.size_twips()
    if kind == lok.DOCTYPE_TEXT:
        rects = doc.page_rectangles()
        if rects:
            return rects[0]
        return 0, 0, w, min(h, int(w * 11 / 8.5))
    if kind == lok.DOCTYPE_SPREADSHEET:
        rw = 10200                       # about seven columns
        return 0, 0, rw, int(rw * 0.75)
    return 0, 0, w, h


def render(office, path, out):
    doc = office.load(path)
    try:
        doc.initialize_for_rendering()
        if doc.doc_type() == lok.DOCTYPE_SPREADSHEET and doc.part() != 0:
            doc.set_part(0)              # files remember the sheet they were saved on
        x, y, tw, th = _first_page(doc)
        if tw <= 0 or th <= 0:
            return False
        pw = WIDTH
        ph = max(1, round(WIDTH * th / tw))
        buf = doc.paint_tile(pw, ph, x, y, tw, th)
    finally:
        doc.destroy()
    if not any(bytes(buf)[3::4][:: max(1, pw * ph // 4096)]):
        return False                     # fully transparent: nothing rendered
    texture = Gdk.MemoryTexture.new(pw, ph, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED,
                                    GLib.Bytes.new(bytes(buf)), pw * 4)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".part"
    texture.save_to_png(tmp)
    os.replace(tmp, out)
    return True
