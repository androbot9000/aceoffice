# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""ctypes bindings for the subset of LibreOfficeKit that AceOffice uses.

The struct layouts mirror LibreOfficeKit.h. LibreOffice only ever appends
members to these vtables, so declaring a prefix of them is ABI-safe; we stop
at the last function we call.
"""

import ctypes
import os
from ctypes import (CFUNCTYPE, POINTER, Structure, c_bool, c_char_p, c_int,
                    c_long, c_size_t, c_ubyte, c_uint, c_ulonglong, c_void_p)

# --- enums (LibreOfficeKitEnums.h) -----------------------------------------

DOCTYPE_TEXT, DOCTYPE_SPREADSHEET, DOCTYPE_PRESENTATION, DOCTYPE_DRAWING, DOCTYPE_OTHER = range(5)

KEYEVENT_KEYINPUT, KEYEVENT_KEYUP = 0, 1
MOUSEEVENT_DOWN, MOUSEEVENT_UP, MOUSEEVENT_MOVE = 0, 1, 2
SETTEXTSELECTION_START, SETTEXTSELECTION_END, SETTEXTSELECTION_RESET = 0, 1, 2

MOUSE_LEFT, MOUSE_MIDDLE, MOUSE_RIGHT = 1, 2, 4

CALLBACK_INVALIDATE_TILES = 0
CALLBACK_INVALIDATE_VISIBLE_CURSOR = 1
CALLBACK_TEXT_SELECTION = 2
CALLBACK_CURSOR_VISIBLE = 5
CALLBACK_GRAPHIC_SELECTION = 6
CALLBACK_STATE_CHANGED = 8
CALLBACK_SEARCH_NOT_FOUND = 12
CALLBACK_DOCUMENT_SIZE_CHANGED = 13
CALLBACK_SET_PART = 14
CALLBACK_CELL_CURSOR = 17
CALLBACK_MOUSE_POINTER = 18
CALLBACK_CELL_FORMULA = 19
CALLBACK_INVALIDATE_HEADER = 33
CALLBACK_CELL_ADDRESS = 34

FEATURE_DOCUMENT_PASSWORD = 1 << 0
FEATURE_PART_IN_INVALIDATION_CALLBACK = 1 << 2
FEATURE_NO_TILED_ANNOTATIONS = 1 << 3

TWIPS_PER_INCH = 1440

# --- structs ----------------------------------------------------------------

LibreOfficeKitCallback = CFUNCTYPE(None, c_int, c_char_p, c_void_p)


class _Office(Structure):
    pass


class _OfficeClass(Structure):
    pass


class _Document(Structure):
    pass


class _DocumentClass(Structure):
    pass


_Office._fields_ = [("pClass", POINTER(_OfficeClass))]
_Document._fields_ = [("pClass", POINTER(_DocumentClass))]

_P = POINTER(_Office)
_D = POINTER(_Document)

_OfficeClass._fields_ = [
    ("nSize", c_size_t),
    ("destroy", CFUNCTYPE(None, _P)),
    ("documentLoad", CFUNCTYPE(_D, _P, c_char_p)),
    ("getError", CFUNCTYPE(c_void_p, _P)),
    ("documentLoadWithOptions", CFUNCTYPE(_D, _P, c_char_p, c_char_p)),
    ("freeError", CFUNCTYPE(None, c_void_p)),
    ("registerCallback", CFUNCTYPE(None, _P, LibreOfficeKitCallback, c_void_p)),
    ("getFilterTypes", CFUNCTYPE(c_void_p, _P)),
    ("setOptionalFeatures", CFUNCTYPE(None, _P, c_ulonglong)),
    ("setDocumentPassword", CFUNCTYPE(None, _P, c_char_p, c_char_p)),
    ("getVersionInfo", CFUNCTYPE(c_void_p, _P)),
]

_DocumentClass._fields_ = [
    ("nSize", c_size_t),
    ("destroy", CFUNCTYPE(None, _D)),
    ("saveAs", CFUNCTYPE(c_int, _D, c_char_p, c_char_p, c_char_p)),
    ("getDocumentType", CFUNCTYPE(c_int, _D)),
    ("getParts", CFUNCTYPE(c_int, _D)),
    ("getPartPageRectangles", CFUNCTYPE(c_void_p, _D)),
    ("getPart", CFUNCTYPE(c_int, _D)),
    ("setPart", CFUNCTYPE(None, _D, c_int)),
    ("getPartName", CFUNCTYPE(c_void_p, _D, c_int)),
    ("setPartMode", CFUNCTYPE(None, _D, c_int)),
    ("paintTile", CFUNCTYPE(None, _D, POINTER(c_ubyte), c_int, c_int, c_int, c_int, c_int, c_int)),
    ("getTileMode", CFUNCTYPE(c_int, _D)),
    ("getDocumentSize", CFUNCTYPE(None, _D, POINTER(c_long), POINTER(c_long))),
    ("initializeForRendering", CFUNCTYPE(None, _D, c_char_p)),
    ("registerCallback", CFUNCTYPE(None, _D, LibreOfficeKitCallback, c_void_p)),
    ("postKeyEvent", CFUNCTYPE(None, _D, c_int, c_int, c_int)),
    ("postMouseEvent", CFUNCTYPE(None, _D, c_int, c_int, c_int, c_int, c_int, c_int)),
    ("postUnoCommand", CFUNCTYPE(None, _D, c_char_p, c_char_p, c_bool)),
    ("setTextSelection", CFUNCTYPE(None, _D, c_int, c_int, c_int)),
    ("getTextSelection", CFUNCTYPE(c_void_p, _D, c_char_p, POINTER(c_char_p))),
    ("paste", CFUNCTYPE(c_bool, _D, c_char_p, c_char_p, c_size_t)),
    ("setGraphicSelection", CFUNCTYPE(None, _D, c_int, c_int, c_int)),
    ("resetSelection", CFUNCTYPE(None, _D)),
    ("getCommandValues", CFUNCTYPE(c_void_p, _D, c_char_p)),
    ("setClientZoom", CFUNCTYPE(None, _D, c_int, c_int, c_int, c_int)),
    ("setClientVisibleArea", CFUNCTYPE(None, _D, c_int, c_int, c_int, c_int)),
    ("createView", CFUNCTYPE(c_int, _D)),
    ("destroyView", CFUNCTYPE(None, _D, c_int)),
    ("setView", CFUNCTYPE(None, _D, c_int)),
    ("getView", CFUNCTYPE(c_int, _D)),
    ("getViewsCount", CFUNCTYPE(c_int, _D)),
    ("renderFont", CFUNCTYPE(c_void_p, _D, c_char_p, c_char_p, POINTER(c_int), POINTER(c_int))),
    ("getPartHash", CFUNCTYPE(c_void_p, _D, c_int)),
    ("paintPartTile", CFUNCTYPE(None, _D, POINTER(c_ubyte), c_int, c_int, c_int, c_int, c_int, c_int, c_int, c_int)),
]

_libc = ctypes.CDLL(None)
_libc.free.argtypes = [c_void_p]


def _take_string(ptr):
    """Copy a malloc'd C string returned by LOK into Python and free it."""
    if not ptr:
        return None
    try:
        return ctypes.string_at(ptr).decode("utf-8", "replace")
    finally:
        _libc.free(ptr)


