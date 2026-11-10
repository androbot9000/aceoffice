# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""ctypes bindings for the subset of LibreOfficeKit that AceOffice uses.

The struct layouts mirror LibreOfficeKit.h. LibreOffice only ever appends
members to these vtables, so declaring a prefix of them is ABI-safe; we stop
at the last function we call.
"""

import ctypes
import json
import os
import threading
from ctypes import (CFUNCTYPE, POINTER, Structure, c_bool, c_char_p, c_double, c_int,
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
CALLBACK_CONTEXT_MENU = 23
CALLBACK_COMMENT = 32
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
    # Members AceOffice doesn't call are typed as plain pointers; they only hold places.
    ("getViewIds", c_void_p), ("setOutlineState", c_void_p), ("paintWindow", c_void_p),
    ("postWindow", c_void_p), ("postWindowKeyEvent", c_void_p), ("postWindowMouseEvent", c_void_p),
    ("setViewLanguage", c_void_p), ("postWindowExtTextInputEvent", c_void_p), ("getPartInfo", c_void_p),
    ("paintWindowDPI", c_void_p), ("insertCertificate", c_void_p), ("addCertificate", c_void_p),
    ("getSignatureState", c_void_p), ("renderShapeSelection", c_void_p), ("postWindowGestureEvent", c_void_p),
    ("createViewWithOptions", c_void_p), ("selectPart", c_void_p), ("moveSelectedParts", c_void_p),
    ("resizeWindow", c_void_p), ("getClipboard", c_void_p), ("setClipboard", c_void_p),
    ("getSelectionType", c_void_p), ("removeTextContext", c_void_p), ("sendDialogEvent", c_void_p),
    ("renderFontOrientation", c_void_p), ("paintWindowForView", c_void_p), ("completeFunction", c_void_p),
    ("setWindowTextSelection", c_void_p), ("sendFormFieldEvent", c_void_p), ("setBlockedCommandList", c_void_p),
    ("renderSearchResult", c_void_p), ("sendContentControlEvent", c_void_p),
    ("getSelectionTypeAndText", c_void_p), ("getDataArea", c_void_p), ("getEditMode", c_void_p),
    ("setViewTimezone", c_void_p), ("setAccessibilityState", c_void_p), ("getA11yFocusedParagraph", c_void_p),
    ("getA11yCaretPosition", c_void_p), ("setViewReadOnly", c_void_p), ("setAllowChangeComments", c_void_p),
    # LibreOffice 24.8+: the slideshow renderer (draws slides as a show does: no empty placeholders).
    ("getPresentationInfo", CFUNCTYPE(c_void_p, _D)),
    ("createSlideRenderer", CFUNCTYPE(c_bool, _D, c_char_p, c_int, POINTER(c_uint), POINTER(c_uint),
                                      c_bool, c_bool)),
    ("postSlideshowCleanup", CFUNCTYPE(None, _D)),
    ("renderNextSlideLayer", CFUNCTYPE(c_bool, _D, POINTER(c_ubyte), POINTER(c_bool), POINTER(c_double),
                                       POINTER(c_void_p))),
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


# Every document loads with these. LibreOffice 26.2.7 turns Basic off for LibreOfficeKit
# unless asked; AceOffice's own page-setup macros need it. Security level 3 ("very high")
# still refuses macros inside the documents themselves (none are in trusted locations).
LOAD_OPTIONS = b"Language=en-US,EnableMacrosExecution=true,MacroSecurityLevel=3"


def uno_args(**kwargs):
    """JSON arguments for postUnoCommand: uno_args(**{"FontHeight.Height": 12.0})."""
    out = {}
    for k, v in kwargs.items():
        t = ("boolean" if isinstance(v, bool) else "long" if isinstance(v, int)
             else "float" if isinstance(v, float) else "string")
        out[k] = {"type": t, "value": v}
    return json.dumps(out)


_MACRO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "macros")
_XML_HEAD = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE library:{kind} PUBLIC '
             '"-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "{dtd}">\n')
_LIB_NS = 'xmlns:library="http://openoffice.org/2000/library"'


def install_macros(profile):
    """Register AceOffice's Basic library (aceoffice/macros/*.bas) in its LibreOffice
    profile, so features LibreOfficeKit has no command for can run as macro:/// URLs."""
    from xml.sax.saxutils import escape
    basic = os.path.join(profile, "user", "basic")
    lib = os.path.join(basic, "AceOffice")
    os.makedirs(lib, exist_ok=True)
    modules = sorted(f[:-4] for f in os.listdir(_MACRO_DIR) if f.endswith(".bas"))
    for name in modules:
        with open(os.path.join(_MACRO_DIR, name + ".bas")) as f:
            code = f.read()
        with open(os.path.join(lib, name + ".xba"), "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE script:module PUBLIC '
                    '"-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">\n'
                    f'<script:module xmlns:script="http://openoffice.org/2000/script" script:name="{name}" '
                    f'script:language="StarBasic" script:moduleType="normal">{escape(code)}</script:module>\n')
    elements = "".join(f' <library:element library:name="{m}"/>\n' for m in modules)
    with open(os.path.join(lib, "script.xlb"), "w") as f:
        f.write(_XML_HEAD.format(kind="library", dtd="library.dtd")
                + f'<library:library {_LIB_NS} library:name="AceOffice" library:readonly="false" '
                  f'library:passwordprotected="false">\n{elements}</library:library>\n')
    with open(os.path.join(lib, "dialog.xlb"), "w") as f:
        f.write(_XML_HEAD.format(kind="library", dtd="library.dtd")
                + f'<library:library {_LIB_NS} library:name="AceOffice" library:readonly="false" '
                  'library:passwordprotected="false"/>\n')
    for index, xlb in (("script.xlc", "script.xlb"), ("dialog.xlc", "dialog.xlb")):
        path = os.path.join(basic, index)
        try:
            with open(path) as f:
                text = f.read()
        except OSError:
            text = (_XML_HEAD.format(kind="libraries", dtd="libraries.dtd")
                    + f'<library:libraries {_LIB_NS} xmlns:xlink="http://www.w3.org/1999/xlink">\n'
                      '</library:libraries>\n')
        if 'library:name="AceOffice"' in text:
            continue
        entry = (f' <library:library library:name="AceOffice" xlink:href="$(USER)/basic/AceOffice/{xlb}/" '
                 'xlink:type="simple" library:link="false"/>\n')
        with open(path, "w") as f:
            f.write(text.replace("</library:libraries>", entry + "</library:libraries>"))


