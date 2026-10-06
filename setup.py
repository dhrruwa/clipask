"""
setup.py - instructions for py2app, the tool that turns ClipAsk into a
double-clickable ClipAsk.app.

Build it with:   python setup.py py2app
The result is:   dist/ClipAsk.app

py2app copies Python itself, our six modules and every library they use
into the .app, so it runs on a Mac without Python or pip installed.
"""

from setuptools import setup

APP = ["app.py"]

OPTIONS = {
    # Info.plist: the settings file every Mac app carries.
    "plist": {
        "CFBundleName": "ClipAsk",
        "CFBundleDisplayName": "ClipAsk",
        "CFBundleIdentifier": "com.clipask.app",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        # Menu-bar only: no Dock icon and no app menu.
        "LSUIElement": True,
        "LSMinimumSystemVersion": "11.0",
    },
    # Copy these libraries in whole. Some of them load parts of themselves
    # in ways py2app can't detect automatically.
    "packages": [
        "rumps",
        "pynput",
        "keyring",
        "requests",
        "certifi",
        "charset_normalizer",
        "idna",
        "urllib3",
    ],
}

setup(
    name="ClipAsk",
    app=APP,
    options={"py2app": OPTIONS},
)
