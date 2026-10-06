"""
settings.py - remembers your choices between runs.

What this module does, in simple words:
    ClipAsk saves two kinds of things, in two different places:

    1. API keys -> the macOS Keychain.
       The Keychain is the encrypted password store built into macOS (the
       same one Safari uses). We talk to it with the `keyring` library.
       Keys are NEVER written to a normal file. You can see them in the
       "Keychain Access" app: search for "ClipAsk".

    2. Everything else (provider, model names, system prompt, whether to
       type the answer or show it in a popup, typing speed) -> a small
       JSON text file:
           ~/Library/Application Support/ClipAsk/settings.json

    It also handles "Start at Login". macOS starts programs at login if
    there is a small description file (a "LaunchAgent") for them in
    ~/Library/LaunchAgents. Turning the option on writes that file;
    turning it off deletes it.
"""

import json
import logging
import os
import plistlib
import sys
from dataclasses import asdict, dataclass, field

import keyring
from keyring.errors import KeyringError

from ai_client import PROVIDERS

log = logging.getLogger(__name__)

# Name used for the Keychain entries (one entry per provider).
KEYCHAIN_SERVICE = "ClipAsk"

SUPPORT_FOLDER = os.path.expanduser("~/Library/Application Support/ClipAsk")
SETTINGS_FILE = os.path.join(SUPPORT_FOLDER, "settings.json")

LAUNCH_AGENT_LABEL = "com.clipask.app"
LAUNCH_AGENT_FILE = os.path.expanduser(f"~/Library/LaunchAgents/{LAUNCH_AGENT_LABEL}.plist")
LOG_FILE = os.path.expanduser("~/Library/Logs/ClipAsk.log")

DEFAULT_PROVIDER = "gemini"

# What happens to the answer: "type" types it into the app you're using,
# "popup" shows it in the floating window.
OUTPUT_MODES = ("type", "popup")
DEFAULT_OUTPUT_MODE = "type"

DEFAULT_TYPING_WPM = 25  # words per minute
MIN_TYPING_WPM = 5
MAX_TYPING_WPM = 300

# Used until you change it. Plain text, because Markdown symbols (**bold**,
# # headings) would be typed literally. Code goes in a ``` block so that
# typist.py can type just the code and leave out any explanation.
DEFAULT_SYSTEM_PROMPT = (
    "For normal questions, answer clearly and concisely in plain text, not Markdown. "
    "If the question asks for code, reply with only the code inside one ``` code block, "
    "with no explanation before or after it."
)

# Default prompts from earlier versions of ClipAsk. If your saved prompt is
# one of these (you never changed it), you get the current default instead.
_OLD_DEFAULT_SYSTEM_PROMPTS = (
    "Answer clearly and concisely. Reply in plain text, not Markdown, "
    "because your answer is shown in a small plain-text window.",
)


class SettingsError(Exception):
    """A setting couldn't be read or saved. The message is shown to the user."""


def _use_macos_keychain():
    """
    Tell `keyring` to use the macOS Keychain.

    keyring normally finds the Keychain on its own, using information that
    pip installs alongside it. Inside a packaged .app that information can
    go missing, so we choose the Keychain explicitly.
    """
    try:
        from keyring.backends import macOS

        keyring.set_keyring(macOS.Keyring())
    except Exception as error:  # fall back to keyring's automatic choice
        log.warning("Couldn't select the macOS Keychain directly: %s", error)


_use_macos_keychain()


# ---------------------------------------------------------------------------
# Provider, model and system prompt (saved in settings.json)
# ---------------------------------------------------------------------------


def _default_models():
    return {provider: info.default_model for provider, info in PROVIDERS.items()}


@dataclass
class Settings:
    provider: str = DEFAULT_PROVIDER
    # One model name per provider, so switching provider keeps a valid model.
    models: dict = field(default_factory=_default_models)
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    output_mode: str = DEFAULT_OUTPUT_MODE
    typing_wpm: int = DEFAULT_TYPING_WPM

    @property
    def model(self):
        """The model name for the currently selected provider."""
        return self.models.get(self.provider) or PROVIDERS[self.provider].default_model


