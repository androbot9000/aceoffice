# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Presentations: the slide navigator down the left, as in Keynote, and Play.

Slide thumbnails come from LibreOfficeKit's paintPartTile, which renders any slide
without moving the editor to it (about 5 ms a slide), so they're drawn on the main
loop, a few per idle pass, and redrawn when LibreOffice reports that a slide changed.

Play shows the slides full screen with a crossfade between them, drawn by
LibreOffice's slideshow renderer at the screen's own resolution. Animations and the
presentation's own transitions aren't played yet.
"""

import os
import tempfile
import time

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Graphene, Gtk, Pango

THUMB_W = 168            # logical pixels


def _texture(doc, part, px_w):
    """Slide part rendered px_w pixels wide, as a texture."""
    w, h = doc.size_twips()
    if not w or not h:
        return None
    px_h = max(1, round(px_w * h / w))
    buf = doc.paint_part_tile(part, px_w, px_h, 0, 0, w, h)
    return Gdk.MemoryTexture.new(px_w, px_h, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED,
                                 GLib.Bytes.new(bytes(buf)), px_w * 4)


def _show_paintable(doc, slide, px_w):
    """A slide as the show presents it: LibreOffice's slideshow renderer leaves out empty
    placeholders ("Click to add Title"), which the editor's rendering shows."""
    w, h = doc.size_twips()
    px_h = max(1, round(px_w * h / w)) if w else round(px_w * 9 / 16)
    result = doc.render_slide(slide["hash"], slide["index"], px_w, px_h)
    if not result or not result[2]:
        return _texture(doc, slide["index"], px_w)
    rw, rh, layers = result
    snapshot = Gtk.Snapshot()
    rect = Graphene.Rect().init(0, 0, rw, rh)
    for buf in layers:
        snapshot.append_texture(Gdk.MemoryTexture.new(rw, rh, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED,
                                                      GLib.Bytes.new(bytes(buf)), rw * 4), rect)
    return snapshot.to_paintable(Graphene.Size().init(rw, rh))


