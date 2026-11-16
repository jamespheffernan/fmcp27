#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p build
/usr/bin/clang -std=c11 -Wall -Wextra -Werror -O2 \
  -o build/fm_fast_reader native/fm_fast_reader.c
/usr/bin/codesign --force --sign - \
  --entitlements native/fm_live_helper.entitlements build/fm_fast_reader
