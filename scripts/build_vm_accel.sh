#!/bin/sh
# Build the in-process VM accelerator used by fm_live_mcp/fmdb/fastvm.py.
# It needs no entitlement: it never reads the game (see native/fm_vm_accel.c).
# Version 2 (read tracking for on-demand cells) is built under its own name, so a process that
# has the version-1 library loaded is not disturbed; fastvm.py prefers version 2.
set -eu
cd "$(dirname "$0")/.."
mkdir -p build
/usr/bin/clang -std=c11 -Wall -Wextra -Werror -O2 -dynamiclib \
  -o build/libfm_vm_accel2.dylib native/fm_vm_accel.c
/usr/bin/codesign --force --sign - build/libfm_vm_accel2.dylib
