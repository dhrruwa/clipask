"""
clipboard.py - reading and writing the Mac clipboard.

What this module does, in simple words:
    The "clipboard" is the invisible place where text goes when you press ⌘C.
    Every Mac comes with two tiny command-line tools for it:

        pbpaste  -> prints whatever text is on the clipboard
        pbcopy   -> puts text onto the clipboard

    We run those tools from Python using the built-in `subprocess` module,
    so there is nothing extra to install.

If the clipboard holds something that isn't text (an image, a file),
pbpaste prints nothing, so get_clipboard_text() returns "".
"""

import os
import subprocess

# Full paths, so the tools are found even when ClipAsk starts at login
# (programs started that way don't always have the usual PATH setting).
PBPASTE = "/usr/bin/pbpaste"
PBCOPY = "/usr/bin/pbcopy"

# Seconds to wait for pbpaste/pbcopy before giving up. They normally
# finish instantly; this just stops a stuck tool from freezing the app.
TIMEOUT_SECONDS = 5


class ClipboardError(Exception):
    """Raised when the clipboard can't be read or written."""


def _utf8_environment():
    """
    Return environment settings that make pbpaste/pbcopy use UTF-8.

    pbpaste and pbcopy pick a text encoding from the "locale" settings.
    Apps opened from Finder or at login often have no locale set, and then
    accented letters, emoji, Chinese, etc. come out garbled. Forcing UTF-8
    fixes that.
    """
    environment = os.environ.copy()
    environment["LANG"] = "en_US.UTF-8"
    environment["LC_CTYPE"] = "en_US.UTF-8"
    return environment


def get_clipboard_text():
    """Return the text currently on the clipboard ("" if there is none)."""
    try:
        result = subprocess.run(
            [PBPASTE],
            capture_output=True,
            env=_utf8_environment(),
            timeout=TIMEOUT_SECONDS,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ClipboardError(f"Couldn't read the clipboard ({error}).") from error
    return result.stdout.decode("utf-8", errors="replace")


def set_clipboard_text(text):
    """Put `text` on the clipboard, replacing what was there."""
    try:
        subprocess.run(
            [PBCOPY],
            input=text.encode("utf-8"),
            env=_utf8_environment(),
            timeout=TIMEOUT_SECONDS,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ClipboardError(f"Couldn't copy to the clipboard ({error}).") from error