# --- locating LibreOffice ---------------------------------------------------

SEARCH_PATHS = [
    "/usr/lib/libreoffice/program",
    "/usr/lib64/libreoffice/program",
    "/opt/libreoffice/program",
    "/app/libreoffice/program",          # Flatpak
    "/snap/libreoffice/current/lib/libreoffice/program",
]


def find_install():
    env = os.environ.get("ACEOFFICE_LO_PATH")
    candidates = [env] if env else []
    candidates += SEARCH_PATHS
    for path in candidates:
        if path and (os.path.exists(os.path.join(path, "libmergedlo.so"))
                     or os.path.exists(os.path.join(path, "libsofficeapp.so"))):
            return path
    return None


class LOKError(RuntimeError):
    pass


def _point_liblangtag_at_runtime(install):
    """An unpacked runtime (tools/dev-runtime.sh) keeps liblangtag's data under its
    own usr/share, but the library only looks in /usr/share unless told otherwise."""
    datadir = os.path.normpath(os.path.join(install, "..", "..", "..", "share", "liblangtag"))
    if datadir == "/usr/share/liblangtag" or not os.path.isdir(datadir):
        return
    try:
        langtag = ctypes.CDLL("liblangtag.so.1")
    except OSError:
        return
    langtag.lt_db_set_datadir.argtypes = [c_char_p]
    langtag.lt_db_set_datadir(datadir.encode())


# --- wrappers ---------------------------------------------------------------

