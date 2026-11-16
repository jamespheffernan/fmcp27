#!/usr/bin/env python3
"""Say whether the running Football Manager has the FMCP attach library loaded.

It finds the FM process and asks the in-game library to answer over its Mach
channel via ``fm_fast_reader --route injected``. A successful PING proves the
library is loaded without any task_for_pid, so this works on a Mac with default
SIP. Exit status: 0 loaded (injected route ready), 2 not loaded, 1 other error.

Usage: PYTHONPATH=. python scripts/fm_attach_doctor.py [--pid N]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fm_live_mcp.fmdb.memory import LiveMemory, MemoryReadError, find_fm_process, launch_fix  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, help="FM process id (default: auto-detect)")
    args = parser.parse_args()

    process = find_fm_process()
    pid = args.pid or (process.pid if process else None)
    if pid is None:
        print("doctor: Football Manager is not running.")
        return 1
    exe = process.executable if process and process.pid == pid else None

    try:
        mem = LiveMemory(pid, expected_executable=exe, route="injected")
    except MemoryReadError as exc:
        print(f"doctor: attach library NOT loaded for pid {pid}.")
        print(f"  reason: {exc}")
        print(f"  fix: quit the game, then {launch_fix()[0]}.")
        return 2
    with mem:
        print(f"doctor: attach library loaded for pid {pid}.")
        print(f"  route={mem.route} page_size={mem.page_size} executable=...{mem.executable[-48:]}")
        region_count = len(mem.regions())
        print(f"  channel live: {region_count:,} memory regions visible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
