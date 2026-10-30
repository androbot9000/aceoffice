# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Formatting controls, and the Format sidebar (an inspector in the style of Pages).

`Formatting` builds every control that sends a LibreOffice command and keeps
them in step with LibreOffice's state reports, so the same command can appear
in the toolbar and the sidebar and both stay right.
"""

import json
import os

from gi.repository import GLib, Gtk, Pango

from .lok import uno_args
from .widgets import FILL_COLORS, TEXT_COLORS, ColorButton, Units, color_value

PARAGRAPH_STYLES = [("Body", "Default Paragraph Style"), ("Title", "Title"), ("Subtitle", "Subtitle"),
                    ("Heading 1", "Heading 1"), ("Heading 2", "Heading 2"), ("Heading 3", "Heading 3"),
                    ("Quote", "Quotations")]

FONT_SIZES = ["8", "9", "10", "11", "12", "14", "16", "18", "20", "24", "28", "32", "36", "48", "64", "72"]

ALIGN = {
    "text": [(".uno:LeftPara", "format-justify-left-symbolic", "Align Left"),
             (".uno:CenterPara", "format-justify-center-symbolic", "Center"),
             (".uno:RightPara", "format-justify-right-symbolic", "Align Right"),
             (".uno:JustifyPara", "format-justify-fill-symbolic", "Justify")],
    "spreadsheet": [(".uno:AlignLeft", "format-justify-left-symbolic", "Align Left"),
                    (".uno:AlignHorizontalCenter", "format-justify-center-symbolic", "Center"),
                    (".uno:AlignRight", "format-justify-right-symbolic", "Align Right")],
}
ALIGN["presentation"] = ALIGN["text"]

# Paper sizes in 1/100 mm, portrait.
PAPER = [("US Letter", 21590, 27940), ("US Legal", 21590, 35560), ("Tabloid", 27940, 43180),
         ("A3", 29700, 42000), ("A4", 21000, 29700), ("A5", 14800, 21000)]

# Margin presets in 1/100 mm: (top, bottom, left, right).
MARGIN_PRESETS = [("Normal", (2540, 2540, 2540, 2540)), ("Narrow", (1270, 1270, 1270, 1270)),
                  ("Wide", (2540, 2540, 5080, 5080))]


class Formatting:
    def __init__(self, win):
        self.win = win
        self.syncing = False
        self._toggles = {}       # command -> [ToggleButton]
        self._fonts = []         # DropDowns
        self._sizes = []         # SpinButtons and DropDowns
        self._styles = []        # DropDowns
        self._font_names = None

    @property
    def doc(self):
        return self.win.doc

    def send(self, command, args=None, refocus=True):
        if self.syncing:
            return
        self.doc.uno(command, args)
        self.win.set_modified(True)
        if refocus:
            self.win.view.grab_focus()

    # --- building controls ---------------------------------------------------------

    def button(self, icon=None, label=None, tooltip=None, command=None, args=None):
        b = Gtk.Button(icon_name=icon, tooltip_text=tooltip, css_classes=["flat"]) if icon else \
            Gtk.Button(label=label, tooltip_text=tooltip, css_classes=["flat"])
        if command:
            b.connect("clicked", lambda *_: self.send(command, args))
        return b

    def toggle(self, icon=None, label=None, tooltip=None, command=None):
        b = Gtk.ToggleButton(icon_name=icon, tooltip_text=tooltip, css_classes=["flat"]) if icon else \
            Gtk.ToggleButton(label=label, tooltip_text=tooltip, css_classes=["flat"])
        b.connect("toggled", lambda *_: self.send(command))
        self._toggles.setdefault(command, []).append(b)
        return b

    @staticmethod
    def group(*widgets):
        g = Gtk.Box(css_classes=["linked"])
        for w in widgets:
            g.append(w)
        return g

    def undo_redo(self):
        return self.group(self.button("edit-undo-symbolic", tooltip="Undo (Ctrl+Z)", command=".uno:Undo"),
                          self.button("edit-redo-symbolic", tooltip="Redo (Ctrl+Shift+Z)", command=".uno:Redo"))

    def emphasis(self, strike=True):
        buttons = [self.toggle("format-text-bold-symbolic", tooltip="Bold (Ctrl+B)", command=".uno:Bold"),
                   self.toggle("format-text-italic-symbolic", tooltip="Italic (Ctrl+I)", command=".uno:Italic"),
                   self.toggle("format-text-underline-symbolic", tooltip="Underline (Ctrl+U)",
                               command=".uno:Underline")]
        if strike:
            buttons.append(self.toggle("format-text-strikethrough-symbolic", tooltip="Strikethrough",
                                       command=".uno:Strikeout"))
        return self.group(*buttons)

    def alignment(self, kind):
        return self.group(*[self.toggle(icon, tooltip=tip, command=cmd) for cmd, icon, tip in ALIGN[kind]])

    def font_names(self):
        if self._font_names is None:
            raw = self.doc.command_values(".uno:CharFontName")
            try:
                names = sorted(json.loads(raw)["commandValues"].keys(), key=str.casefold) if raw else []
            except (ValueError, KeyError, AttributeError):
                names = []
            self._font_names = Gtk.StringList.new(names)
        return self._font_names

    def font_dropdown(self, width=170):
        dd = Gtk.DropDown(model=self.font_names(), enable_search=True, tooltip_text="Font",
                          expression=Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        dd.set_size_request(width, -1)

        def selected(d, _p):
            item = d.get_selected_item()
            if item:
                self.send(".uno:CharFontName", uno_args(**{"CharFontName.FamilyName": item.get_string()}))
        dd.connect("notify::selected", selected)
        self._fonts.append(dd)
        return dd

    def size_dropdown(self):
        """Compact size picker for the toolbar; exact sizes go in the sidebar's spin button."""
        dd = Gtk.DropDown.new_from_strings(FONT_SIZES)
        dd.set_tooltip_text("Text size")

        def selected(d, _p):
            item = d.get_selected_item()
            if item:
                self.send(".uno:FontHeight", uno_args(**{"FontHeight.Height": float(item.get_string())}))
        dd.connect("notify::selected", selected)
        self._sizes.append(dd)
        return dd

    def size_spin(self):
        spin = Gtk.SpinButton.new_with_range(1, 999, 1)
        spin.set_digits(1)
        spin.set_value(12)
        spin.set_tooltip_text("Text size")
        spin.connect("value-changed", lambda s: self.send(
            ".uno:FontHeight", uno_args(**{"FontHeight.Height": float(s.get_value())}), refocus=False))
        self._sizes.append(spin)
        return spin

    def style_dropdown(self):
        dd = Gtk.DropDown.new_from_strings([s[0] for s in PARAGRAPH_STYLES])
        dd.set_tooltip_text("Paragraph style")
        dd.connect("notify::selected", lambda d, _p: self.send(
            ".uno:StyleApply", uno_args(Style=PARAGRAPH_STYLES[d.get_selected()][1], FamilyName="ParagraphStyles")))
        self._styles.append(dd)
        return dd

    def colors(self, kind):
        fill_cmd = ".uno:BackgroundColor" if kind == "spreadsheet" else ".uno:CharBackColor"
        text = ColorButton("A", "Text color", "#c01c28", TEXT_COLORS)
        text.connect("color-chosen", lambda _b, c: self.send(".uno:Color", uno_args(Color=color_value(c))))
        fill = ColorButton("ab", "Highlight" if kind == "text" else "Fill color", "#f9f06b", FILL_COLORS)
        fill.connect("color-chosen", lambda _b, c: self.send(
            fill_cmd, uno_args(**{fill_cmd.split(":")[1]: color_value(c)})))
        box = Gtk.Box(spacing=2)
        box.append(text)
        box.append(fill)
        return box

    # --- state from LibreOffice ---------------------------------------------------------

    def on_state(self, command, value):
        """Reflect a LibreOffice state report in every control bound to it."""
        self.syncing = True
        try:
            if command in self._toggles and value in ("true", "false"):
                for b in self._toggles[command]:
                    b.set_active(value == "true")
            elif command == ".uno:CharFontName" and value:
                names = self.font_names()
                index = next((i for i in range(names.get_n_items()) if names.get_string(i) == value), None)
                if index is None:
                    names.append(value)        # a font the document uses but this system lacks
                    index = names.get_n_items() - 1
                for dd in self._fonts:
                    dd.set_selected(index)
            elif command == ".uno:FontHeight":
                try:
                    size = float(value)
                except ValueError:
                    return
                for w in self._sizes:
                    if isinstance(w, Gtk.SpinButton):
                        w.set_value(size)
                    else:
                        label = f"{size:g}"
                        if label in FONT_SIZES:
                            w.set_selected(FONT_SIZES.index(label))
            elif command == ".uno:StyleApply":
                names = [s[1] for s in PARAGRAPH_STYLES]
                if value in names:
                    for dd in self._styles:
                        dd.set_selected(names.index(value))
        finally:
            self.syncing = False