def allow_basic(profile):
    """Undo the 'macros disabled' switch a load without EnableMacrosExecution writes into
    the profile (LibreOffice 26.2.7 and later); it would block AceOffice's own macros too."""
    import re
    path = os.path.join(profile, "user", "registrymodifications.xcu")
    try:
        with open(path) as f:
            text = f.read()
    except OSError:
        return
    cleaned = re.sub(r'<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
                     r'<prop oor:name="DisableMacrosExecution"[^>]*><value>true</value></prop></item>\n?',
                     "", text)
    if cleaned != text:
        with open(path, "w") as f:
            f.write(cleaned)


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
        install_macros(profile)
        allow_basic(profile)
        self._p = hook(install.encode(), ("file://" + profile).encode())
        if not self._p:
            raise LOKError(f"LibreOfficeKit failed to start from {install}")
        # A brand-new profile is created during startup, replacing the library list;
        # register again now (Basic loads the list lazily, on the first macro).
        install_macros(profile)
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
        with _VIEW_LOCK:
            d = self._c.documentLoadWithOptions(self._p, url.encode(), LOAD_OPTIONS)
        if not d:
            raise LOKError(self.error() or f"Could not open {path}")
        return Document(d, path)

    def new(self, kind):
        """Create a blank document. kind is 'text', 'spreadsheet' or 'presentation'."""
        factory = {"text": "swriter", "spreadsheet": "scalc", "presentation": "simpress"}[kind]
        with _VIEW_LOCK:
            d = self._c.documentLoadWithOptions(self._p, f"private:factory/{factory}".encode(), LOAD_OPTIONS)
        if not d:
            raise LOKError(self.error() or f"Could not create a {kind} document")
        return Document(d, None)


