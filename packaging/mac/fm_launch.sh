#!/bin/sh
# Steam launch option for Football Manager 27:
#
#   /Users/YOUR-NAME/FMCP27/fm_launch.sh %command%
#
# The full path: Steam does not expand "~". install.sh prints the exact line.
#
# Starts the game with the FMCP 27 library loaded. Delete the line in Steam to go
# back to a normal launch. scripts/fm_launch.sh has the details.
exec /bin/sh "$(cd "$(dirname "$0")" && pwd)/scripts/fm_launch.sh" "$@"
