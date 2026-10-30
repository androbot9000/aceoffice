# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The AceOffice window: a start page, then one document per window."""

import json
import os
import threading

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from . import lok
from .docview import DocView

KINDS = {
    lok.DOCTYPE_TEXT: "text",
    lok.DOCTYPE_SPREADSHEET: "spreadsheet",
    lok.DOCTYPE_PRESENTATION: "presentation",
}

# Default save format per document kind. Office formats travel best for people
# coming from iWork, who mostly share files with Word/Excel/PowerPoint users.
DEFAULT_EXT = {"text": "docx", "spreadsheet": "xlsx", "presentation": "pptx"}

# LibreOfficeKit 26.2 returns blank tiles for slides (see issue #1), so presentations
# are switched off until that's solved. The slide sidebar below is ready for it.
PRESENTATIONS_ENABLED = False

# iWork files open through LibreOffice's importers but can't be written back.
IMPORT_ONLY = {".pages": "Pages", ".numbers": "Numbers", ".key": "Keynote"}

OPEN_PATTERNS = ["*.docx", "*.doc", "*.odt", "*.rtf", "*.txt", "*.pages",
                 "*.xlsx", "*.xls", "*.ods", "*.csv", "*.numbers",
                 "*.pptx", "*.ppt", "*.odp", "*.key"]

SAVE_FORMATS = {
    "text": [("Word Document", "docx"), ("OpenDocument Text", "odt"), ("Rich Text", "rtf"),
             ("Plain Text", "txt")],
    "spreadsheet": [("Excel Workbook", "xlsx"), ("OpenDocument Spreadsheet", "ods"),
                    ("CSV (current sheet)", "csv")],
    "presentation": [("PowerPoint Presentation", "pptx"), ("OpenDocument Presentation", "odp")],
}

PARAGRAPH_STYLES = [("Body", "Default Paragraph Style"), ("Title", "Title"), ("Subtitle", "Subtitle"),
                    ("Heading 1", "Heading 1"), ("Heading 2", "Heading 2"), ("Heading 3", "Heading 3"),
                    ("Quote", "Quotations")]

# Toolbar commands per document kind: (icon or label, tooltip, uno command, toggles).
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


def _uno_args(**kwargs):
    out = {}
    for k, v in kwargs.items():
        t = "long" if isinstance(v, int) else "string"
        out[k] = {"type": t, "value": v}
    return json.dumps(out)


class DocumentWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, default_width=1100, default_height=800)
        self.app = app
        self.doc = None
        self.view = None
        self.kind = None
        self.path = None
        self.imported_from = None
        self.modified = False
        self._syncing = False
        self._toggles = {}
        self._parts_model_part = -1

        self.title = Adw.WindowTitle(title="AceOffice")
        header = Adw.HeaderBar(title_widget=self.title)

        new_menu = Gio.Menu()
        new_menu.append("Document", "app.new-document")
        new_menu.append("Spreadsheet", "app.new-spreadsheet")
        if PRESENTATIONS_ENABLED:
            new_menu.append("Presentation", "app.new-presentation")
        header.pack_start(Gtk.MenuButton(icon_name="document-new-symbolic", menu_model=new_menu,
                                         tooltip_text="New"))
        header.pack_start(Gtk.Button(icon_name="document-open-symbolic", action_name="app.open",
                                     tooltip_text="Open… (Ctrl+O)"))

        main_menu = Gio.Menu()
        file_section = Gio.Menu()
        file_section.append("Save As…", "win.save-as")
        file_section.append("Export as PDF…", "win.export-pdf")
        main_menu.append_section(None, file_section)
        view_section = Gio.Menu()
        view_section.append("Zoom In", "win.zoom-in")
        view_section.append("Zoom Out", "win.zoom-out")
        view_section.append("Actual Size", "win.zoom-reset")
        main_menu.append_section(None, view_section)
        app_section = Gio.Menu()
        app_section.append("About AceOffice", "app.about")
        main_menu.append_section(None, app_section)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=main_menu,
                                       primary=True, tooltip_text="Main Menu"))
        self.save_button = Gtk.Button(icon_name="document-save-symbolic", action_name="win.save",
                                      tooltip_text="Save (Ctrl+S)", visible=False)
        header.pack_end(self.save_button)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self._build_start_page(), "start")
        self.loading = Adw.StatusPage(title="Opening…")
        self.loading.set_child(Adw.Spinner() if hasattr(Adw, "Spinner") else Gtk.Spinner(spinning=True))
        self.stack.add_named(self.loading, "loading")
        self.error_page = Adw.StatusPage(icon_name="dialog-error-symbolic", title="Something went wrong")
        back = Gtk.Button(label="Back", halign=Gtk.Align.CENTER, css_classes=["pill"])
        back.connect("clicked", lambda *_: self.stack.set_visible_child_name("start"))
        self.error_page.set_child(back)
        self.stack.add_named(self.error_page, "error")

        self.toasts = Adw.ToastOverlay(child=self.stack)
        toolbar_view = Adw.ToolbarView(content=self.toasts)
        toolbar_view.add_top_bar(header)
        self.set_content(toolbar_view)

        for name, cb in [("save", self.save), ("save-as", self.save_as), ("export-pdf", self.export_pdf),
                         ("zoom-in", lambda: self._zoom(1.1)), ("zoom-out", lambda: self._zoom(1 / 1.1)),
                         ("zoom-reset", lambda: self._zoom(None))]:
            action = Gio.SimpleAction(name=name)
            action.connect("activate", lambda _a, _p, cb=cb: cb())
            self.add_action(action)
        self._set_doc_actions(False)
        self.connect("close-request", self._on_close_request)

    # --- start page -------------------------------------------------------------

    def _build_start_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24, valign=Gtk.Align.CENTER,
                      halign=Gtk.Align.CENTER, margin_top=36, margin_bottom=36, margin_start=24, margin_end=24)
        box.append(Gtk.Label(label="AceOffice", css_classes=["title-1"]))
        blurb = ("Documents, spreadsheets and presentations. Opens Word, Excel, PowerPoint, "
                 "and your old Pages, Numbers and Keynote files." if PRESENTATIONS_ENABLED else
                 "Documents and spreadsheets. Opens Word and Excel files, "
                 "and your old Pages and Numbers files.")
        box.append(Gtk.Label(label=blurb,
                             css_classes=["dim-label"], wrap=True, justify=Gtk.Justification.CENTER,
                             max_width_chars=60))

        cards = Gtk.Box(spacing=16, halign=Gtk.Align.CENTER, homogeneous=True)
        kinds = [("Document", "x-office-document-symbolic", "app.new-document"),
                 ("Spreadsheet", "x-office-spreadsheet-symbolic", "app.new-spreadsheet")]
        if PRESENTATIONS_ENABLED:
            kinds.append(("Presentation", "x-office-presentation-symbolic", "app.new-presentation"))
        for label, icon, action in kinds:
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=18,
                            margin_bottom=14, margin_start=18, margin_end=18)
            inner.append(Gtk.Image(icon_name=icon, pixel_size=48))
            inner.append(Gtk.Label(label=label, css_classes=["heading"]))
            cards.append(Gtk.Button(child=inner, action_name=action, css_classes=["card", "ace-new-card"]))
        box.append(cards)

        box.append(Gtk.Button(label="Open a File…", action_name="app.open", halign=Gtk.Align.CENTER,
                              css_classes=["pill", "suggested-action"]))

        self.engine_status = Gtk.Label(css_classes=["dim-label", "caption"], visible=False)
        box.append(self.engine_status)

        self.recent_group = Adw.PreferencesGroup(title="Recent")
        self.recent_list = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        self.recent_group.add(self.recent_list)
        box.append(self.recent_group)
        self._fill_recent()

        clamp = Adw.Clamp(maximum_size=640, child=box)
        return Gtk.ScrolledWindow(child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER)

    def _fill_recent(self):
        while (row := self.recent_list.get_first_child()) is not None:
            self.recent_list.remove(row)
        exts = tuple(p[1:] for p in OPEN_PATTERNS)
        items = [i for i in Gtk.RecentManager.get_default().get_items()
                 if i.get_uri().startswith("file://") and i.get_uri().lower().endswith(exts) and i.exists()]
        items.sort(key=lambda i: i.get_modified().to_unix(), reverse=True)
        for item in items[:8]:
            path = Gio.File.new_for_uri(item.get_uri()).get_path()
            row = Adw.ActionRow(title=GLib.markup_escape_text(os.path.basename(path)),
                                subtitle=GLib.markup_escape_text(os.path.dirname(path).replace(os.path.expanduser("~"), "~")),
                                activatable=True)
            row.add_prefix(Gtk.Image(gicon=item.get_gicon()))
            row.connect("activated", lambda _r, p=path: self.app.open_path(p, self))
            self.recent_list.append(row)
        self.recent_group.set_visible(bool(items))

    def set_engine_status(self, text):
        self.engine_status.set_label(text or "")
        self.engine_status.set_visible(bool(text))

    def show_error(self, title, message):
        self.error_page.set_title(title)
        self.error_page.set_description(GLib.markup_escape_text(message))
        self.stack.set_visible_child_name("error")

    @property
    def is_empty(self):
        return self.doc is None and self.stack.get_visible_child_name() != "loading"

    # --- loading ------------------------------------------------------------------

    def load(self, office, path=None, kind=None):
        """Open path, or create a new document of kind. Runs the load off the UI thread."""
        name = os.path.basename(path) if path else f"new {kind}"
        self.loading.set_title(f"Opening {name}…")
        self.stack.set_visible_child_name("loading")

        def work():
            try:
                doc = office.load(path) if path else office.new(kind)
                doc.initialize_for_rendering()
                GLib.idle_add(self._loaded, doc, path)
            except Exception as e:  # noqa: BLE001 - shown to the user
                GLib.idle_add(self.show_error, f"Couldn't open {name}", str(e))
        threading.Thread(target=work, daemon=True).start()

    def _loaded(self, doc, path):
        kind = KINDS.get(doc.doc_type(), "text")
        if kind == "presentation" and not PRESENTATIONS_ENABLED:
            doc.destroy()
            self.show_error("Presentations aren't ready yet",
                            "This early build of AceOffice edits documents and spreadsheets. "
                            "Presentation support (PowerPoint and Keynote) is next. "
                            "Follow github.com/androbot9000/aceoffice/issues/1.")
            return False
        self.doc = doc
        self.kind = kind
        self.path = path
        ext = os.path.splitext(path)[1].lower() if path else ""
        self.imported_from = IMPORT_ONLY.get(ext)
        if self.imported_from:
            # Nothing to write back to; the first save asks where to put the converted copy.
            self.path = None
            self._import_stem = os.path.splitext(path)[0]
        if path:
            Gtk.RecentManager.get_default().add_item(Gio.File.new_for_path(path).get_uri())

        self.view = DocView(doc)
        self.view.connect("state-changed", self._on_state_changed)
        self.view.connect("part-changed", lambda _v, n: self._select_part(n))
        self.view.connect("edited", lambda *_: self._set_modified(True))
        self.view.connect("zoom-changed", lambda _v, z: self.zoom_label.set_label(f"{round(z * 100)}%"))

        self.stack.add_named(self._build_editor(), "editor")
        self.stack.set_visible_child_name("editor")
        self._set_doc_actions(True)
        self.save_button.set_visible(True)
        self._update_title()
        if self.kind == "text":
            GLib.idle_add(self._initial_fit)
        self.view.grab_focus()
        if self.imported_from:
            self.toasts.add_toast(Adw.Toast(title=f"Imported from {self.imported_from}. "
                                                  f"Saving will create a {DEFAULT_EXT[self.kind]} copy.",
                                            timeout=6))
        return False

    def _initial_fit(self):
        width = self.scrolled.get_width()
        if width > 0 and self.view:
            page_px = self.view.doc.size_twips()[0] / 15
            if page_px + 64 > width:
                self.view.fit_width(width)
        return False

    # --- editor -------------------------------------------------------------------

    def _build_editor(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(self._build_format_bar())
        if self.kind == "spreadsheet":
            outer.append(self._build_formula_bar())

        self.scrolled = Gtk.ScrolledWindow(child=self.view, hexpand=True, vexpand=True,
                                           css_classes=["ace-canvas"])
        self.view.attach_scrolled(self.scrolled)

        body = Gtk.Box(vexpand=True)
        if self.kind == "presentation":
            body.append(self._build_slide_sidebar())
            body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        body.append(self.scrolled)
        outer.append(body)

        if self.kind == "spreadsheet":
            outer.append(Gtk.Separator())
            outer.append(self._build_sheet_tabs())
        return outer

    def _button(self, icon=None, label=None, tooltip=None, command=None, toggle=False, args=None):
        cls = Gtk.ToggleButton if toggle else Gtk.Button
        b = cls(icon_name=icon, tooltip_text=tooltip, css_classes=["flat"]) if icon else \
            cls(label=label, tooltip_text=tooltip, css_classes=["flat"])
        if command:
            def clicked(_b):
                if self._syncing:
                    return
                self.doc.uno(command, args)
                self._set_modified(True)
                self.view.grab_focus()
            b.connect("toggled" if toggle else "clicked", clicked)
            if toggle:
                self._toggles[command] = b
        return b

    def _group(self, *buttons):
        g = Gtk.Box(css_classes=["linked"])
        for b in buttons:
            g.append(b)
        return g

    def _build_format_bar(self):
        bar = Gtk.Box(spacing=10, margin_start=8, margin_end=8, margin_top=4, margin_bottom=4)
        bar.append(self._group(self._button("edit-undo-symbolic", tooltip="Undo (Ctrl+Z)", command=".uno:Undo"),
                               self._button("edit-redo-symbolic", tooltip="Redo (Ctrl+Shift+Z)", command=".uno:Redo")))

        if self.kind == "text":
            self.style_dropdown = Gtk.DropDown.new_from_strings([s[0] for s in PARAGRAPH_STYLES])
            self.style_dropdown.set_tooltip_text("Paragraph style")
            self.style_dropdown.connect("notify::selected", self._on_style_selected)
            bar.append(self.style_dropdown)

        bar.append(self._group(
            self._button("format-text-bold-symbolic", tooltip="Bold (Ctrl+B)", command=".uno:Bold", toggle=True),
            self._button("format-text-italic-symbolic", tooltip="Italic (Ctrl+I)", command=".uno:Italic", toggle=True),
            self._button("format-text-underline-symbolic", tooltip="Underline (Ctrl+U)",
                         command=".uno:Underline", toggle=True),
            self._button("format-text-strikethrough-symbolic", tooltip="Strikethrough",
                         command=".uno:Strikeout", toggle=True)))
        bar.append(self._group(self._button(label="A−", tooltip="Smaller text", command=".uno:Shrink"),
                               self._button(label="A+", tooltip="Bigger text", command=".uno:Grow")))
        bar.append(self._group(*[self._button(icon, tooltip=tip, command=cmd, toggle=True)
                                 for cmd, icon, tip in ALIGN[self.kind]]))

        if self.kind == "text":
            bar.append(self._group(
                self._button("view-list-bullet-symbolic", tooltip="Bulleted list", command=".uno:DefaultBullet",
                             toggle=True),
                self._button("view-list-ordered-symbolic", tooltip="Numbered list",
                             command=".uno:DefaultNumbering", toggle=True)))
            bar.append(self._image_button())
        elif self.kind == "spreadsheet":
            bar.append(self._group(
                self._button(label="$", tooltip="Currency", command=".uno:NumberFormatCurrency", toggle=True),
                self._button(label="%", tooltip="Percent", command=".uno:NumberFormatPercent", toggle=True),
                self._button(label="Σ", tooltip="Sum", command=".uno:AutoSum")))
        elif self.kind == "presentation":
            add = self._button("list-add-symbolic", tooltip="New slide")
            add.connect("clicked", lambda *_: self._add_slide())
            bar.append(add)
            bar.append(self._image_button())

        bar.append(Gtk.Box(hexpand=True))
        self.zoom_label = Gtk.Label(label="100%", width_chars=5, css_classes=["numeric"])
        out_b = self._button("zoom-out-symbolic", tooltip="Zoom out (Ctrl+−)")
        out_b.connect("clicked", lambda *_: self._zoom(1 / 1.1))
        in_b = self._button("zoom-in-symbolic", tooltip="Zoom in (Ctrl++)")
        in_b.connect("clicked", lambda *_: self._zoom(1.1))
        bar.append(out_b)
        bar.append(self.zoom_label)
        bar.append(in_b)

        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrap.append(bar)
        wrap.append(Gtk.Separator())
        return wrap

    def _image_button(self):
        b = self._button("insert-image-symbolic", tooltip="Insert image…")
        b.connect("clicked", lambda *_: self._insert_image())
        return b

    def _build_formula_bar(self):
        bar = Gtk.Box(spacing=6, margin_start=8, margin_end=8, margin_top=4, margin_bottom=4)
        self.cell_label = Gtk.Label(label="A1", width_chars=8, css_classes=["monospace", "dim-label"])
        bar.append(self.cell_label)
        bar.append(Gtk.Label(label="ƒx", css_classes=["dim-label"]))
        self.formula = Gtk.Entry(hexpand=True, placeholder_text="Value or =formula")
        self.formula.connect("activate", self._on_formula_activate)
        bar.append(self.formula)
        self.view.connect("formula-changed", lambda _v, f: self.formula.set_text(f))
        self.view.connect("cell-address-changed", lambda _v, a: self.cell_label.set_label(a))
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrap.append(bar)
        wrap.append(Gtk.Separator())
        return wrap

    def _on_formula_activate(self, entry):
        # Typing into a selected cell replaces its contents; Enter commits it.
        self.view.grab_focus()
        self.view.type_text(entry.get_text())
        self.view.press_key(13, 1280)

    def _build_sheet_tabs(self):
        self.tabs = Gtk.Box(spacing=4, margin_start=6, margin_end=6, margin_top=4, margin_bottom=4)
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New sheet", css_classes=["flat"])
        add.connect("clicked", lambda *_: self._add_sheet())
        row = Gtk.Box(spacing=4)
        row.append(add)
        row.append(Gtk.ScrolledWindow(child=self.tabs, vscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True))
        self._refresh_parts()
        return row

    def _build_slide_sidebar(self):
        self.slides = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.slides.connect("row-selected", self._on_slide_selected)
        self._refresh_parts()
        return Gtk.ScrolledWindow(child=self.slides, width_request=190, hscrollbar_policy=Gtk.PolicyType.NEVER)

    def _refresh_parts(self):
        count = self.doc.parts()
        current = self.doc.part()
        self._syncing = True
        if self.kind == "spreadsheet":
            while (c := self.tabs.get_first_child()) is not None:
                self.tabs.remove(c)
            group = None
            for i in range(count):
                b = Gtk.ToggleButton(label=self.doc.part_name(i) or f"Sheet {i + 1}", css_classes=["flat"],
                                     group=group, active=i == current)
                group = group or b
                b.connect("toggled", lambda btn, n=i: btn.get_active() and not self._syncing and self._set_part(n))
                self.tabs.append(b)
        elif self.kind == "presentation":
            self.slides.remove_all()
            for i in range(count):
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6, margin_bottom=6)
                box.append(Gtk.Label(label=str(i + 1), xalign=0, css_classes=["caption", "dim-label"]))
                box.append(Gtk.Label(label=self.doc.part_name(i) or f"Slide {i + 1}", xalign=0,
                                     ellipsize=Pango.EllipsizeMode.END))
                self.slides.append(box)
            row = self.slides.get_row_at_index(current)
            if row:
                self.slides.select_row(row)
        self._syncing = False

    def _set_part(self, n):
        if n != self.doc.part():
            self.doc.set_part(n)
            self.view.invalidate_all(keep_showing=False)
            self.view.queue_resize()
        return False

    def _select_part(self, n):
        GLib.idle_add(self._refresh_parts)

    def _on_slide_selected(self, _list, row):
        if row and not self._syncing:
            self._set_part(row.get_index())
            self.view.grab_focus()

    def _add_slide(self):
        self.doc.uno(".uno:InsertPage")
        self._set_modified(True)
        GLib.timeout_add(300, self._after_part_added)

    def _add_sheet(self):
        n = self.doc.parts()
        self.doc.uno(".uno:Insert", _uno_args(Name="", Index=n + 1))
        self._set_modified(True)
        GLib.timeout_add(300, self._after_part_added)

    def _after_part_added(self):
        self._refresh_parts()
        self._set_part(self.doc.parts() - 1 if self.kind == "spreadsheet" else self.doc.part())
        self._refresh_parts()
        return False

    def _on_style_selected(self, dropdown, _pspec):
        if self._syncing or not self.doc:
            return
        style = PARAGRAPH_STYLES[dropdown.get_selected()][1]
        self.doc.uno(".uno:StyleApply", _uno_args(Style=style, FamilyName="ParagraphStyles"))
        self._set_modified(True)
        self.view.grab_focus()

    def _insert_image(self):
        dialog = Gtk.FileDialog(title="Insert Image")
        f = Gtk.FileFilter(name="Images")
        f.add_mime_type("image/*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        dialog.set_filters(filters)

        def done(d, res):
            try:
                file = d.open_finish(res)
            except GLib.Error:
                return
            self.doc.uno(".uno:InsertGraphic", _uno_args(FileName=file.get_uri()))
            self._set_modified(True)
        dialog.open(self, None, done)

    def _on_state_changed(self, _view, command, value):
        if command == ".uno:ModifiedStatus":
            self._set_modified(value == "true")
            return
        if command == ".uno:StyleApply" and self.kind == "text":
            names = [s[1] for s in PARAGRAPH_STYLES]
            if value in names:
                self._syncing = True
                self.style_dropdown.set_selected(names.index(value))
                self._syncing = False
            return
        button = self._toggles.get(command)
        if button and value in ("true", "false"):
            self._syncing = True
            button.set_active(value == "true")
            self._syncing = False

    def _zoom(self, factor):
        if self.view:
            self.view.set_zoom(1.0 if factor is None else self.view.zoom * factor)

    # --- title / state ------------------------------------------------------------

    def _display_name(self):
        if self.path:
            return os.path.basename(self.path)
        if self.imported_from:
            return os.path.basename(self._import_stem) + f".{DEFAULT_EXT[self.kind]}"
        return {"text": "Untitled Document", "spreadsheet": "Untitled Spreadsheet",
                "presentation": "Untitled Presentation"}[self.kind]

    def _update_title(self):
        name = self._display_name()
        self.title.set_title(("• " if self.modified else "") + name)
        if self.imported_from:
            self.title.set_subtitle(f"Imported from {self.imported_from}")
        elif self.path:
            self.title.set_subtitle(os.path.dirname(self.path).replace(os.path.expanduser("~"), "~"))
        else:
            self.title.set_subtitle("Not saved yet")
        self.set_title(f"{name} — AceOffice")

    def _set_modified(self, value):
        if value != self.modified:
            self.modified = value
            self._update_title()

    def _set_doc_actions(self, enabled):
        for name in ("save", "save-as", "export-pdf", "zoom-in", "zoom-out", "zoom-reset"):
            self.lookup_action(name).set_enabled(enabled)

    # --- saving -------------------------------------------------------------------

    def save(self, then=None):
        if not self.path:
            self.save_as(then)
            return
        self._write(self.path, then)

    def _write(self, path, then=None):
        ext = os.path.splitext(path)[1].lstrip(".").lower() or DEFAULT_EXT[self.kind]
        try:
            # TakeOwnership makes the document adopt the new file and format, like a real Save As,
            # and clears LibreOffice's modified flag.
            self.doc.save_as(path, ext, "TakeOwnership")
        except lok.LOKError as e:
            self.toasts.add_toast(Adw.Toast(title=f"Couldn't save: {e}"))
            return
        self.path = path
        self.imported_from = None
        self._set_modified(False)
        self._update_title()
        Gtk.RecentManager.get_default().add_item(Gio.File.new_for_path(path).get_uri())
        self.toasts.add_toast(Adw.Toast(title=f"Saved {os.path.basename(path)}", timeout=2))
        if then:
            then()

    def _file_dialog(self, title, initial_name, formats):
        dialog = Gtk.FileDialog(title=title, initial_name=initial_name)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        for label, ext in formats:
            f = Gtk.FileFilter(name=f"{label} (.{ext})")
            f.add_suffix(ext)
            filters.append(f)
        dialog.set_filters(filters)
        folder = os.path.dirname(self.path) if self.path else (
            os.path.dirname(self._import_stem) if self.imported_from else
            GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS) or os.path.expanduser("~"))
        dialog.set_initial_folder(Gio.File.new_for_path(folder))
        return dialog

    def save_as(self, then=None):
        formats = SAVE_FORMATS[self.kind]
        stem = os.path.splitext(self._display_name())[0]
        dialog = self._file_dialog("Save As", f"{stem}.{DEFAULT_EXT[self.kind]}", formats)

        def done(d, res):
            try:
                path = d.save_finish(res).get_path()
            except GLib.Error:
                return
            if not os.path.splitext(path)[1]:
                path += "." + DEFAULT_EXT[self.kind]
            self._write(path, then)
        dialog.save(self, None, done)

    def export_pdf(self):
        stem = os.path.splitext(self._display_name())[0]
        dialog = self._file_dialog("Export as PDF", f"{stem}.pdf", [("PDF", "pdf")])

        def done(d, res):
            try:
                path = d.save_finish(res).get_path()
            except GLib.Error:
                return
            try:
                self.doc.save_as(path, "pdf")
                self.toasts.add_toast(Adw.Toast(title=f"Exported {os.path.basename(path)}", timeout=2))
            except lok.LOKError as e:
                self.toasts.add_toast(Adw.Toast(title=f"Couldn't export: {e}"))
        dialog.save(self, None, done)

    # --- closing --------------------------------------------------------------------

    def _on_close_request(self, _win):
        if not (self.doc and self.modified):
            self._dispose_doc()
            return False
        dialog = Adw.AlertDialog(heading=f"Save changes to “{self._display_name()}”?",
                                 body="Your changes will be lost if you don't save them.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("discard", "Don't Save")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def response(_d, r):
            if r == "discard":
                self.modified = False
                self.close()
            elif r == "save":
                self.save(then=self.close)
        dialog.connect("response", response)
        dialog.present(self)
        return True

    def _dispose_doc(self):
        if self.doc:
            self.doc.destroy()
            self.doc = None
