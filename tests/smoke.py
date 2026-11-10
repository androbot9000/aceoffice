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
    win.show_templates()
    cards = win.templates.cards
    loop_until(lambda: all(c.picture.get_visible() for c in cards), 30000)
    check(f"template thumbnails rendered ({sum(c.picture.get_visible() for c in cards)} of {len(cards)})",
          all(c.picture.get_visible() for c in cards))
    loop_until(lambda: False, 300)
    shot(win, "1b-templates")
    win.show_start()
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


def step_everyday(win):
    """Spelling suggestions on right-click; the copies that Print and Share by Email hand over."""
    from aceoffice import share, window
    v = win.view
    v.type_text(" wrold")
    loop_until(lambda: False, 1500)                 # the spell checker runs in idle time
    x, y, _w, h = v._cursor
    menus = []
    handler = v.connect("context-menu", lambda _v, _x, _y, payload: menus.append(payload))
    v.handler_block_by_func(win._on_context_menu)
    v.context_click(v._offset_x() + (x - 300) * v.ppt, (y + h / 2) * v.ppt)
    loop_until(lambda: menus, 3000)
    v.disconnect(handler)
    v.handler_unblock_by_func(win._on_context_menu)
    spelling, _extra = window.context_commands(menus[0] if menus else "")
    labels = [label for label, _c in spelling]
    check(f"right-click offers spelling suggestions ({labels})", "world" in labels and "Learn Spelling" in labels)
    if spelling:
        win.doc.uno(dict(spelling)["world"])
        loop_until(lambda: False, 400)
        v.press_key(0, 1029)                        # End: drop the selection the correction leaves
        loop_until(lambda: not v._selection, 1000)
    pdf = win._copy_for("print", pdf=True)
    with open(pdf, "rb") as f:
        check(f"Print lays the document out as a PDF ({os.path.basename(pdf)})", f.read(5) == b"%PDF-")
    sent = []
    real, share.email_file = share.email_file, lambda path, subject, done: sent.append((path, subject))
    win.share_by_email(False)
    share.email_file = real
    check(f"Share by Email attaches a copy named like the document ({sent and os.path.basename(sent[0][0])})",
          bool(sent) and os.path.basename(sent[0][0]) == "Untitled.docx" and os.path.getsize(sent[0][0]) > 1000)


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


def step_tools(win):
    """The labelled toolbar: a table, a shape and a comment, then the Comments tab."""
    check("toolbar items are in the title bar", len(win.tools.buttons) >= 6)
    v = win.view
    v.press_key(0, 1030)                     # Ctrl+End would need modifiers; End of line is enough
    v.press_key(13, 1280)
    win.tools.run(".uno:InsertTable", '{"Columns":{"type":"long","value":3},"Rows":{"type":"long","value":2}}')
    loop_until(lambda: False, 600)
    v.press_key(0, 1028)
    win.tools.run(".uno:BasicShapes.round-rectangle", '{"KeyModifier":{"type":"long","value":8192}}')
    loop_until(lambda: False, 600)
    v.press_key(0, 1281)                     # Escape: leave the shape
    loop_until(lambda: False, 300)
    win.tools.run(".uno:InsertAnnotation", '{"Text":{"type":"string","value":"Can we say this more simply?"}}')
    win.show_inspector("comments")
    loop_until(lambda: win.inspector.comments.list.get_first_child() is not None, 4000)
    check("the comment shows in the Comments tab", win.inspector.comments.list.get_first_child() is not None)
    texts = [w.get_label() for w in iter_widgets(win.inspector.comments.list) if isinstance(w, Gtk.Label)]
    check("with its text and author", "Can we say this more simply?" in texts
          and any(t and t != "Unknown" and "Author" not in t for t in texts[:1]))
    check("the Format and Document buttons follow the sidebar",
          not win.format_button.get_active() and not win.document_button.get_active())
    loop_until(lambda: False, 400)
    shot(win, "2f-tools-comments")
    win.show_inspector("text")
    check("Format lights up for the Text tab", win.format_button.get_active())
    v.grab_focus()


