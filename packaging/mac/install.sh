#!/bin/sh
# FMCP 27 installer for macOS on Apple Silicon.
#
#   sh ~/Downloads/FMCP27/install.sh
#
# Copies this folder to ~/FMCP27 (FMCP27_DIR=/other/place overrides), clears the
# download quarantine from the copy, and sets up a private Python there with uv.
# It needs no administrator password and writes only to that folder. It changes
# nothing in Steam or in the game: pasting the launch line into Steam is yours.
#
# Running it again replaces the installed copy (an update or a repair).
# To remove FMCP 27: delete the Steam launch line, then delete the folder.
set -eu

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${FMCP27_DIR:-$HOME/FMCP27}"
PYTHON_VERSION="3.14"

say() { printf '%s\n' "$*"; }
fail() { printf 'FMCP 27 install: %s\n' "$*" >&2; exit 1; }

[ "$(/usr/bin/uname -s)" = "Darwin" ] || fail "this package is for macOS."
[ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = "1" ] \
    || fail "this package needs a Mac with Apple Silicon."
[ -f "$SRC/VERSION" ] && [ -d "$SRC/fm_live_mcp" ] && [ -f "$SRC/build/libfmcp_attach.dylib" ] \
    || fail "run install.sh from inside the unzipped FMCP27 folder."

say "Installing FMCP 27 $(/usr/bin/head -n 1 "$SRC/VERSION") to $DEST"

if [ "$SRC" != "$DEST" ]; then
    if [ -e "$DEST" ] && [ ! -f "$DEST/VERSION" ]; then
        fail "$DEST exists and is not an FMCP 27 folder. Move it away, or set FMCP27_DIR to another place."
    fi
    /bin/mkdir -p "$DEST"
    # Remove the old program files first. A running game keeps its loaded copy of the
    # library; writing over that file in place could crash it, a new file cannot.
    for item in fm_live_mcp build scripts builds; do
        if [ -e "$DEST/$item" ]; then /bin/rm -r -f "$DEST/$item"; fi
    done
    for item in fm_live_mcp build scripts builds fm_launch.sh fmcp27-mcp fmcp27-doctor install.sh \
                seed_builds.py requirements.txt README.txt VERSION; do
        /bin/cp -R "$SRC/$item" "$DEST/"
    done
fi

# Files from a browser download carry a quarantine mark, and macOS refuses to load a
# quarantined library into the game. Clear it from our own copy.
/usr/bin/xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
/bin/chmod +x "$DEST/fm_launch.sh" "$DEST/fmcp27-mcp" "$DEST/fmcp27-doctor" "$DEST/scripts/fm_launch.sh" \
    "$DEST/build/fm_fast_reader" "$DEST/build/fm_live_helper"

for binary in libfmcp_attach.dylib fm_fast_reader fm_live_helper libfm_vm_accel2.dylib libfm_ui_accel2.dylib; do
    /usr/bin/codesign --verify "$DEST/build/$binary" 2>/dev/null \
        || fail "build/$binary did not pass its signature check. Download the package again."
done

# Python: uv, a private Python, and the pinned packages from requirements.txt.
UV="$DEST/bin/uv"
if [ ! -x "$UV" ]; then
    UV="$(command -v uv 2>/dev/null || true)"
fi
if [ -z "$UV" ]; then
    say "Downloading uv (the Python installer) from astral.sh"
    /usr/bin/curl -LsSf https://astral.sh/uv/install.sh \
        | /usr/bin/env UV_UNMANAGED_INSTALL="$DEST/bin" /bin/sh >/dev/null 2>&1 \
        || fail "could not download uv. Check the internet connection and run install.sh again."
    UV="$DEST/bin/uv"
    [ -x "$UV" ] || fail "uv was not installed to $DEST/bin."
fi

export UV_PYTHON_INSTALL_DIR="$DEST/python"
export UV_PYTHON_PREFERENCE="only-managed"
export UV_CACHE_DIR="$DEST/.uv-cache"
say "Setting up Python $PYTHON_VERSION and the reader's packages (a few minutes the first time)"
"$UV" venv --quiet --allow-existing --python "$PYTHON_VERSION" "$DEST/.venv" \
    || fail "could not set up Python. Check the internet connection and run install.sh again."
"$UV" pip install --quiet --link-mode copy --python "$DEST/.venv/bin/python" --require-hashes \
    -r "$DEST/requirements.txt" \
    || fail "could not install the Python packages. Check the internet connection and run install.sh again."
"$UV" cache clean --quiet 2>/dev/null || true

(cd "$DEST" && "$DEST/.venv/bin/python" -W ignore -c "import fm_live_mcp.server") \
    || fail "the reader did not start. Run install.sh again; if it still fails, download the package again."

# The full path, always: Steam starts the launch option itself, with no shell, so "~" is not
# expanded and "~/FMCP27/fm_launch.sh" fails with "OS Error 260" (seen 14 November 2026).
case "$DEST" in
    *[!A-Za-z0-9/._-]*) LINE="\"$DEST/fm_launch.sh\" %command%" ;;
    *) LINE="$DEST/fm_launch.sh %command%" ;;
esac
COPIED=""
if [ -z "${FMCP27_NO_CLIPBOARD:-}" ] && printf '%s' "$LINE" | /usr/bin/pbcopy 2>/dev/null; then
    COPIED=" (it is on the clipboard now)"
fi

say ""
say "FMCP 27 is installed."
say ""
say "1. In Steam: Football Manager 27 > Properties > General > Launch Options."
say "   Paste this line$COPIED:"
say ""
say "     $LINE"
say ""
say "2. Add FMCP 27 to your assistant:"
say ""
say "     Claude Code:  claude mcp add --scope user fmcp27 -- \"$DEST/fmcp27-mcp\""
say "     Codex:        codex mcp add fmcp27 -- \"$DEST/fmcp27-mcp\""
say "     Pi:           pi mcp add fmcp27 -- \"$DEST/fmcp27-mcp\""
say "     Other:        the server is the command  $DEST/fmcp27-mcp"
say ""
say "3. Start Football Manager 27 from Steam and load your save."
say "   To check the link at any time:  $DEST/fmcp27-doctor"
say ""
say "README.txt in $DEST has these steps and how to remove FMCP 27."
