#!/bin/sh
# Build and ad-hoc sign the in-game attach library (native/fmcp_attach_lib.c).
#
# The game disables library validation (com.apple.security.cs.disable-library-validation),
# so an ad-hoc signature is enough for it to load the library; verified on this
# machine. A universal slice (arm64 + x86_64) matches the game, which is universal.
set -eu
cd "$(dirname "$0")/.."
mkdir -p build
/usr/bin/clang -std=c11 -Wall -Wextra -Werror -O2 \
  -arch arm64 -arch x86_64 \
  -Inative -dynamiclib \
  -o build/libfmcp_attach.dylib native/fmcp_attach_lib.c -lbsm
/usr/bin/codesign --force --sign - build/libfmcp_attach.dylib
echo "built build/libfmcp_attach.dylib"
