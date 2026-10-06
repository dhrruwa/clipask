#!/bin/bash
# install.sh - installs (or updates) ClipAsk on this Mac and starts it.
#
# First time on a Mac, paste this into Terminal:
#
#     curl -fsSL https://raw.githubusercontent.com/dhrruwa/clipask/main/install.sh | bash
#
# After that, open a new Terminal window and just type:  clipask
#
# What it does, step by step:
#   1. Checks this is a Mac with Apple's Command Line Tools (they include
#      Python 3 and git).
#   2. Downloads ClipAsk from GitHub into ~/.clipask, or updates it if it's
#      already there. (No internet? It keeps using the version it has.)
#   3. Creates ClipAsk's private Python environment and installs its
#      libraries. This only happens the first time or when they change.
#   4. Adds the short `clipask` command to your shell (once).
#   5. Starts ClipAsk in the background, so it keeps running after you
#      close Terminal. A copy that's already running is stopped first.
#
# Settings for testing: CLIPASK_DIR (install folder), CLIPASK_REPO (where to
# download from), CLIPASK_NO_START=1 (set up but don't start).

set -euo pipefail

REPO_URL="${CLIPASK_REPO:-https://github.com/dhrruwa/clipask.git}"
INSTALL_DIR="${CLIPASK_DIR:-$HOME/.clipask}"

say() { printf '\033[1m==> %s\033[0m\n' "$1"; }
fail() { printf '\033[31mClipAsk: %s\033[0m\n' "$1" >&2; exit 1; }

# 1. A Mac with the Command Line Tools.
[ "$(uname)" = "Darwin" ] || fail "ClipAsk only runs on macOS."
if ! xcode-select -p >/dev/null 2>&1; then
    xcode-select --install >/dev/null 2>&1 || true
    fail "Apple's Command Line Tools are needed. Click Install in the window that just opened, wait for it to finish, then run this command again."
fi

# 2. Download or update ClipAsk.
if [ -d "$INSTALL_DIR/.git" ]; then
    say "Updating ClipAsk in $INSTALL_DIR"
    git -C "$INSTALL_DIR" pull --ff-only --quiet \
        || echo "    Couldn't update (offline?). Using the version already installed."
else
    say "Downloading ClipAsk to $INSTALL_DIR"
    git clone --quiet "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# 3. Python environment and libraries.
if [ ! -x .venv/bin/python ]; then
    say "Creating ClipAsk's Python environment"
    python3 -m venv .venv
fi
# A copy of requirements.txt is kept in .venv after installing, so we only
# run pip again when the list of libraries has changed.
if ! cmp -s requirements.txt .venv/installed-requirements.txt; then
    say "Installing libraries (the first time takes a minute or two)"
    .venv/bin/python -m pip install --quiet --upgrade pip
    .venv/bin/python -m pip install --quiet -r requirements.txt
    cp requirements.txt .venv/installed-requirements.txt
fi

# 4. The `clipask` command: an alias in your shell's settings file.
case "$(basename "${SHELL:-zsh}")" in
    bash) SHELL_FILE="$HOME/.bash_profile" ;;
    *) SHELL_FILE="$HOME/.zshrc" ;;
esac
if ! grep -q "alias clipask=" "$SHELL_FILE" 2>/dev/null; then
    say "Adding the 'clipask' command to $SHELL_FILE"
    {
        echo ""
        echo "# ClipAsk: type 'clipask' to update and start it"
        echo "alias clipask='bash \"$INSTALL_DIR/install.sh\"'"
    } >> "$SHELL_FILE"
fi

# 5. Start it.
if [ "${CLIPASK_NO_START:-}" = "1" ]; then
    say "Set up finished (not starting, because CLIPASK_NO_START=1)"
    exit 0
fi
say "Starting ClipAsk"
.venv/bin/python app.py --background

cat <<'EOF'

ClipAsk is in the menu bar (top right of the screen).

First time on this Mac:
  1. System Settings → Privacy & Security → Input Monitoring: turn on Terminal.
  2. Same under Accessibility: turn on Terminal.
  3. Open a new Terminal window and type:  clipask   (restarts it with the permissions)
  4. Menu bar → ClipAsk → "Google Gemini API Key…" and paste your key.

From now on, type  clipask  in any new Terminal window to update and restart it.
EOF
