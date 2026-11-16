#!/bin/sh
# Build the Mac download: site/public/download/FMCP27-mac.zip.
#
#   sh scripts/package_mac.sh
#
# The package is built from a commit, never from the working tree, so what a
# player downloads can be named by its commit: the reader (fm_live_mcp), the
# native sources, the launcher and the installer files in packaging/mac all come
# from `git archive $FMCP27_REF` (default HEAD). The native pieces are compiled
# here with the flags of scripts/build_*.sh into the package, not into build/,
# so a reader that is running from this checkout is not disturbed.
#
# What a player gets (see packaging/mac/README.txt for their steps):
#   FMCP27/install.sh, README.txt, VERSION
#   FMCP27/fm_launch.sh            the Steam launch option
#   FMCP27/fmcp27-mcp              the MCP server command
#   FMCP27/fmcp27-doctor           says whether the game has the library loaded
#   FMCP27/build/                  libfmcp_attach.dylib (universal), fm_fast_reader,
#                                  fm_live_helper, libfm_vm_accel2.dylib, libfm_ui_accel2.dylib
#   FMCP27/fm_live_mcp/            the reader
#   FMCP27/scripts/                fm_launch.sh, fm_attach_doctor.py
#   FMCP27/requirements.txt        pinned, hashed packages exported from uv.lock
#   FMCP27/builds/                 the address map, anchors, front-end files and read plans of
#                                  the game build installed on this Mac (seed_builds.py). The
#                                  reader's source addresses build 27.0.0.2493426 only; a player
#                                  cannot derive another build's files, so they ship. These come
#                                  from this Mac's reader cache, not from the commit: run
#                                  scripts/fm_update_build.py --installed after a game update,
#                                  then package again.
# Python itself is not in the zip: install.sh fetches uv and a private Python.
#
# Not in the package: fm_live_write and fm_training_editor (the edit tier), the
# adviser (pi-fm), tests, evidence.
#
# Environment:
#   FMCP27_REF            commit to package (default HEAD)
#   FMCP27_OUT            output zip (default site/public/download/FMCP27-mac.zip)
#   FMCP27_SIGN_IDENTITY  codesign identity. Default: the first "Developer ID Application"
#                         identity in the keychain, else "-" (ad-hoc). Set "-" for a test build.
#   FMCP27_NOTARIZE       1 (default with a Developer ID) sends the zip to Apple's notary
#                         service and fails if Apple does not accept it; 0 skips it.
#   FMCP27_NOTARY_KEY, FMCP27_NOTARY_KEY_ID, FMCP27_NOTARY_ISSUER
#                         App Store Connect API key for notarytool. Default: key_path, key_id
#                         and issuer_id from ~/.config/app-store-connect/config.json, whose
#                         developer_dir also picks the Xcode that runs notarytool.
#
# With a Developer ID every binary is signed with the hardened runtime and a secure
# timestamp, as notarization requires. A zip cannot carry a stapled ticket; Gatekeeper
# looks the ticket up online on first use.
#   FMCP_CACHE_DIR        the reader cache holding fmdb/anchors and fmdb/plans
#   FMCP_PLUGIN_PATH      the game_plugin whose build files to ship (default: the Steam install)
#
# Cloudflare Pages serves no file over 25 MiB; the script fails above that.
# Check the result with: python3 scripts/test_package_mac.py
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REF="${FMCP27_REF:-HEAD}"
OUT="${FMCP27_OUT:-$ROOT/site/public/download/FMCP27-mac.zip}"
MAX_BYTES=$((25 * 1024 * 1024))

if [ -n "${FMCP27_SIGN_IDENTITY:-}" ]; then
    IDENTITY="$FMCP27_SIGN_IDENTITY"
