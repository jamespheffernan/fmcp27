#!/bin/sh
# Start the FM live reader from another checkout of the reader repository (for example a git
# worktree), using the main checkout's Python environment. A worktree has no .venv of its own.
#
#   run_reader_from.sh <checkout>            serve the reader from <checkout>
#   FM_READER_CHECKOUT=<checkout> run_reader_from.sh
#   run_reader_from.sh                       serve the checkout that contains this script
#
# pi-fm starts its reader as `/bin/sh "$PI_FM_MCP_LAUNCHER"` with no arguments, so for evals pass
# the checkout through the environment:
#   node adviser/evals/run.mjs --smoke \
#     --env PI_FM_MCP_LAUNCHER="$PWD/adviser/evals/run_reader_from.sh" \
#     --env FM_READER_CHECKOUT=/path/to/worktree
# FMCP_CACHE_DIR (snapshot, knowledge store, UI caches) passes through unchanged; pi-fm sets its default.
# FM_READER_PYTHON overrides the interpreter (default: the main checkout's .venv/bin/python).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
checkout=${1:-${FM_READER_CHECKOUT:-$(cd "$here/../.." && pwd)}}
python=${FM_READER_PYTHON:-"/Volumes/4TB Private/Offloaded/FMCP 27/.venv/bin/python"}
[ -d "$checkout/fm_live_mcp" ] || { echo "run_reader_from.sh: no fm_live_mcp package in $checkout" >&2; exit 2; }
[ -x "$python" ] || { echo "run_reader_from.sh: Python missing: $python" >&2; exit 2; }
cd "$checkout"
PYTHONPATH="$checkout${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH
exec "$python" -m fm_live_mcp.server
