# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""DocView: a GTK4 widget that shows and edits a LibreOfficeKit document.

LibreOffice renders the document as tiles; we cache them as textures, draw
only the ones in view, and drop them when LibreOffice reports a region has
changed. The caret, selections and cell cursor are drawn by us on top, from
the positions LibreOffice reports through callbacks.
"""

import json
import math

from gi.repository import Adw, Gdk, GLib, GObject, Graphene, Gsk, Gtk

from . import keys, lok

TILE = 256                       # logical pixels per tile edge
TWIPS_PER_PX = lok.TWIPS_PER_INCH / 96
TILES_PER_PASS = 8               # render this many tiles per idle pass, then repaint

# Keys that move around the document without changing it.
_NAV_KEYS = {1024, 1025, 1026, 1027, 1028, 1029, 1030, 1031, 1281}


def _rect(payload):
    """Parse 'x, y, w, h[, ...]' (twips) into a tuple, or None for EMPTY."""
    if not payload or payload.startswith("EMPTY"):
        return None
    try:
        x, y, w, h = (int(float(v)) for v in payload.split(",")[:4])
    except ValueError:
        return None
    return x, y, w, h


class DocView(Gtk.Widget):
    __gtype_name__ = "AceDocView"

    __gsignals__ = {
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        "part-changed": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "formula-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "cell-address-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "zoom-changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        "edited": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # Right-click at x, y; the string is LibreOffice's own menu for that spot as JSON
        # (spelling suggestions, table commands), or "" if it offered none.
        "context-menu": (GObject.SignalFlags.RUN_FIRST, None, (float, float, str)),
        "search-not-found": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "comment": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        # LibreOffice redrew part of a sheet or slide (-1: the current one); slide thumbnails follow.
        "tiles-invalidated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        # Visible area, zoom or row/column sizes changed: spreadsheet headers redraw.
        "geometry-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        self.zoom = 1.0
        self._tiles = {}
        self._stale = set()      # tiles LibreOffice says changed; still shown until re-rendered
        self._render_source = 0
        self.frames = 0               # frames drawn, and frames that had to show a
        self.placeholder_frames = 0   # blank tile (for tests)
        self._cursor = None
        self._cursor_visible = True
        self._blink_on = True
        self._blink_source = 0
        self._selection = []
        self._cell_cursor = None
        self._graphic = None
        self._buttons = 0
        self._hadj = self._vadj = None
        self._menu_at = None
        # Slides sit in the middle of the window, with a shadow, as in Keynote.
        self.center = False
        # Keep the page fitted to the window as it resizes, until the user zooms.
        self.auto_fit = False
        self._fitted_to = None

        self.set_focusable(True)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.set_cursor_from_name("text")

        doc.register_callback(lambda kind, payload: GLib.idle_add(self._on_lok, kind, payload))
        self._apply_zoom()

        self._im = Gtk.IMMulticontext()
        self._im.set_client_widget(self)
        self._im.connect("commit", self._on_commit)
        key = Gtk.EventControllerKey()
        key.set_im_context(self._im)
        key.connect("key-pressed", self._on_key_pressed)
        key.connect("key-released", self._on_key_released)
        self.add_controller(key)

        focus = Gtk.EventControllerFocus()
        focus.connect("enter", self._on_focus_in)
        focus.connect("leave", self._on_focus_out)
        self.add_controller(focus)

        click = Gtk.GestureClick(button=0)
        click.connect("pressed", self._on_pressed)
        click.connect("released", self._on_released)
        self.add_controller(click)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.add_controller(motion)

        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

    # --- geometry -----------------------------------------------------------

    @property
    def ppt(self):
        """Logical pixels per twip at the current zoom."""
        return self.zoom / TWIPS_PER_PX

    def _tile_twips(self):
        return max(1, round(TILE / self.ppt))

    def _doc_px(self):
        w, h = self.doc.size_twips()
        return math.ceil(w * self.ppt), math.ceil(h * self.ppt)

    def _offset_x(self):
        return max(0, (self.get_width() - self._doc_px()[0]) // 2)

    def _offset_y(self):
        return max(0, (self.get_height() - self._doc_px()[1]) // 2) if self.center else 0

    def to_twips(self, x, y):
        return int((x - self._offset_x()) / self.ppt), int((y - self._offset_y()) / self.ppt)

    def _visible(self):
        """Visible area in widget pixels: (x, y, w, h)."""
        if self._hadj and self._vadj:
            return (self._hadj.get_value(), self._vadj.get_value(),
                    self._hadj.get_page_size() or self.get_width(),
                    self._vadj.get_page_size() or self.get_height())
        return 0, 0, self.get_width(), self.get_height()

    def attach_scrolled(self, scrolled):
        self._hadj = scrolled.get_hadjustment()
        self._vadj = scrolled.get_vadjustment()
        for adj in (self._hadj, self._vadj):
            adj.connect("value-changed", self._on_scrolled)
            adj.connect("notify::page-size", self._on_scrolled)

    def _on_scrolled(self, *_):
        if self.doc.closed:
            return
        x, y, w, h = self._visible()
        ox = self._offset_x()
        self.doc.set_visible_area(*self.visible_twips())
        self.queue_draw()
        self.emit("geometry-changed")

    def visible_twips(self):
        x, y, w, h = self._visible()
        return (int(max(0, x - self._offset_x()) / self.ppt), int(max(0, y - self._offset_y()) / self.ppt),
                int(w / self.ppt), int(h / self.ppt))

    @property
    def cell_cursor(self):
        return self._cell_cursor

    def do_measure(self, orientation, for_size):
        if self.doc.closed:
            return 0, 0, -1, -1
        w, h = self._doc_px()
        size = w if orientation == Gtk.Orientation.HORIZONTAL else h
        return size, size, -1, -1

    def do_size_allocate(self, width, height, baseline):
        self._on_scrolled()
        if self.auto_fit and self._hadj:
            area = (int(self._hadj.get_page_size()), int(self._vadj.get_page_size()))
            if area != self._fitted_to and all(area):
                self._fitted_to = area
                GLib.idle_add(lambda: self.auto_fit and self.fit_page(*area, auto=True) and False)

    # --- zoom -----------------------------------------------------------------

    def set_zoom(self, zoom, auto=False):
        if not auto:
            self.auto_fit = False
        zoom = min(4.0, max(0.1, round(zoom, 2)))
        if zoom == self.zoom:
            return
        frac = None
        if self._vadj and self._vadj.get_upper() > 0:
            frac = self._vadj.get_value() / self._vadj.get_upper()
        self.zoom = zoom
        self._apply_zoom()
        self.queue_resize()
        if frac is not None:
            GLib.idle_add(lambda: self._vadj.set_value(frac * self._vadj.get_upper()) and False)
        self.emit("zoom-changed", zoom)

    def _apply_zoom(self):
        self._tiles.clear()
        self._stale.clear()
        tw = self._tile_twips()
        self.doc.set_client_zoom(TILE, tw)

    def fit_page(self, available_w, available_h, margin=56, auto=False):
        """Zoom so the whole page (a slide) fits in the given area."""
        w, h = self.doc.size_twips()
        if w and h and available_w > margin and available_h > margin:
            self.set_zoom(min((available_w - margin) / (w / TWIPS_PER_PX),
                              (available_h - margin) / (h / TWIPS_PER_PX)), auto=auto)

    def start_auto_fit(self):
        self.auto_fit = True
        self._fitted_to = None
        self.queue_allocate()

    def fit_width(self, available_px):
        w, _ = self.doc.size_twips()
        if w:
            self.set_zoom((available_px - 32) / (w / TWIPS_PER_PX))

    # --- painting -------------------------------------------------------------

    def _scale(self):
        native = self.get_native()
        surface = native.get_surface() if native else None
        return surface.get_scale() if surface and hasattr(surface, "get_scale") else self.get_scale_factor()

    def _visible_tiles(self):
        vx, vy, vw, vh = self._visible()
        ox = self._offset_x()
        vy -= self._offset_y()
        tw = self._tile_twips()
        step = tw * self.ppt
        doc_w, doc_h = self._doc_px()
        x0 = max(0, int((vx - ox) // step))
        x1 = int(min(doc_w, vx - ox + vw) // step)
        y0 = max(0, int(vy // step))
        y1 = int(min(doc_h, vy + vh) // step)
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                yield tx, ty

    def do_snapshot(self, snapshot):
        if self.doc.closed:
            return
        ox, oy = self._offset_x(), self._offset_y()
        step = self._tile_twips() * self.ppt
        self.frames += 1
        missing = stale = False
        if self.center:
            w, h = self._doc_px()
            page = Gsk.RoundedRect()
            page.init_from_rect(Graphene.Rect().init(ox, oy, w, h), 0)
            snapshot.append_outset_shadow(page, _SHADOW, 0, 3, 0, 14)
            snapshot.push_clip(Graphene.Rect().init(ox, oy, w, h))
        for key in self._visible_tiles():
            tex = self._tiles.get(key)
            rect = Graphene.Rect().init(ox + key[0] * step, oy + key[1] * step, step, step)
            if tex:
                snapshot.append_texture(tex, rect)
                stale = stale or key in self._stale
            else:
                missing = True
                snapshot.append_color(_WHITE, rect)
        if self.center:
            snapshot.pop()
        if missing:
            self.placeholder_frames += 1
        if missing or stale:
            self._schedule_render()
        self._snapshot_overlays(snapshot, ox, oy)

    def _schedule_render(self):
        # HIGH_IDLE runs before GTK's layout and paint (HIGH_IDLE + 10/20), so fresh
        # tiles land in the very next frame instead of one frame late.
        if not self._render_source:
            self._render_source = GLib.idle_add(self._render_pending, priority=GLib.PRIORITY_HIGH_IDLE)

    def _render_pending(self):
        self._render_source = 0
        if self.doc.closed:
            return False
        scale = self._scale()
        tw = self._tile_twips()
        px = math.ceil(TILE * scale)
        visible = list(self._visible_tiles())
        # Changed tiles first, all in one pass so an edit never shows half-updated;
        # then tiles never rendered (scrolling), a few at a time to stay responsive.
        todo = [k for k in visible if k in self._stale]
        todo += [k for k in visible if k not in self._tiles][:TILES_PER_PASS]
        for tx, ty in todo:
            buf = self.doc.paint_tile(px, px, tx * tw, ty * tw, tw, tw)
            self._tiles[(tx, ty)] = Gdk.MemoryTexture.new(
                px, px, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED, GLib.Bytes.new(bytes(buf)), px * 4)
            self._stale.discard((tx, ty))
        if todo:
            self.queue_draw()
        return False

    def _px_rect(self, r, ox, oy=0):
        x, y, w, h = r
        return Graphene.Rect().init(ox + x * self.ppt, oy + y * self.ppt, max(w * self.ppt, 1),
                                    max(h * self.ppt, 1))

    def _snapshot_overlays(self, snapshot, ox, oy=0):
        accent = _accent()
        sel = accent.copy()
        sel.alpha = 0.28
        for r in self._selection:
            snapshot.append_color(sel, self._px_rect(r, ox, oy))
        for r in (self._cell_cursor, self._graphic):
            if r:
                rr = self._px_rect(r, ox, oy)
                width = [2.0] * 4
                outline = Gsk.RoundedRect()
                outline.init_from_rect(rr, 0)
                snapshot.append_border(outline, width, [accent] * 4)
        if (self._cursor and self._cursor_visible and self._blink_on and self.has_focus()
                and not self._selection):
            x, y, w, h = self._cursor
            snapshot.append_color(_BLACK,
                                  Graphene.Rect().init(ox + x * self.ppt, oy + y * self.ppt,
                                                       max(1.5, w * self.ppt), h * self.ppt))

    def invalidate_all(self, keep_showing=True):
        """Re-render every tile. keep_showing=False drops them at once, for when the
        old pixels would be wrong to show (a different sheet or slide)."""
        if keep_showing:
            self._stale.update(self._tiles)
        else:
            self._tiles.clear()
            self._stale.clear()
        self._schedule_render()
        self.queue_draw()

    def _invalidate(self, r):
        tw = self._tile_twips()
        x, y, w, h = r
        self._stale.update(k for k in self._tiles
                           if k[0] * tw < x + w and (k[0] + 1) * tw > x
                           and k[1] * tw < y + h and (k[1] + 1) * tw > y)
        self._schedule_render()

    # --- LibreOffice callbacks -------------------------------------------------

    def _on_lok(self, kind, payload):
        if self.doc.closed:
            return False             # the last messages of a document that has since closed
        if kind == lok.CALLBACK_INVALIDATE_TILES:
            # "x, y, w, h, part, mode" or "EMPTY, part, mode"; ignore other sheets/slides.
            fields = [f.strip() for f in payload.split(",")]
            part_field = fields[1] if fields[0] == "EMPTY" else (fields[4] if len(fields) > 4 else None)
            try:
                self.emit("tiles-invalidated", int(part_field) if part_field not in (None, "-1") else self.doc.part())
            except ValueError:
                pass
            if part_field not in (None, "-1") and part_field.lstrip("-").isdigit() \
                    and int(part_field) != self.doc.part():
                return False
            r = _rect(payload)
            self.invalidate_all() if r is None else self._invalidate(r)
        elif kind == lok.CALLBACK_INVALIDATE_VISIBLE_CURSOR:
            self._cursor = _rect(payload)
            self._restart_blink()
            self._scroll_to(self._cursor)
            self.queue_draw()
        elif kind == lok.CALLBACK_CURSOR_VISIBLE:
            self._cursor_visible = payload == "true"
            self.queue_draw()
        elif kind == lok.CALLBACK_TEXT_SELECTION:
            self._selection = [r for r in (_rect(p) for p in payload.split(";")) if r] if payload else []
            if self._selection:
                self._scroll_to(self._selection[0])   # e.g. a search result off screen
            self.queue_draw()
        elif kind == lok.CALLBACK_SEARCH_NOT_FOUND:
            self.emit("search-not-found")
        elif kind == lok.CALLBACK_GRAPHIC_SELECTION:
            self._graphic = _rect(payload)
            self.queue_draw()
        elif kind == lok.CALLBACK_CELL_CURSOR:
            self._cell_cursor = _rect(payload)
            self._scroll_to(self._cell_cursor)
            self.queue_draw()
            self.emit("geometry-changed")
        elif kind == lok.CALLBACK_STATE_CHANGED:
            self._on_state(payload)
        elif kind == lok.CALLBACK_DOCUMENT_SIZE_CHANGED:
            self.invalidate_all()
            self.queue_resize()
        elif kind == lok.CALLBACK_SET_PART:
            self._selection, self._graphic, self._cursor = [], None, None
            self.invalidate_all(keep_showing=False)
            self.queue_resize()
            try:
                self.emit("part-changed", int(payload))
            except ValueError:
                pass
        elif kind == lok.CALLBACK_CELL_FORMULA:
            self.emit("formula-changed", payload)
        elif kind == lok.CALLBACK_CELL_ADDRESS:
            self.emit("cell-address-changed", payload)
        elif kind == lok.CALLBACK_CONTEXT_MENU:
            if self._menu_at:
                at, self._menu_at = self._menu_at, None
                self.emit("context-menu", at[0], at[1], payload)
        elif kind == lok.CALLBACK_COMMENT:
            self.emit("comment", payload)
        elif kind == lok.CALLBACK_INVALIDATE_HEADER:
            self.emit("geometry-changed")
        elif kind == lok.CALLBACK_MOUSE_POINTER:
            self.set_cursor_from_name(payload or "default")
        return False

    def _on_state(self, payload):
        if payload.startswith("{"):
            try:
                data = json.loads(payload)
            except ValueError:
                return
            name, value = data.get("commandName"), data.get("state")
            if name and isinstance(value, (str, bool, int)):
                self.emit("state-changed", name, str(value).lower())
            return
        name, sep, value = payload.partition("=")
        if sep:
            self.emit("state-changed", name, value)

    def _scroll_to(self, r):
        if not r or not self._vadj:
            return
        vx, vy, vw, vh = self._visible()
        top, bottom = self._offset_y() + r[1] * self.ppt, self._offset_y() + (r[1] + r[3]) * self.ppt
        if top < vy:
            self._vadj.set_value(top - 24)
        elif bottom > vy + vh:
            self._vadj.set_value(bottom - vh + 24)
        left, right = self._offset_x() + r[0] * self.ppt, self._offset_x() + (r[0] + r[2]) * self.ppt
        if left < vx:
            self._hadj.set_value(left - 24)
        elif right > vx + vw:
            self._hadj.set_value(right - vw + 24)

    # --- caret blink ------------------------------------------------------------

    def _restart_blink(self):
        self._blink_on = True
        if self._blink_source:
            GLib.source_remove(self._blink_source)
        self._blink_source = GLib.timeout_add(530, self._blink)

    def _blink(self):
        self._blink_on = not self._blink_on
        if self._cursor:
            self.queue_draw()
        return True

    def _on_focus_in(self, *_):
        self._im.focus_in()
        self._restart_blink()
        self.queue_draw()

    def _on_focus_out(self, *_):
        self._im.focus_out()
        if self._blink_source:
            GLib.source_remove(self._blink_source)
            self._blink_source = 0
        self.queue_draw()

    # --- keyboard -----------------------------------------------------------------

    def type_text(self, text):
        for ch in text:
            code = ord(ch)
            key_code = {"\n": 1280, "\t": 1282}.get(ch, 0)
            if ch == "\n":
                code = 13
            self.doc.key(lok.KEYEVENT_KEYINPUT, code, key_code)
            self.doc.key(lok.KEYEVENT_KEYUP, code, key_code)
        self.emit("edited")

    def press_key(self, char_code, key_code):
        self.doc.key(lok.KEYEVENT_KEYINPUT, char_code, key_code)
        self.doc.key(lok.KEYEVENT_KEYUP, char_code, key_code)

    def _on_commit(self, _im, text):
        self.type_text(text)

    def _on_key_pressed(self, _ctl, keyval, _keycode, state):
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        if ctrl:
            lower = Gdk.keyval_to_lower(keyval)
            if lower == Gdk.KEY_c:
                self.copy()
                return True
            if lower == Gdk.KEY_x:
                self.cut()
                return True
            if lower == Gdk.KEY_v:
                self.paste()
                return True
            # Leave the app's own shortcuts (new, open, save, print, close, find, zoom, help)
            # to the window.
            if lower in (Gdk.KEY_n, Gdk.KEY_o, Gdk.KEY_s, Gdk.KEY_w, Gdk.KEY_q, Gdk.KEY_p, Gdk.KEY_f,
                         Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_minus, Gdk.KEY_0,
                         Gdk.KEY_question, Gdk.KEY_slash):
                return False
        t = keys.translate(keyval, state)
        if t is None:
            return False
        self.doc.key(lok.KEYEVENT_KEYINPUT, *t)
        if (t[1] & 0x0FFF) not in _NAV_KEYS:
            self.emit("edited")
        return True

    def _on_key_released(self, _ctl, keyval, _keycode, state):
        t = keys.translate(keyval, state)
        if t is not None:
            self.doc.key(lok.KEYEVENT_KEYUP, *t)

    # --- clipboard ------------------------------------------------------------------
    #
    # LibreOffice keeps its own rich clipboard. We put plain text on the system
    # clipboard as well, and when pasting back our own copy we let LibreOffice
    # paste its rich version so formatting survives.

    def copy(self):
        text = self.doc.selected_text()
        self.doc.uno(".uno:Copy")
        if text:
            self.get_clipboard().set(text)

    def cut(self):
        text = self.doc.selected_text()
        self.doc.uno(".uno:Cut")
        if text:
            self.get_clipboard().set(text)
        self.emit("edited")

    def paste(self):
        clipboard = self.get_clipboard()
        if clipboard.is_local():
            self.doc.uno(".uno:Paste")
            self.emit("edited")
            return

        def done(cb, res):
            try:
                text = cb.read_text_finish(res)
            except GLib.Error:
                return
            if text:
                self.doc.paste(text)
                self.emit("edited")
        clipboard.read_text_async(None, done)

    # --- mouse ------------------------------------------------------------------------

    def _on_pressed(self, gesture, n_press, x, y):
        self.grab_focus()
        if gesture.get_current_button() == 3:
            # LibreOffice moves the caret there (as a Mac does) and answers with its menu;
            # if it stays silent, show ours anyway.
            self.context_click(x, y)
            return
        button = {1: lok.MOUSE_LEFT, 2: lok.MOUSE_MIDDLE}.get(gesture.get_current_button())
        if not button:
            return
        self._buttons = button
        tx, ty = self.to_twips(x, y)
        mods = keys.modifiers(gesture.get_current_event_state())
        self.doc.mouse(lok.MOUSEEVENT_DOWN, tx, ty, n_press, button, mods)

    def context_click(self, x, y):
        tx, ty = self.to_twips(x, y)
        self._menu_at = (x, y)
        self.doc.mouse(lok.MOUSEEVENT_DOWN, tx, ty, 1, lok.MOUSE_RIGHT, 0)
        self.doc.mouse(lok.MOUSEEVENT_UP, tx, ty, 1, lok.MOUSE_RIGHT, 0)
        GLib.timeout_add(250, self._menu_fallback, self._menu_at)

    def _menu_fallback(self, at):
        if self._menu_at is at:
            self._menu_at = None
            if not self.doc.closed:
                self.emit("context-menu", at[0], at[1], "")
        return False

    def _on_released(self, gesture, n_press, x, y):
        if not self._buttons:
            return
        tx, ty = self.to_twips(x, y)
        mods = keys.modifiers(gesture.get_current_event_state())
        self.doc.mouse(lok.MOUSEEVENT_UP, tx, ty, n_press, self._buttons, mods)
        self._buttons = 0

    def _on_motion(self, ctl, x, y):
        if self._buttons:
            tx, ty = self.to_twips(x, y)
            self.doc.mouse(lok.MOUSEEVENT_MOVE, tx, ty, 1, self._buttons,
                           keys.modifiers(ctl.get_current_event_state()))

    def _on_scroll(self, ctl, _dx, dy):
        if ctl.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK:
            self.set_zoom(self.zoom * (0.9 if dy > 0 else 1.1))
            return True
        return False


# --- small helpers ------------------------------------------------------------------

def _rgba(spec):
    c = Gdk.RGBA()
    c.parse(spec)
    return c


_WHITE = _rgba("white")
_SHADOW = _rgba("rgba(0,0,0,0.22)")
_BLACK = _rgba("black")


def _accent():
    manager = Adw.StyleManager.get_default()
    if hasattr(manager, "get_accent_color_rgba"):
        return manager.get_accent_color_rgba()
    return _rgba("#3584e4")
