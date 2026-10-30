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
appmod.Adw = __import__('gi.repository.Adw', fromlist=['Adw'])

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
    GLib.timeout_add(1500, lambda: step_typing() or False)


def step_typing():
    """Type one key at a time, like a person, and count frames that showed a blank tile."""
    v = editor_win().view
    v.press_key(13, 1280)
    v.placeholder_frames = v.frames = 0
    keys = list(" Typing should never flash the page.")

    def next_key():
        if not keys:
            GLib.timeout_add(800, lambda: step_text_shot() or False)
            return False
        v.type_text(keys.pop(0))
        return True
    GLib.timeout_add(40, next_key)


def step_find_and_menu(win):
    """Find a word, then search for one that isn't there; and open the colour palette."""
    found = []
    win.view.connect("search-not-found", lambda *_: found.append("missing"))
    win.activate_action("win.find")
    win.find_entry.set_text("Pages")
    win._find(backward=False)
    loop_until(lambda: win.view._selection, 3000)
    check("find selects the match", bool(win.view._selection)
          and (win.doc.selected_text() or "").strip() == "Pages")
    win.find_entry.set_text("zebra")
    win._find(backward=False)
    loop_until(lambda: found, 3000)
    check("find reports a missing word", found == ["missing"] and win._find_status.get_label() == "Not found")
    loop_until(lambda: False, 500)   # let the find bar finish revealing
    check("'Not found' still shown after the entry settles", win._find_status.get_label() == "Not found")
    shot(win, "2b-find")
    win._hide_find()
    for b in iter_widgets(win):
        if isinstance(b, appmod.Adw.SplitButton) and b.get_tooltip_text() == "Highlight":
            b.get_popover().popup()
            loop_until(lambda: False, 400)
            shot(win, "2c-palette")
            b.get_popover().popdown()
            break


def iter_widgets(w):
    child = w.get_first_child()
    while child:
        yield child
        yield from iter_widgets(child)
        child = child.get_next_sibling()


def step_page_setup(win):
    """Open the Format sidebar's Document tab, read the page, apply the Narrow margins."""
    win.activate_action("win.format-panel")
    win.inspector.stack.set_visible_child_name("document")
    ps = win.inspector.page_setup
    loop_until(lambda: ps.page, 4000)
    check(f"page setup read from the document ({ps.page})", ps.page is not None and len(ps.page) == 7)
    before = win.view._cursor
    ps._set_margins(1270, 1270, 1270, 1270)          # the Narrow preset
    loop_until(lambda: ps.page and ps.page[3] == 1270, 4000)
    check(f"narrow margins applied ({ps.page})", ps.page and ps.page[3:] == [1270, 1270, 1270, 1270])
    win.view.press_key(0, 1028)                        # Home, so LibreOffice reports the caret again
    loop_until(lambda: win.view._cursor != before, 2000)
    loop_until(lambda: False, 600)
    shot(win, "2d-inspector-document")
    win.inspector.stack.set_visible_child_name("text")
    loop_until(lambda: False, 300)
    shot(win, "2e-inspector-text")
    win.activate_action("win.format-panel")


def loop_until(pred, ms):
    ctx = GLib.MainContext.default()
    end = GLib.get_monotonic_time() + ms * 1000
    while not pred() and GLib.get_monotonic_time() < end:
        ctx.iteration(False)


def step_text_shot():
    win = editor_win()
    check("document marked modified", win.modified)
    check(f"status bar shows pages and words ({win.status_label.get_label()!r})",
          "Page 1 of 1" in win.status_label.get_label() and "words" in win.status_label.get_label())
    font = win.fmt._fonts[0].get_selected_item()
    names = win.fmt.font_names()
    check(f"font list loaded, current font shown ({names.get_n_items()} fonts, "
          f"{font.get_string() if font else None})", names.get_n_items() > 5 and font)
    check(f"no blank tiles while typing ({win.view.placeholder_frames} of {win.view.frames} frames)",
          win.view.frames > 20 and win.view.placeholder_frames == 0)
    shot(win, "2-document")
    step_find_and_menu(win)
    step_page_setup(win)
    path = os.path.join(DOCS, "Notes.docx")
    win._write(path)
    check("saved docx", os.path.exists(path) and os.path.getsize(path) > 1000)
    check("modified cleared after save", not win.modified)
    app.new("spreadsheet")
    wait(lambda: editor_win().doc is not None and editor_win().kind == "spreadsheet", step_sheet)


def step_sheet():
    win = editor_win()
    loop_until(lambda: win.grid_visible is False, 2000)
    check("new spreadsheet starts without gridlines", win.grid_visible is False)
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
    cols = [e[0] for e in win.headers.columns.entries[:3]]
    rows = [e[0] for e in win.headers.rows.entries[:3]]
    check(f"row and column headers ({cols}, {rows})", cols == ["A", "B", "C"] and rows == ["1", "2", "3"])
    print("  formula:", win.formula.get_text(), "cell:", win.cell_label.get_label(), flush=True)
    win._add_sheet()
    GLib.timeout_add(1200, lambda: step_sheet2() or False)


def step_sheet2():
    win = editor_win()
    check("added a second sheet", win.doc.parts() == 2)
    check("the new sheet has no gridlines either", win.grid_visible is False)
    win.activate_action("win.format-panel")
    win.inspector.stack.set_visible_child_name("sheet")
    loop_until(lambda: False, 800)
    shot(win, "3b-inspector-sheet")
    win.inspector.grid_switch.set_active(True)
    loop_until(lambda: win.grid_visible, 2000)
    check("gridlines switch turns them on", win.grid_visible is True)
    win.inspector.grid_switch.set_active(False)
    loop_until(lambda: not win.grid_visible, 2000)
    win.activate_action("win.format-panel")
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
    try:
        app.shortcuts()
        ok = True
    except Exception as e:  # noqa: BLE001
        print("  shortcuts:", e, flush=True)
        ok = False
    check("keyboard shortcuts dialog opens", ok)
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
