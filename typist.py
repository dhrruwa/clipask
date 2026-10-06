"""
typist.py - types the answer into whatever app you're using, like a person.

What this module does, in simple words:
    pynput's keyboard "Controller" can press keys for us: macOS treats the
    key presses exactly as if you typed them. We type the answer one
    character at a time, waiting between characters to match the chosen
    speed in words per minute (WPM).

    Typing-speed tests count every 5 characters (spaces included) as one
    "word". So 25 WPM = 125 characters per minute = one character about
    every 0.48 seconds.

    The typing happens on a background thread, because it can take
    minutes. Call stop() to end it early.

Things to know:
    - The text goes wherever your cursor is. If you click another window
      while it's typing, the rest goes there.
    - While you hold ⌘, ⌃, ⌥ or ⇧, typing pauses. Otherwise a held key
      would combine with typed letters into shortcuts (⌘ + "q" = Quit).
    - macOS only lets apps press keys if they have the "Accessibility"
      permission. Without it, the key presses are silently thrown away.
"""

import re
import threading
import time

import Quartz
from ApplicationServices import AXIsProcessTrusted
from pynput import keyboard

CHARACTERS_PER_WORD = 5

_HELD_MODIFIER_FLAGS = (
    Quartz.kCGEventFlagMaskCommand
    | Quartz.kCGEventFlagMaskControl
    | Quartz.kCGEventFlagMaskAlternate
    | Quartz.kCGEventFlagMaskShift
)

# AI models put code between "fence" lines: ```c on its own line before
# the code, ``` after it. _CODE_BLOCK finds the code between a pair of
# fences; _CODE_FENCE_LINE finds a lone fence line (e.g. when the answer
# was cut off before the closing fence).
_CODE_BLOCK = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
_CODE_FENCE_LINE = re.compile(r"^\s*```[\w+-]*\s*$\n?", re.MULTILINE)


def can_type():
    """True if macOS lets this app press keys (the Accessibility permission)."""
    return bool(AXIsProcessTrusted())


def seconds_per_character(wpm):
    return 60.0 / (wpm * CHARACTERS_PER_WORD)


def prepare_text(text):
    """
    Decide exactly what to type.

    If the answer contains code blocks, only the code inside them is typed,
    so a code question gets just the code, without sentences like "Here is
    the program:". Otherwise the whole answer is typed.
    """
    text = text.replace("\r\n", "\n")
    code_blocks = _CODE_BLOCK.findall(text)
    if code_blocks:
        return "\n\n".join(block.strip("\n") for block in code_blocks).rstrip()
    return _CODE_FENCE_LINE.sub("", text).strip()


class Typist:
    def __init__(self):
        self._keyboard = keyboard.Controller()
        self._stop_requested = threading.Event()
        self._thread = None

    @property
    def is_typing(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, text, wpm, on_progress, on_done):
        """
        Start typing `text` at `wpm` words per minute.

        on_progress(seconds_left) is called after each character, and
        on_done(was_stopped) at the end. Both run on the background
        thread, so they must not touch the UI directly.
        """
        self._stop_requested.clear()
        self._thread = threading.Thread(
            target=self._type_all, args=(text, wpm, on_progress, on_done), daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop_requested.set()

    # ----- Runs on the background thread -----

    def _type_all(self, text, wpm, on_progress, on_done):
        delay = seconds_per_character(wpm)
        # Give macOS a moment to put the keyboard focus back where you were
        # (for example after ClipAsk closes its popup).
        self._stop_requested.wait(0.3)
        for index, character in enumerate(text):
            self._wait_while_modifier_keys_are_held()
            if self._stop_requested.is_set():
                break
            try:
                self._keyboard.type(character)  # "\n" presses Return, "\t" presses Tab
            except keyboard.Controller.InvalidCharacterException:
                pass  # a character this keyboard can't produce: skip it
            on_progress((len(text) - index - 1) * delay)
            # Sleep until the next character, but wake up at once if stopped.
            self._stop_requested.wait(delay)
        on_done(self._stop_requested.is_set())

    def _wait_while_modifier_keys_are_held(self):
        while not self._stop_requested.is_set():
            # Asks macOS which keys are physically held down right now.
            flags = Quartz.CGEventSourceFlagsState(Quartz.kCGEventSourceStateHIDSystemState)
            if not flags & _HELD_MODIFIER_FLAGS:
                return
            time.sleep(0.05)
