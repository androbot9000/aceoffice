# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import os
import shutil
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__, lok  # noqa: E402
from .widgets import swatch_css  # noqa: E402
from .manager import blank_template  # noqa: E402
from .window import OPEN_PATTERNS, DocumentWindow  # noqa: E402

APP_ID = "io.github.androbot9000.AceOffice"

CSS = """
/* Flat, quiet chrome in the spirit of classic Mac apps: the title bar and toolbar read as
   one surface, controls only show a background on hover, and thin rules separate areas.
   Colours come from the current theme (currentColor), so it follows Adwaita, WhiteSur, etc. */
.ace-toolbar { padding: 2px 8px 4px; }
.ace-toolbar dropdown > button, .ace-toolbar splitbutton > button, .ace-toolbar splitbutton > menubutton > button {
  background: none; box-shadow: none; }
.ace-toolbar dropdown > button:hover, .ace-toolbar splitbutton > button:hover,
.ace-toolbar splitbutton > menubutton > button:hover { background: alpha(currentColor, 0.08); }
.ace-split { border-top: 1px solid alpha(currentColor, 0.12); }
.ace-statusbar { border-top: 1px solid alpha(currentColor, 0.12); padding: 0 6px; min-height: 30px; }
.ace-statusbar button { min-height: 24px; padding-top: 0; padding-bottom: 0; }
.ace-inspector { border-left: 1px solid alpha(currentColor, 0.12); }
.ace-inspector-heading { font-size: 9pt; font-weight: 700; opacity: 0.6; }
/* A slightly deeper shade of the window behind the page. */
.ace-canvas { background-color: alpha(currentColor, 0.07); }
.ace-header { background-color: alpha(currentColor, 0.04); font-size: 9pt; font-feature-settings: "tnum"; }
/* Start window: places on the left, page thumbnails on the right, as in Pages' Open window. */
.ace-start-sidebar { background-color: alpha(currentColor, 0.035); border-right: 1px solid alpha(currentColor, 0.1);
                     padding: 10px 8px; }
.ace-start-sidebar .navigation-sidebar { background: none; }
.ace-sidebar-heading { font-size: 9pt; font-weight: 700; opacity: 0.55; margin: 4px 10px 6px; }
.ace-start-top { padding: 16px 20px 10px; }
.ace-new-button { padding-left: 16px; padding-right: 16px; }
button.ace-card { padding: 8px 6px 6px; border-radius: 10px; }
button.ace-card:hover { background: alpha(currentColor, 0.06); }
.ace-thumb { background-color: white; border-radius: 3px; color: #555;
             box-shadow: 0 0 0 1px alpha(black, 0.12), 0 2px 6px alpha(black, 0.18); }
.ace-card-title { font-weight: 600; font-size: 10pt; }
/* Toolbar items with a caption under the icon, as in Pages and Numbers. */
.ace-tools { margin: 0 6px; }
button.ace-tool { padding: 3px 7px 2px; min-width: 44px; border-radius: 7px; }
button.ace-tool image { -gtk-icon-size: 16px; }
.ace-tool-label { font-size: 8pt; opacity: 0.78; }
button.ace-tool:checked { background: alpha(currentColor, 0.12); }
/* Table size picker */
.ace-table-cell { min-width: 16px; min-height: 16px; padding: 0; border-radius: 3px;
                  background: alpha(currentColor, 0.06); box-shadow: inset 0 0 0 1px alpha(currentColor, 0.18); }
.ace-table-cell.on { background: alpha(@accent_bg_color, 0.35); box-shadow: inset 0 0 0 1px @accent_bg_color; }
/* Comments */
list.ace-comment-list { background: transparent; }
.ace-comment-list > row { padding: 0; margin-bottom: 8px; background: none; }
.ace-comment { padding: 10px 12px 4px; border-radius: 10px; background: alpha(currentColor, 0.05);
               border-left: 3px solid @accent_bg_color; }
.ace-comment-entry { border-radius: 8px; background: alpha(currentColor, 0.05); }
.ace-swatch { min-width: 24px; min-height: 24px; padding: 0; border-radius: 6px;
              box-shadow: inset 0 0 0 1px alpha(black, 0.15); }
/* Presentations: the slide navigator, as in Keynote, and Play. */
.ace-slide-navigator { background-color: alpha(currentColor, 0.035); border-right: 1px solid alpha(currentColor, 0.1); }
list.ace-slide-list { background: transparent; padding: 6px 0; }
.ace-slide-list > row { padding: 0; border-radius: 8px; margin: 0 6px; background: none; }
.ace-slide-list > row:selected { background: none; }
.ace-slide-thumb { border-radius: 3px; background: white;
                   box-shadow: 0 0 0 1px alpha(black, 0.14), 0 1px 3px alpha(black, 0.16); }
.ace-slide-list > row:selected .ace-slide-thumb { box-shadow: 0 0 0 3px @accent_bg_color; }
.ace-slide-list > row:selected label { color: @accent_color; opacity: 1; font-weight: 700; }
window.ace-presenter, window.ace-presenter stack { background: black; }
.ace-presenter-end { color: alpha(white, 0.6); }
.ace-layout-button { padding: 6px 4px; }
.ace-swatch-none { background: linear-gradient(to top right, transparent 46%, #c01c28 48%, #c01c28 52%, transparent 54%); }
"""


