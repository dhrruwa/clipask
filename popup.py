"""
popup.py - the small floating window that shows the AI's answer.

What this module does, in simple words:
    Mac windows are drawn by Apple's "AppKit" framework. The PyObjC library
    (installed automatically with rumps) lets Python use AppKit directly,
    so we don't need a separate GUI toolkit. The window looks like this:

        ┌─ ClipAsk ──────────────────────────────┐
        │ The answer text appears here. If it's  │  <- a text view inside a
        │ long, you can scroll down to read it.  │     scroll view
        │                        [ Copy ][Close] │  <- two buttons
        └────────────────────────────────────────┘

    It's 500 points wide, grows with the text up to a maximum height
    (then scrolls), floats above other windows, and appears near the
    mouse pointer.

    Keyboard: Esc or ⌘W closes it. ⌘C copies the selected text (or the
    whole answer if nothing is selected). Return presses "Copy".

Rule: every function here must run on the main thread (app.py takes care
of that).
"""

import objc
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSButton,
    NSColor,
    NSEvent,
    NSEventMaskKeyDown,
    NSEventModifierFlagCommand,
    NSFont,
    NSNoBorder,
    NSPanel,
    NSScreen,
    NSScrollView,
    NSTextView,
    NSViewHeightSizable,
    NSViewMaxYMargin,
    NSViewMinXMargin,
    NSViewWidthSizable,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakePoint, NSMakeRect, NSMakeSize, NSObject, NSPointInRect
from PyObjCTools import AppHelper

import clipboard

# Sizes, in screen points.
WIDTH = 500
MIN_HEIGHT = 120
MAX_HEIGHT = 520
MARGIN = 14  # space around the edges
BUTTON_WIDTH = 90
BUTTON_HEIGHT = 32
BUTTON_GAP = 8
TEXT_INSET = 4  # space between the text and the edge of the text area
FONT_SIZE = 14

ESCAPE_KEY_CODE = 53  # hardware key code of the Esc key


class _PopupBridge(NSObject):
    """
    AppKit can't call Python functions directly: buttons and windows send
    "messages" to an Objective-C object instead. This tiny object receives
    those messages and passes them on to our Popup.
    """

    def initWithPopup_(self, popup):
        self = objc.super(_PopupBridge, self).init()
        if self is None:
            return None
        self.popup = popup
        return self

    def copyClicked_(self, sender):  # the Copy button
        self.popup.copy_answer()

    def closeClicked_(self, sender):  # the Close button
        self.popup.close()

    def windowWillClose_(self, notification):  # the red close button
        self.popup.give_focus_back()


