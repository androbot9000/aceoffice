# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Row and column headers for spreadsheets (A, B, C… and 1, 2, 3…).

LibreOfficeKit only renders the cells, so headers are drawn here from
.uno:ViewRowColumnHeaders, which gives each visible row's or column's end
position in pixels at the current zoom, measured from the sheet's origin.
"""

import json

from gi.repository import Gdk, GLib, Graphene, Gtk

from .docview import _accent

COLUMN_HEIGHT = 24
ROW_WIDTH = 48


def _args(**kwargs):
    return json.dumps({k: {"type": t, "value": v} for k, (t, v) in kwargs.items()})


class SheetHeaders:
    """Owns the two header strips for one spreadsheet view and keeps them in sync."""

    def __init__(self, view):
        self.view = view
        self.columns = HeaderStrip(self, Gtk.Orientation.HORIZONTAL)
        self.rows = HeaderStrip(self, Gtk.Orientation.VERTICAL)
        self.corner = Gtk.Box(width_request=ROW_WIDTH, height_request=COLUMN_HEIGHT,
                              css_classes=["ace-header"])
        self._source = 0
        view.connect("geometry-changed", lambda *_: self.refresh())
        view.connect("part-changed", lambda *_: self.refresh())

    def refresh(self):
        # Scrolling emits many changes in a row; ask LibreOffice once per frame.
        if not self._source:
            self._source = GLib.idle_add(self._fetch, priority=GLib.PRIORITY_HIGH_IDLE)

    def _fetch(self):
        self._source = 0
        x, y, w, h = self.view.visible_twips()
        raw = self.view.doc.command_values(
            f".uno:ViewRowColumnHeaders?x={x}&y={y}&width={w}&height={h}")
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            return False
        self.columns.set_entries(data.get("columns", []))
        self.rows.set_entries(data.get("rows", []))
        return False

    def grid(self, scrolled):
        """Lay the headers out around the scrolled document view."""
        grid = Gtk.Grid()
        grid.attach(self.corner, 0, 0, 1, 1)
        grid.attach(self.columns, 1, 0, 1, 1)
        grid.attach(self.rows, 0, 1, 1, 1)
        grid.attach(scrolled, 1, 1, 1, 1)
        for adj in (scrolled.get_hadjustment(), scrolled.get_vadjustment()):
            adj.connect("value-changed", lambda *_: (self.columns.queue_draw(), self.rows.queue_draw()))
        return grid


class HeaderStrip(Gtk.Widget):
    __gtype_name__ = "AceHeaderStrip"

    def __init__(self, owner, orientation):
        super().__init__(css_classes=["ace-header"])
        self.owner = owner
        self.orientation = orientation
        self.entries = []   # (label, start_px, end_px), absolute document pixels
        if orientation == Gtk.Orientation.HORIZONTAL:
            self.set_size_request(-1, COLUMN_HEIGHT)
            self.set_hexpand(True)
        else:
            self.set_size_request(ROW_WIDTH, -1)
            self.set_vexpand(True)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        click = Gtk.GestureClick()
        click.connect("pressed", self._on_pressed)
        self.add_controller(click)

    @property
    def horizontal(self):
        return self.orientation == Gtk.Orientation.HORIZONTAL

    def set_entries(self, raw):
        entries = []
        if raw:
            prev = raw[0].get("size", 0)
            for item in raw[1:]:
                end = item.get("size", prev)
                entries.append((str(item.get("text", "")), prev, end))
                prev = end
        self.entries = entries
        self.queue_draw()

    def _offset(self):
        view = self.owner.view
        if self.horizontal:
            return view._offset_x() - view._hadj.get_value()
        return -view._vadj.get_value()

    def _active_range(self):
        """Pixel span of the cell cursor along this strip, to highlight its header."""
        r = self.owner.view.cell_cursor
        if not r:
            return None
        ppt = self.owner.view.ppt
        x, y, w, h = r
        return (x * ppt, (x + w) * ppt) if self.horizontal else (y * ppt, (y + h) * ppt)

    def do_snapshot(self, snapshot):
        width, height = self.get_width(), self.get_height()
        fg = self.get_color()
        line = fg.copy()
        line.alpha = 0.15
        active = _accent()
        active.alpha = 0.22
        off = self._offset()
        span = self._active_range()
        for label, start, end in self.entries:
            a, b = start + off, end + off
            if b < 0 or a > (width if self.horizontal else height):
                continue
            rect = (Graphene.Rect().init(a, 0, b - a, height) if self.horizontal
                    else Graphene.Rect().init(0, a, width, b - a))
            if span and start < span[1] - 0.5 and end > span[0] + 0.5:
                snapshot.append_color(active, rect)
            edge = (Graphene.Rect().init(b - 1, 0, 1, height) if self.horizontal
                    else Graphene.Rect().init(0, b - 1, width, 1))
            snapshot.append_color(line, edge)
            layout = self.create_pango_layout(label)
            tw, th = layout.get_pixel_size()
            if (b - a) < tw + 2:
                continue
            snapshot.save()
            if self.horizontal:
                snapshot.translate(Graphene.Point().init(a + (b - a - tw) / 2, (height - th) / 2))
            else:
                snapshot.translate(Graphene.Point().init((width - tw) / 2, a + (b - a - th) / 2))
            snapshot.append_layout(layout, fg)
            snapshot.restore()
        border = (Graphene.Rect().init(0, height - 1, width, 1) if self.horizontal
                  else Graphene.Rect().init(width - 1, 0, 1, height))
        snapshot.append_color(line, border)

    def _on_pressed(self, gesture, _n, x, y):
        pos = (x if self.horizontal else y) - self._offset()
        for i, (label, start, end) in enumerate(self.entries):
            if start <= pos < end:
                self._select(label, gesture.get_current_event_state())
                break

    def _select(self, label, state):
        view = self.owner.view
        modifier = 0
        if state & Gdk.ModifierType.SHIFT_MASK:
            modifier = 0x1000
        elif state & Gdk.ModifierType.CONTROL_MASK:
            modifier = 0x2000
        if self.horizontal:
            index = _column_index(label)
            view.doc.uno(".uno:SelectColumn", _args(Col=("long", index), Modifier=("unsigned short", modifier)))
        else:
            view.doc.uno(".uno:SelectRow", _args(Row=("long", int(label) - 1),
                                                   Modifier=("unsigned short", modifier)))
        view.grab_focus()


def _column_index(label):
    n = 0
    for ch in label:
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1
