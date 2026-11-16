#!/bin/sh
# fm_launch.sh: start Football Manager 27 with the FMCP attach library loaded.
#
# The library (build/libfmcp_attach.dylib) is loaded into the game at launch via
# DYLD_INSERT_LIBRARIES. The game's entitlements allow this: it has
# com.apple.security.cs.allow-dyld-environment-variables and
# com.apple.security.cs.disable-library-validation (verify with
# `codesign -d --entitlements - <fm.app>`). Once loaded the library serves the
# FMCP readers over a Mach channel so they never need task_for_pid.
#
# Two ways to use it:
#
#   1. Steam launch option (recommended). In Steam, Football Manager 27 ->
#      Properties -> General -> Launch Options, set:
#
#        /ABSOLUTE/PATH/TO/scripts/fm_launch.sh %command%
#
#      Steam passes the .app bundle path as %command%; this script resolves it to
#      the inner executable, sets the environment, and execs it. Remove the launch
#      option to go back to a normal launch (that is the whole uninstall).
#
#   2. Directly, for a stock (non-Steam) run:  scripts/fm_launch.sh
#      It finds fm.app in the default Steam library and launches its executable.
#
# This script never modifies the game bundle or any Steam file.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIB="${FMCP_ATTACH_LIB:-$ROOT/build/libfmcp_attach.dylib}"
DEFAULT_APP="$HOME/Library/Application Support/Steam/steamapps/common/Football Manager 27/fm.app"

if [ ! -f "$LIB" ]; then
    echo "fm_launch: attach library missing at $LIB (run sh scripts/build_attach_lib.sh)" >&2
    exit 1
fi

# Resolve the target executable from the first argument, or the default bundle.
target=""
if [ "$#" -ge 1 ]; then
    arg="$1"; shift
    case "$arg" in
        *.app) target="$arg/Contents/MacOS/$(/usr/bin/defaults read "$arg/Contents/Info" CFBundleExecutable 2>/dev/null || basename "$arg" .app)" ;;
        *) target="$arg" ;;  # Steam sometimes passes the executable directly
    esac
else
    app="$DEFAULT_APP"
    target="$app/Contents/MacOS/$(/usr/bin/defaults read "$app/Contents/Info" CFBundleExecutable 2>/dev/null || echo 'Football Manager 27')"
fi

if [ ! -x "$target" ]; then
    echo "fm_launch: game executable not found or not executable: $target" >&2
    exit 1
fi

# FMCP_ATTACH_TARGET gates the library: it serves only the process whose
# executable path matches, so a child process that inherits the environment stays
# inert. FMCP_ATTACH_DISABLE=1 (set in the environment before launching) turns the
# library off entirely without removing the launch option.
export FMCP_ATTACH_TARGET="$target"
export DYLD_INSERT_LIBRARIES="$LIB"

# On Apple Silicon, start the native arm64 slice. Steam runs launch-option wrappers in a way
# that made the game start as the x86_64 slice under Rosetta (seen 12 Nov 2026 on 27.0.1: the
# library loaded, but the reader is matched to the arm64 plugin and found none). /usr/bin/arch
# selects the slice; it is a protected system binary, so the DYLD variable must be given to it
# with -e (the system strips DYLD_* from the environment of protected binaries).
if [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = "1" ] && [ "${FMCP_ATTACH_ARCH:-arm64}" = "arm64" ]; then
    exec /usr/bin/arch -arm64 -e DYLD_INSERT_LIBRARIES="$LIB" -e FMCP_ATTACH_TARGET="$target" "$target" "$@"
fi
exec "$target" "$@"
