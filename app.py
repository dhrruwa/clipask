"""
app.py - the main program. Start ClipAsk with:  python app.py

What this module does, in simple words:
    It creates the menu-bar item and its menu (using the `rumps` library)
    and connects the other modules together:

        hotkey.py    -> notices when you press ⌃⌥A
        clipboard.py -> reads the text you copied
        ai_client.py -> sends it to the AI and gets the answer
        typist.py    -> types the answer into the app you're using
        popup.py     -> shows errors (or the answer, if you prefer) in a
                        small window
        settings.py  -> remembers provider, model, system prompt, output,
                        typing speed, API keys (in the Keychain) and
                        Start at Login

What happens when you press ⌃⌥A:
    1. hotkey.py notices the shortcut (on pynput's background thread).
    2. We hand the work to the main thread, which reads the clipboard,
       checks there's an API key, and changes the menu-bar title to
       "Thinking…".
    3. A new background thread asks the AI. This can take several
       seconds, and doing it on the main thread would freeze the app.
    4. When the answer arrives, we hand it back to the main thread, which
       starts typing it (on another background thread, since typing takes
       a while) or shows it in the popup. Errors always go to the popup.
    5. While typing, the menu bar shows the time left. Pressing ⌃⌥A again
       stops the typing.

Why the main thread matters:
    macOS only allows the main thread to change windows and menus. So
    anything that touches the UI goes through AppHelper.callAfter(...),
    which means "run this function on the main thread as soon as it's free".
"""

import logging
import threading

import rumps
from AppKit import NSApp, NSApplication, NSApplicationActivationPolicyAccessory
from PyObjCTools import AppHelper

import ai_client
import clipboard
import hotkey
import settings
import typist
from popup import Popup

log = logging.getLogger("clipask")

APP_NAME = "ClipAsk"
IDLE_TITLE = "ClipAsk"  # shown in the menu bar normally
THINKING_TITLE = "Thinking…"  # shown while waiting for the AI

OUTPUT_LABELS = {
    "type": "Type It Out",
    "popup": "Show in Popup",
}

PERMISSION_HELP = f"""ClipAsk can't see the {hotkey.HOTKEY_LABEL} shortcut yet, because macOS hasn't given it permission.

1. Open System Settings → Privacy & Security → Input Monitoring.
2. Turn on ClipAsk. If you're running app.py instead of ClipAsk.app, turn on the app you started it from (Terminal or VS Code), or "Python" if Start at Login started it.
3. Do the same under Privacy & Security → Accessibility.
4. Quit ClipAsk from the menu bar and start it again.

Until then, you can use "Ask About Clipboard" in the ClipAsk menu."""

TYPING_PERMISSION_HELP = """ClipAsk can't type for you yet, because macOS hasn't given it the Accessibility permission.

1. Open System Settings → Privacy & Security → Accessibility.
2. Turn on ClipAsk. If you're running app.py instead of ClipAsk.app, turn on the app you started it from (Terminal or VS Code).
3. Quit ClipAsk from the menu bar and start it again.

Or choose ClipAsk → Answer Output → Show in Popup."""


