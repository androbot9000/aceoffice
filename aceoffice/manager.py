# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The window you see before opening anything, in the style of Pages' Open window:
places on the left, page thumbnails on the right, and a template chooser for new files."""

import os
import time

from gi.repository import Gio, GLib, Gtk, Pango

from . import thumbs

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

# (id, file, title, kind)
TEMPLATES = {
    "Documents": [("blank", "blank.fodt", "Blank", "text"),
                  ("report", "report.fodt", "Report", "text"),
                  ("letter", "letter.fodt", "Letter", "text"),
                  ("resume", "resume.fodt", "Résumé", "text"),
                  ("essay", "essay.fodt", "Essay", "text")],
    "Spreadsheets": [("blank-sheet", "blank-sheet.fods", "Blank", "spreadsheet"),
                     ("budget", "budget.fods", "Budget", "spreadsheet"),
                     ("checklist", "checklist.fods", "Checklist", "spreadsheet"),
                     ("invoice", "invoice.fods", "Invoice", "spreadsheet")],
}


def template_path(name):
    return os.path.join(TEMPLATE_DIR, name)


def blank_template(kind):
    return template_path({"text": "blank.fodt", "spreadsheet": "blank-sheet.fods"}[kind])


def _when(mtime):
    t = time.localtime(mtime)
    now = time.localtime()
    if t[:3] == now[:3]:
        return "Today, " + time.strftime("%-I:%M %p", t)
    if t.tm_year == now.tm_year:
        return time.strftime("%b %-d", t)
    return time.strftime("%b %-d, %Y", t)


class Thumb(Gtk.Picture):
    """A picture that is always exactly w x h, whatever the image's own size."""
    __gtype_name__ = "AceThumb"

    def __init__(self, w, h):
        super().__init__(content_fit=Gtk.ContentFit.COVER, can_shrink=True, visible=False,
                         halign=Gtk.Align.CENTER, valign=Gtk.Align.START)
        self._size = (w, h)

    def do_measure(self, orientation, _for_size):
        n = self._size[0] if orientation == Gtk.Orientation.HORIZONTAL else self._size[1]
        return n, n, -1, -1


class Card(Gtk.Button):
    """A file or template: a page thumbnail with its name underneath."""
    __gtype_name__ = "AceCard"

    def __init__(self, title, subtitle=None, gicon=None, landscape=False):
        super().__init__(css_classes=["flat", "ace-card"], halign=Gtk.Align.CENTER, valign=Gtk.Align.END)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        w, h = (180, 135) if landscape else (150, 194)
        self.frame = Gtk.Box(css_classes=["ace-thumb"], halign=Gtk.Align.CENTER, valign=Gtk.Align.END,
                             overflow=Gtk.Overflow.HIDDEN)
        self.frame.set_size_request(w, h)
        self.picture = Thumb(w, h)
        self.icon = Gtk.Image(gicon=gicon, pixel_size=48, hexpand=True, vexpand=True,
                              css_classes=["dim-label"]) if gicon else None
        if self.icon:
            self.frame.append(self.icon)
        self.frame.append(self.picture)
        box.append(Gtk.Box(vexpand=True))
        box.append(self.frame)
        box.append(Gtk.Label(label=title, ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=20,
                             css_classes=["ace-card-title"]))
        if subtitle:
            box.append(Gtk.Label(label=subtitle, css_classes=["caption", "dim-label"]))
        self.set_child(box)
        self.title = title

    def set_thumbnail(self, png):
        if not png:
            return False
        self.picture.set_filename(png)
        self.picture.set_visible(True)
        if self.icon:
            self.icon.set_visible(False)
        return False