class Document:
    def __init__(self, d, path):
        self._d = d
        self._c = d.contents.pClass.contents
        self.path = path
        # Listen from the start and hold events until someone registers: LibreOffice
        # reports some state (e.g. gridlines) while the document is still loading.
        self._lock = threading.Lock()
        self._pending = []
        self._sink = None

        def tramp(kind, payload, _data):
            text = payload.decode("utf-8", "replace") if payload else ""
            with self._lock:
                sink = self._sink
                if sink is None:
                    self._pending.append((kind, text))
                    return
            sink(kind, text)
        self._cb = LibreOfficeKitCallback(tramp)   # keep the ctypes callback alive
        self._c.registerCallback(self._d, self._cb, None)
        self._view = self._c.getView(self._d)

    @property
    def closed(self):
        return not self._d

    def _activate(self):
        if self._d:
            self._c.setView(self._d, self._view)

    # lifecycle / info
    def initialize_for_rendering(self, author=None):
        """Prepare for painting. author names this user on comments and tracked changes."""
        args = {".uno:Author": {"type": "string", "value": author}} if author else {}
        self._c.initializeForRendering(self._d, json.dumps(args).encode())

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

    def page_rectangles(self):
        """Writer's pages as [(x, y, w, h)] in twips."""
        raw = _take_string(self._c.getPartPageRectangles(self._d)) or ""
        rects = []
        for chunk in raw.split(";"):
            try:
                x, y, w, h = (int(v) for v in chunk.split(","))
            except ValueError:
                continue
            rects.append((x, y, w, h))
        return rects

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

    def export(self, path, fmt, options=None):
        """Write a copy (a PDF, say) without the document adopting that file."""
        url = "file://" + os.path.abspath(path)
        if not self._c.saveAs(self._d, url.encode(), fmt.encode(), options.encode() if options else None):
            raise LOKError(Office.get().error() or f"Could not write {path}")

    def destroy(self):
        with _VIEW_LOCK:
            if self._d:
                self._c.destroy(self._d)
                self._d = None

    # rendering
    def paint_tile(self, px_w, px_h, tw_x, tw_y, tw_w, tw_h):
        """Render a region (in twips) into a px_w x px_h BGRA premultiplied buffer."""
        buf = (c_ubyte * (px_w * px_h * 4))()
        self._c.paintTile(self._d, buf, px_w, px_h, tw_x, tw_y, tw_w, tw_h)
        return buf

    def paint_part_tile(self, part, px_w, px_h, tw_x, tw_y, tw_w, tw_h):
        """paint_tile for a given part (slide or sheet) without switching the view to it."""
        buf = (c_ubyte * (px_w * px_h * 4))()
        self._c.paintPartTile(self._d, buf, part, 0, px_w, px_h, tw_x, tw_y, tw_w, tw_h)
        return buf

    def _has(self, member):
        """Whether this LibreOffice's vtable reaches member (older versions are shorter)."""
        field = getattr(_DocumentClass, member)
        return field.offset + field.size <= self._c.nSize

    def presentation_info(self):
        """Slides as a show plays them (hidden slides left out): [{'hash', 'index', ...}]."""
        if not self._has("getPresentationInfo"):
            return None
        try:
            return json.loads(_take_string(self._c.getPresentationInfo(self._d)) or "")
        except ValueError:
            return None

    def render_slide(self, slide_hash, index, width, height):
        """Render a slide as a slideshow shows it. Returns (width, height, [layer buffers]),
        bottom layer first, each BGRA premultiplied; None if this LibreOffice can't."""
        if not self._has("renderNextSlideLayer"):
            return None
        w, h = c_uint(width), c_uint(height)
        if not self._c.createSlideRenderer(self._d, str(slide_hash).encode(), index, ctypes.byref(w),
                                           ctypes.byref(h), True, True):
            return None
        layers = []
        try:
            for _ in range(256):
                buf = (c_ubyte * (w.value * h.value * 4))()
                is_bitmap, scale, meta = c_bool(), c_double(), c_void_p()
                done = self._c.renderNextSlideLayer(self._d, buf, ctypes.byref(is_bitmap), ctypes.byref(scale),
                                                    ctypes.byref(meta))
                _take_string(meta.value)             # describes the layer (for animations); not used
                if done:
                    break
                if is_bitmap.value:
                    layers.append(buf)
        finally:
            self._c.postSlideshowCleanup(self._d)
        return w.value, h.value, layers

    def set_client_zoom(self, tile_px, tile_twips):
        self._c.setClientZoom(self._d, tile_px, tile_px, tile_twips, tile_twips)

    def set_visible_area(self, x, y, w, h):
        self._c.setClientVisibleArea(self._d, x, y, w, h)

    # input
    def register_callback(self, fn):
        """Receive (kind, payload) for every event, starting with any held since loading."""
        with self._lock:
            pending, self._pending = self._pending, []
            self._sink = fn
        for kind, text in pending:
            fn(kind, text)

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

    def run_macro(self, call):
        """Run a Basic routine from AceOffice's library on this document, e.g. 'Page.SetPage(1,2)'."""
        self.uno(f"macro:///AceOffice.{call}")

    def command_values(self, command):
        return _take_string(self._c.getCommandValues(self._d, command.encode()))


# With several documents open, LibreOffice works on whichever view is current, and closing
# a document (a thumbnail, say) can leave none current: Impress then reports a size of 0.
# So every call first makes its own document's view current (cheap when it already is),
# under one lock so the thumbnail thread can't switch views in between.
_VIEW_LOCK = threading.RLock()


def _in_own_view(method):
    def call(self, *args, **kwargs):
        with _VIEW_LOCK:
            if not self._d:
                # LibreOffice would crash on a closed document; a late idle callback gets this instead.
                raise LOKError(f"{method.__name__}: the document is closed")
            self._activate()
            return method(self, *args, **kwargs)
    call.__name__, call.__doc__ = method.__name__, method.__doc__
    return call


for _name, _method in list(vars(Document).items()):
    if callable(_method) and not _name.startswith("_") and _name not in ("register_callback", "destroy"):
        setattr(Document, _name, _in_own_view(_method))