def load_settings():
    """Read settings.json. Missing or broken values fall back to defaults."""
    settings = Settings()
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as file:
            saved = json.load(file)
    except FileNotFoundError:  # first run: nothing saved yet
        return settings
    except (OSError, ValueError) as error:
        log.warning("Ignoring unreadable settings file %s: %s", SETTINGS_FILE, error)
        return settings
    if not isinstance(saved, dict):
        return settings

    if saved.get("provider") in PROVIDERS:
        settings.provider = saved["provider"]
    if isinstance(saved.get("models"), dict):
        for provider, model in saved["models"].items():
            if provider in PROVIDERS and isinstance(model, str) and model.strip():
                settings.models[provider] = model.strip()
    if isinstance(saved.get("system_prompt"), str) and saved["system_prompt"] not in _OLD_DEFAULT_SYSTEM_PROMPTS:
        settings.system_prompt = saved["system_prompt"]
    if saved.get("output_mode") in OUTPUT_MODES:
        settings.output_mode = saved["output_mode"]
    wpm = saved.get("typing_wpm")
    if isinstance(wpm, int) and MIN_TYPING_WPM <= wpm <= MAX_TYPING_WPM:
        settings.typing_wpm = wpm
    return settings


def save_settings(settings):
    """Write settings.json."""
    try:
        os.makedirs(SUPPORT_FOLDER, exist_ok=True)
        # Write to a temporary file first, then swap it in, so a crash
        # halfway through can't leave a half-written settings file.
        temporary_file = SETTINGS_FILE + ".tmp"
        with open(temporary_file, "w", encoding="utf-8") as file:
            json.dump(asdict(settings), file, indent=2)
        os.replace(temporary_file, SETTINGS_FILE)
    except OSError as error:
        raise SettingsError(f"Couldn't save settings to {SETTINGS_FILE}.\n\nDetails: {error}") from error


# ---------------------------------------------------------------------------
# API keys (saved in the macOS Keychain)
# ---------------------------------------------------------------------------


def get_api_key(provider):
    """Return the saved API key for `provider`, or None if there isn't one."""
    try:
        return keyring.get_password(KEYCHAIN_SERVICE, provider) or None
    except KeyringError as error:
        raise SettingsError(f"Couldn't read the API key from the Keychain.\n\nDetails: {error}") from error


def set_api_key(provider, api_key):
    """Save (or replace) the API key for `provider` in the Keychain."""
    try:
        keyring.set_password(KEYCHAIN_SERVICE, provider, api_key)
    except KeyringError as error:
        raise SettingsError(f"Couldn't save the API key to the Keychain.\n\nDetails: {error}") from error


# ---------------------------------------------------------------------------
# Start at login (a LaunchAgent file)
# ---------------------------------------------------------------------------


def _launch_command():
    """The command macOS should run at login to start ClipAsk."""
    if getattr(sys, "frozen", None) == "macosx_app":
        # Running as ClipAsk.app (built with py2app): open the app bundle.
        from Foundation import NSBundle

        return ["/usr/bin/open", NSBundle.mainBundle().bundlePath()]
    # Running from source: the same Python, running the same app.py.
    app_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
    return [sys.executable, app_script]


def is_start_at_login_enabled():
    return os.path.exists(LAUNCH_AGENT_FILE)


def set_start_at_login(enabled):
    """Turn "Start at Login" on or off."""
    try:
        if enabled:
            agent = {
                "Label": LAUNCH_AGENT_LABEL,
                "ProgramArguments": _launch_command(),
                "RunAtLoad": True,  # run once, when you log in
                "ProcessType": "Interactive",
                "StandardOutPath": LOG_FILE,  # messages and errors go here
                "StandardErrorPath": LOG_FILE,
            }
            os.makedirs(os.path.dirname(LAUNCH_AGENT_FILE), exist_ok=True)
            with open(LAUNCH_AGENT_FILE, "wb") as file:
                plistlib.dump(agent, file)
        elif os.path.exists(LAUNCH_AGENT_FILE):
            # We only delete the file. We don't unload it with `launchctl`,
            # because that could stop ClipAsk itself if launchd started it.
            os.remove(LAUNCH_AGENT_FILE)
    except OSError as error:
        raise SettingsError(f"Couldn't change \"Start at Login\".\n\nDetails: {error}") from error
