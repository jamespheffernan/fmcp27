#!/bin/sh
# Build the in-process accelerator of fm_live_mcp/fmdb/ui_fastvm.py (FastUiHandlerVM).
# A separate library from libfm_vm_accel.dylib (fastvm.FastVM keeps loading that one).
# It needs no entitlement: it never reads the game (see native/fm_ui_accel.c).
# FM_UI_ACCEL_OUT names another output file (default build/libfm_ui_accel2.dylib, ABI 2).
set -eu
cd "$(dirname "$0")/.."
mkdir -p build
OUT="${FM_UI_ACCEL_OUT:-build/libfm_ui_accel2.dylib}"
/usr/bin/clang -std=c11 -Wall -Wextra -Werror -O2 -dynamiclib \
  -o "$OUT.tmp$$" native/fm_ui_accel.c
/usr/bin/codesign --force --sign - "$OUT.tmp$$"
mv -f "$OUT.tmp$$" "$OUT"
