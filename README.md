# ClipAsk

A tiny macOS menu-bar app: copy a question, click where you want the answer, press **Control + Option + A** (⌃⌥A), and ClipAsk types an AI's answer there at 25 words per minute. It can show answers in a small floating window instead.

- Lives in the menu bar (no Dock icon). The menu-bar title shows **Thinking…** while it waits for the AI, then **Typing… 0:48** (time left) while it types.
- Press **⌃⌥A** again to stop typing.
- Works with **OpenAI**, **Anthropic (Claude)** or **Google Gemini**. You choose in the menu.
- Your API key is stored in the **macOS Keychain**, never in a plain file.
- Errors always appear in a small floating window, never typed into your document. The window scrolls if the text is long. **Esc** closes it, **⌘C** or the **Copy** button copies it.

## Quick start: one command on any Mac

On each Mac you use, open **Terminal** and paste:

```bash
curl -sL dhrruwa.github.io/clipask | sh
```

`curl` downloads the installer and `| sh` runs it. If that address ever doesn't work, the long form does the same:
`curl -fsSL https://raw.githubusercontent.com/dhrruwa/clipask/main/install.sh | bash`

This downloads ClipAsk into `~/.clipask` and installs what it needs (about a minute the first time). If this Mac has no API key saved yet, it asks you to paste one; what you paste stays hidden and is saved in this Mac's Keychain. It then starts ClipAsk and adds a short **`clipask`** command.

Once per Mac, after the first run:

1. **System Settings → Privacy & Security → Input Monitoring**: turn on **Terminal**. Do the same under **Accessibility**.
2. Open a new Terminal window and type `clipask` to restart ClipAsk with the permissions.
3. If you skipped the API key, click **ClipAsk** in the menu bar → **Google Gemini API Key…** and paste it there.

Each Mac keeps its own copy of the key in its own Keychain, so you paste it once per Mac. A handy place to keep the key is Apple's **Passwords** app, which syncs it across your Macs through iCloud. Never put the key in the GitHub repo: it's public.

From then on, typing **`clipask`** in any new Terminal window updates ClipAsk from GitHub and (re)starts it. Without internet it skips the update and starts the version it has.

- ClipAsk keeps running after you close Terminal.
- Only one ClipAsk runs at a time: starting it again replaces the running copy, so answers are never typed twice.
- Messages and errors go to `~/Library/Logs/ClipAsk.log`.

The rest of this README covers the same setup step by step, and how to build a standalone `ClipAsk.app`.

## What's in the folder

| File | What it does |
|---|---|
| `app.py` | The main program. It builds the menu-bar menu and connects the other modules. Run this. |
| `hotkey.py` | Watches the keyboard for ⌃⌥A using `pynput`. |
| `clipboard.py` | Reads and writes the clipboard (using the built-in `pbpaste` / `pbcopy`). |
| `ai_client.py` | Sends the question to OpenAI / Anthropic / Gemini and turns errors into readable messages. |
| `typist.py` | Types the answer into the app you're using, at the chosen words-per-minute speed, using `pynput`. |
| `popup.py` | The floating window for errors, or for answers if you choose "Show in Popup" (Copy / Close buttons, scrolling, Esc to close). |
| `settings.py` | Saves your provider, model, system prompt, output choice and typing speed, keeps API keys in the Keychain, and handles Start at Login. |
| `setup.py` | Instructions for `py2app` to build `ClipAsk.app`. |
| `install.sh` | The one-command installer: downloads or updates ClipAsk, sets it up, adds the `clipask` command and starts it. |
| `docs/index.html` | The short starter script served at `dhrruwa.github.io/clipask` (GitHub Pages). It just runs `install.sh`. |

Every module starts with a plain-English explanation of how it works.

## 1. Set up and run

You need macOS 11 or newer and Python 3.9 or newer. Macs with the Xcode Command Line Tools already have Python 3.9; check with:

```bash
python3 --version
```