class Office:
    """One LibreOfficeKit instance per process (LOK cannot be re-initialised)."""

    _instance = None

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        install = find_install()
        if not install:
            raise LOKError("LibreOffice was not found. Install it with:\n"
                           "  sudo apt install libreoffice-writer libreoffice-calc libreoffice-impress\n"
                           "or set ACEOFFICE_LO_PATH to a LibreOffice 'program' directory.")
        lib = None
        for name in ("libsofficeapp.so", "libmergedlo.so"):
            p = os.path.join(install, name)
            if os.path.exists(p):
                lib = ctypes.CDLL(p, mode=ctypes.RTLD_GLOBAL)
                break
        _point_liblangtag_at_runtime(install)
        # LibreOfficeKit turns spelling and hyphenation off unless languages are listed.
        lang = (os.environ.get("LANG") or "en_US").split(".")[0]
        os.environ.setdefault("LOK_ALLOWLIST_LANGUAGES", " ".join(dict.fromkeys([lang, "en_US"])))
        hook = lib.libreofficekit_hook_2
        hook.restype = _P
        hook.argtypes = [c_char_p, c_char_p]

        profile = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                               "aceoffice", "lo-profile")
        os.makedirs(profile, exist_ok=True)
        self._p = hook(install.encode(), ("file://" + profile).encode())
        if not self._p:
            raise LOKError(f"LibreOfficeKit failed to start from {install}")
        self._c = self._p.contents.pClass.contents
        # Without PART_IN_INVALIDATION_CALLBACK, LibreOffice never reports changed tiles.
        self._c.setOptionalFeatures(self._p, FEATURE_NO_TILED_ANNOTATIONS | FEATURE_PART_IN_INVALIDATION_CALLBACK)
        self.install_path = install

    def version(self):
        return _take_string(self._c.getVersionInfo(self._p))

    def error(self):
        return _take_string(self._c.getError(self._p))

    def load(self, path):
        url = "file://" + os.path.abspath(path)
        d = self._c.documentLoadWithOptions(self._p, url.encode(), b"Language=en-US")
        if not d:
            raise LOKError(self.error() or f"Could not open {path}")
        return Document(d, path)

    def new(self, kind):
        """Create a blank document. kind is 'text', 'spreadsheet' or 'presentation'."""
        factory = {"text": "swriter", "spreadsheet": "scalc", "presentation": "simpress"}[kind]
        d = self._c.documentLoadWithOptions(self._p, f"private:factory/{factory}".encode(),
                                            b"Language=en-US")
        if not d:
            raise LOKError(self.error() or f"Could not create a {kind} document")
        return Document(d, None)


class Document:
    def __init__(self, d, path):
        self._d = d
        self._c = d.contents.pClass.contents
        self.path = path
        self._cb = None  # keep the ctypes callback alive

    # lifecycle / info
    def initialize_for_rendering(self):
        self._c.initializeForRendering(self._d, b"{}")

    def doc_type(self):
        return self._c.getDocumentType(self._d)

    def size_twips(self):
        w, h = c_long(), c_long()
        self._c.getDocumentSize(self._d, ctypes.byref(w), ctypes.byref(h))
        return w.value, h.value

    def parts(self):
        return self._c.getParts(self._d)

    def part(self):
        return self._c.getPart(self._d)

    def set_part(self, n):
        self._c.setPart(self._d, n)

    def part_name(self, n):
        return _take_string(self._c.getPartName(self._d, n))

    def save_as(self, path, fmt=None, options=None):
        url = "file://" + os.path.abspath(path)
        ok = self._c.saveAs(self._d, url.encode(),
                            fmt.encode() if fmt else None,
                            options.encode() if options else None)
        if not ok:
            raise LOKError(Office.get().error() or f"Could not save {path}")
        self.path = path

    def destroy(self):
        if self._d:
            self._c.destroy(self._d)
            self._d = None

    # rendering
    def paint_tile(self, px_w, px_h, tw_x, tw_y, tw_w, tw_h):
        """Render a region (in twips) into a px_w x px_h BGRA premultiplied buffer."""
        buf = (c_ubyte * (px_w * px_h * 4))()
        self._c.paintTile(self._d, buf, px_w, px_h, tw_x, tw_y, tw_w, tw_h)
        return buf

    def set_client_zoom(self, tile_px, tile_twips):
        self._c.setClientZoom(self._d, tile_px, tile_px, tile_twips, tile_twips)

    def set_visible_area(self, x, y, w, h):
        self._c.setClientVisibleArea(self._d, x, y, w, h)

    # input
    def register_callback(self, fn):
        def tramp(kind, payload, _data):
            fn(kind, payload.decode("utf-8", "replace") if payload else "")
        self._cb = LibreOfficeKitCallback(tramp)
        self._c.registerCallback(self._d, self._cb, None)

    def key(self, kind, char_code, key_code):
        self._c.postKeyEvent(self._d, kind, char_code, key_code)

    def mouse(self, kind, x, y, count=1, buttons=MOUSE_LEFT, modifier=0):
        self._c.postMouseEvent(self._d, kind, x, y, count, buttons, modifier)

    def uno(self, command, args=None, notify=False):
        self._c.postUnoCommand(self._d, command.encode(),
                               args.encode() if args else None, notify)

    def selected_text(self, mime="text/plain;charset=utf-8"):
        used = c_char_p()
        return _take_string(self._c.getTextSelection(self._d, mime.encode(), ctypes.byref(used)))

    def paste(self, text, mime="text/plain;charset=utf-8"):
        data = text.encode("utf-8")
        return self._c.paste(self._d, mime.encode(), data, len(data))

    def command_values(self, command):
        return _take_string(self._c.getCommandValues(self._d, command.encode()))