class Popup:
    def __init__(self):
        self._answer = ""
        self._bridge = _PopupBridge.alloc().initWithPopup_(self)
        self._build_window()
        # Watch key presses in ClipAsk's windows, for Esc, ⌘W and ⌘C.
        self._key_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, self._handle_key
        )

    # ----- Public functions, used by app.py -----

    def show(self, text, title="ClipAsk", is_error=False):
        """Show `text` in the popup (red text if `is_error`)."""
        self._answer = text
        self._window.setTitle_(title)
        self._text_view.setString_(text)
        self._text_view.setFont_(NSFont.systemFontOfSize_(FONT_SIZE))
        self._text_view.setTextColor_(NSColor.systemRedColor() if is_error else NSColor.labelColor())
        self._text_view.setSelectedRange_((0, 0))
        self._copy_button.setTitle_("Copy")

        self._resize_to_fit_text()
        self._move_near_mouse()
        self._text_view.scrollRangeToVisible_((0, 0))

        # A menu-bar app isn't the "active" app, so bring it forward;
        # otherwise the popup can't receive key presses like Esc.
        NSApp.unhide_(None)
        NSApp.activateIgnoringOtherApps_(True)
        self._window.makeKeyAndOrderFront_(None)
        self._window.orderFrontRegardless()
        self._window.makeFirstResponder_(self._text_view)

    def close(self):
        if self._window.isVisible():
            self._window.orderOut_(None)
            self.give_focus_back()

    def copy_answer(self):
        """Copy the whole answer (the Copy button)."""
        self._copy(self._answer)

    def give_focus_back(self):
        """Hide ClipAsk so the app you were using becomes active again."""
        NSApp.hide_(None)

    # ----- Building the window (runs once) -----

    def _build_window(self):
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskResizable
        window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, MIN_HEIGHT), style, NSBackingStoreBuffered, False
        )
        window.setFloatingPanel_(True)  # stay above normal windows
        window.setHidesOnDeactivate_(False)  # stay visible when you click another app
        window.setReleasedWhenClosed_(False)  # keep the window so we can reuse it
        window.setMinSize_(NSMakeSize(300, MIN_HEIGHT))
        # Also appear on top of full-screen apps, on whichever desktop you're on.
        window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        window.setDelegate_(self._bridge)
        content = window.contentView()

        # Buttons, in the bottom-right corner. Coordinates start at the
        # BOTTOM-left on macOS, so y=MARGIN means "near the bottom".
        close_x = WIDTH - MARGIN - BUTTON_WIDTH
        copy_x = close_x - BUTTON_GAP - BUTTON_WIDTH
        self._close_button = self._make_button("Close", "closeClicked:", close_x)
        self._copy_button = self._make_button("Copy", "copyClicked:", copy_x)
        self._copy_button.setKeyEquivalent_("\r")  # Return presses Copy (and makes it blue)
        content.addSubview_(self._close_button)
        content.addSubview_(self._copy_button)

        # The scrollable text area fills the rest of the window.
        text_bottom = MARGIN + BUTTON_HEIGHT + BUTTON_GAP
        scroll_view = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(MARGIN, text_bottom, WIDTH - 2 * MARGIN, MIN_HEIGHT - text_bottom - MARGIN)
        )
        scroll_view.setHasVerticalScroller_(True)
        scroll_view.setHasHorizontalScroller_(False)
        scroll_view.setAutohidesScrollers_(True)
        scroll_view.setBorderType_(NSNoBorder)
        scroll_view.setDrawsBackground_(False)
        scroll_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)  # grow with the window

        size = scroll_view.contentSize()
        text_view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, size.width, size.height))
        text_view.setEditable_(False)
        text_view.setSelectable_(True)  # you can still select and copy parts
        text_view.setDrawsBackground_(False)
        text_view.setTextContainerInset_(NSMakeSize(TEXT_INSET, TEXT_INSET))
        # Wrap long lines at the window's width, and grow downwards.
        text_view.setVerticallyResizable_(True)
        text_view.setHorizontallyResizable_(False)
        text_view.setAutoresizingMask_(NSViewWidthSizable)
        text_view.setMinSize_(NSMakeSize(0, size.height))
        text_view.setMaxSize_(NSMakeSize(1e7, 1e7))
        text_view.textContainer().setContainerSize_(NSMakeSize(size.width, 1e7))
        text_view.textContainer().setWidthTracksTextView_(True)
        scroll_view.setDocumentView_(text_view)
        content.addSubview_(scroll_view)

        self._window = window
        self._text_view = text_view

    def _make_button(self, title, action, x):
        button = NSButton.alloc().initWithFrame_(NSMakeRect(x, MARGIN, BUTTON_WIDTH, BUTTON_HEIGHT))
        button.setTitle_(title)
        button.setBezelStyle_(NSBezelStyleRounded)
        button.setTarget_(self._bridge)
        button.setAction_(action)
        # Stay glued to the bottom-right corner when the window is resized.
        button.setAutoresizingMask_(NSViewMinXMargin | NSViewMaxYMargin)
        return button

    # ----- Sizing and positioning -----

    def _resize_to_fit_text(self):
        """Make the window just tall enough for the text, within limits."""
        screen_limit = self._current_screen().visibleFrame().size.height - 80
        max_height = min(MAX_HEIGHT, screen_limit)

        # 1. Full width first, so the text wraps where it finally will.
        self._window.setContentSize_(NSMakeSize(WIDTH, max_height))
        # 2. Ask the text system how tall the wrapped text is.
        layout = self._text_view.layoutManager()
        container = self._text_view.textContainer()
        layout.ensureLayoutForTextContainer_(container)
        text_height = layout.usedRectForTextContainer_(container).size.height + 2 * TEXT_INSET
        # 3. Add room for the margins and buttons; keep within min/max.
        extra = MARGIN + BUTTON_HEIGHT + BUTTON_GAP + MARGIN
        height = max(MIN_HEIGHT, min(max_height, text_height + extra))
        self._window.setContentSize_(NSMakeSize(WIDTH, height))

    def _move_near_mouse(self):
        """Put the window just below the mouse pointer, fully on screen."""
        mouse = NSEvent.mouseLocation()
        visible = self._current_screen().visibleFrame()
        frame = self._window.frame()
        width, height = frame.size.width, frame.size.height

        x = mouse.x - width / 2
        y = mouse.y - height - 16
        left, bottom = visible.origin.x + 8, visible.origin.y + 8
        right = visible.origin.x + visible.size.width - width - 8
        top = visible.origin.y + visible.size.height - height - 8
        x = min(max(x, left), right)
        y = min(max(y, bottom), top)
        self._window.setFrameOrigin_(NSMakePoint(x, y))

    def _current_screen(self):
        """The screen the mouse pointer is on."""
        mouse = NSEvent.mouseLocation()
        for screen in NSScreen.screens():
            if NSPointInRect(mouse, screen.frame()):
                return screen
        return NSScreen.mainScreen()

    # ----- Keyboard and copying -----

    def _handle_key(self, event):
        """
        Called for every key press in ClipAsk's windows. Return None to
        "use up" the key press, or return the event to let it through.
        """
        if event.window() != self._window:  # e.g. a settings dialog
            return event
        if event.keyCode() == ESCAPE_KEY_CODE:
            self.close()
            return None
        if event.modifierFlags() & NSEventModifierFlagCommand:
            letter = (event.charactersIgnoringModifiers() or "").lower()
            if letter == "w":
                self.close()
                return None
            if letter == "c":
                self._copy(self._selected_text() or self._answer)
                return None
            if letter == "a":
                self._text_view.selectAll_(None)
                return None
        return event

    def _selected_text(self):
        selection = self._text_view.selectedRange()
        if selection.length == 0:
            return ""
        return self._text_view.attributedString().attributedSubstringFromRange_(selection).string()

    def _copy(self, text):
        try:
            clipboard.set_clipboard_text(text)
        except clipboard.ClipboardError:
            self._copy_button.setTitle_("Copy failed")
            return
        self._copy_button.setTitle_("Copied ✓")
        AppHelper.callLater(1.5, self._copy_button.setTitle_, "Copy")