If that fails, run `xcode-select --install`, or install Python from [python.org](https://www.python.org/downloads/macos/).

Then, in Terminal:

```bash
cd ~/Documents/clipask              # the folder with app.py in it
python3 -m venv .venv               # create a private Python environment for ClipAsk
source .venv/bin/activate           # switch to it (do this again in each new Terminal window)
pip install --upgrade pip           # the pip that comes with macOS is too old (see below)
pip install -r requirements.txt     # install rumps, pynput, keyring, requests, PyObjC
python app.py                       # start ClipAsk
```

**ClipAsk** now appears in the menu bar. Keep the Terminal window open while it runs, or see section 4 to make a real app.

Don't skip `pip install --upgrade pip`. The pip that comes with Apple's Python can't find the ready-made PyObjC packages for newer macOS versions, so it tries to compile them and fails with a long `Building wheel for pyobjc-core … error`.

With Apple's built-in Python 3.9 you'll see a `NotOpenSSLWarning` line in Terminal. It's harmless. A python.org Python doesn't show it.

## 2. Give ClipAsk keyboard permission

On first start, ClipAsk checks whether macOS lets it see the shortcut. If not, it shows a window explaining what to do, and macOS may show its own prompt too.

Open **System Settings → Privacy & Security** and turn ClipAsk on in both of these lists:

| Permission | Why ClipAsk needs it |
|---|---|
| **Input Monitoring** | A global shortcut works by watching key presses while *other* apps are in front. Since macOS 10.15, reading key presses meant for other apps requires this permission. Without it, macOS silently hides every key press from ClipAsk and ⌃⌥A does nothing. |
| **Accessibility** | Needed for ClipAsk to **type** the answer. macOS only lets apps press keys in other apps if they have this permission; otherwise it silently throws the key presses away. Without it, ClipAsk shows an explanation instead of typing. It also helps keyboard listening on some macOS versions. |

Things that commonly go wrong:

- **Which app to turn on.** When you run `python app.py`, macOS gives the permission to the app you typed it in (**Terminal**, **iTerm**, or **Visual Studio Code**), not to "ClipAsk". Turn on that app. When you run the packaged `ClipAsk.app`, turn on **ClipAsk**.
- **Restart after granting.** macOS applies the change only to newly started programs. Quit ClipAsk from its menu and start it again.
- **After rebuilding the .app**, macOS may treat it as a new app. If the shortcut stops working, select ClipAsk in both lists, remove it with **–**, then add it again with **+**.

ClipAsk sees every key press, because that's the only way a global shortcut can work, but it ignores all of them except ⌃⌥A. It never stores or sends what you type. The only keys it presses are the ones that type the answer. It never copies anything for you: you copy the question yourself.

## 3. Add your API key and try it

1. Click **ClipAsk** in the menu bar → **Provider** → choose OpenAI, Anthropic or Gemini.
2. Click **… API Key…** and paste your key with ⌘V. Get a key here:
   - OpenAI: <https://platform.openai.com/api-keys>
   - Anthropic: <https://console.anthropic.com/settings/keys>
   - Gemini: <https://aistudio.google.com/apikey>
3. Select a question anywhere and press **⌘C**. Text copied on your iPhone works too, through Apple's Universal Clipboard.
4. Click where you want the answer, for example an empty note or document.
5. Press **⌃⌥A** and take your hands off the keyboard.

The menu bar shows **Thinking…**, then **Typing… 0:48** while the answer is typed in. Press **⌃⌥A** again to stop early. You can also use the first item in the menu (**Ask About Clipboard** / **Stop Typing**) instead of the shortcut.

### Things to know about typing

- **The text goes wherever the cursor is.** If you click another window while ClipAsk is typing, the rest of the answer goes there.
- **Holding ⌘, ⌃, ⌥ or ⇧ pauses typing.** Otherwise a held key would turn typed letters into shortcuts (for example ⌘ + a typed "q" would quit the app). Let go and it continues.
- **It's slow on purpose.** At 25 WPM a 100-word answer takes about 4 minutes. The menu bar shows the time left. Change the speed in **Typing Speed…**.
- **Line breaks press Return.** In a spreadsheet, each line goes into the next cell down.
- **Code editors may add extra characters.** Editors like VS Code and Xcode add their own indentation and closing brackets as you type, so typed code can end up with extra spaces or doubled `}`. Type into a plain editor such as TextEdit or Notes, or turn off auto-indent and auto-closing brackets in the editor.
- **Code questions get only the code.** The default system prompt asks the AI to put code in a ``` block with no explanation. If the answer contains such a block, only the code inside it is typed; any sentences around it are left out.
- **Prefer a window?** Choose **Answer Output → Show in Popup**.

### Menu settings

| Menu item | What it does |
|---|---|
| **Ask About Clipboard / Stop Typing** | Same as pressing ⌃⌥A. |
| **Answer Output** | **Type It Out** (default) types the answer where your cursor is. **Show in Popup** shows it in the floating window. |
| **Typing Speed: … WPM** | How fast answers are typed, in words per minute (5 to 300). Default 25. |
| **Provider** | Which AI service to use. Each provider has its own saved key and model. |
| **Model: …** | The model name. Defaults: `gpt-5.4-mini` (OpenAI), `claude-sonnet-5-5` (Anthropic), `gemini-3.6-flash` (Gemini). Model names change over time; if you get a "model wasn't found" error, look up a current name on the provider's website and type it here. Leave it empty to return to the default. |
| **… API Key…** | Save or replace the key for the current provider. It shows the last 4 characters of the saved key so you can tell which one it is. |
| **System Prompt…** | Optional instructions sent with every question. The default asks for short plain-text answers (so no Markdown symbols like `**` get typed), and for code questions, only the code. Clear it to send none. Option+Return adds a new line. |
| **Start at Login** | Starts ClipAsk automatically when you log in (see below). |
| **Quit ClipAsk** | Stops the app. |

### What happens when something goes wrong

Every problem is shown in the popup in red, never typed into your document, instead of crashing or doing nothing:

- **Empty clipboard**, or the clipboard holds an image instead of text
- **No API key** saved for the current provider
- **Network failure** (no internet, or the service can't be reached)
- **Timeout**: no answer within 20 seconds
- **API errors**: wrong key, unknown model, out of credit or rate-limited, service down. The provider's own error message is shown under "Details".

When a provider replies that it's overloaded ("high demand", HTTP 503), ClipAsk waits and tries again twice (after 1 and 3 seconds) before showing the error. These overloads often hit one model at a time, so if the error keeps coming back, choose a different model in the menu.

### Where things are saved

| What | Where |
|---|---|
| API keys | macOS Keychain. Open **Keychain Access** and search "ClipAsk". |
| Provider, models, system prompt, output, typing speed | `~/Library/Application Support/ClipAsk/settings.json` |
| Start at Login | `~/Library/LaunchAgents/com.clipask.app.plist` (exists only while the option is on) |
| Log when started at login | `~/Library/Logs/ClipAsk.log` |

**Start at Login** writes a small "LaunchAgent" file that tells macOS what to run when you log in. Turn it on from the packaged `ClipAsk.app` (section 4), not while testing with `python app.py`. A script started at login doesn't run inside Terminal, so the permission you gave Terminal doesn't apply: macOS asks for permission for "Python" instead, and the shortcut won't work until you grant that too. If you move the app, turn the option off and on again. macOS may show a "Background Items Added" notice; that's expected.

## 4. Package it as ClipAsk.app (py2app)

A packaged app contains Python and all the libraries. It runs without Terminal, can live in your Applications folder and has no Dock icon.

```bash
cd ~/Documents/clipask
source .venv/bin/activate
pip install py2app
python setup.py py2app
```

This takes a minute and creates `dist/ClipAsk.app` (about 30 MB). Then:

1. Drag `dist/ClipAsk.app` into **Applications** and double-click it.
2. Quit any copy you're running with `python app.py` first, so you don't get two.
3. Grant the permissions from section 2, this time to **ClipAsk**, and restart it.
4. Your API keys and settings carry over, because they're stored per user, not inside the app. macOS may ask once whether ClipAsk can use its Keychain item; click **Always Allow**.
5. Turn **Start at Login** on from the app's menu, so it points to the app instead of the script.

Tips:

- `python setup.py py2app -A` builds a quick "alias" version that uses your source files directly. It's handy for testing, but it only works on your Mac.
- Delete the `build` and `dist` folders before rebuilding if something seems stale.
- The app isn't code-signed. It runs fine on the Mac that built it. On another Mac, macOS will block the first launch: right-click the app → **Open**, or go to **System Settings → Privacy & Security → Open Anyway**.

## Troubleshooting

- **Installer error mentioning `ensurepip`.** An older installer used whichever Python came first on the Mac (for example Homebrew's), and some of those can't set up pip. Run the install command again: it now uses Apple's own Python and replaces the unfinished environment automatically.
- **⌃⌥A does nothing.** Check section 2 (right app, both permissions, restart). Use **Ask About Clipboard** in the menu to test everything else.
- **"ClipAsk can't type for you yet".** Turn on the Accessibility permission (section 2) and restart ClipAsk.
- **It answered the wrong text.** ClipAsk answers whatever you copied last. Copying anything else in between (even an error message) replaces your question.
- **"The model … wasn't found".** Change the model name in the menu.
- **"didn't answer within 20 seconds".** Try a shorter question or a faster model. To change the limit, edit `TIMEOUT_SECONDS` in `ai_client.py`.
- **Different shortcut.** Edit `_HOTKEY_MODIFIERS` and `_KEY_CODE_A` in `hotkey.py`, plus `HOTKEY_LABEL` for the menu text.

## Privacy

When you press ⌃⌥A, the text on your clipboard is sent to the provider you chose. Nothing is sent at any other time. Don't press it while a password or other secret is on your clipboard.

## Uninstall

1. Quit ClipAsk and turn off **Start at Login** first, or delete `~/Library/LaunchAgents/com.clipask.app.plist`.
2. Delete `ClipAsk.app` and `~/Library/Application Support/ClipAsk`. If you used the one-command install, also delete the `~/.clipask` folder and the ClipAsk lines at the end of `~/.zshrc`.
3. Remove the "ClipAsk" items in **Keychain Access**.
4. Remove ClipAsk from the Input Monitoring and Accessibility lists.