# --- the sidebar -----------------------------------------------------------------------

def _section(title):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_bottom=18)
    box.append(Gtk.Label(label=title, xalign=0, css_classes=["ace-inspector-heading"]))
    return box


def _row(label, widget):
    row = Gtk.Box(spacing=8)
    row.append(Gtk.Label(label=label, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END))
    row.append(widget)
    return row


class Inspector(Gtk.Box):
    """Format sidebar: tabs chosen by document kind."""
    __gtype_name__ = "AceInspector"

    def __init__(self, win, fmt):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["ace-inspector"])
        self.win, self.fmt = win, fmt
        kind = win.kind
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vhomogeneous=False,
                               vexpand=True)
        switcher = Gtk.StackSwitcher(stack=self.stack, halign=Gtk.Align.CENTER, margin_top=10, margin_bottom=6)
        self.append(switcher)
        self.append(self.stack)

        if kind == "text":
            self._add("text", "Text", self._text_page())
            self.page_setup = PageSetup(win)
            self._add("document", "Document", self._wrap(self.page_setup))
        elif kind == "spreadsheet":
            self._add("cell", "Cell", self._cell_page())
            self.page_setup = PageSetup(win, heading="Printing")
            self._add("sheet", "Sheet", self._sheet_page())
        else:
            self._add("text", "Text", self._text_page())
            self.page_setup = None

        self.stack.connect("notify::visible-child-name", self._on_tab)

    def _add(self, name, title, child):
        self.stack.add_titled(Gtk.ScrolledWindow(child=child, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                                 vexpand=True), name, title)

    @staticmethod
    def _wrap(*children):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=16, margin_end=16, margin_top=10)
        for c in children:
            box.append(c)
        return box

    def _on_tab(self, *_):
        if self.page_setup and self.stack.get_visible_child_name() in ("document", "sheet"):
            self.page_setup.refresh()

    def refresh(self):
        self._on_tab()

    def _text_page(self):
        fmt = self.fmt
        style = _section("Paragraph Style")
        style.append(fmt.style_dropdown())

        font = _section("Font")
        font.append(fmt.font_dropdown(width=-1))
        row = Gtk.Box(spacing=8)
        row.append(fmt.emphasis())
        row.append(Gtk.Box(hexpand=True))
        row.append(fmt.size_spin())
        font.append(row)
        font.append(_row("Color", fmt.colors(self.win.kind)))

        para = _section("Alignment & Spacing")
        para.append(fmt.alignment(self.win.kind))
        spacing = Gtk.DropDown.new_from_strings(["Single", "1.5", "Double"])
        spacing.connect("notify::selected", lambda d, _p: fmt.send(
            [".uno:SpacePara1", ".uno:SpacePara15", ".uno:SpacePara2"][d.get_selected()]))
        para.append(_row("Line spacing", spacing))
        para.append(_row("Indent", fmt.group(
            fmt.button("format-indent-less-symbolic", tooltip="Decrease indent", command=".uno:DecrementIndent"),
            fmt.button("format-indent-more-symbolic", tooltip="Increase indent", command=".uno:IncrementIndent"))))
        if self.win.kind == "text":
            para.append(_row("Lists", fmt.group(
                fmt.toggle("view-list-bullet-symbolic", tooltip="Bulleted list", command=".uno:DefaultBullet"),
                fmt.toggle("view-list-ordered-symbolic", tooltip="Numbered list", command=".uno:DefaultNumbering"))))
        return self._wrap(style, font, para)

    def _cell_page(self):
        fmt = self.fmt
        font = _section("Text")
        font.append(fmt.font_dropdown(width=-1))
        row = Gtk.Box(spacing=8)
        row.append(fmt.emphasis(strike=False))
        row.append(Gtk.Box(hexpand=True))
        row.append(fmt.size_spin())
        font.append(row)
        font.append(_row("Color", fmt.colors("spreadsheet")))
        font.append(_row("Alignment", fmt.alignment("spreadsheet")))
        font.append(_row("Wrap text", fmt.toggle("format-text-direction-symbolic", tooltip="Wrap text in cell",
                                                 command=".uno:WrapText")))

        number = _section("Number Format")
        formats = [("General", ".uno:NumberFormatStandard"), ("Number", ".uno:NumberFormatDecimal"),
                   ("Currency", ".uno:NumberFormatCurrency"), ("Percent", ".uno:NumberFormatPercent"),
                   ("Date", ".uno:NumberFormatDate"), ("Scientific", ".uno:NumberFormatScientific")]
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, homogeneous=True,
                           column_spacing=4, row_spacing=4)
        for label, cmd in formats:
            grid.append(fmt.toggle(label=label, tooltip=label, command=cmd))
        number.append(grid)
        number.append(_row("Decimal places", fmt.group(
            fmt.button(label="−.0", tooltip="Fewer decimal places", command=".uno:NumberFormatDecDecimals"),
            fmt.button(label="+.0", tooltip="More decimal places", command=".uno:NumberFormatIncDecimals"))))

        cells = _section("Cells")
        cells.append(_row("Merge cells", fmt.toggle(label="Merge", tooltip="Merge and center",
                                                    command=".uno:ToggleMergeCells")))
        return self._wrap(font, number, cells)

    def _sheet_page(self):
        view = _section("View")
        self.grid_switch = Gtk.Switch(valign=Gtk.Align.CENTER, tooltip_text="Show gridlines on this sheet")
        self.grid_switch.connect("notify::active", self._on_grid_switch)
        view.append(_row("Gridlines", self.grid_switch))
        headers = Gtk.Switch(active=True, valign=Gtk.Align.CENTER)
        headers.connect("notify::active", lambda s, _p: self.win.show_sheet_headers(s.get_active()))
        view.append(_row("Row & column headers", headers))
        return self._wrap(view, self.page_setup)

    def _on_grid_switch(self, switch, _pspec):
        if self.fmt.syncing:
            return
        if switch.get_active() != self.win.grid_visible:
            self.fmt.send(".uno:ToggleSheetGrid", refocus=False)

    def on_state(self, command, value):
        if command == ".uno:ToggleSheetGrid" and hasattr(self, "grid_switch"):
            self.fmt.syncing = True
            self.grid_switch.set_active(value == "true")
            self.fmt.syncing = False


