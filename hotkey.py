"""
hotkey.py - watches the keyboard for the shortcut Control + Option + A.

What this module does, in simple words:
    The `pynput` library gives us a keyboard "Listener". It runs in its own
    background thread and calls our functions every time any key goes down
    (on_press) or comes back up (on_release), whichever app you're using.

    We keep a small set of the modifier keys (Control, Option, Command,
    Shift) that are held down right now. When the A key goes down while
    exactly Control and Option are held, we call the function app.py gave
    us. Holding the keys doesn't repeat the action: you have to let go of A
    and press it again. Key presses made by programs (including ClipAsk's
    own typing) are ignored; only real key presses count.

Privacy:
    A global shortcut only works if the program can see every key press;
    that's why macOS asks for the "Input Monitoring" permission. This code
    ignores every key except the shortcut, and never stores or sends them.

Threads:
    The function we call runs on pynput's background thread, NOT the main
    thread. Mac UI code must run on the main thread, so app.py hands the
    work over before touching any windows or menus.
"""

import Quartz
from ApplicationServices import AXIsProcessTrusted
from pynput import keyboard

# How macOS menus write Control + Option + A.
HOTKEY_LABEL = "⌃⌥A"

# The A key on Mac keyboards has the hardware key code 0 ("kVK_ANSI_A").
# We check it as well as the letter, because holding Option changes the
# letter the key types (Option + A types "å" on US keyboards).
_KEY_CODE_A = 0

# pynput calls the Option key "alt", and has left/right versions of each.
_MODIFIER_NAMES = {
    keyboard.Key.ctrl: "control",
    keyboard.Key.ctrl_l: "control",
    keyboard.Key.ctrl_r: "control",
    keyboard.Key.alt: "option",
    keyboard.Key.alt_l: "option",
    keyboard.Key.alt_r: "option",
    keyboard.Key.cmd: "command",
    keyboard.Key.cmd_l: "command",
    keyboard.Key.cmd_r: "command",
    keyboard.Key.shift: "shift",
    keyboard.Key.shift_l: "shift",
    keyboard.Key.shift_r: "shift",
}

_HOTKEY_MODIFIERS = {"control", "option"}


def _is_a_key(key):
    """True if `key` is the A key, whatever modifiers are changing its letter."""
    if getattr(key, "vk", None) == _KEY_CODE_A:
        return True
    char = getattr(key, "char", None) or ""
    return char.lower() in ("a", "å")


class HotkeyListener:
    """Calls `on_activate()` whenever Control + Option + A is pressed."""

    def __init__(self, on_activate):
        self._on_activate = on_activate
        self._held_modifiers = set()  # e.g. {"control", "option"}
        self._a_is_down = False  # used to ignore key-repeat while A is held
        self._listener = None

    def start(self):
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.daemon = True  # don't keep the app alive on quit
        self._listener.start()

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    # pynput calls these two on its own thread, for every key on the keyboard.
    # `injected` is True for key presses made by a program rather than a
    # person, such as ClipAsk itself typing an answer. We ignore those.

    def _on_press(self, key, injected=False):
        if injected:
            return
        modifier = _MODIFIER_NAMES.get(key)
        if modifier:
            self._held_modifiers.add(modifier)
        elif _is_a_key(key):
            if self._held_modifiers == _HOTKEY_MODIFIERS and not self._a_is_down:
                self._on_activate()
            self._a_is_down = True

    def _on_release(self, key, injected=False):
        if injected:
            return
        modifier = _MODIFIER_NAMES.get(key)
        if modifier:
            self._held_modifiers.discard(modifier)
        elif _is_a_key(key):
            self._a_is_down = False


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


def has_keyboard_permission():
    """
    True if macOS lets this app see key presses in other apps.

    Either "Input Monitoring" or "Accessibility" permission is enough for
    pynput's listener. Without them the listener still starts, but macOS
    silently never delivers any key presses to it.
    """
    try:
        if Quartz.CGPreflightListenEventAccess():  # Input Monitoring
            return True
    except AttributeError:  # macOS older than 10.15 has no such permission
        return True
    return bool(AXIsProcessTrusted())  # Accessibility


def request_keyboard_permission():
    """
    Ask macOS to show its "allow Input Monitoring" prompt. This also adds the
    app to the list in System Settings, so you only need to flip the switch.
    macOS shows the prompt once; after that it does nothing.
    """
    try:
        Quartz.CGRequestListenEventAccess()
    except AttributeError:
        pass