SHORTCUTS = [
    ("Files", [("New from a template", "<Ctrl>n"), ("Open", "<Ctrl>o"), ("Save", "<Ctrl>s"),
               ("Save as", "<Ctrl><Shift>s"), ("Export as PDF", "<Ctrl>p"), ("Close window", "<Ctrl>w"),
               ("Quit", "<Ctrl>q")]),
    ("Editing", [("Undo", "<Ctrl>z"), ("Redo", "<Ctrl><Shift>z"), ("Cut", "<Ctrl>x"), ("Copy", "<Ctrl>c"),
                 ("Paste", "<Ctrl>v"), ("Select all", "<Ctrl>a"), ("Find", "<Ctrl>f")]),
    ("Formatting", [("Bold", "<Ctrl>b"), ("Italic", "<Ctrl>i"), ("Underline", "<Ctrl>u")]),
    ("View", [("Zoom in", "<Ctrl>plus"), ("Zoom out", "<Ctrl>minus"), ("Actual size", "<Ctrl>0"),
              ("Keyboard shortcuts", "<Ctrl>question")]),
]


class AceOfficeApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.office = None
        self.office_error = None
        self._waiting = []

    # --- startup --------------------------------------------------------------

    def do_startup(self):
        Adw.Application.do_startup(self)
        GLib.set_application_name("AceOffice")

        # Running from a checkout: find the app icon in data/.
        data = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        if os.path.isdir(data):
            Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(data)
        # AceOffice's own toolbar icons (table, chart, shape, comment, …).
        icons = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(icons)
        Gtk.Window.set_default_icon_name(APP_ID)

        css = Gtk.CssProvider()
        css.load_from_string(CSS + swatch_css())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        for name, cb, accels in [
            ("new", self.show_templates, ["<Ctrl>n"]),
            ("new-document", lambda: self.new("text"), []),
            ("new-spreadsheet", lambda: self.new("spreadsheet"), []),
            ("new-presentation", lambda: self.new("presentation"), []),
            ("open", self.open_dialog, ["<Ctrl>o"]),
            ("about", self.about, []),
            ("shortcuts", self.shortcuts, ["<Ctrl>question"]),
            ("quit", self.quit_all, ["<Ctrl>q"]),
        ]:
            action = Gio.SimpleAction(name=name)
            action.connect("activate", lambda _a, _p, cb=cb: cb())
            self.add_action(action)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)
        for action, accels in [("win.save", ["<Ctrl>s"]), ("win.save-as", ["<Ctrl><Shift>s"]),
                               ("win.export-pdf", ["<Ctrl>p"]), ("win.zoom-in", ["<Ctrl>plus", "<Ctrl>equal"]),
                               ("win.zoom-out", ["<Ctrl>minus"]), ("win.zoom-reset", ["<Ctrl>0"]),
                               ("win.find", ["<Ctrl>f"]), ("win.format-panel", ["<Ctrl><Shift>f"]),
                               # Keynote: Option-Command-P plays; PowerPoint: F5 from the start.
                               ("win.play", ["<Ctrl><Alt>p", "<Shift>F5"]), ("win.play-beginning", ["F5"]),
                               ("win.slide-new", ["<Ctrl><Shift>n"]), ("win.slide-duplicate", ["<Ctrl>d"]),
                               ("window.close", ["<Ctrl>w"])]:
            self.set_accels_for_action(action, accels)

        # Copies of templates opened last time (see window.private_copy).
        shutil.rmtree(os.path.join(GLib.get_user_cache_dir(), "aceoffice", "open"), ignore_errors=True)
        # Starting LibreOffice takes a few seconds; do it while the start page is up.
        threading.Thread(target=self._start_office, daemon=True).start()

    def _start_office(self):
        try:
            office = lok.Office.get()
            GLib.idle_add(self._office_ready, office, None)
        except Exception as e:  # noqa: BLE001 - shown to the user
            GLib.idle_add(self._office_ready, None, str(e))

    def _office_ready(self, office, error):
        self.office, self.office_error = office, error
        for win in self.get_windows():
            if isinstance(win, DocumentWindow) and office:
                win.office_ready(office)
            elif isinstance(win, DocumentWindow):
                win.set_engine_status(None)
        waiting, self._waiting = self._waiting, []
        for fn in waiting:
            fn()
        return False

    def _with_office(self, win, fn):
        """Run fn() once LibreOffice is ready, or show why it can't start."""
        if self.office:
            fn()
        elif self.office_error:
            win.show_error("LibreOffice isn't available", self.office_error)
        else:
            win.set_engine_status("Starting the document engine…")
            self._waiting.append(lambda: fn() if self.office else
                                 win.show_error("LibreOffice isn't available", self.office_error))

    # --- windows --------------------------------------------------------------

    def _target_window(self, reuse=None):
        win = reuse or self.get_active_window()
        if isinstance(win, DocumentWindow) and win.is_empty:
            return win
        win = DocumentWindow(self)
        win.present()
        return win

    def do_activate(self):
        win = self.get_active_window() or DocumentWindow(self)
        win.present()

    def do_open(self, files, n_files, hint):
        for f in files:
            if f.get_path():
                self.open_path(f.get_path())

    def new(self, kind):
        """A blank document of kind ('text', 'spreadsheet' or 'presentation'), from AceOffice's
        Blank template."""
        win = self._target_window()
        try:
            template = blank_template(kind)
        except KeyError:
            template = None
        if template and os.path.exists(template):
            self._with_office(win, lambda: win.load(self.office, template=template, title="Blank"))
        else:
            self._with_office(win, lambda: win.load(self.office, kind=kind))

    def new_from_template(self, path, title, kind, reuse=None):
        win = self._target_window(reuse)
        self._with_office(win, lambda: win.load(self.office, template=path, title=title))

    def show_templates(self):
        win = self._target_window()
        win.show_templates()

    def open_path(self, path, reuse=None):
        for win in self.get_windows():
            if isinstance(win, DocumentWindow) and win.path == path:
                win.present()
                return
        win = self._target_window(reuse)
        self._with_office(win, lambda: win.load(self.office, path=path))

    def open_dialog(self):
        dialog = Gtk.FileDialog(title="Open")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        everything = Gtk.FileFilter(name="All Documents")
        for p in OPEN_PATTERNS:
            everything.add_pattern(p)
            everything.add_pattern(p.upper())
        filters.append(everything)
        iwork = Gtk.FileFilter(name="Pages, Numbers and Keynote")
        for p in ("*.pages", "*.numbers", "*.key"):
            iwork.add_pattern(p)
        filters.append(iwork)
        dialog.set_filters(filters)

        def done(d, res):
            try:
                files = d.open_multiple_finish(res)
            except GLib.Error:
                return
            for i in range(files.get_n_items()):
                self.open_path(files.get_item(i).get_path())
        dialog.open_multiple(self.get_active_window(), None, done)

    def about(self):
        engine = self.office.version() if self.office else None
        details = f"Document engine: LibreOfficeKit\n{engine}" if engine else None
        about = Adw.AboutDialog(application_name="AceOffice", application_icon=APP_ID,
                                version=__version__, license_type=Gtk.License.MPL_2_0,
                                developer_name="AceOffice contributors",
                                website="https://github.com/androbot9000/aceoffice",
                                issue_url="https://github.com/androbot9000/aceoffice/issues",
                                comments="A friendly office suite for people leaving the Apple ecosystem.")
        if details:
            about.set_debug_info(details)
        about.present(self.get_active_window())

    def shortcuts(self):
        dialog = Adw.ShortcutsDialog()
        for title, items in SHORTCUTS:
            section = Adw.ShortcutsSection(title=title)
            for label, accel in items:
                section.add(Adw.ShortcutsItem(title=label, accelerator=accel))
            dialog.add(section)
        dialog.present(self.get_active_window())

    def quit_all(self):
        for win in list(self.get_windows()):
            win.close()


def main():
    app = AceOfficeApp()
    code = app.run(sys.argv)
    # LibreOfficeKit keeps its own threads alive; skip interpreter teardown so exit is instant.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
