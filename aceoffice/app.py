# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import os
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__, lok  # noqa: E402
from .window import OPEN_PATTERNS, PRESENTATIONS_ENABLED, DocumentWindow  # noqa: E402

APP_ID = "io.github.androbot9000.AceOffice"

CSS = """
.ace-canvas { background-color: #e8e8eb; }
.ace-new-card { min-width: 150px; }
"""


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
        Gtk.Window.set_default_icon_name(APP_ID)

        css = Gtk.CssProvider()
        css.load_from_string(CSS) if hasattr(css, "load_from_string") else css.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        for name, cb, accels in [
            ("new-document", lambda: self.new("text"), ["<Ctrl>n"]),
            ("new-spreadsheet", lambda: self.new("spreadsheet"), []),
            ("new-presentation", lambda: self.new("presentation"), []),
            ("open", self.open_dialog, ["<Ctrl>o"]),
            ("about", self.about, []),
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
                               ("window.close", ["<Ctrl>w"])]:
            self.set_accels_for_action(action, accels)

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
            if isinstance(win, DocumentWindow):
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
        if kind == "presentation" and not PRESENTATIONS_ENABLED:
            return
        win = self._target_window()
        self._with_office(win, lambda: win.load(self.office, kind=kind))

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
