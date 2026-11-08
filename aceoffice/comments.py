# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The Comments tab of the sidebar.

AceOffice asks LibreOffice not to paint comments into the page (they would be
drawn in LibreOffice's own style, and couldn't be clicked), so they're listed
here instead: author, date and text, with Reply and Delete.
"""

import html
import json
import re
from datetime import datetime

from gi.repository import GLib, Gtk, Pango

from .lok import uno_args


def _text(c):
    """Comment text: older LibreOffice sends 'text', newer sends 'html'."""
    if c.get("text"):
        return c["text"]
    body = re.sub(r"</(div|p)>|<br\s*/?>", "\n", c.get("html", ""))
    return html.unescape(re.sub(r"<[^>]+>", "", body)).strip()


def _parent(c):
    return str(c.get("parentId", c.get("parent", "0")))


def _when(stamp):
    try:
        dt = datetime.fromisoformat(re.split(r"[.,]", stamp)[0])
    except (ValueError, AttributeError):
        return ""
    today = datetime.now().date()
    if dt.date() == today:
        return dt.strftime("%-I:%M %p")
    return dt.strftime("%b %-d" if dt.year == today.year else "%b %-d, %Y")


class Comments(Gtk.Box):
    __gtype_name__ = "AceComments"

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_start=16, margin_end=16,
                         margin_top=10, margin_bottom=10)
        self.win = win
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["ace-comment-list"])
        self.empty = Gtk.Label(label="No comments yet.\nSelect some text and click Comment in the toolbar.",
                               justify=Gtk.Justification.CENTER, wrap=True,
                               css_classes=["dim-label"], margin_top=24)
        self.append(self.empty)
        self.append(self.list)
        self._source = 0

    def changed(self, _payload=None):
        """A comment was added, changed or removed; refresh once things settle."""
        if self._source:
            GLib.source_remove(self._source)
        self._source = GLib.timeout_add(150, self.refresh)

    def refresh(self):
        self._source = 0
        raw = self.win.doc.command_values(".uno:ViewAnnotations") if self.win.doc else None
        try:
            comments = json.loads(raw)["comments"] if raw else []
        except (ValueError, KeyError, TypeError):
            comments = []
        self.list.remove_all()
        by_id = {str(c.get("id")): c for c in comments}
        # Replies follow their parent, indented.
        roots = [c for c in comments if _parent(c) in ("0", "", "None") or _parent(c) not in by_id]
        for root in roots:
            self.list.append(self._card(root, reply=False))
            for c in comments:
                if _parent(c) == str(root.get("id")) and c is not root:
                    self.list.append(self._card(c, reply=True))
        self.empty.set_visible(not comments)
        self.list.set_visible(bool(comments))
        return False

    def _card(self, c, reply):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, css_classes=["ace-comment"],
                      margin_start=18 if reply else 0)
        head = Gtk.Box(spacing=6)
        head.append(Gtk.Label(label=c.get("author") or "Unknown", xalign=0, hexpand=True,
                              ellipsize=Pango.EllipsizeMode.END, css_classes=["heading"]))
        head.append(Gtk.Label(label=_when(c.get("dateTime", "")), css_classes=["caption", "dim-label"]))
        box.append(head)
        box.append(Gtk.Label(label=_text(c), xalign=0, wrap=True, selectable=True,
                             wrap_mode=Pango.WrapMode.WORD_CHAR))
        actions = Gtk.Box(spacing=4, halign=Gtk.Align.END)
        cid = str(c.get("id"))
        if not reply:
            r = Gtk.Button(label="Reply", css_classes=["flat", "caption"])
            r.connect("clicked", lambda *_: self._reply(box, cid))
            actions.append(r)
        d = Gtk.Button(label="Delete", css_classes=["flat", "caption"])
        d.connect("clicked", lambda *_: self._send(".uno:DeleteComment", uno_args(Id=cid)))
        actions.append(d)
        box.append(actions)
        return box

    def _reply(self, card, cid):
        entry = Gtk.Entry(placeholder_text="Reply", activates_default=False)
        card.append(entry)
        entry.grab_focus()

        def done(e):
            text = e.get_text().strip()
            if text:
                self._send(".uno:ReplyComment", uno_args(Id=cid, Text=text))
            card.remove(e)
        entry.connect("activate", done)

    def _send(self, command, args):
        self.win.doc.uno(command, args)
        self.win.set_modified(True)
        self.changed()