class StartPage(Gtk.Box):
    """Places and recent files, with thumbnails."""
    __gtype_name__ = "AceStartPage"

    def __init__(self, win, patterns):
        super().__init__()
        self.win = win
        self.app = win.app
        self.exts = tuple(p[1:].lower() for p in patterns)
        self.place = "recent"

        side = Gtk.ListBox(css_classes=["navigation-sidebar"], selection_mode=Gtk.SelectionMode.SINGLE)
        self.places = []
        for key, label, icon in [("recent", "Recents", "document-open-recent-symbolic"),
                                 (GLib.UserDirectory.DIRECTORY_DOCUMENTS, "Documents", "folder-documents-symbolic"),
                                 (GLib.UserDirectory.DIRECTORY_DESKTOP, "Desktop", "user-desktop-symbolic"),
                                 (GLib.UserDirectory.DIRECTORY_DOWNLOAD, "Downloads", "folder-download-symbolic")]:
            if key != "recent" and not GLib.get_user_special_dir(key):
                continue
            row = Gtk.Box(spacing=10, margin_start=4)
            row.append(Gtk.Image(icon_name=icon))
            row.append(Gtk.Label(label=label, xalign=0))
            side.append(row)
            self.places.append(key)
        side.connect("row-selected", self._on_place)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["ace-start-sidebar"])
        sidebar.set_size_request(190, -1)
        sidebar.append(Gtk.Label(label="Locations", xalign=0, css_classes=["ace-sidebar-heading"]))
        sidebar.append(side)
        self.append(sidebar)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        top = Gtk.Box(spacing=12, css_classes=["ace-start-top"])
        self.heading = Gtk.Label(label="Recents", xalign=0, hexpand=True, css_classes=["title-2"])
        top.append(self.heading)
        self.search = Gtk.SearchEntry(placeholder_text="Search", width_chars=18)
        self.search.connect("search-changed", lambda *_: self.grid.invalidate_filter())
        top.append(self.search)
        new = Gtk.Button(label="New Document", css_classes=["suggested-action", "pill", "ace-new-button"],
                         action_name="win.choose-template")
        top.append(new)
        content.append(top)

        self.grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, row_spacing=18,
                                column_spacing=12, max_children_per_line=12, valign=Gtk.Align.START,
                                margin_start=20, margin_end=20, margin_top=6, margin_bottom=24)
        self.grid.set_filter_func(self._filter)
        self.empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER,
                             vexpand=True, visible=False)
        self.empty.append(Gtk.Image(icon_name="x-office-document-symbolic", pixel_size=64,
                                    css_classes=["dim-label"]))
        self.empty_label = Gtk.Label(label="No documents yet", css_classes=["title-3"])
        self.empty.append(self.empty_label)
        self.empty.append(Gtk.Label(label="Create one with New Document, or open a Word, Excel, Pages or "
                                          "Numbers file with Ctrl+O.", css_classes=["dim-label"], wrap=True,
                                    justify=Gtk.Justification.CENTER, max_width_chars=50))
        self.engine_status = Gtk.Label(css_classes=["dim-label", "caption"], visible=False, margin_bottom=8)
        scroller = Gtk.ScrolledWindow(child=self.grid, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        content.append(scroller)
        content.append(self.empty)
        content.append(self.engine_status)
        self.append(content)
        side.select_row(side.get_row_at_index(0))

    # --- listing --------------------------------------------------------------------

    def _on_place(self, _box, row):
        if row is None:
            return
        self.place = self.places[row.get_index()]
        self.refresh()

    def _files(self):
        if self.place == "recent":
            items = [i for i in Gtk.RecentManager.get_default().get_items()
                     if i.get_uri().startswith("file://") and i.get_uri().lower().endswith(self.exts)
                     and i.exists()]
            paths = [Gio.File.new_for_uri(i.get_uri()).get_path() for i in items]
        else:
            folder = GLib.get_user_special_dir(self.place)
            try:
                paths = [os.path.join(folder, n) for n in os.listdir(folder)
                         if n.lower().endswith(self.exts) and not n.startswith((".", "~$", ".~lock"))]
            except OSError:
                paths = []
        files = []
        for p in paths:
            try:
                files.append((os.path.getmtime(p), p))
            except OSError:
                pass
        files.sort(reverse=True)
        return files[:60]

    def refresh(self):
        labels = {"recent": "Recents"}
        self.heading.set_label(labels.get(self.place) or os.path.basename(GLib.get_user_special_dir(self.place)))
        self.grid.remove_all()
        files = self._files()
        for mtime, path in files:
            info = Gio.content_type_guess(path, None)[0]
            landscape = path.lower().endswith((".xlsx", ".xls", ".ods", ".csv", ".numbers"))
            card = Card(os.path.basename(path), _when(mtime), Gio.content_type_get_icon(info), landscape)
            card.path = path
            card.connect("clicked", lambda c: self.app.open_path(c.path, self.win))
            card.set_tooltip_text(path.replace(os.path.expanduser("~"), "~"))
            self.grid.append(card)
            if self.app.office:
                thumbs.request(self.app.office, path, card.set_thumbnail)
        self.empty_label.set_label("No documents yet" if self.place == "recent" else "No documents here")
        self.empty.set_visible(not files)
        self.grid.get_parent().get_parent().set_visible(bool(files))

    def _filter(self, child):
        text = self.search.get_text().strip().casefold()
        return not text or text in child.get_child().title.casefold()

    def set_engine_status(self, text):
        self.engine_status.set_label(text or "")
        self.engine_status.set_visible(bool(text))


class TemplateChooser(Gtk.ScrolledWindow):
    """Choose a template, as in Pages and Numbers."""
    __gtype_name__ = "AceTemplateChooser"

    def __init__(self, win):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.win = win
        self.cards = []
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=28, margin_end=28,
                      margin_top=18, margin_bottom=28)
        box.append(Gtk.Label(label="Choose a Template", xalign=0, css_classes=["title-2"]))
        for section, items in TEMPLATES.items():
            box.append(Gtk.Label(label=section, xalign=0, css_classes=["ace-sidebar-heading"], margin_top=14))
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, row_spacing=14,
                               column_spacing=12, max_children_per_line=8, valign=Gtk.Align.START)
            for tid, name, title, kind in items:
                card = Card(title, gicon=Gio.ThemedIcon.new("x-office-document-symbolic"
                                                            if kind == "text" else "x-office-spreadsheet-symbolic"),
                            landscape=kind == "spreadsheet")
                card.template = (template_path(name), title, kind)
                card.connect("clicked", lambda c: self.win.app.new_from_template(*c.template, reuse=self.win))
                flow.append(card)
                self.cards.append(card)
            box.append(flow)
        self.set_child(box)

    def load_thumbnails(self, office):
        for card in self.cards:
            thumbs.request(office, card.template[0], card.set_thumbnail)