def step_arrange(win):
    """Insert a rectangle, resize it by its corner handle, colour it from the Arrange tab."""
    v = win.view
    win.tools.run(".uno:BasicShapes.rectangle", __import__("aceoffice.tools").tools.INSERT_HERE)
    loop_until(lambda: v._graphic, 3000)
    check(f"selecting a shape opens the Arrange tab ({win.inspector.stack.get_visible_child_name()})",
          bool(v._graphic) and win.inspector.stack.get_visible_child_name() == "arrange")
    before = v._graphic
    name, hx, hy = [h for h in v._handles() if h[0] == "se"][0]
    check("the shape has resize handles", v._handle_at(hx + 2, hy - 2) is not None and len(v._handles()) == 8)
    v.doc.graphic_selection(0, *v.to_twips(hx, hy))
    v.doc.graphic_selection(1, *v.to_twips(hx + 60, hy + 40))
    loop_until(lambda: v._graphic and v._graphic[2] != before[2], 3000)
    after = v._graphic
    check(f"dragging a corner handle resizes it ({before[2]}x{before[3]} to {after[2]}x{after[3]} twips)",
          after[2] > before[2] and after[3] > before[3])
    win.inspector._shape_color("Fill", "#ff7800")
    loop_until(lambda: False, 500)
    shot(win, "2g-arrange")
    v.press_key(0, 1281)          # Escape: back to the text
    loop_until(lambda: not v._graphic, 2000)
    check(f"and the sidebar returns to Text afterwards ({win.inspector.stack.get_visible_child_name()})",
          win.inspector.stack.get_visible_child_name() == "text")


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
    check(f"a new document is called Untitled ({win._display_name()})", win._display_name() == "Untitled")
    check(f"status bar shows pages and words ({win.status_label.get_label()!r})",
          "Page 1 of 1" in win.status_label.get_label() and "words" in win.status_label.get_label())
    font = win.fmt._fonts[0].get_selected_item()
    names = win.fmt.font_names()
    check(f"font list loaded, current font shown ({names.get_n_items()} fonts, "
          f"{font.get_string() if font else None})", names.get_n_items() > 5 and font)
    check(f"no blank tiles while typing ({win.view.placeholder_frames} of {win.view.frames} frames)",
          win.view.frames > 20 and win.view.placeholder_frames == 0)
    shot(win, "2-document")
    step_everyday(win)
    step_find_and_menu(win)
    step_page_setup(win)
    step_tools(win)
    step_arrange(win)
    path = os.path.join(DOCS, "Notes.docx")
    win._write(path)
    check("saved docx", os.path.exists(path) and os.path.getsize(path) > 1000)
    import zipfile
    with zipfile.ZipFile(path) as z:
        body = z.read("word/document.xml").decode("utf-8", "replace")
        names = z.namelist()
    check("the table was saved", "<w:tbl>" in body)
    check("the shape was saved", "<wps:wsp" in body or "<v:shape" in body or "<w:drawing>" in body)
    check("the comment was saved", "word/comments.xml" in names)
    check("modified cleared after save", not win.modified)
    app.new("spreadsheet")
    wait(lambda: editor_win().doc is not None and editor_win().kind == "spreadsheet", step_sheet)


def step_sheet():
    win = editor_win()
    check("new spreadsheet shows gridlines", win.grid_visible is True)
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
    cols = win.headers.columns
    width = lambda i: cols.entries[i][2] - cols.entries[i][1]   # noqa: E731
    before = width(0)
    cols.resize(0, before * 2)
    loop_until(lambda: width(0) != before, 3000)
    check(f"dragging a column border resizes the column ({before:.0f} to {width(0):.0f} px)",
          abs(width(0) - before * 2) < 3)
    cols.fit(0)
    loop_until(lambda: abs(width(0) - before * 2) > 3, 3000)
    check(f"double-clicking it fits the contents ({width(0):.0f} px)", width(0) < before * 2 - 3)
    win._add_sheet()
    GLib.timeout_add(1200, lambda: step_sheet2() or False)


def step_sheet2():
    win = editor_win()
    check("added a second sheet", win.doc.parts() == 2)
    check("the new sheet shows gridlines too", win.grid_visible is True)
    win.activate_action("win.format-panel")
    win.inspector.stack.set_visible_child_name("sheet")
    loop_until(lambda: False, 800)
    shot(win, "3b-inspector-sheet")
    win.inspector.grid_switch.set_active(False)
    loop_until(lambda: not win.grid_visible, 2000)
    check("gridlines switch turns them off", win.grid_visible is False)
    win.inspector.grid_switch.set_active(True)
    loop_until(lambda: win.grid_visible, 2000)
    check("and back on", win.grid_visible is True)
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
    from aceoffice.manager import template_path
    app.new_from_template(template_path("slate.fodp"), "Slate", "presentation")
    wait(lambda: editor_win().doc is not None and editor_win().kind == "presentation", step_slides)