class SlideNavigator(Gtk.Box):
    """Numbered slide thumbnails. Click to edit a slide; right-click for slide commands."""
    __gtype_name__ = "AceSlideNavigator"

    __gsignals__ = {"slide-activated": (GObject.SignalFlags.RUN_FIRST, None, (int,))}

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["ace-slide-navigator"])
        self.win = win
        self.list = Gtk.ListBox(css_classes=["ace-slide-list"], selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.connect("row-selected", self._on_selected)
        self.pictures = []
        self._stale = set()
        self._source = 0
        self._debounce = 0
        self._syncing = False
        scroller = Gtk.ScrolledWindow(child=self.list, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_size_request(THUMB_W + 52, -1)
        self.scroller = scroller
        self.append(scroller)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.list.add_controller(keys)
        click = Gtk.GestureClick(button=3)
        click.connect("pressed", self._on_right_click)
        self.list.add_controller(click)
        # Drag a slide to a new place in the list.
        drop = Gtk.DropTarget.new(GObject.TYPE_INT, Gdk.DragAction.MOVE)
        drop.connect("drop", self._on_drop)
        self.list.add_controller(drop)

    @property
    def doc(self):
        return self.win.doc

    # --- rows -----------------------------------------------------------------------

    def rebuild(self):
        """Match the rows to the document's slides (after adding, deleting or moving)."""
        if not self.doc:
            return
        count = self.doc.parts()
        self._syncing = True
        while len(self.pictures) > count:
            self.list.remove(self.list.get_row_at_index(len(self.pictures) - 1))
            self.pictures.pop()
        w, h = self.doc.size_twips()
        thumb_h = round(THUMB_W * h / w) if w else round(THUMB_W * 9 / 16)
        while len(self.pictures) < count:
            n = len(self.pictures)
            row = Gtk.Box(spacing=8, margin_top=5, margin_bottom=5, margin_start=6, margin_end=10)
            row.append(Gtk.Label(label=str(n + 1), valign=Gtk.Align.START, width_chars=2, xalign=1,
                                 css_classes=["caption", "dim-label", "numeric"]))
            frame = Gtk.Box(css_classes=["ace-slide-thumb"], overflow=Gtk.Overflow.HIDDEN)
            picture = Gtk.Picture(content_fit=Gtk.ContentFit.FILL, can_shrink=True)
            picture.set_size_request(THUMB_W, thumb_h)
            frame.append(picture)
            row.append(frame)
            drag = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
            drag.connect("prepare", lambda _s, _x, _y, n=n: Gdk.ContentProvider.new_for_value(
                GObject.Value(GObject.TYPE_INT, n)))
            drag.connect("drag-begin", lambda s, _d, p=picture: s.set_icon(p.get_paintable(), 0, 0)
                         if p.get_paintable() else None)
            row.add_controller(drag)
            self.list.append(row)
            self.pictures.append(picture)
        self._syncing = False
        self.select(self.doc.part())
        self.mark_all_stale()

    def select(self, n):
        row = self.list.get_row_at_index(n)
        if row and self.list.get_selected_row() is not row:
            self._syncing = True
            self.list.select_row(row)
            self._syncing = False
            GLib.idle_add(self._scroll_into_view, row)

    def _scroll_into_view(self, row):
        ok, bounds = row.compute_bounds(self.list)
        if ok:
            adj = self.scroller.get_vadjustment()
            top, bottom = bounds.get_y(), bounds.get_y() + bounds.get_height()
            if top < adj.get_value():
                adj.set_value(top)
            elif bottom > adj.get_value() + adj.get_page_size():
                adj.set_value(bottom - adj.get_page_size())
        return False

    def _on_selected(self, _list, row):
        if row and not self._syncing:
            self.emit("slide-activated", row.get_index())

    # --- thumbnails -------------------------------------------------------------------

    def mark_all_stale(self):
        self._stale.update(range(len(self.pictures)))
        self._schedule()

    def slide_changed(self, part):
        """LibreOffice repainted part of a slide: redraw its thumbnail once editing pauses."""
        if 0 <= part < len(self.pictures):
            self._stale.add(part)
            if self._debounce:
                GLib.source_remove(self._debounce)
            self._debounce = GLib.timeout_add(400, self._after_pause)

    def _after_pause(self):
        self._debounce = 0
        self._schedule()
        return False

    def _schedule(self):
        if not self._source:
            self._source = GLib.idle_add(self._render, priority=GLib.PRIORITY_LOW)

    def _render(self):
        self._source = 0
        if not self.doc:
            return False
        scale = self.get_scale_factor()
        for part in sorted(self._stale)[:4]:
            self._stale.discard(part)
            if part < len(self.pictures):
                self.pictures[part].set_paintable(_texture(self.doc, part, THUMB_W * scale))
        if self._stale:
            self._schedule()
        return False

    def rendered(self):
        """Slides that have a thumbnail (for tests)."""
        return sum(1 for p in self.pictures if p.get_paintable() is not None)

    # --- commands ---------------------------------------------------------------------

    def _on_key(self, _ctl, keyval, _code, _state):
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            self.win.slide_command("delete")
            return True
        return False

    def _on_drop(self, _target, source, _x, y):
        row = self.list.get_row_at_y(int(y))
        target = row.get_index() if row else len(self.pictures) - 1
        if target != source:
            self.win.move_slide(source, target)
        return True

    def _on_right_click(self, gesture, _n, x, y):
        row = self.list.get_row_at_y(int(y))
        if row:
            self.list.select_row(row)
        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("New Slide", "win.slide-new")
        section.append("Duplicate Slide", "win.slide-duplicate")
        section.append("Delete Slide", "win.slide-delete")
        menu.append_section(None, section)
        move = Gio.Menu()
        move.append("Move Up", "win.slide-up")
        move.append("Move Down", "win.slide-down")
        menu.append_section(None, move)
        play = Gio.Menu()
        play.append("Play from This Slide", "win.play")
        menu.append_section(None, play)
        popover = Gtk.PopoverMenu(menu_model=menu, has_arrow=False, halign=Gtk.Align.START)
        popover.set_parent(self.list)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        popover.connect("closed", lambda p: GLib.idle_add(p.unparent))
        popover.popup()


class Presenter(Adw.Window):
    """Full-screen slideshow. Arrows, Space, Page Up/Down or a click move between
    slides; Home and End jump; Esc ends the show."""
    __gtype_name__ = "AcePresenter"

    def __init__(self, win, start=0, console=None):
        super().__init__(transient_for=win, modal=True, css_classes=["ace-presenter"],
                         title="Slideshow", decorated=False)
        self.win = win
        self.doc = win.doc
        info = self.doc.presentation_info()
        # The show's slides (hidden ones left out); start at the first at or after `start`.
        self.slides = (info or {}).get("slides") or [{"hash": None, "index": i} for i in range(self.doc.parts())]
        self.count = len(self.slides)
        self.index = next((i for i, sl in enumerate(self.slides) if sl["index"] >= start), 0)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=350,
                               hexpand=True, vexpand=True)
        self.pictures = [Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True) for _ in range(2)]
        for i, p in enumerate(self.pictures):
            self.stack.add_named(p, str(i))
        self.end = Gtk.Label(label="End of slideshow. Click or press Esc to exit.",
                             css_classes=["ace-presenter-end"])
        self.stack.add_named(self.end, "end")
        self.set_content(self.stack)
        self._front = 0
        self._cache = {}
        self.set_cursor_from_name("none")

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        click = Gtk.GestureClick(button=0)
        click.connect("pressed", self._on_click)
        self.add_controller(click)
        self.connect("notify::default-width", lambda *_: self._cache.clear())
        # With a second screen (a projector), the slides go there and this screen shows the
        # presenter display: current and next slide, notes, a clock and a timer.
        self.console = None
        monitors = list(self.get_display().get_monitors())
        here = (self.get_display().get_monitor_at_surface(win.get_surface()) if win.get_surface() else None)
        others = [m for m in monitors if m is not here]
        if console is None:
            console = bool(here and others)
        if console and others:
            self.fullscreen_on_monitor(others[0])
        else:
            self.fullscreen()
        self.present()
        if console:
            self.console = Console(self)
        GLib.idle_add(self._show, False)

    def _width_px(self):
        monitor = self.get_display().get_monitor_at_surface(self.get_surface()) if self.get_surface() else None
        if monitor:
            geo = monitor.get_geometry()
            return int(geo.width * monitor.get_scale())
        return max(1280, self.get_width() * self.get_scale_factor())

    def _texture(self, n):
        if n not in self._cache:
            slide = self.slides[n]
            self._cache[n] = (_show_paintable(self.doc, slide, self._width_px()) if slide["hash"] is not None
                              else _texture(self.doc, slide["index"], self._width_px()))
        return self._cache[n]

    def _show(self, animate=True):
        if self.console:
            self.console.update()
        if self.index >= self.count:
            self.stack.set_visible_child_full("end", Gtk.StackTransitionType.CROSSFADE)
            return False
        self._front ^= 1
        picture = self.pictures[self._front]
        picture.set_paintable(self._texture(self.index))
        self.stack.set_visible_child_full(str(self._front), Gtk.StackTransitionType.CROSSFADE if animate
                                          else Gtk.StackTransitionType.NONE)
        # Render the next slide now, so moving on is instant.
        if self.index + 1 < self.count:
            GLib.idle_add(lambda n=self.index + 1: self._texture(n) and False)
        return False

    def go(self, n):
        n = max(0, min(n, self.count))
        if n != self.index:
            self.index = n
            self._show()

    def finish(self):
        if self.win.view and self.count:
            self.win.select_slide(self.slides[min(self.index, self.count - 1)]["index"])
        if self.console:
            self.console.finish()
        self.close()

    def _on_key(self, _ctl, keyval, _code, _state):
        if keyval in (Gdk.KEY_Escape, Gdk.KEY_q):
            self.finish()
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_Down, Gdk.KEY_space, Gdk.KEY_Page_Down, Gdk.KEY_Return,
                        Gdk.KEY_KP_Enter, Gdk.KEY_n):
            if self.index >= self.count:
                self.finish()
            else:
                self.go(self.index + 1)
        elif keyval in (Gdk.KEY_Left, Gdk.KEY_Up, Gdk.KEY_Page_Up, Gdk.KEY_BackSpace, Gdk.KEY_p):
            self.go(self.index - 1)
        elif keyval == Gdk.KEY_Home:
            self.go(0)
        elif keyval == Gdk.KEY_End:
            self.go(self.count - 1)
        else:
            return False
        return True

    def _on_click(self, gesture, _n, _x, _y):
        if gesture.get_current_button() == 3:
            self.go(self.index - 1)
        elif self.index >= self.count:
            self.finish()
        else:
            self.go(self.index + 1)


