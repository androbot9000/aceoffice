# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Translate GDK key events into LibreOffice (com.sun.star.awt.Key) key codes."""

from gi.repository import Gdk

KEY_NUM0 = 256
KEY_A = 512
KEY_F1 = 768

KEY_SHIFT = 0x1000
KEY_MOD1 = 0x2000   # Ctrl
KEY_MOD2 = 0x4000   # Alt

_SPECIAL = {
    Gdk.KEY_Down: 1024, Gdk.KEY_Up: 1025, Gdk.KEY_Left: 1026, Gdk.KEY_Right: 1027,
    Gdk.KEY_Home: 1028, Gdk.KEY_End: 1029, Gdk.KEY_Page_Up: 1030, Gdk.KEY_Page_Down: 1031,
    Gdk.KEY_Return: 1280, Gdk.KEY_KP_Enter: 1280, Gdk.KEY_Escape: 1281,
    Gdk.KEY_Tab: 1282, Gdk.KEY_ISO_Left_Tab: 1282, Gdk.KEY_BackSpace: 1283,
    Gdk.KEY_space: 1284, Gdk.KEY_Insert: 1285, Gdk.KEY_Delete: 1286,
    Gdk.KEY_KP_Delete: 1286, Gdk.KEY_KP_Up: 1025, Gdk.KEY_KP_Down: 1024,
    Gdk.KEY_KP_Left: 1026, Gdk.KEY_KP_Right: 1027, Gdk.KEY_KP_Home: 1028,
    Gdk.KEY_KP_End: 1029, Gdk.KEY_KP_Page_Up: 1030, Gdk.KEY_KP_Page_Down: 1031,
}


def modifiers(state):
    m = 0
    if state & Gdk.ModifierType.SHIFT_MASK:
        m |= KEY_SHIFT
    if state & Gdk.ModifierType.CONTROL_MASK:
        m |= KEY_MOD1
    if state & Gdk.ModifierType.ALT_MASK:
        m |= KEY_MOD2
    return m


def translate(keyval, state):
    """Return (char_code, key_code) for a key press, or None if LibreOffice
    doesn't need to see it (plain text arrives through the input method)."""
    mods = modifiers(state)
    if keyval in _SPECIAL:
        char = 13 if _SPECIAL[keyval] == 1280 else (9 if _SPECIAL[keyval] == 1282 else 0)
        if keyval == Gdk.KEY_space:
            char = 32
        return char, _SPECIAL[keyval] | mods
    if Gdk.KEY_F1 <= keyval <= Gdk.KEY_F12:
        return 0, (KEY_F1 + keyval - Gdk.KEY_F1) | mods
    if mods & (KEY_MOD1 | KEY_MOD2):
        lower = Gdk.keyval_to_lower(keyval)
        if Gdk.KEY_a <= lower <= Gdk.KEY_z:
            return 0, (KEY_A + lower - Gdk.KEY_a) | mods
        if Gdk.KEY_0 <= keyval <= Gdk.KEY_9:
            return 0, (KEY_NUM0 + keyval - Gdk.KEY_0) | mods
    return None
