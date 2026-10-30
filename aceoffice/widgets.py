# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Small reusable widgets: colour buttons, and the measurement unit helpers."""

import locale

from gi.repository import Adw, Gdk, GLib, GObject, Graphene, Gtk

TEXT_COLORS = ["#000000", "#5e5c64", "#c01c28", "#e66100", "#c88800",
               "#26a269", "#2190a4", "#1c71d8", "#813d9c", "#ffffff"]
FILL_COLORS = ["#f9f06b", "#ffbe6f", "#f66151", "#8ff0a4", "#99c1f1",
               "#dc8add", "#cdab8f", "#deddda", "#ffffff", None]


def _swatch_class(color):
    return "ace-sw-" + color.lstrip("#")


def swatch_css():
    return "\n".join(f".{_swatch_class(c)} {{ background: {c}; }}" for c in TEXT_COLORS + FILL_COLORS if c)


class ColorBar(Gtk.Widget):
    """The thin colour stripe under a colour button's glyph."""
    __gtype_name__ = "AceColorBar"

    def __init__(self, color):
        super().__init__(width_request=18, height_request=4)
        self.set_color(color)

    def set_color(self, color):
        self._rgba = Gdk.RGBA()
        self._rgba.parse(color or "rgba(128,128,128,0.4)")
        self.queue_draw()

    def do_snapshot(self, snapshot):
        snapshot.append_color(self._rgba, Graphene.Rect().init(0, 0, self.get_width(), self.get_height()))


class ColorButton(Gtk.Box):
    """A split button (AdwSplitButton is final, so this wraps one): the face reapplies
    the last colour; the arrow opens a palette with Custom….

    Emits "color-chosen" with "#rrggbb", or "" for no colour."""
    __gtype_name__ = "AceColorButton"
    __gsignals__ = {"color-chosen": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, glyph, tooltip, default, palette):
        self.current = default
        self._bar = ColorBar(default)
        face = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, valign=Gtk.Align.CENTER)
        face.append(Gtk.Label(label=glyph, css_classes=["heading"]))
        face.append(self._bar)
        super().__init__()
        self.split = Adw.SplitButton(child=face, tooltip_text=tooltip, dropdown_tooltip=f"Choose {tooltip.lower()}",
                                     css_classes=["flat"])
        self.split.connect("clicked", lambda *_: self._choose(self.current))
        self.append(self.split)

        popover = Gtk.Popover()
        grid = Gtk.Grid(row_spacing=6, column_spacing=6, margin_top=6, margin_bottom=6,
                        margin_start=6, margin_end=6)
        for n, color in enumerate(palette):
            swatch = Gtk.Button(css_classes=["ace-swatch", _swatch_class(color) if color else "ace-swatch-none"],
                                tooltip_text=color or "None")
            swatch.connect("clicked", lambda _b, c=color: (popover.popdown(), self._choose(c)))
            grid.attach(swatch, n % 5, n // 5, 1, 1)
        custom = Gtk.Button(label="Custom…", css_classes=["flat"])
        custom.connect("clicked", lambda *_: (popover.popdown(), self._custom()))
        grid.attach(custom, 0, 2, 5, 1)
        popover.set_child(grid)
        self.split.set_popover(popover)

    def _choose(self, color):
        self.current = color
        self._bar.set_color(color)
        self.emit("color-chosen", color or "")

    def _custom(self):
        rgba = Gdk.RGBA()
        rgba.parse(self.current or "#000000")

        def done(dialog, res):
            try:
                c = dialog.choose_rgba_finish(res)
            except GLib.Error:
                return
            self._choose("#%02x%02x%02x" % (round(c.red * 255), round(c.green * 255), round(c.blue * 255)))
        Gtk.ColorDialog(with_alpha=False).choose_rgba(self.get_root(), rgba, None, done)


def color_value(color):
    """LibreOffice colour value for '#rrggbb', or -1 (automatic / no fill) for ''."""
    return int(color[1:], 16) if color else -1


# --- units ------------------------------------------------------------------------

def uses_inches():
    """Inches where Letter paper and imperial rulers are the norm, centimetres elsewhere."""
    loc = (locale.getlocale(locale.LC_MEASUREMENT)[0] if hasattr(locale, "LC_MEASUREMENT") else None) \
        or locale.getlocale()[0] or ""
    return loc.split(".")[0] in ("en_US", "en_CA", "en_PH", "es_US", "my_MM", "en_LR")


class Units:
    """Converts between LibreOffice's 1/100 mm and what the user sees."""

    def __init__(self):
        self.inches = uses_inches()
        self.suffix = "in" if self.inches else "cm"
        self.step = 0.05 if self.inches else 0.1
        self.digits = 2 if self.inches else 1

    def to_user(self, hmm):
        return hmm / 2540 if self.inches else hmm / 1000

    def from_user(self, value):
        return round(value * 2540) if self.inches else round(value * 1000)