class Console(Adw.Window):
    """The presenter display, on the presenter's own screen while the slides are on another:
    the current slide, the next one, this slide's notes, the time and a timer."""
    __gtype_name__ = "AcePresenterConsole"

    def __init__(self, show):
        super().__init__(transient_for=show.win, css_classes=["ace-console"], title="Presenter Display",
                         default_width=1100, default_height=700)
        self.presenter = show
        self.started = time.monotonic()
        self.current = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True, hexpand=True, vexpand=True)
        from .manager import Thumb          # a picture of fixed size, whatever its image
        w, h = show.doc.size_twips()
        self.next = Thumb(340, round(340 * h / w) if w else 191)
        self.next.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.next.set_visible(True)
        self.next_label = Gtk.Label(label="Next", xalign=0, css_classes=["ace-console-caption"])
        self.count = Gtk.Label(xalign=0, css_classes=["ace-console-caption"])
        self.notes = Gtk.Label(xalign=0, yalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, selectable=False,
                               css_classes=["ace-console-notes"])
        self.clock = Gtk.Label(css_classes=["ace-console-clock", "numeric"], xalign=0, hexpand=True)
        self.timer = Gtk.Label(css_classes=["ace-console-clock", "numeric"], xalign=1)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True)
        left.append(self.count)
        left.append(self.current)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=False)
        right.set_size_request(340, -1)
        right.append(self.next_label)
        right.append(self.next)
        right.append(Gtk.Label(label="Notes", xalign=0, css_classes=["ace-console-caption"], margin_top=10))
        right.append(Gtk.ScrolledWindow(child=self.notes, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER))
        body = Gtk.Box(spacing=24, vexpand=True)
        body.append(left)
        body.append(right)
        top = Gtk.Box(spacing=12)
        top.append(self.clock)
        top.append(self.timer)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_start=24, margin_end=24,
                      margin_top=18, margin_bottom=24)
        box.append(top)
        box.append(body)
        self.set_content(box)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", show._on_key)
        self.add_controller(keys)
        self.connect("close-request", lambda *_: self._closed())
        self._tick_source = GLib.timeout_add(500, self._tick)
        self._tick()
        self.maximize()
        self.present()

    def update(self):
        show = self.presenter
        n = show.index
        if n >= show.count:
            self.count.set_label("End of slideshow")
            self.next.set_paintable(None)
            self.next_label.set_label("")
            self.notes.set_label("")
            return
        self.count.set_label(f"Slide {n + 1} of {show.count}")
        self.current.set_paintable(show._texture(n))
        has_next = n + 1 < show.count
        self.next.set_paintable(show._texture(n + 1) if has_next else None)
        self.next_label.set_label("Next" if has_next else "Last slide")
        notes = show.win.notes.text_for(show.slides[n]["index"]) if show.win.notes else ""
        self.notes.set_label(notes or "No notes for this slide.")
        if notes:
            self.notes.remove_css_class("dim-label")
        else:
            self.notes.add_css_class("dim-label")

    def _tick(self):
        self.clock.set_label(time.strftime("%-I:%M %p"))
        elapsed = int(time.monotonic() - self.started)
        self.timer.set_label(f"{elapsed // 3600}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}")
        return True

    def _closed(self):
        # Closing the presenter display ends the show.
        if self._tick_source:
            GLib.source_remove(self._tick_source)
            self._tick_source = 0
            self.presenter.console = None
            self.presenter.finish()
        return False

    def finish(self):
        if self._tick_source:
            GLib.source_remove(self._tick_source)
            self._tick_source = 0
        self.close()


