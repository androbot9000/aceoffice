# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The labelled toolbar in the title bar (Insert, Table, Chart, Text, Shape, Image,
Comment), in the style of Pages and Numbers.

Every command here works without a LibreOffice dialog: LibreOfficeKit can't show
LibreOffice's own dialogs, so anything that needs input (a link, a comment, a table
size) asks with a small GTK popover and passes the answer as command arguments.
"""

from gi.repository import Adw, Gio, GLib, Gtk

from .lok import uno_args

# KeyModifier=8192 (Ctrl) makes LibreOffice insert a shape or text box at a default
# size in the middle of the view, instead of waiting for the user to drag one out.
INSERT_HERE = uno_args(KeyModifier=8192)

SHAPES = [("Rectangle", ".uno:BasicShapes.rectangle"),
          ("Rounded Rectangle", ".uno:BasicShapes.round-rectangle"),
          ("Oval", ".uno:BasicShapes.ellipse"),
          ("Triangle", ".uno:BasicShapes.isosceles-triangle"),
          ("Arrow", ".uno:BlockArrowShapes.right-arrow"),
          ("Star", ".uno:StarShapes.star5"),
          ("Speech Bubble", ".uno:CalloutShapes.round-rectangular-callout")]

TABLE_MAX = 8   # the size picker's grid


def tool_content(icon, label):
    """An icon with a small caption beneath it, like a Mac toolbar item."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
    box.append(Gtk.Image(icon_name=icon))
    caption = Gtk.Label(label=label, css_classes=["ace-tool-label"])
    box.append(caption)
    return box, caption


def tool_button(icon, label, tooltip=None, menu=None, popover=None, toggle=False):
    box, caption = tool_content(icon, label)
    if toggle:
        b = Gtk.ToggleButton(child=box, tooltip_text=tooltip or label, css_classes=["flat", "ace-tool"])
    elif menu is not None or popover is not None:
        b = Gtk.MenuButton(child=box, tooltip_text=tooltip or label, css_classes=["flat", "ace-tool"],
                           always_show_arrow=False)
        if menu is not None:
            b.set_menu_model(menu)
        else:
            b.set_popover(popover)
    else:
        b = Gtk.Button(child=box, tooltip_text=tooltip or label, css_classes=["flat", "ace-tool"])
    b.caption = caption
    return b


