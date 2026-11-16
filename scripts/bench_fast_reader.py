#!/usr/bin/env python3
"""Benchmark fm_fast_reader against the live game and against the old ReadStream path.

Usage: bench_fast_reader.py [--pid N] [--old-helper PATH] [--seed S]
Read-only. Needs FM running and the desktop session (task_for_pid).
"""
import argparse
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fm_live_mcp.fmdb.memory import LiveMemory, find_fm_process  # noqa: E402
from fm_live_mcp.reader import ReadStream  # noqa: E402

OLD_HELPER = "/Volumes/4TB Private/Offloaded/FMCP 27/build/fm_live_helper"


def report(label, items, nbytes, seconds, failed=0):
    mib = nbytes / (1024 * 1024)
    print(f"{label}: {items:,} items ({failed:,} failed), {mib:,.2f} MiB in {seconds:.3f}s = "
          f"{items / seconds:,.0f} items/s, {mib / seconds:,.1f} MiB/s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int)
    parser.add_argument("--old-helper", default=os.environ.get("FM_LIVE_HELPER_FOR_TEST", OLD_HELPER))
    parser.add_argument("--seed", type=int, default=27)
    args = parser.parse_args()
    process = find_fm_process()
    pid = args.pid or (process.pid if process else None)
    if pid is None:
        sys.exit("FM is not running")
    rng = random.Random(args.seed)
    with LiveMemory(pid, expected_executable=process.executable if process and process.pid == pid else None) as m:
        print(f"pid {pid} page_size {m.page_size} exe ...{m.executable[-40:]}")
        t = time.perf_counter()
        regions = m.regions()
        print(f"regions: {len(regions):,} in {time.perf_counter() - t:.3f}s")
        resident = [r for r in regions if r.readable and r.pages_resident]
        weights = [r.pages_resident for r in resident]

        # (1) 100,000 scattered 8-byte reads in batches of 10,000, inside resident regions
        addresses = []
        for r in rng.choices(resident, weights, k=100_000):
            addresses.append((r.start + rng.randrange(0, max(1, r.size - 8)) // 8 * 8, 8))
        failed = 0
        got = []
        t = time.perf_counter()
        for i in range(0, len(addresses), 10_000):
            out = m.read_many(addresses[i:i + 10_000])
            failed += sum(d is None for d in out)
            got.extend(out)
        seconds = time.perf_counter() - t
        report("(1) new scattered 8B, batches of 10,000", len(addresses), 8 * (len(addresses) - failed), seconds, failed)

        # (2) contiguous 1 MiB reads over the largest readable regions (up to 1,000)
        big = sorted((r for r in resident if r.size >= 1 << 20), key=lambda r: -r.size)[:1000]
        wanted = [(r.start + ((r.size - (1 << 20)) // 2) // 16384 * 16384, 1 << 20) for r in big]
        before = m.stats.bytes
        t = time.perf_counter()
        out = m.read_many(wanted)
        seconds = time.perf_counter() - t
        failed = sum(d is None for d in out)
        report("(2) new contiguous 1 MiB over largest regions", len(wanted), m.stats.bytes - before, seconds, failed)
        before = m.stats.bytes
        t = time.perf_counter()
        out = m.read_many(wanted)
        seconds = time.perf_counter() - t
        report("(2) same reads again (warm)", len(wanted), m.stats.bytes - before, seconds,
               sum(d is None for d in out))

        # (3) the same 10,000 small reads, old ReadStream path vs new (readable ones only,
        # because a failed read closes the old stream)
        good = [(a, n) for (a, n), d in zip(addresses, got) if d is not None][:10_000]
        t = time.perf_counter()
        new = m.read_many(good)
        report("(3) new, same 10,000 reads, one batch", len(good), 8 * len(good), time.perf_counter() - t)
        if not Path(args.old_helper).is_file():
            print(f"(3) old ReadStream skipped: {args.old_helper} missing")
            return
        stream = ReadStream(Path(args.old_helper), pid)
        old = []
        t = time.perf_counter()
        try:
            for a, n in good:
                old.append(stream.read(a, n))
        finally:
            seconds = time.perf_counter() - t
            stream.close()
        report("(3) old ReadStream, same 10,000 reads", len(old), 8 * len(old), seconds)
        same = sum(a == b for a, b in zip(old, new))
        print(f"(3) bytes identical on {same:,} of {len(old):,} (live memory may change between reads)")
        t = time.perf_counter()
        singles = [m.read(a, n) for a, n in good[:2000]]
        report("(3) new, one read() per address (2,000)", len(singles), 8 * len(singles), time.perf_counter() - t)
        print(f"stats: round_trips={m.stats.round_trips} items={m.stats.items} bytes={m.stats.bytes} "
              f"seconds={m.stats.seconds:.3f} failed={m.stats.failed_items}")


if __name__ == "__main__":
    main()