class PageSetup(Gtk.Box):
    """Paper size, orientation and margins for the current page style.

    LibreOfficeKit has no dialog-free command for margins, so this reads and
    writes the page style through AceOffice's macros (aceoffice/macros/Page.bas).
    """
    __gtype_name__ = "AcePageSetup"

    def __init__(self, win, heading="Page"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.units = Units()
        self.page = None       # (width, height, landscape, left, right, top, bottom) in 1/100 mm
        self._syncing = False
        self._apply_source = 0

        paper = _section(heading)
        self.paper = Gtk.DropDown.new_from_strings([p[0] for p in PAPER] + ["Custom"])
        self.paper.connect("notify::selected", self._on_paper)
        paper.append(_row("Paper", self.paper))
        self.portrait = Gtk.ToggleButton(label="Portrait", active=True)
        self.landscape = Gtk.ToggleButton(label="Landscape", group=self.portrait)
        self.landscape.connect("toggled", self._on_orientation)
        paper.append(_row("Orientation", Formatting.group(self.portrait, self.landscape)))
        self.append(paper)

        margins = _section("Margins")
        presets = Gtk.Box(css_classes=["linked"], homogeneous=True)
        for name, values in MARGIN_PRESETS:
            b = Gtk.Button(label=name)
            b.connect("clicked", lambda _b, v=values: self._set_margins(*v))
            presets.append(b)
        margins.append(presets)
        self.spins = {}
        grid = Gtk.Grid(row_spacing=6, column_spacing=8)
        for i, (key, label) in enumerate([("top", "Top"), ("bottom", "Bottom"), ("left", "Left"), ("right", "Right")]):
            spin = Gtk.SpinButton.new_with_range(0, 20 if self.units.inches else 50, self.units.step)
            spin.set_digits(self.units.digits)
            spin.connect("value-changed", self._on_margin_spin)
            self.spins[key] = spin
            cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            cell.append(Gtk.Label(label=f"{label} ({self.units.suffix})", xalign=0, css_classes=["caption", "dim-label"]))
            cell.append(spin)
            grid.attach(cell, i % 2, i // 2, 1, 1)
        margins.append(grid)
        self.append(margins)

    # --- reading ---------------------------------------------------------------------

    def _state_file(self):
        return os.path.join(GLib.get_user_runtime_dir(), f"aceoffice-page-{os.getpid()}-{id(self)}.txt")

    def refresh(self):
        """Ask LibreOffice for the page settings; the macro writes them to a file."""
        path = self._state_file()
        try:
            os.remove(path)
        except OSError:
            pass
        self.win.doc.run_macro(f'Page.GetPage("{path}")')
        waited = [0]

        def poll():
            waited[0] += 50
            try:
                with open(path) as f:
                    values = [int(float(v)) for v in f.read().split()]
                os.remove(path)
            except (OSError, ValueError):
                return waited[0] < 3000
            if len(values) == 7:
                self._show(values)
            return False
        GLib.timeout_add(50, poll)

    def _show(self, values):
        self.page = values
        w, h, landscape, left, right, top, bottom = values
        self._syncing = True
        short, long_ = sorted((w, h))
        index = next((i for i, (_n, pw, ph) in enumerate(PAPER)
                      if abs(pw - short) < 60 and abs(ph - long_) < 60), len(PAPER))
        self.paper.set_selected(index)
        (self.landscape if w > h else self.portrait).set_active(True)
        for key, v in zip(("left", "right", "top", "bottom"), (left, right, top, bottom)):
            self.spins[key].set_value(self.units.to_user(v))
        self._syncing = False

    # --- writing ---------------------------------------------------------------------

    def _set_page(self, width=-1, height=-1, landscape=-1, left=-1, right=-1, top=-1, bottom=-1):
        self.win.doc.run_macro(f"Page.SetPage({width},{height},{landscape},{left},{right},{top},{bottom})")
        self.win.set_modified(True)
        GLib.timeout_add(250, lambda: self.refresh() or False)

    def _on_paper(self, dropdown, _pspec):
        i = dropdown.get_selected()
        if self._syncing or not self.page or i >= len(PAPER):
            return
        _name, w, h = PAPER[i]
        if self.landscape.get_active():
            w, h = h, w
        self._set_page(w, h)

    def _on_orientation(self, *_):
        if self._syncing or not self.page:
            return
        w, h = self.page[0], self.page[1]
        want_landscape = self.landscape.get_active()
        if (w > h) != want_landscape:
            w, h = h, w
        self._set_page(w, h, int(want_landscape))

    def _set_margins(self, top, bottom, left, right):
        self._set_page(left=left, right=right, top=top, bottom=bottom)

    def _on_margin_spin(self, *_):
        if self._syncing or not self.page:
            return
        # Typing a value fires several changes; apply once it settles.
        if self._apply_source:
            GLib.source_remove(self._apply_source)

        def apply():
            self._apply_source = 0
            v = {k: self.units.from_user(s.get_value()) for k, s in self.spins.items()}
            self._set_margins(v["top"], v["bottom"], v["left"], v["right"])
            return False
        self._apply_source = GLib.timeout_add(350, apply)