def _format_seconds(seconds):
    """65 -> "1:05" """
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class ClipAskApp(rumps.App):
    def __init__(self):
        # quit_button=None: we add our own Quit item, which also stops the
        # keyboard listener.
        super().__init__(APP_NAME, title=IDLE_TITLE, quit_button=None)
        self.settings = settings.load_settings()
        self.popup = Popup()
        self.typist = typist.Typist()
        self.is_busy = False  # True while waiting for an answer
        self._build_menu()
        self.hotkey_listener = hotkey.HotkeyListener(on_activate=self._on_hotkey_pressed)

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self):
        self.ask_item = rumps.MenuItem("Ask About Clipboard", callback=self.on_ask_clicked)

        self.provider_menu = rumps.MenuItem("Provider")
        self.provider_items = {}  # provider id -> its menu item
        for provider_id, info in ai_client.PROVIDERS.items():
            item = rumps.MenuItem(info.label, callback=self.on_provider_chosen)
            self.provider_menu.add(item)
            self.provider_items[provider_id] = item

        self.output_menu = rumps.MenuItem("Answer Output")
        self.output_items = {}  # "type"/"popup" -> its menu item
        for mode in settings.OUTPUT_MODES:
            item = rumps.MenuItem(OUTPUT_LABELS[mode], callback=self.on_output_chosen)
            self.output_menu.add(item)
            self.output_items[mode] = item

        self.speed_item = rumps.MenuItem("Typing Speed…", callback=self.on_change_typing_speed)
        self.model_item = rumps.MenuItem("Model…", callback=self.on_change_model)
        self.api_key_item = rumps.MenuItem("API Key…", callback=self.on_set_api_key)
        self.login_item = rumps.MenuItem("Start at Login", callback=self.on_toggle_start_at_login)

        self.menu = [
            self.ask_item,
            None,  # None draws a separator line
            self.output_menu,
            self.speed_item,
            None,
            self.provider_menu,
            self.model_item,
            self.api_key_item,
            rumps.MenuItem("System Prompt…", callback=self.on_edit_system_prompt),
            None,
            self.login_item,
            None,
            rumps.MenuItem("Quit ClipAsk", callback=self.on_quit),
        ]
        self._refresh_menu()

    def _refresh_menu(self):
        """Update the menu's titles and check marks to match the settings."""
        if self.typist.is_typing:
            self.ask_item.title = f"Stop Typing   {hotkey.HOTKEY_LABEL}"
        else:
            self.ask_item.title = f"Ask About Clipboard   {hotkey.HOTKEY_LABEL}"

        for mode, item in self.output_items.items():
            item.state = 1 if mode == self.settings.output_mode else 0  # 1 = check mark
        self.output_menu.title = f"Answer Output: {OUTPUT_LABELS[self.settings.output_mode]}"
        self.speed_item.title = f"Typing Speed: {self.settings.typing_wpm} WPM…"

        provider = self.settings.provider
        info = ai_client.PROVIDERS[provider]
        for provider_id, item in self.provider_items.items():
            item.state = 1 if provider_id == provider else 0
        self.provider_menu.title = f"Provider: {info.label}"
        self.model_item.title = f"Model: {self.settings.model}…"
        try:
            has_key = settings.get_api_key(provider) is not None
        except settings.SettingsError:
            has_key = False
        self.api_key_item.title = f"{info.label} API Key…" + ("" if has_key else "  (not set)")
        self.login_item.state = 1 if settings.is_start_at_login_enabled() else 0

    # ------------------------------------------------------------------
    # Asking the AI
    # ------------------------------------------------------------------

    def _on_hotkey_pressed(self):
        # Runs on pynput's thread: hand the work to the main thread.
        AppHelper.callAfter(self.ask_or_stop)

    def on_ask_clicked(self, _sender):
        self.ask_or_stop()

    def ask_or_stop(self):
        """The shortcut (and first menu item) starts asking, or stops typing."""
        if self.typist.is_typing:
            self.typist.stop()
        else:
            self.ask_about_clipboard()

    def ask_about_clipboard(self):
        """Read the clipboard and start asking the AI (runs on the main thread)."""
        if self.is_busy:  # already waiting for an answer
            return

        if self.settings.output_mode == "type" and not typist.can_type():
            self._show_error(TYPING_PERMISSION_HELP)
            return

        try:
            question = clipboard.get_clipboard_text()
        except clipboard.ClipboardError as error:
            self._show_error(str(error))
            return
        if not question.strip():
            self._show_error(
                "Your clipboard is empty, or it holds something that isn't text (like an image).\n\n"
                f"Select some text, press ⌘C to copy it, then press {hotkey.HOTKEY_LABEL} again."
            )
            return

        provider = self.settings.provider
        info = ai_client.PROVIDERS[provider]
        try:
            api_key = settings.get_api_key(provider)
        except settings.SettingsError as error:
            self._show_error(str(error))
            return
        if not api_key:
            self._show_error(
                f"No {info.label} API key is saved yet.\n\n"
                f"Click \"{IDLE_TITLE}\" in the menu bar → \"{info.label} API Key…\" and paste your key.\n\n"
                f"You can create a key at {info.key_url}"
            )
            return

        self.is_busy = True
        self.title = THINKING_TITLE
        worker = threading.Thread(
            target=self._ask_ai_in_background,
            args=(provider, self.settings.model, api_key, question, self.settings.system_prompt),
            daemon=True,  # don't keep the app alive if you quit while waiting
        )
        worker.start()

    def _ask_ai_in_background(self, provider, model, api_key, question, system_prompt):
        """Runs on a background thread. Must NOT touch windows or menus."""
        try:
            answer = ai_client.ask(provider, model, api_key, question, system_prompt)
            AppHelper.callAfter(self._finish, answer, False)
        except ai_client.AIError as error:
            AppHelper.callAfter(self._finish, str(error), True)
        except Exception as error:  # a bug: still report it, don't stay stuck on "Thinking…"
            log.exception("Unexpected error while asking the AI")
            AppHelper.callAfter(self._finish, f"Unexpected error: {error!r}", True)

    def _finish(self, text, is_error):
        """Back on the main thread: deliver the answer, or show the error."""
        self.is_busy = False
        self.title = IDLE_TITLE
        if is_error:
            self._show_error(text)
        elif self.settings.output_mode == "type":
            self._start_typing(text)
        else:
            self.popup.show(text)

    def _show_error(self, message):
        self.popup.show(message, title="ClipAsk: something went wrong", is_error=True)

    # ------------------------------------------------------------------
    # Typing the answer
    # ------------------------------------------------------------------

    def _start_typing(self, answer):
        # If an earlier popup has the keyboard focus, close it so the typing
        # goes to the app you were using.
        self.popup.close()
        text = typist.prepare_text(answer)
        seconds = len(text) * typist.seconds_per_character(self.settings.typing_wpm)
        self.title = f"Typing… {_format_seconds(seconds)}"
        self.typist.start(
            text,
            self.settings.typing_wpm,
            on_progress=lambda seconds_left: AppHelper.callAfter(self._typing_progress, seconds_left),
            on_done=lambda was_stopped: AppHelper.callAfter(self._typing_done),
        )
        self._refresh_menu()

    def _typing_progress(self, seconds_left):
        if self.typist.is_typing:
            self.title = f"Typing… {_format_seconds(seconds_left)}"

    def _typing_done(self):
        self.title = IDLE_TITLE
        self._refresh_menu()

    # ------------------------------------------------------------------
    # Settings menu items
    # ------------------------------------------------------------------

    def on_output_chosen(self, sender):
        for mode, item in self.output_items.items():
            if item is sender:
                self.settings.output_mode = mode
        self._save_settings()

    def on_change_typing_speed(self, _sender):
        text = self._ask_for_text(
            title="Typing Speed",
            message=(
                "How fast ClipAsk types, in words per minute.\n"
                f"25 is a relaxed human speed; 60 is fast. Any number from "
                f"{settings.MIN_TYPING_WPM} to {settings.MAX_TYPING_WPM}."
            ),
            default_text=str(self.settings.typing_wpm),
        )
        if text is None:
            return
        try:
            wpm = int(text.strip())
        except ValueError:
            wpm = 0
        if not settings.MIN_TYPING_WPM <= wpm <= settings.MAX_TYPING_WPM:
            self._show_error(
                f"\"{text.strip()}\" isn't a valid typing speed. "
                f"Use a whole number from {settings.MIN_TYPING_WPM} to {settings.MAX_TYPING_WPM}."
            )
            return
        self.settings.typing_wpm = wpm
        self._save_settings()

    def on_provider_chosen(self, sender):
        for provider_id, item in self.provider_items.items():
            if item is sender:
                self.settings.provider = provider_id
        self._save_settings()

    def on_change_model(self, _sender):
        provider = self.settings.provider
        info = ai_client.PROVIDERS[provider]
        text = self._ask_for_text(
            title=f"{info.label} Model",
            message=(
                f"Type the name of the {info.label} model to use.\n"
                f"Leave it empty to go back to the default ({info.default_model})."
            ),
            default_text=self.settings.model,
        )
        if text is None:  # Cancel
            return
        self.settings.models[provider] = text.strip() or info.default_model
        self._save_settings()

    def on_set_api_key(self, _sender):
        provider = self.settings.provider
        info = ai_client.PROVIDERS[provider]
        try:
            current_key = settings.get_api_key(provider)
        except settings.SettingsError as error:
            self._show_error(str(error))
            return
        status = f"A key is saved (ending in …{current_key[-4:]})." if current_key else "No key is saved yet."
        text = self._ask_for_text(
            title=f"{info.label} API Key",
            message=(
                f"{status}\n\nPaste a new key below with ⌘V. It is stored in the macOS Keychain, "
                f"never in a plain file.\n\nCreate a key at {info.key_url}"
            ),
            secure=True,
        )
        if text is None or not text.strip():  # Cancel, or nothing typed: keep the old key
            return
        try:
            settings.set_api_key(provider, text.strip())
        except settings.SettingsError as error:
            self._show_error(str(error))
        self._refresh_menu()

    def on_edit_system_prompt(self, _sender):
        text = self._ask_for_text(
            title="System Prompt",
            message=(
                "Optional instructions sent along with every question, for example "
                "\"Answer in one short paragraph.\" Leave empty for none.\n\n"
                "Press Option+Return to start a new line."
            ),
            default_text=self.settings.system_prompt,
            multiline=True,
        )
        if text is None:
            return
        self.settings.system_prompt = text.strip()
        self._save_settings()

    def on_toggle_start_at_login(self, sender):
        try:
            settings.set_start_at_login(not sender.state)
        except settings.SettingsError as error:
            self._show_error(str(error))
        self._refresh_menu()

    def on_quit(self, _sender):
        self.typist.stop()
        self.hotkey_listener.stop()
        rumps.quit_application()

    def _save_settings(self):
        try:
            settings.save_settings(self.settings)
        except settings.SettingsError as error:
            self._show_error(str(error))
        self._refresh_menu()

    def _ask_for_text(self, title, message, default_text="", secure=False, multiline=False):
        """Show a dialog with a text box. Returns the text, or None for Cancel."""
        window = rumps.Window(
            title=title,
            message=message,
            default_text=default_text,
            ok="Save",
            cancel="Cancel",
            dimensions=(420, 110) if multiline else (320, 24),
            secure=secure,
        )
        if multiline:
            # rumps' text box is one long line by default; let it wrap.
            # (`_textfield` is rumps' own name for the box inside its dialog.)
            cell = window._textfield.cell()
            cell.setWraps_(True)
            cell.setScrollable_(False)
        # A menu-bar app isn't the active app, so the dialog would open
        # behind your other windows. Bring ClipAsk to the front first.
        NSApp.activateIgnoringOtherApps_(True)
        response = window.run()
        return response.text if response.clicked == 1 else None

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def start_up(self):
        """Runs once the menu-bar app is up and running."""
        self.hotkey_listener.start()
        if not hotkey.has_keyboard_permission():
            hotkey.request_keyboard_permission()
            self.popup.show(PERMISSION_HELP, title="ClipAsk needs a permission")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Menu-bar only: no Dock icon. (The packaged .app also sets LSUIElement
    # in its Info.plist; this line covers running `python app.py`.)
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    app = ClipAskApp()
    AppHelper.callAfter(app.start_up)  # runs as soon as app.run() starts the event loop
    app.run()


if __name__ == "__main__":
    main()
