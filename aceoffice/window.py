# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The AceOffice window: a start page, then one document per window."""

import json
import os
import shutil
import threading

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from . import lok, recovery
from .docview import DocView
from .headers import SheetHeaders
from .inspector import Formatting, Inspector
from .manager import StartPage, TemplateChooser
from .slides import NotesPane, Presenter, SlideNavigator
from .tools import Tools, tool_button
from .lok import uno_args

KINDS = {
    lok.DOCTYPE_TEXT: "text",
    lok.DOCTYPE_SPREADSHEET: "spreadsheet",
    lok.DOCTYPE_PRESENTATION: "presentation",
}

# Default save format per document kind. Office formats travel best for people
# coming from iWork, who mostly share files with Word/Excel/PowerPoint users.
DEFAULT_EXT = {"text": "docx", "spreadsheet": "xlsx", "presentation": "pptx"}

# Slide layouts (LibreOffice's AutoLayout numbers), as offered by Add Slide and the Slide tab.
LAYOUTS = [("Title", 0), ("Title & Bullets", 1), ("Title & Two Columns", 3), ("Title Only", 19),
           ("Centered Text", 32), ("Blank", 20)]


def private_copy(path):
    """Copy path into AceOffice's cache, for LibreOffice to open without touching the original
    (no lock file beside it, and a read-only original still opens for editing)."""
    import shutil
    import tempfile
    folder = os.path.join(GLib.get_user_cache_dir(), "aceoffice", "open")
    os.makedirs(folder, exist_ok=True)
    fd, copy = tempfile.mkstemp(suffix=os.path.splitext(path)[1], dir=folder)
    os.close(fd)
    shutil.copyfile(path, copy)
    os.chmod(copy, 0o600)
    return copy


# Commands from LibreOffice's own right-click menu that AceOffice passes on, with its labels.
# Only ones that work without a LibreOffice dialog.
CONTEXT_LABELS = {
    ".uno:SpellCheckIgnore": "Ignore Spelling", ".uno:SpellCheckIgnoreAll": "Ignore All",
    ".uno:AddToWordbook": "Learn Spelling",
    ".uno:InsertRowsBefore": "Add Row Above", ".uno:InsertRowsAfter": "Add Row Below",
    ".uno:InsertColumnsBefore": "Add Column Before", ".uno:InsertColumnsAfter": "Add Column After",
    ".uno:DeleteRows": "Delete Row", ".uno:DeleteColumns": "Delete Column", ".uno:DeleteTable": "Delete Table",
    ".uno:MergeCells": "Merge Cells",
    ".uno:BringToFront": "Bring to Front", ".uno:SendToBack": "Send to Back",
    ".uno:ObjectForwardOne": "Bring Forward", ".uno:ObjectBackOne": "Send Backward",
    ".uno:Forward": "Bring Forward", ".uno:Backward": "Send Backward",
    ".uno:HideRow": "Hide Row", ".uno:ShowRow": "Unhide Rows",
    ".uno:HideColumn": "Hide Column", ".uno:ShowColumn": "Unhide Columns",
}


def context_commands(payload):
    """From LibreOffice's context-menu JSON: ([spelling items], [other items]) as (label, command)."""
    try:
        items = json.loads(payload).get("menu", []) if payload else []
    except ValueError:
        items = []
    spelling, extra, seen = [], [], set()

    def walk(entries):
        for e in entries:
            if e.get("type") == "menu":
                walk(e.get("menu", []))
                continue
            command = e.get("command", "")
            name = command.split("?")[0]
            if e.get("enabled") == "false" or command in seen:
                continue
            if name == ".uno:SpellCheckApplySuggestion":
                seen.add(command)
                spelling.append((e.get("text", "").replace("~", ""), command))
            elif name in CONTEXT_LABELS and CONTEXT_LABELS[name] not in [x[0] for x in spelling + extra]:
                seen.add(command)
                (spelling if "Spell" in name or "Wordbook" in name else extra).append((CONTEXT_LABELS[name], command))
    walk(items)
    return spelling[:8], extra


def slides_render(doc):
    """Ubuntu's LibreOffice 26.2.6 paints every slide transparent through LibreOfficeKit
    (issue #1); The Document Foundation's build (which the Flatpak ships) doesn't."""
    w, h = doc.size_twips()
    buf = doc.paint_part_tile(0, 32, 18, 0, 0, w, h) if w and h else b""
    return any(bytes(buf)[3::4])

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

class DocumentWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        size = load_state().get("window", {})
        super().__init__(application=app, default_width=size.get("width", 1100),
                         default_height=size.get("height", 800), maximized=size.get("maximized", False))
        self.app = app
        self.doc = None
        self.view = None
        self.kind = None
        self.path = None
        self.imported_from = None
        self.modified = False
        self._syncing = False
        self.grid_visible = True

        self.title = Adw.WindowTitle(title="AceOffice")
        header = self.header = Adw.HeaderBar(title_widget=self.title)
        self.tools = None

        self.new_button = Gtk.Button(icon_name="document-new-symbolic", action_name="win.choose-template",
                                     tooltip_text="New from a template (Ctrl+N)")
        self.back_button = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text="Back", visible=False)
        self.back_button.connect("clicked", lambda *_: self.show_start())
        header.pack_start(self.back_button)
        self.open_button = Gtk.Button(icon_name="document-open-symbolic", action_name="app.open",
                                      tooltip_text="Open… (Ctrl+O)")
        header.pack_start(self.new_button)
        header.pack_start(self.open_button)

        main_menu = Gio.Menu()
        file_section = Gio.Menu()
        file_section.append("New from Template…", "app.new")
        file_section.append("New Document", "app.new-document")
        file_section.append("New Spreadsheet", "app.new-spreadsheet")
        file_section.append("New Presentation", "app.new-presentation")
        file_section.append("Open…", "app.open")
        file_section.append("Convert iWork Files…", "app.convert-iwork")
        main_menu.append_section(None, file_section)
        file_section = Gio.Menu()
        file_section.append("Save As…", "win.save-as")
        file_section.append("Export as PDF…", "win.export-pdf")
        file_section.append("Print…", "win.print")
        share = Gio.Menu()
        share.append("Email the Document", "win.share-email")
        share.append("Email a PDF", "win.share-email-pdf")
        file_section.append_submenu("Share", share)
        main_menu.append_section(None, file_section)
        view_section = Gio.Menu()
        view_section.append("Zoom In", "win.zoom-in")
        view_section.append("Zoom Out", "win.zoom-out")
        view_section.append("Actual Size", "win.zoom-reset")
        main_menu.append_section(None, view_section)
        view_section.prepend("Find…", "win.find")
        view_section.append("Show Format Bar", "win.show-format-bar")
        app_section = Gio.Menu()
        app_section.append("Keyboard Shortcuts", "app.shortcuts")
        app_section.append("About AceOffice", "app.about")
        main_menu.append_section(None, app_section)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=main_menu,
                                       primary=True, tooltip_text="Main Menu"))
        # Format and Document open the sidebar on its formatting or page tab, as in Pages.
        self.document_button = self._sidebar_toggle("ace-document-symbolic", "Document",
                                                    "Paper, margins and sheet settings")
        self.format_button = self._sidebar_toggle("ace-format-symbolic", "Format", "Format (Ctrl+Shift+F)")
        header.pack_end(self.document_button)
        header.pack_end(self.format_button)
        self.save_button = Gtk.Button(icon_name="document-save-symbolic", action_name="win.save",
                                      tooltip_text="Save (Ctrl+S)", visible=False)
        header.pack_end(self.save_button)
        self._toggling = False
        self.split = None

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.start = StartPage(self, OPEN_PATTERNS)
        self.stack.add_named(self.start, "start")
        self.templates = TemplateChooser(self)
        self.stack.add_named(self.templates, "templates")
        if app.office:
            self.start.refresh()
            self.templates.load_thumbnails(app.office)
        self.template_title = None
        self.loading = Adw.StatusPage(title="Opening…")
        self.loading.set_child(Adw.Spinner() if hasattr(Adw, "Spinner") else Gtk.Spinner(spinning=True))
        self.stack.add_named(self.loading, "loading")
        self.error_page = Adw.StatusPage(icon_name="dialog-error-symbolic", title="Something went wrong")
        back = Gtk.Button(label="Back", halign=Gtk.Align.CENTER, css_classes=["pill"])
        back.connect("clicked", lambda *_: self.show_start())
        self.error_page.set_child(back)
        self.stack.add_named(self.error_page, "error")

        self.toasts = Adw.ToastOverlay(child=self.stack)
        # The header and, once a document is open, its toolbar share one flat, unified bar.
        self.toolbar_view = Adw.ToolbarView(content=self.toasts, top_bar_style=Adw.ToolbarStyle.FLAT,
                                            css_classes=["ace-unified"])
        self.toolbar_view.add_top_bar(header)
        self.set_content(self.toolbar_view)

        for name, cb in [("save", self.save), ("save-as", self.save_as), ("export-pdf", self.export_pdf),
                         ("print", self.print_document), ("share-email", lambda: self.share_by_email(False)),
                         ("share-email-pdf", lambda: self.share_by_email(True)),
                         ("zoom-in", lambda: self._zoom(1.1)), ("zoom-out", lambda: self._zoom(1 / 1.1)),
                         ("zoom-reset", lambda: self._zoom(None)), ("find", self._show_find),
                         ("cut", lambda: self.view.cut()), ("copy", lambda: self.view.copy()),
                         ("paste", lambda: self.view.paste()),
                         ("select-all", lambda: self.doc.uno(".uno:SelectAll")),
                         ("format-panel", lambda: self._on_sidebar_toggle(self.format_button)),
                         ("choose-template", self.show_templates)]:
            action = Gio.SimpleAction(name=name)
            action.connect("activate", lambda _a, _p, cb=cb: cb())
            self.add_action(action)
        show_bar = Gio.SimpleAction.new_stateful("show-format-bar", None,
                                                 GLib.Variant.new_boolean(load_state().get("format_bar", True)))
        show_bar.connect("change-state", self._on_show_format_bar)
        self.add_action(show_bar)
        self.format_bar = None

        # Narrow windows: drop the captions under the toolbar icons.
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 980sp"))
        narrow.connect("apply", lambda *_: self.tools and self.tools.set_labels_visible(False))
        narrow.connect("unapply", lambda *_: self.tools and self.tools.set_labels_visible(True))
        self.add_breakpoint(narrow)
        self._set_doc_actions(False)
        self.connect("close-request", self._on_close_request)

    # --- start page -------------------------------------------------------------

    def show_templates(self):
        if self.doc is not None:
            # One document per window: choose the template in a fresh window.
            self.app.show_templates()
            return
        self.stack.set_visible_child_name("templates")
        self.back_button.set_visible(True)
        self.title.set_title("New")

    def show_start(self):
        self.stack.set_visible_child_name("start")
        self.back_button.set_visible(False)
        self.title.set_title("AceOffice")
        self.start.refresh()

    def office_ready(self, office):
        self.set_engine_status(None)
        if self.doc is None:
            self.start.refresh()
            self.templates.load_thumbnails(office)

    def set_engine_status(self, text):
        self.start.set_engine_status(text)

    def show_error(self, title, message):
        self.error_page.set_title(title)
        self.error_page.set_description(GLib.markup_escape_text(message))
        self.stack.set_visible_child_name("error")

    @property
    def is_empty(self):
        return self.doc is None and self.stack.get_visible_child_name() != "loading"

    # --- loading ------------------------------------------------------------------

    def load(self, office, path=None, kind=None, template=None, title=None, recovered=None):
        """Open path, or start a new document from a template file (or LibreOffice's blank
        document of kind). Runs the load off the UI thread."""
        name = os.path.basename(path) if path else f"new {(title or kind or 'document').lower()}"
        self.loading.set_title(f"Opening {name}…")
        self.stack.set_visible_child_name("loading")
        self.back_button.set_visible(False)
        self.template_title = title if template else None
        # recovered: an entry from recovery.pending(): open its copy, as the document it was.
        self._recovered = recovered
        if recovered:
            template, path = recovered["file"], None
            name = recovered["name"]
            self.loading.set_title(f"Restoring {name}…")

        def work():
            try:
                # A template is opened from a private copy: the installed one may be read-only
                # (the Flatpak), and LibreOffice opens read-only files read-only.
                source = path or (private_copy(template) if template else None)
                doc = office.load(source) if source else office.new(kind)
                doc.initialize_for_rendering(author=GLib.get_real_name() or GLib.get_user_name())
                if doc.doc_type() == lok.DOCTYPE_PRESENTATION and not slides_render(doc):
                    doc.destroy()
                    raise lok.LOKError(
                        "The LibreOffice AceOffice found can't draw slides (Ubuntu's own LibreOffice "
                        "has this bug). The AceOffice Flatpak includes one that can; from a source "
                        "checkout, run tools/dev-runtime.sh. See github.com/androbot9000/aceoffice/issues/1.")
                GLib.idle_add(self._loaded, doc, (recovered or {}).get("original") if recovered else path)
            except Exception as e:  # noqa: BLE001 - shown to the user
                GLib.idle_add(self.show_error, f"Couldn't open {name}", str(e))
        threading.Thread(target=work, daemon=True).start()

    def _loaded(self, doc, path):
        kind = KINDS.get(doc.doc_type(), "text")
        self.doc = doc
        self.kind = kind
        self.path = path
        ext = os.path.splitext(path)[1].lower() if path else ""
        self.imported_from = IMPORT_ONLY.get(ext)
        if self.imported_from:
            # Nothing to write back to; the first save asks where to put the converted copy.
            self.path = None
            self._import_stem = os.path.splitext(path)[0]
        if path and not self._recovered:
            Gtk.RecentManager.get_default().add_item(Gio.File.new_for_path(path).get_uri())
        self.keeper = recovery.Keeper(self)

        self.view = DocView(doc)
        self.view.connect("state-changed", self._on_state_changed)
        self.view.connect("part-changed", lambda _v, n: self._select_part(n))
        self.slides_nav = None
        self.notes = None
        self.view.connect("edited", lambda *_: self._set_modified(True))
        self.view.connect("zoom-changed", lambda _v, z: self.zoom_label.set_label(f"{round(z * 100)}%"))
        self.headers = None

        self.stack.add_named(self._build_editor(), "editor")
        self.stack.set_visible_child_name("editor")
        self._set_doc_actions(True)
        self.save_button.set_visible(True)
        self.format_button.set_visible(True)
        self.document_button.set_visible(True)
        # The document's name moves to the left and the labelled tools take the middle.
        self.new_button.set_visible(False)
        self.open_button.set_visible(False)
        self.header.set_title_widget(self.tools.build())
        self.title.set_halign(Gtk.Align.START)
        self.header.pack_start(self.title)
        if load_state().get("inspector", True):
            self.show_inspector(None)
        self._update_title()
        if self.kind == "text":
            GLib.idle_add(self._initial_fit)
        elif self.kind == "presentation":
            self._add_slide_actions()
            self.view.start_auto_fit()
            self.slides_nav.rebuild()
            self._update_slide_status()
            self.notes.reload()
        self.view.grab_focus()
        if self._recovered:
            # Unsaved until you say so: Save writes over the original, as it would have.
            entry, self._recovered = self._recovered, None
            if not self.path and entry["name"].startswith("Untitled "):
                self.template_title = entry["name"][len("Untitled "):]
            self._set_modified(True)
            self.keeper.touched()
            recovery.discard([entry])
            self.keeper.write()
            self.toasts.add_toast(Adw.Toast(title=f"Restored {entry['name']} with your unsaved changes", timeout=5))
        elif self.imported_from:
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
        self.fmt = Formatting(self)
        self.tools = Tools(self)
        self.format_bar = Gtk.Revealer(child=self._build_format_bar(),
                                       reveal_child=self.lookup_action("show-format-bar").get_state().get_boolean())
        for bar in (self.format_bar,
                    self._build_formula_bar() if self.kind == "spreadsheet" else None,
                    self._build_find_bar()):
            if bar:
                self.toolbar_view.add_top_bar(bar)
        self.view.connect("context-menu", self._on_context_menu)
        self.view.connect("search-not-found", lambda *_: self._set_find_status("Not found"))

        self.scrolled = Gtk.ScrolledWindow(child=self.view, hexpand=True, vexpand=True,
                                           css_classes=["ace-canvas"])
        self.view.attach_scrolled(self.scrolled)
        content = self.scrolled
        if self.kind == "spreadsheet":
            self.headers = SheetHeaders(self.view)
            content = self.headers.grid(self.scrolled)
        elif self.kind == "presentation":
            self.view.center = True
            self.slides_nav = SlideNavigator(self)
            self.slides_nav.connect("slide-activated", lambda _n, i: self.select_slide(i, focus=False))
            self.view.connect("tiles-invalidated", lambda _v, part: self.slides_nav.slide_changed(part))
            self.notes = NotesPane(self)
            self.notes_revealer = Gtk.Revealer(child=self.notes, reveal_child=load_state().get("notes", False),
                                               transition_type=Gtk.RevealerTransitionType.SLIDE_UP)
            editor = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            editor.append(self.scrolled)
            editor.append(self.notes_revealer)
            body = Gtk.Box()
            body.append(self.slides_nav)
            body.append(editor)
            content = body

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main.append(content)
        main.append(self._build_status_bar())

        self.inspector = Inspector(self, self.fmt)
        self.view.connect("object-selected", lambda _v, on: self.inspector.object_selected(on))
        self.view.connect("comment", lambda _v, p: self.inspector.comments and self.inspector.comments.changed(p))
        split = self.split = Adw.OverlaySplitView(
            content=main, sidebar=self.inspector, sidebar_position=Gtk.PackType.END, show_sidebar=False,
            min_sidebar_width=270, max_sidebar_width=320, css_classes=["ace-split"])
        split.connect("notify::show-sidebar", self._on_sidebar_shown)
        self.inspector.stack.connect("notify::visible-child-name", lambda *_: self._sync_sidebar_toggles())
        return split

    # --- sidebar (Format / Document) ----------------------------------------------

    def _sidebar_toggle(self, icon, label, tooltip):
        toggle = tool_button(icon, label, tooltip, toggle=True)
        toggle.set_visible(False)
        toggle.connect("toggled", lambda t: not self._toggling and self._on_sidebar_toggle(t, clicked=True))
        return toggle

    def _tab_for(self, button):
        format_tab = {"text": "text", "spreadsheet": "cell"}.get(self.kind, "text")
        doc_tab = {"text": "document", "spreadsheet": "sheet", "presentation": "slide"}.get(self.kind, format_tab)
        return format_tab if button is self.format_button else doc_tab

    def _on_sidebar_toggle(self, button, clicked=False):
        if not self.split:
            return
        tab = self._tab_for(button)
        showing = self.split.get_show_sidebar() and self.inspector.stack.get_visible_child_name() == tab
        if clicked:
            showing = not button.get_active()
        if showing:
            self.split.set_show_sidebar(False)
        else:
            self.show_inspector(tab)

    def show_inspector(self, tab=None):
        """Open the sidebar, on tab if given ('text', 'document', 'cell', 'sheet', 'comments')."""
        if tab:
            self.inspector.stack.set_visible_child_name(tab)
        self.split.set_show_sidebar(True)
        self._sync_sidebar_toggles()

    def _on_sidebar_shown(self, split, _pspec):
        shown = split.get_show_sidebar()
        if shown:
            self.inspector.refresh()
        save_state(inspector=shown)
        self._sync_sidebar_toggles()

    def _sync_sidebar_toggles(self):
        if not self.split:
            return
        shown = self.split.get_show_sidebar()
        tab = self.inspector.stack.get_visible_child_name()
        self._toggling = True
        self.format_button.set_active(shown and tab == self._tab_for(self.format_button))
        self.document_button.set_active(shown and tab == self._tab_for(self.document_button)
                                        and self.document_button.get_visible())
        self._toggling = False

    def _on_show_format_bar(self, action, value):
        action.set_state(value)
        save_state(format_bar=value.get_boolean())
        if self.format_bar:
            self.format_bar.set_reveal_child(value.get_boolean())

    @staticmethod
    def _group(*buttons):
        return Formatting.group(*buttons)

    def _button(self, icon=None, label=None, tooltip=None):
        return self.fmt.button(icon=icon, label=label, tooltip=tooltip)

    def _build_format_bar(self):
        fmt = self.fmt
        bar = Gtk.Box(spacing=14, css_classes=["toolbar", "ace-toolbar"])
        bar.append(fmt.undo_redo())
        if self.kind == "text":
            bar.append(fmt.style_dropdown())
        fonts = Gtk.Box(spacing=2)
        fonts.append(fmt.font_dropdown())
        fonts.append(fmt.size_dropdown())
        bar.append(fonts)
        bar.append(fmt.emphasis(strike=False))
        bar.append(fmt.colors(self.kind))
        bar.append(fmt.alignment(self.kind))
        if self.kind == "text":
            bar.append(fmt.group(
                fmt.toggle("view-list-bullet-symbolic", tooltip="Bulleted list", command=".uno:DefaultBullet"),
                fmt.toggle("view-list-ordered-symbolic", tooltip="Numbered list", command=".uno:DefaultNumbering")))
        elif self.kind == "spreadsheet":
            bar.append(fmt.group(
                fmt.toggle(label="$", tooltip="Currency", command=".uno:NumberFormatCurrency"),
                fmt.toggle(label="%", tooltip="Percent", command=".uno:NumberFormatPercent"),
                fmt.button(label="Σ", tooltip="Sum", command=".uno:AutoSum")))
        elif self.kind == "presentation":
            add = self._button("list-add-symbolic", tooltip="New slide (Ctrl+Shift+N)")
            add.connect("clicked", lambda *_: self.slide_command("new"))
            bar.append(add)
            bar.append(self._image_button())

        # Narrow windows scroll the toolbar sideways instead of forcing a minimum width.
        return Gtk.ScrolledWindow(child=bar, vscrollbar_policy=Gtk.PolicyType.NEVER,
                                  hscrollbar_policy=Gtk.PolicyType.EXTERNAL, propagate_natural_height=True)

    def show_sheet_headers(self, show):
        if self.headers:
            for w in (self.headers.rows, self.headers.columns, self.headers.corner):
                w.set_visible(show)

    # --- find ---------------------------------------------------------------------

    def _build_find_bar(self):
        self.find_entry = Gtk.SearchEntry(placeholder_text="Find in document", width_chars=30)
        self.find_entry.connect("activate", lambda *_: self._find(backward=False))
        self.find_entry.connect("next-match", lambda *_: self._find(backward=False))
        self.find_entry.connect("previous-match", lambda *_: self._find(backward=True))
        # "changed" fires at once; "search-changed" is delayed and could land after the result.
        self.find_entry.connect("changed", lambda *_: self._set_find_status(""))
        self.find_entry.connect("stop-search", lambda *_: self._hide_find())
        prev_b = Gtk.Button(icon_name="go-up-symbolic", tooltip_text="Previous (Shift+Enter)")
        prev_b.connect("clicked", lambda *_: self._find(backward=True))
        next_b = Gtk.Button(icon_name="go-down-symbolic", tooltip_text="Next (Enter)")
        next_b.connect("clicked", lambda *_: self._find(backward=False))
        self._find_status = Gtk.Label(css_classes=["dim-label", "caption"], width_chars=10)
        box = Gtk.Box(spacing=6)
        box.append(self.find_entry)
        box.append(self._group(prev_b, next_b))
        box.append(self._find_status)
        self.find_bar = Gtk.SearchBar(child=box, show_close_button=True)
        self.find_bar.connect_entry(self.find_entry)
        return self.find_bar

    def _set_find_status(self, text):
        self._find_status.set_label(text)
        if text:
            self.find_entry.add_css_class("error")
        else:
            self.find_entry.remove_css_class("error")

    def _show_find(self):
        text = self.view.doc.selected_text() if self.view else None
        if text and "\n" not in text and len(text) < 100:
            self.find_entry.set_text(text)
        self.find_bar.set_search_mode(True)
        self.find_entry.grab_focus()

    def _hide_find(self):
        self.find_bar.set_search_mode(False)
        self.view.grab_focus()

    def _find(self, backward):
        text = self.find_entry.get_text()
        if not text:
            return
        self._set_find_status("")
        self.doc.uno(".uno:ExecuteSearch", uno_args(**{
            "SearchItem.SearchString": text, "SearchItem.Backward": backward,
            "SearchItem.Command": 0}))

    # --- context menu ------------------------------------------------------------

    def _on_context_menu(self, view, x, y, payload=""):
        menu = Gio.Menu()
        group = Gio.SimpleActionGroup()
        view.insert_action_group("ctx", group)
        spelling, extra = context_commands(payload)
        for n, (items, section) in enumerate(((spelling, Gio.Menu()), (extra, Gio.Menu()))):
            for i, (label, command) in enumerate(items):
                action = Gio.SimpleAction(name=f"c{n}-{i}")
                action.connect("activate", lambda _a, _p, c=command: (self.doc.uno(c), self._set_modified(True),
                                                                      self.view.grab_focus()))
                group.add_action(action)
                section.append(label, f"ctx.c{n}-{i}")
            if items:
                menu.append_section(None, section)
        edit = Gio.Menu()
        edit.append("Cut", "win.cut")
        edit.append("Copy", "win.copy")
        edit.append("Paste", "win.paste")
        menu.append_section(None, edit)
        more = Gio.Menu()
        more.append("Select All", "win.select-all")
        more.append("Find…", "win.find")
        menu.append_section(None, more)
        popover = Gtk.PopoverMenu(menu_model=menu, has_arrow=False, halign=Gtk.Align.START)
        popover.set_parent(view)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        popover.connect("closed", lambda p: GLib.idle_add(p.unparent))
        popover.popup()

    def _build_status_bar(self):
        bar = Gtk.Box(spacing=8, css_classes=["toolbar", "ace-statusbar"])
        if self.kind == "spreadsheet":
            bar.append(self._build_sheet_tabs())
        else:
            self.status_label = Gtk.Label(xalign=0, hexpand=True, css_classes=["dim-label", "caption"],
                                          ellipsize=Pango.EllipsizeMode.END)
            bar.append(self.status_label)
            if self.kind == "presentation":
                notes = Gtk.ToggleButton(label="Presenter Notes", css_classes=["flat", "caption"],
                                         active=load_state().get("notes", False),
                                         tooltip_text="Show or hide this slide's presenter notes")
                notes.connect("toggled", lambda b: self.toggle_notes(b.get_active()))
                self.notes_button = notes
                bar.append(notes)
            self._page_status = self._word_status = ""
        self.zoom_label = Gtk.Button(label="100%", tooltip_text="Actual size (Ctrl+0)",
                                     css_classes=["flat", "numeric", "caption"], action_name="win.zoom-reset")
        out_b = self._button("zoom-out-symbolic", tooltip="Zoom out (Ctrl+−)")
        out_b.connect("clicked", lambda *_: self._zoom(1 / 1.1))
        in_b = self._button("zoom-in-symbolic", tooltip="Zoom in (Ctrl++)")
        in_b.connect("clicked", lambda *_: self._zoom(1.1))
        bar.append(self._group(out_b, self.zoom_label, in_b))
        return bar

    def _image_button(self):
        b = self._button("insert-image-symbolic", tooltip="Insert image…")
        b.connect("clicked", lambda *_: self.insert_image())
        return b

    def _build_formula_bar(self):
        bar = Gtk.Box(spacing=6, css_classes=["toolbar", "ace-toolbar"])
        self.cell_label = Gtk.Label(label="A1", width_chars=8, css_classes=["monospace", "dim-label"])
        bar.append(self.cell_label)
        bar.append(Gtk.Label(label="ƒx", css_classes=["dim-label"]))
        self.formula = Gtk.Entry(hexpand=True, placeholder_text="Value or =formula")
        self.formula.connect("activate", self._on_formula_activate)
        bar.append(self.formula)
        self.view.connect("formula-changed", lambda _v, f: self.formula.set_text(f))
        self.view.connect("cell-address-changed", lambda _v, a: self.cell_label.set_label(a))
        return bar

    def _on_formula_activate(self, entry):
        # Typing into a selected cell replaces its contents; Enter commits it.
        self.view.grab_focus()
        self.view.type_text(entry.get_text())
        self.view.press_key(13, 1280)

    def _build_sheet_tabs(self):
        self.tabs = Gtk.Box(spacing=4)
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New sheet", css_classes=["flat"])
        add.connect("clicked", lambda *_: self._add_sheet())
        row = Gtk.Box(spacing=4, hexpand=True)
        row.append(add)
        row.append(Gtk.ScrolledWindow(child=self.tabs, vscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True))
        self._refresh_parts()
        return row

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
        elif self.kind == "presentation" and self.slides_nav:
            self.slides_nav.rebuild()
            self._update_slide_status()
        self._syncing = False

    def _set_part(self, n):
        if n != self.doc.part():
            self.doc.set_part(n)
            self.view.invalidate_all(keep_showing=False)
            self.view.queue_resize()
        return False

    def _select_part(self, n):
        if self.slides_nav:
            # LibreOffice moved to another slide (Page Down, a new or deleted slide).
            GLib.idle_add(lambda: self.doc and self.slides_nav and (self.slides_nav.rebuild(),
                                                                   self._update_slide_status()) and False)
            return
        GLib.idle_add(self._refresh_parts)

    # --- slides -------------------------------------------------------------------

    def select_slide(self, n, focus=True):
        self._set_part(n)
        self.slides_nav.select(n)
        self._update_slide_status()
        if focus:
            self.view.grab_focus()

    def move_slide(self, source, target):
        """Move slide source to position target (dragged in the navigator)."""
        if source == target or not 0 <= target < self.doc.parts():
            return
        self._set_part(source)
        for _ in range(abs(target - source)):
            self.doc.uno(".uno:MovePageDown" if target > source else ".uno:MovePageUp")
        self._set_modified(True)
        self._notes_stale = True
        GLib.timeout_add(150 + 30 * abs(target - source), self._after_slides_changed)

    def _update_slide_status(self):
        if self.notes and self.doc:
            self.notes.show_slide(self.doc.part())
        if self.kind == "presentation":
            self.status_label.set_label(f"Slide {self.doc.part() + 1} of {self.doc.parts()}")

    def _add_slide_actions(self):
        for name, cb in [("slide-new", lambda: self.slide_command("new")),
                         ("slide-duplicate", lambda: self.slide_command("duplicate")),
                         ("slide-delete", lambda: self.slide_command("delete")),
                         ("slide-up", lambda: self.slide_command("up")),
                         ("slide-down", lambda: self.slide_command("down")),
                         ("play", lambda: self.play()),
                         ("play-beginning", lambda: self.play(0))]:
            action = Gio.SimpleAction(name=name)
            action.connect("activate", lambda _a, _p, cb=cb: cb())
            self.add_action(action)
        layout = Gio.SimpleAction(name="slide-layout", parameter_type=GLib.VariantType.new("i"))
        layout.connect("activate", lambda _a, v: self.set_layout(v.get_int32()))
        self.add_action(layout)
        add = Gio.SimpleAction(name="slide-add", parameter_type=GLib.VariantType.new("i"))
        add.connect("activate", lambda _a, v: self.slide_command("new", layout=v.get_int32()))
        self.add_action(add)

    def slide_command(self, name, layout=None):
        """New, duplicate, delete or move the current slide (Keynote's Slide menu)."""
        if name == "delete" and self.doc.parts() <= 1:
            return
        command = {"new": ".uno:InsertPage", "duplicate": ".uno:DuplicatePage", "delete": ".uno:DeletePage",
                   "up": ".uno:MovePageUp", "down": ".uno:MovePageDown"}[name]
        self.notes.commit()
        self._notes_stale = True
        self.doc.uno(command)
        # LibreOffice runs commands in turn but not at once: the layout goes on the new slide
        # once it exists (and is current).
        self._pending_layout = layout
        self._set_modified(True)
        GLib.timeout_add(150, self._after_slides_changed)

    def set_layout(self, layout):
        page = {"type": "unsigned short", "value": self.doc.part()}
        self.doc.uno(".uno:AssignLayout", json.dumps({"WhatPage": page,
                                                      "WhatLayout": {"type": "unsigned short", "value": layout}}))
        self._set_modified(True)

    def _after_slides_changed(self):
        if not self.doc:
            return False
        layout, self._pending_layout = getattr(self, "_pending_layout", None), None
        if layout is not None:
            self.set_layout(layout)
        self.view.invalidate_all(keep_showing=False)
        self.view.queue_resize()
        self._refresh_parts()
        if getattr(self, "_notes_stale", False):
            self._notes_stale = False
            self.notes.reload()          # the slides' numbers changed
        return False

    def play(self, start=None):
        """Show the slides full screen, from start (default: the current slide)."""
        if self.kind == "presentation":
            self.notes.commit()
            Presenter(self, self.doc.part() if start is None else start)

    def toggle_notes(self, show):
        self.notes_revealer.set_reveal_child(show)
        save_state(notes=show)
        if show:
            self.notes.view.grab_focus()

    def _add_sheet(self):
        n = self.doc.parts()
        self.doc.uno(".uno:Insert", uno_args(Name="", Index=n + 1))
        self._set_modified(True)
        GLib.timeout_add(300, self._after_part_added)

    def _after_part_added(self):
        if not self.doc:
            return False
        self._refresh_parts()
        self._set_part(self.doc.parts() - 1 if self.kind == "spreadsheet" else self.doc.part())
        self._refresh_parts()
        return False

    def insert_image(self):
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
            self.doc.uno(".uno:InsertGraphic", uno_args(FileName=file.get_uri()))
            self._set_modified(True)
        dialog.open(self, None, done)

    def _on_state_changed(self, _view, command, value):
        if command == ".uno:ModifiedStatus":
            self._set_modified(value == "true")
            return
        if command in (".uno:StatePageNumber", ".uno:StateWordCount") and self.kind == "text":
            if command == ".uno:StatePageNumber":
                self._page_status = value
            else:
                self._word_status = value
            self.status_label.set_label("   ·   ".join(v for v in (self._page_status, self._word_status) if v))
            return
        if command == ".uno:ToggleSheetGrid":
            self.grid_visible = value == "true"
            self.inspector.on_state(command, value)
            return
        self.fmt.on_state(command, value)

    def _zoom(self, factor):
        if self.view and factor is None and self.kind == "presentation":
            self.view.start_auto_fit()              # "Actual size" for slides is: fit the window
        elif self.view:
            self.view.set_zoom(1.0 if factor is None else self.view.zoom * factor)

    # --- title / state ------------------------------------------------------------

    def _display_name(self):
        if self.path:
            return os.path.basename(self.path)
        if self.imported_from:
            return os.path.basename(self._import_stem) + f".{DEFAULT_EXT[self.kind]}"
        if self.template_title and self.template_title != "Blank":
            return f"Untitled {self.template_title}"
        return "Untitled"

    def _update_title(self):
        name = self._display_name()
        self.title.set_title(name)
        if self.modified:
            self.title.set_subtitle("Edited")       # as a Mac shows an unsaved document
        elif self.imported_from:
            self.title.set_subtitle(f"Imported from {self.imported_from}")
        elif self.path:
            self.title.set_subtitle(os.path.dirname(self.path).replace(os.path.expanduser("~"), "~"))
        else:
            self.title.set_subtitle("Not saved yet")
        self.set_title(f"{name} — AceOffice")

    def set_modified(self, value):
        self._set_modified(value)

    def _set_modified(self, value):
        keeper = getattr(self, "keeper", None)
        if keeper and value:
            keeper.touched()
        elif keeper:
            keeper.clear()
        if value != self.modified:
            self.modified = value
            self._update_title()

    def _set_doc_actions(self, enabled):
        for name in ("save", "save-as", "export-pdf", "print", "share-email", "share-email-pdf", "zoom-in", "zoom-out", "zoom-reset", "find",
                     "cut", "copy", "paste", "select-all", "format-panel", "show-format-bar"):
            self.lookup_action(name).set_enabled(enabled)

    # --- saving -------------------------------------------------------------------

    def save(self, then=None):
        if not self.path:
            self.save_as(then)
            return
        self._write(self.path, then)

    def _write(self, path, then=None):
        ext = os.path.splitext(path)[1].lstrip(".").lower() or DEFAULT_EXT[self.kind]
        if self.notes:
            self.notes.commit(wait=True)
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
                self.doc.export(path, "pdf")
                self.toasts.add_toast(Adw.Toast(title=f"Exported {os.path.basename(path)}", timeout=2))
            except lok.LOKError as e:
                self.toasts.add_toast(Adw.Toast(title=f"Couldn't export: {e}"))
        dialog.save(self, None, done)

    # --- printing and sharing -------------------------------------------------------

    def _copy_for(self, purpose, pdf):
        """Write a copy of the document as it stands now (unsaved edits included) into
        AceOffice's cache, named like the document, and return its path."""
        if self.notes:
            self.notes.commit(wait=True)
        folder = os.path.join(GLib.get_user_cache_dir(), "aceoffice", purpose)
        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder, exist_ok=True)
        name = self._display_name()
        stem, ext = os.path.splitext(name)
        ext = "pdf" if pdf else (ext.lstrip(".").lower() if self.path else DEFAULT_EXT[self.kind])
        path = os.path.join(folder, f"{stem or 'Untitled'}.{ext}")
        self.doc.export(path, ext)
        return path

    def print_document(self):
        """Print through the system dialog. LibreOffice lays the pages out as a PDF first."""
        try:
            pdf = self._copy_for("print", pdf=True)
        except lok.LOKError as e:
            self.toasts.add_toast(Adw.Toast(title=f"Couldn't prepare for printing: {e}"))
            return
        dialog = Gtk.PrintDialog(title=f"Print {self._display_name()}", modal=True)

        def done(d, res):
            try:
                d.print_file_finish(res)
            except GLib.Error as e:
                if not e.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                    self.toasts.add_toast(Adw.Toast(title=f"Couldn't print: {e.message}"))
        dialog.print_file(self, None, Gio.File.new_for_path(pdf), None, done)

    def share_by_email(self, pdf):
        """A new message in your mail app with this document attached (as it is now)."""
        try:
            path = self._copy_for("share", pdf)
        except lok.LOKError as e:
            self.toasts.add_toast(Adw.Toast(title=f"Couldn't prepare the attachment: {e}"))
            return
        from . import share
        share.email_file(path, self._display_name(),
                         lambda error: error and self.toasts.add_toast(Adw.Toast(title=error, timeout=6)))

    # --- closing --------------------------------------------------------------------

    def _on_close_request(self, _win):
        save_state(window={"width": self.get_width(), "height": self.get_height(),
                           "maximized": self.is_maximized()})
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
        if getattr(self, "keeper", None):
            self.keeper.stop()
            self.keeper = None
        if self.doc:
            self.doc.destroy()
            self.doc = None


# --- small persisted UI state (window size) ------------------------------------------

def _state_path():
    return os.path.join(GLib.get_user_config_dir(), "aceoffice", "state.json")


def load_state():
    try:
        with open(_state_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(**changes):
    state = load_state()
    state.update(changes)
    try:
        os.makedirs(os.path.dirname(_state_path()), exist_ok=True)
        with open(_state_path(), "w") as f:
            json.dump(state, f)
    except OSError:
        pass
