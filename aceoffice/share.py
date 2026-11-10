# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Share by Email: a new message in the user's mail app with a file attached.

Three routes, tried in order:
1. ACE Mail, asked directly to open the file (its `acemail FILE…`), over D-Bus if it's
   running or by launching it when it's the default mail app. ACE Mail ignores `attach=`
   in mailto: links on purpose, so the portal route below can't attach for it.
2. The desktop's Email portal (works inside the Flatpak; hands the file over as an open
   file descriptor, so the mail app needs no access to AceOffice's folders).
3. Failing both, tell the user where the copy is.
"""

import os

from gi.repository import Gio, GLib

ACEMAIL_IDS = ("ai.playerpiano.AceMail", "ca.ayrescapital.AceMail")


def _acemail_running(bus, uri):
    """Ask a running ACE Mail to open uri (org.freedesktop.Application.Open)."""
    for app_id in ACEMAIL_IDS:
        try:
            bus.call_sync(app_id, "/" + app_id.replace(".", "/"), "org.freedesktop.Application", "Open",
                          GLib.Variant("(asa{sv})", ([uri], {})), None, Gio.DBusCallFlags.NO_AUTO_START,
                          3000, None)
            return True
        except GLib.Error:
            continue
    return False


def _acemail_default(uri):
    """Launch ACE Mail with the file if it's the default mail app (not visible from a sandbox)."""
    if os.path.exists("/.flatpak-info"):
        return False
    info = Gio.AppInfo.get_default_for_uri_scheme("mailto")
    if not info or "acemail" not in (info.get_id() or "").lower():
        return False
    try:
        return info.launch_uris([uri], None)
    except GLib.Error:
        return False


def _portal(bus, path, subject, done):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    fds = Gio.UnixFDList.new()
    index = fds.append(fd)
    os.close(fd)
    options = {"subject": GLib.Variant("s", subject),
               "attachment_fds": GLib.Variant("ah", [index])}

    def finished(source, result):
        try:
            source.call_with_unix_fd_list_finish(result)
            done(None)
        except GLib.Error:
            done(f"No mail app answered. The copy is at {path.replace(os.path.expanduser('~'), '~')}")
    bus.call_with_unix_fd_list("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                               "org.freedesktop.portal.Email", "ComposeEmail",
                               GLib.Variant("(sa{sv})", ("", options)), None, Gio.DBusCallFlags.NONE,
                               10000, fds, None, finished)


def email_file(path, subject, done):
    """Start a message with path attached. Calls done(None), or done(message) on failure."""
    uri = Gio.File.new_for_path(path).get_uri()
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error:
        bus = None
    if (bus and _acemail_running(bus, uri)) or _acemail_default(uri):
        done(None)
    elif bus:
        _portal(bus, path, subject, done)
    else:
        done(f"No mail app answered. The copy is at {path}")