def step_slides():
    """A presentation from the Slate template: navigator, editing, slide commands, Play, save."""
    win = editor_win()
    nav = win.slides_nav
    loop_until(lambda: nav.rendered() == 2, 10000)
    check(f"slide navigator shows both slides with thumbnails ({nav.rendered()} of {win.doc.parts()})",
          win.doc.parts() == 2 and nav.rendered() == 2)
    loop_until(lambda: False, 800)
    w, h = win.view._doc_px()
    check(f"the slide fits the window ({w}x{h} in {win.scrolled.get_width()}x{win.scrolled.get_height()})",
          0 < w <= win.scrolled.get_width() and 0 < h <= win.scrolled.get_height())
    check(f"status bar shows the slide ({win.status_label.get_label()!r})",
          win.status_label.get_label() == "Slide 1 of 2")
    # Tab selects the first object (the title), Enter edits its text.
    v = win.view
    v.grab_focus()
    # LibreOffice handles keys and commands asynchronously; give each a moment.
    for step in (lambda: v.press_key(0, 1282), lambda: v.press_key(13, 1280),
                 lambda: win.doc.uno(".uno:SelectAll"), lambda: v.type_text("Leaving iCloud behind"),
                 lambda: v.press_key(0, 1281), lambda: v.press_key(0, 1281)):     # Tab, Enter, …, Escape
        step()
        loop_until(lambda: False, 250)
    win.lookup_action("slide-add").activate(GLib.Variant.new_int32(1))
    loop_until(lambda: win.doc.parts() == 3 and len(nav.pictures) == 3, 5000)
    check(f"Add Slide adds a slide after the current one ({win.doc.parts()} slides, on {win.doc.part() + 1})",
          win.doc.parts() == 3 and win.doc.part() == 1)
    win.activate_action("win.slide-duplicate")
    loop_until(lambda: len(nav.pictures) == 4, 5000)
    win.activate_action("win.slide-delete")
    loop_until(lambda: len(nav.pictures) == 3, 5000)
    check(f"duplicate and delete ({win.doc.parts()} slides, navigator {len(nav.pictures)})",
          win.doc.parts() == 3 and len(nav.pictures) == 3)
    # Drag slide 3 (Agenda) up to second place, as the navigator does on a drop.
    win.move_slide(2, 1)
    loop_until(lambda: win.doc.part_name(1) == "Agenda", 5000)
    check(f"dragging a slide moves it ({[win.doc.part_name(i) for i in range(3)]})",
          win.doc.part_name(1) == "Agenda")
    loop_until(lambda: False, 600)
    win.select_slide(0)
    win.notes_button.set_active(True)
    loop_until(lambda: len(win.notes.texts) == 3, 3000)
    win.notes.view.get_buffer().set_text("Welcome everyone.\nMention the café.")
    loop_until(lambda: False, 1200)
    shot(win, "7-presentation")
    win.show_inspector("slide")
    loop_until(lambda: False, 600)
    shot(win, "7b-presentation-slide-tab")
    from aceoffice.slides import Presenter
    show = Presenter(win, 0, console=True)        # as with a projector attached
    loop_until(lambda: show is not None and show.pictures[show._front].get_paintable() is not None, 5000)
    check("Play opens the slideshow on the first slide",
          show is not None and show.index == 0 and show.pictures[show._front].get_paintable() is not None)
    loop_until(lambda: False, 800)
    if show:
        shot(show, "7c-play")
        shot(show.console, "7d-presenter-display")
        check(f"the presenter display shows this slide's notes ({show.console.notes.get_label()[:17]!r})",
              show.console.notes.get_label().startswith("Welcome everyone.")
              and show.console.next.get_paintable() is not None)
        show.go(1)
        loop_until(lambda: False, 600)
        check("and moves to the next slide", show.index == 1)
        show.finish()
    path = os.path.join(DOCS, "Pitch.pptx")
    win._write(path)
    import zipfile
    with zipfile.ZipFile(path) as z:
        slides = [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
        first = z.read("ppt/slides/slide1.xml").decode("utf-8", "replace")
    check(f"saved pptx with 3 slides ({len(slides)})", len(slides) == 3)
    check("with the new title", "Leaving iCloud behind" in first)
    with zipfile.ZipFile(path) as z:
        notes = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist()
                        if n.startswith("ppt/notesSlides/") and n.endswith(".xml"))
    check("and the presenter notes", "Mention the café." in notes)
    win.modified = False
    win.close()
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
    step_recents()


def step_recents():
    """A fresh window lists the files saved above, with page thumbnails."""
    win = appmod.DocumentWindow(app)
    win.present()
    win.show_start()
    grid = win.start.grid

    def cards():
        out, child = [], grid.get_first_child()
        while child:
            out.append(child.get_child())
            child = child.get_next_sibling()
        return out
    loop_until(lambda: len(cards()) >= 3 and all(c.picture.get_visible() for c in cards()), 20000)
    names = sorted(c.title for c in cards())
    check(f"recent files listed with thumbnails ({names})", "Notes.docx" in names and "Budget.xlsx" in names
          and "Pitch.pptx" in names and all(c.picture.get_visible() for c in cards()))
    loop_until(lambda: False, 400)
    shot(win, "6-start-recents")
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
