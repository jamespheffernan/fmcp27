#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec .venv/bin/python -m fm_live_mcp.server