class Tools:
    """Builds the toolbar items for one document window and runs their commands."""

    def __init__(self, win):
        self.win = win
        self.buttons = []

    @property
    def doc(self):
        return self.win.doc

    def run(self, command, args=None):
        self.doc.uno(command, args)
        self.win.set_modified(True)
        self.win.view.grab_focus()

    def _action(self, name, cb):
        action = Gio.SimpleAction(name=name)
        action.connect("activate", lambda *_: cb())
        self.group.add_action(action)

    # --- building ----------------------------------------------------------------

    def build(self):
        kind = self.win.kind
        self.group = Gio.SimpleActionGroup()
        self.win.insert_action_group("tool", self.group)
        box = Gtk.Box(spacing=2, css_classes=["ace-tools"])

        box.append(self._track(tool_button("ace-insert-symbolic", "Insert", menu=self._insert_menu())))
        if kind == "text":
            box.append(self._track(tool_button("ace-table-symbolic", "Table", "Insert a table",
                                               popover=self._table_picker())))
        elif kind == "spreadsheet":
            sort = Gio.Menu()
            sort.append("Sort Ascending", "tool.sort-asc")
            sort.append("Sort Descending", "tool.sort-desc")
            self._action("sort-asc", lambda: self.run(".uno:SortAscending"))
            self._action("sort-desc", lambda: self.run(".uno:SortDescending"))
            box.append(self._track(tool_button("ace-sort-symbolic", "Sort", menu=sort)))
            filt = tool_button("ace-filter-symbolic", "Filter", "Show filter buttons on the column headings")
            filt.connect("clicked", lambda *_: self.run(".uno:DataFilterAutoFilter"))
            box.append(self._track(filt))

        chart = tool_button("ace-chart-symbolic", "Chart", "Insert a chart")
        chart.connect("clicked", lambda *_: self.run(".uno:InsertObjectChart"))
        box.append(self._track(chart))

        text = tool_button("ace-textbox-symbolic", "Text", "Insert a text box")
        text.connect("clicked", lambda *_: self.run(".uno:DrawText", INSERT_HERE))
        box.append(self._track(text))

        shapes = Gio.Menu()
        for i, (label, _cmd) in enumerate(SHAPES):
            shapes.append(label, f"tool.shape-{i}")
            self._action(f"shape-{i}", lambda c=SHAPES[i][1]: self.run(c, INSERT_HERE))
        box.append(self._track(tool_button("ace-shape-symbolic", "Shape", "Insert a shape", menu=shapes)))

        image = tool_button("insert-image-symbolic", "Image", "Insert an image…")
        image.connect("clicked", lambda *_: self.win.insert_image())
        box.append(self._track(image))

        box.append(self._track(tool_button("ace-comment-symbolic", "Comment", "Add a comment",
                                           popover=self._comment_popover())))
        return box

    def _track(self, button):
        self.buttons.append(button)
        return button

    def set_labels_visible(self, visible):
        for b in self.buttons:
            b.caption.set_visible(visible)

    # --- Insert menu -------------------------------------------------------------

    def _insert_menu(self):
        kind = self.win.kind
        menu = Gio.Menu()
        if kind == "text":
            breaks = Gio.Menu()
            breaks.append("Page Break", "tool.page-break")
            self._action("page-break", lambda: self.run(".uno:InsertPagebreak"))
            menu.append_section(None, breaks)
            fields = Gio.Menu()
            fields.append("Page Number", "tool.page-number")
            fields.append("Date", "tool.date")
            fields.append("Footnote", "tool.footnote")
            self._action("page-number", lambda: self.run(".uno:InsertPageNumberField"))
            self._action("date", lambda: self.run(".uno:InsertDateField"))
            self._action("footnote", lambda: self.run(".uno:InsertFootnote"))
            menu.append_section(None, fields)
        else:
            cells = Gio.Menu()
            for label, name, cmd in [("Row Above", "row-above", ".uno:InsertRowsBefore"),
                                     ("Row Below", "row-below", ".uno:InsertRowsAfter"),
                                     ("Column Before", "col-before", ".uno:InsertColumnsBefore"),
                                     ("Column After", "col-after", ".uno:InsertColumnsAfter")]:
                cells.append(label, f"tool.{name}")
                self._action(name, lambda c=cmd: self.run(c))
            menu.append_section(None, cells)
            sums = Gio.Menu()
            sums.append("Sum", "tool.autosum")
            sums.append("Today's Date", "tool.today")
            self._action("autosum", lambda: self.run(".uno:AutoSum"))
            self._action("today", lambda: self.run(".uno:InsertCurrentDate"))
            menu.append_section(None, sums)
        other = Gio.Menu()
        other.append("Link…", "tool.link")
        self._action("link", self._ask_link)
        other.append("Image…", "tool.image")
        self._action("image", self.win.insert_image)
        menu.append_section(None, other)
        return menu

    def _ask_link(self):
        text = self.doc.selected_text() if self.win.kind == "text" else None
        dialog = Adw.AlertDialog(heading="Add Link")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        url = Gtk.Entry(placeholder_text="https://", activates_default=True)
        label = Gtk.Entry(placeholder_text="Text to show", activates_default=True,
                          text=text if text and "\n" not in text else "")
        box.append(url)
        box.append(label)
        dialog.set_extra_child(box)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("add", "Add Link")
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("add")
        dialog.set_close_response("cancel")

        def response(_d, r):
            address = url.get_text().strip()
            if r != "add" or not address:
                return
            if "://" not in address and not address.startswith("mailto:"):
                address = ("mailto:" if "@" in address and "/" not in address else "https://") + address
            self.run(".uno:SetHyperlink", uno_args(**{"Hyperlink.Text": label.get_text() or address,
                                                     "Hyperlink.URL": address}))
        dialog.connect("response", response)
        dialog.present(self.win)
        GLib.idle_add(url.grab_focus)

    # --- table size picker ---------------------------------------------------------

    def _table_picker(self):
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=8, margin_bottom=8,
                      margin_start=8, margin_end=8)
        grid = Gtk.Grid(row_spacing=3, column_spacing=3, css_classes=["ace-table-picker"])
        caption = Gtk.Label(label="Table", css_classes=["caption", "dim-label"])
        cells = {}
        state = {"size": (3, 3)}

        def highlight(cols, rows):
            state["size"] = (cols, rows)
            for (c, r), w in cells.items():
                if c < cols and r < rows:
                    w.add_css_class("on")
                else:
                    w.remove_css_class("on")
            caption.set_label(f"{cols} × {rows}")

        def insert(*_):
            popover.popdown()
            cols, rows = state["size"]
            self.run(".uno:InsertTable", uno_args(Columns=cols, Rows=rows))

        for r in range(TABLE_MAX):
            for c in range(TABLE_MAX):
                cell = Gtk.Button(css_classes=["ace-table-cell"], can_focus=False)
                motion = Gtk.EventControllerMotion()
                motion.connect("enter", lambda *_a, c=c, r=r: highlight(c + 1, r + 1))
                cell.add_controller(motion)
                cell.connect("clicked", insert)
                cells[(c, r)] = cell
                grid.attach(cell, c, r, 1, 1)
        box.append(grid)
        box.append(caption)
        popover.set_child(box)
        popover.connect("show", lambda *_: highlight(3, 3))
        return popover

    # --- comments -------------------------------------------------------------------

    def _comment_popover(self):
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=10, margin_bottom=10,
                      margin_start=10, margin_end=10)
        box.append(Gtk.Label(label="Comment", xalign=0, css_classes=["heading"]))
        view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=6, bottom_margin=6, left_margin=6,
                            right_margin=6, css_classes=["ace-comment-entry"])
        view.set_size_request(260, 80)
        box.append(view)
        add = Gtk.Button(label="Add Comment", css_classes=["suggested-action"], halign=Gtk.Align.END)
        box.append(add)
        popover.set_child(box)

        def submit(*_):
            buf = view.get_buffer()
            text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
            popover.popdown()
            if text:
                self.run(".uno:InsertAnnotation", uno_args(Text=text))
                buf.set_text("")
                self.win.show_inspector("comments")
        add.connect("clicked", submit)
        popover.connect("show", lambda *_: GLib.idle_add(view.grab_focus))
        return popover