class NotesPane(Gtk.Box):
    """Presenter notes for the current slide, under the slide as in Keynote.

    Notes are read and written by the Slides macros (see macros/Slides.bas): all of them
    once when the presentation opens and after slides are added, removed or moved; one
    slide's shortly after you stop typing in it.
    """
    __gtype_name__ = "AceNotesPane"

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["ace-notes"])
        self.win = win
        self.texts = []          # per slide
        self.slide = -1
        self._dirty = False
        self._loading = False
        self._debounce = 0
        self._folder = tempfile.mkdtemp(prefix="notes-", dir=_cache_dir())
        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8,
                                 left_margin=14, right_margin=14, css_classes=["ace-notes-text"])
        self.view.get_buffer().connect("changed", self._on_changed)
        self.placeholder = Gtk.Label(label="Presenter notes", xalign=0, yalign=0, margin_start=14, margin_top=8,
                                     css_classes=["dim-label"], can_target=False)
        overlay = Gtk.Overlay(child=Gtk.ScrolledWindow(child=self.view, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                                       min_content_height=96, max_content_height=96))
        overlay.add_overlay(self.placeholder)
        self.append(overlay)

    def text_for(self, slide):
        if slide == self.slide:
            return self._buffer_text()
        return self.texts[slide] if 0 <= slide < len(self.texts) else ""

    def _buffer_text(self):
        buf = self.view.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    # --- reading ---------------------------------------------------------------------

    def reload(self):
        """Read every slide's notes from the document (the macro answers through a file)."""
        self.commit()
        out = os.path.join(self._folder, f"all-{time.monotonic_ns()}.txt")
        self.win.doc.run_macro(f'Slides.GetNotes("{out}")')
        tries = [0]

        def poll():
            tries[0] += 1
            if not self.win.doc:
                return False
            if not os.path.exists(out):
                return tries[0] < 60
            with open(out, encoding="utf-8") as f:
                records = f.read().split("\n\x1e\n")
            os.unlink(out)
            self.texts = [r for r in records[:-1]]
            self.slide = -1
            self.show_slide(self.win.doc.part())
            return False
        GLib.timeout_add(50, poll)

    def show_slide(self, n):
        if n == self.slide:
            return
        self.commit()
        self.slide = n
        self._loading = True
        self.view.get_buffer().set_text(self.texts[n] if 0 <= n < len(self.texts) else "")
        self._loading = False
        self.placeholder.set_visible(not self._buffer_text())

    # --- writing ---------------------------------------------------------------------

    def _on_changed(self, _buf):
        self.placeholder.set_visible(not self._buffer_text())
        if self._loading:
            return
        self._dirty = True
        self.win.set_modified(True)
        if self._debounce:
            GLib.source_remove(self._debounce)
        self._debounce = GLib.timeout_add(700, self._after_pause)

    def _after_pause(self):
        self._debounce = 0
        self.commit()
        return False

    def commit(self, wait=False):
        """Write this slide's notes into the document if they changed. wait: give LibreOffice
        a moment to run the macro, for callers about to save."""
        if self._debounce:
            GLib.source_remove(self._debounce)
            self._debounce = 0
        if not self._dirty or self.slide < 0 or not self.win.doc:
            return
        self._dirty = False
        text = self._buffer_text()
        while len(self.texts) <= self.slide:
            self.texts.append("")
        self.texts[self.slide] = text
        path = os.path.join(self._folder, f"slide-{time.monotonic_ns()}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.win.doc.run_macro(f'Slides.SetNotes("{self.slide}","{path}")')
        if wait:
            time.sleep(0.3)


def _cache_dir():
    folder = os.path.join(GLib.get_user_cache_dir(), "aceoffice", "open")
    os.makedirs(folder, exist_ok=True)
    return folder
