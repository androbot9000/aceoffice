"""Drive AceOffice end to end and save a screenshot after each step.

    tests/smoke.sh OUTDIR

Runs on a headless Broadway display so nothing appears on screen.
"""
import os
import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
from gi.repository import GLib, Gsk, Gtk  # noqa: E402

from aceoffice import app as appmod  # noqa: E402

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
DOCS = os.path.join(os.path.expanduser("~"), "Documents")
app = appmod.AceOfficeApp()
results = []


def shot(win, name):
    paintable = Gtk.WidgetPaintable(widget=win)
    w, h = win.get_width(), win.get_height()
    snap = Gtk.Snapshot()
    paintable.snapshot(snap, w, h)
    node = snap.to_node()
    if node is None:
        print("  (no frame yet for " + name + ")", flush=True)
        return
    renderer = Gsk.CairoRenderer()
    renderer.realize(None)
    tex = renderer.render_texture(node, None)
    tex.save_to_png(os.path.join(OUT, name + ".png"))
    renderer.unrealize()


def check(label, ok):
    results.append((label, bool(ok)))
    print(("PASS " if ok else "FAIL ") + label, flush=True)


def wait(pred, then, timeout=30000):
    left = [timeout]

    def tick():
        if pred():
            GLib.timeout_add(600, lambda: then() or False)  # let tiles render
            return False
        left[0] -= 100
        if left[0] <= 0:
            check("timed out waiting", False)
            finish()
            return False
        return True
    GLib.timeout_add(100, tick)


created = []
_target = app._target_window


def _tracking_target(reuse=None):
    win = _target(reuse)
    if win in created:
        created.remove(win)
    created.append(win)
    return win


app._target_window = _tracking_target


def editor_win():
    return created[-1] if created else app.get_active_window()


def step_start():
    win = app.get_active_window()
    check("engine started", app.office is not None)
    shot(win, "1-start")
    app.new("text")
    wait(lambda: editor_win().doc is not None, step_text)


def step_text():
    win = editor_win()
    v = win.view
    v.grab_focus()
    win.doc.uno(".uno:StyleApply",
                '{"Style":{"type":"string","value":"Title"},"FamilyName":{"type":"string","value":"ParagraphStyles"}}')
    v.type_text("Leaving iCloud behind\n")
    win.doc.uno(".uno:StyleApply",
                '{"Style":{"type":"string","value":"Default Paragraph Style"},"FamilyName":{"type":"string","value":"ParagraphStyles"}}')
    v.type_text("AceOffice opens Word, Excel and PowerPoint files, ")
    win.doc.uno(".uno:Bold")
    v.type_text("and your old Pages files too.")
    win.doc.uno(".uno:Bold")
    GLib.timeout_add(1500, lambda: step_text_shot() or False)


def step_text_shot():
    win = editor_win()
    check("document marked modified", win.modified)
    shot(win, "2-document")
    path = os.path.join(DOCS, "Notes.docx")
    win._write(path)
    check("saved docx", os.path.exists(path) and os.path.getsize(path) > 1000)
    check("modified cleared after save", not win.modified)
    app.new("spreadsheet")
    wait(lambda: editor_win().doc is not None and editor_win().kind == "spreadsheet", step_sheet)


def step_sheet():
    win = editor_win()
    v = win.view
    v.grab_focus()
    v.type_text("Item\tCost\n")
    v.type_text("Rent\t1800\nPhone\t65\nTotal\t=SUM(B2:B3)\n")
    v.press_key(0, 1025)  # up to the total
    v.press_key(0, 1027)
    GLib.timeout_add(1500, lambda: step_sheet_shot() or False)


def step_sheet_shot():
    win = editor_win()
    check("formula bar shows formula", win.formula.get_text().upper() == "=SUM(B2:B3)")
    check("cell address shown", win.cell_label.get_label() not in ("", "A1"))
    print("  formula:", win.formula.get_text(), "cell:", win.cell_label.get_label(), flush=True)
    win._add_sheet()
    GLib.timeout_add(1200, lambda: step_sheet2() or False)


def step_sheet2():
    win = editor_win()
    check("added a second sheet", win.doc.parts() == 2)
    shot(win, "3-spreadsheet")
    win._write(os.path.join(DOCS, "Budget.xlsx"))
    win.view.invalidate_all()
    win._set_part(0)
    GLib.timeout_add(1500, lambda: step_sheet3() or False)


def step_sheet3():
    win = editor_win()
    shot(win, "4-spreadsheet-sheet1")
    first = created[0]
    first.modified = False
    first.close()
    app.open_path(os.path.join(DOCS, "Notes.docx"))
    wait(lambda: editor_win().doc is not None and editor_win().path
         and editor_win().path.endswith("Notes.docx"), step_reopen)


def step_reopen():
    win = editor_win()
    check("reopened saved docx", win.kind == "text")
    shot(win, "5-reopened")
    finish()


def finish():
    for w in app.get_windows():
        if isinstance(w, appmod.DocumentWindow):
            w.modified = False
    failed = [r for r in results if not r[1]]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed", flush=True)
    os._exit(1 if failed else 0)


def on_activate(_app):
    wait(lambda: app.office is not None or app.office_error, step_start, timeout=60000)


app.connect("activate", on_activate)
app.run([sys.argv[0]])