else
    IDENTITY="$(/usr/bin/security find-identity -v -p codesigning 2>/dev/null \
        | /usr/bin/sed -n 's/.*"\(Developer ID Application: [^"]*\)".*/\1/p' | /usr/bin/head -n 1)"
    IDENTITY="${IDENTITY:--}"
fi
if [ "$IDENTITY" = "-" ]; then
    SIGN_FLAGS=""
    NOTARIZE="${FMCP27_NOTARIZE:-0}"
else
    SIGN_FLAGS="--options runtime --timestamp"
    NOTARIZE="${FMCP27_NOTARIZE:-1}"
fi
echo "package_mac: signing with ${IDENTITY}; notarize=${NOTARIZE}" >&2

command -v uv >/dev/null 2>&1 || { echo "package_mac: uv is needed to export requirements.txt" >&2; exit 1; }

COMMIT="$(git -C "$ROOT" rev-parse --short=10 "$REF")"
COMMIT_DATE="$(git -C "$ROOT" show -s --format=%cd --date=format:%Y%m%d%H%M.%S "$REF")"
COMMIT_DAY="$(git -C "$ROOT" show -s --format=%cd --date=format:%Y-%m-%d "$REF")"

WORK="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/fmcp27-package.XXXXXX")"
cleanup() { /bin/rm -r -f "$WORK"; }
trap cleanup EXIT INT TERM

SRC="$WORK/src"
STAGE="$WORK/stage/FMCP27"
/bin/mkdir -p "$SRC" "$STAGE/build" "$STAGE/scripts"

git -C "$ROOT" archive "$REF" fm_live_mcp native packaging/mac pyproject.toml uv.lock \
    scripts/fm_launch.sh scripts/fm_attach_doctor.py | /usr/bin/tar -x -C "$SRC"

VERSION="$(/usr/bin/sed -n 's/^version = "\(.*\)"/\1/p' "$SRC/pyproject.toml" | /usr/bin/head -n 1)"
[ -n "$VERSION" ] || { echo "package_mac: no version in pyproject.toml at $REF" >&2; exit 1; }

changed="$(git -C "$ROOT" status --porcelain -- fm_live_mcp native packaging/mac scripts/fm_launch.sh scripts/fm_attach_doctor.py uv.lock)"
if [ -n "$changed" ]; then
    echo "package_mac: note: these paths differ from the index or are untracked; the package uses $REF ($COMMIT), not the working tree:" >&2
    echo "$changed" | /usr/bin/sed 's/^/  /' >&2
fi

# Native pieces. Flags as in scripts/build_attach_lib.sh, build_fast_reader.sh,
# build_helper.sh, build_vm_accel.sh and build_ui_accel.sh.
CC="/usr/bin/clang -std=c11 -Wall -Wextra -Werror -O2"
N="$SRC/native"
B="$STAGE/build"
$CC -arch arm64 -arch x86_64 -I"$N" -dynamiclib -o "$B/libfmcp_attach.dylib" "$N/fmcp_attach_lib.c" -lbsm
$CC -o "$B/fm_fast_reader" "$N/fm_fast_reader.c"
$CC -o "$B/fm_live_helper" "$N/fm_live_helper.c"
$CC -dynamiclib -o "$B/libfm_vm_accel2.dylib" "$N/fm_vm_accel.c"
$CC -dynamiclib -o "$B/libfm_ui_accel2.dylib" "$N/fm_ui_accel.c"
# shellcheck disable=SC2086  # SIGN_FLAGS is a word list on purpose
for library in libfmcp_attach.dylib libfm_vm_accel2.dylib libfm_ui_accel2.dylib; do
    /usr/bin/codesign --force --sign "$IDENTITY" $SIGN_FLAGS "$B/$library"
done
# shellcheck disable=SC2086
for tool in fm_fast_reader fm_live_helper; do
    /usr/bin/codesign --force --sign "$IDENTITY" $SIGN_FLAGS --entitlements "$N/fm_live_helper.entitlements" "$B/$tool"
done

# The reader, the launcher and the player's files.
/bin/cp -R "$SRC/fm_live_mcp" "$STAGE/fm_live_mcp"
/bin/cp "$SRC/scripts/fm_launch.sh" "$SRC/scripts/fm_attach_doctor.py" "$STAGE/scripts/"
for item in install.sh fm_launch.sh fmcp27-mcp fmcp27-doctor seed_builds.py README.txt; do
    /bin/cp "$SRC/packaging/mac/$item" "$STAGE/$item"
done
/bin/chmod 755 "$STAGE/install.sh" "$STAGE/fm_launch.sh" "$STAGE/fmcp27-mcp" "$STAGE/fmcp27-doctor" \
    "$STAGE/scripts/fm_launch.sh" "$B/fm_fast_reader" "$B/fm_live_helper"

# The game build installed here: ship its derived files unless it is the pinned build.
PINNED_SHA="$(/usr/bin/sed -n "s/^PINNED_SHA256 = '\(.*\)'/\1/p" "$SRC/fm_live_mcp/address_book.py")"
PLUGIN="${FMCP_PLUGIN_PATH:-$HOME/Library/Application Support/Steam/steamapps/common/Football Manager 27/fm.app/Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin}"
CACHE="${FMCP_CACHE_DIR:-/Volumes/4TB Private/Offloaded/Agent Work/fmcp-source-cache}"
[ -f "$PLUGIN" ] || { echo "package_mac: no game plugin at $PLUGIN; set FMCP_PLUGIN_PATH" >&2; exit 1; }
[ -n "$PINNED_SHA" ] || { echo "package_mac: no PINNED_SHA256 in address_book.py at $REF" >&2; exit 1; }
GAME_SHA="$(/usr/bin/shasum -a 256 "$PLUGIN" | /usr/bin/cut -d ' ' -f 1)"
GAME_VERSION="$(/usr/bin/defaults read "${PLUGIN%/Contents/PlugIns/*}/Contents/Info" CFBundleShortVersionString 2>/dev/null || echo unknown)"
/bin/mkdir -p "$STAGE/builds/anchors" "$STAGE/builds/plans"
if [ "$GAME_SHA" != "$PINNED_SHA" ]; then
    /usr/bin/python3 "$SRC/packaging/mac/seed_builds.py" collect "$CACHE/fmdb" "$GAME_SHA" "$STAGE/builds"
fi

/usr/bin/python3 "$SRC/packaging/mac/seed_builds.py" scrub "$STAGE/fm_live_mcp/fmdb/data"

(cd "$SRC" && uv export --quiet --frozen --no-dev --no-emit-project --no-header --no-annotate \
    -o "$STAGE/requirements.txt") >/dev/null
printf '%s\ncommit %s\n%s\ngame %s\n' "$VERSION" "$COMMIT" "$COMMIT_DAY" "$GAME_VERSION" > "$STAGE/VERSION"

# The packaging user's name must not ship: not in a script, a binary's strings or a data file.
OWNER="$(/usr/bin/id -un)"
if /usr/bin/grep -r -l -i -e "$OWNER" "$STAGE" 2>/dev/null \
        || /usr/bin/find "$STAGE" -name '*.gz' -exec /bin/sh -c '/usr/bin/gzip -dc "$1" | /usr/bin/grep -q -i -e "$2"' sh {} "$OWNER" \; -print | /usr/bin/grep .; then
    echo "package_mac: the files above contain the packaging user's name ($OWNER)" >&2
    exit 1
fi

# Notarization rejects any unsigned Mach-O file, so check that every one carries our signature.
/usr/bin/find "$STAGE" -type f -print | while IFS= read -r file; do
    case "$(/usr/bin/file -b "$file")" in
        *Mach-O*)
            /usr/bin/codesign --verify --strict "$file" 2>/dev/null \
                || { echo "package_mac: $file is not validly signed" >&2; exit 1; }
            if [ "$IDENTITY" != "-" ]; then
                /usr/bin/codesign -dvv "$file" 2>&1 | /usr/bin/grep -q "^Authority=$IDENTITY\$" \
                    || { echo "package_mac: $file is not signed by $IDENTITY" >&2; exit 1; }
            fi ;;
    esac
done

# Same bytes for the same commit: fixed times, no Finder files, sorted names.
/usr/bin/find "$WORK/stage" -name .DS_Store -delete
/usr/bin/find "$WORK/stage" -exec /usr/bin/touch -h -t "$COMMIT_DATE" {} +
/bin/mkdir -p "$(dirname "$OUT")"
/bin/rm -f "$OUT"
(cd "$WORK/stage" && /usr/bin/find FMCP27 -print | LC_ALL=C /usr/bin/sort | /usr/bin/zip -X -q -9 "$OUT" -@)

BYTES="$(/usr/bin/stat -f %z "$OUT")"
if [ "$BYTES" -gt "$MAX_BYTES" ]; then
    echo "package_mac: $OUT is $BYTES bytes, over the 25 MiB Cloudflare Pages file limit. Host it elsewhere (an R2 bucket) and point the button there." >&2
    exit 1
fi
if [ "$NOTARIZE" = "1" ]; then
    config_value() {
        /usr/bin/python3 -c 'import json, os, sys
path = os.path.expanduser("~/.config/app-store-connect/config.json")
print(json.load(open(path)).get(sys.argv[1], "") if os.path.exists(path) else "")' "$1"
    }
    NOTARY_KEY="${FMCP27_NOTARY_KEY:-$(config_value key_path)}"
    NOTARY_KEY_ID="${FMCP27_NOTARY_KEY_ID:-$(config_value key_id)}"
    NOTARY_ISSUER="${FMCP27_NOTARY_ISSUER:-$(config_value issuer_id)}"
    CONFIG_DEVELOPER_DIR="$(config_value developer_dir)"
    [ -n "$NOTARY_KEY" ] && [ -n "$NOTARY_KEY_ID" ] && [ -n "$NOTARY_ISSUER" ] \
        || { echo "package_mac: no notary key; set FMCP27_NOTARY_KEY, _KEY_ID and _ISSUER, or FMCP27_NOTARIZE=0" >&2; exit 1; }
    if [ -n "$CONFIG_DEVELOPER_DIR" ] && [ -z "${DEVELOPER_DIR:-}" ]; then
        export DEVELOPER_DIR="$CONFIG_DEVELOPER_DIR"
    fi
    echo "package_mac: sending $OUT to Apple's notary service (this can take minutes)" >&2
    RESULT="$(/usr/bin/xcrun notarytool submit "$OUT" --key "$NOTARY_KEY" --key-id "$NOTARY_KEY_ID" \
        --issuer "$NOTARY_ISSUER" --wait --output-format json 2>&1)" || true
    STATUS="$(printf '%s' "$RESULT" | /usr/bin/python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("status", ""))
except Exception: print("")')"
    if [ "$STATUS" != "Accepted" ]; then
        echo "package_mac: notarization did not succeed:" >&2
        printf '%s\n' "$RESULT" >&2
        echo "package_mac: the zip at $OUT is signed but not notarized. Fix the cause and package again, or set FMCP27_NOTARIZE=0." >&2
        exit 1
    fi
    echo "  notarized: $(printf '%s' "$RESULT" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin).get("id", ""))')"
fi

echo "built $OUT"
echo "  reader $VERSION, commit $COMMIT, game build $GAME_VERSION, $BYTES bytes"
echo "  sha256 $(/usr/bin/shasum -a 256 "$OUT" | /usr/bin/cut -d ' ' -f 1)"
