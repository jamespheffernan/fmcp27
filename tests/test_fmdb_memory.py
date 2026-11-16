"""LiveMemory against a fake helper that speaks the fm_fast_reader protocol, plus a
live-gated comparison with the existing Bridge read path."""
import json
import os
import shlex
import struct
import sys
import time
from pathlib import Path

import pytest

from fm_live_mcp.fmdb import memory as mem
from fm_live_mcp.fmdb.memory import (
    LiveMemory, MemoryReadError, ProcessGoneError, Region, SnapshotMemory,
)

FAKE = r'''
import json, os, struct, sys, time
cfg = json.loads(os.environ["FAKE_CFG"])
PS = cfg.get("page_size", 16384)
pages = {int(k): bytes.fromhex(v) for k, v in cfg.get("pages", {}).items()}
log = open(cfg["log"], "a") if cfg.get("log") else None
out = sys.stdout.buffer
def rd(n):
    d = b""
    while len(d) < n:
        c = sys.stdin.buffer.read(n - len(d))
        if not c: sys.exit(0)
        d += c
    return d
path = cfg.get("path", "/fake/FM").encode()
if cfg.get("mode") == "garbage_hello":
    out.write(b"x" * 40); out.flush(); time.sleep(5)
out.write(struct.pack("<7I", 0x4C484D46, cfg.get("hello_status", 0), 1, int(sys.argv[2]), PS, 0, len(path)) + path); out.flush()
if cfg.get("hello_status"): sys.exit(1)
served = 0
while True:
    magic, op, count = struct.unpack("<3I", rd(12))
    if op == 3:
        out.write(struct.pack("<3I", 0x53524D46, 0, 0)); out.flush(); sys.exit(0)
    if op == 2:
        out.write(struct.pack("<3I", 0x53524D46, 0, 0)); out.flush(); continue
    if op == 4:
        recs = [struct.pack("<QQIIII", a, s, p, p, 0, 1) for a, s, p in cfg.get("regions", [])]
        out.write(struct.pack("<3I", 0x53524D46, 0, len(recs)) + b"".join(recs)); out.flush(); continue
    items = [struct.unpack("<QI", rd(12)) for _ in range(count)]
    served += 1
    if log: log.write(json.dumps([len(items), sum(n for _, n in items)]) + "\n"); log.flush()
    mode = cfg.get("mode")
    if mode == "hang":
        time.sleep(60)
    if mode == "die_after" and served > cfg["after"]:
        sys.exit(3)
    if mode == "gone":
        table = b"".join(struct.pack("<II", 8, 0) for _ in items)
        out.write(struct.pack("<3I", 0x53524D46, 8, len(items)) + table); out.flush(); sys.exit(3)
    if mode == "bad_magic":
        out.write(struct.pack("<3I", 1, 0, 0)); out.flush(); continue
    table, payload = b"", b""
    for a, n in items:
        data = b""
        for base in range(a & ~(PS - 1), a + n, PS):
            if base not in pages: data = None; break
            data += pages[base]
        if data is None:
            table += struct.pack("<II", 6, 0)
        else:
            chunk = data[a - (a & ~(PS - 1)):][:n]
            table += struct.pack("<II", 0, n); payload += chunk
    out.write(struct.pack("<3I", 0x53524D46, 0, len(items)) + table + payload); out.flush()
'''


def page_bytes(base, fill=None):
    return bytes((base // 16384 + i) & 0xFF for i in range(16384)) if fill is None else bytes([fill]) * 16384


def make_helper(tmp_path, **cfg):
    if sys.platform == "win32":
        # The stand-in is a shell script, and the helper process is the macOS read route.
        # Windows reads through WindowsMemory (tests/test_fmdb_memory_windows.py).
        pytest.skip("the helper process is the macOS read route")
    script = tmp_path / "fake.py"
    script.write_text(FAKE)
    cfg.setdefault("log", str(tmp_path / "log.jsonl"))
    wrapper = tmp_path / "fake_helper"
    wrapper.write_text(f"#!/bin/sh\nFAKE_CFG={shlex.quote(json.dumps(cfg))} exec {shlex.quote(sys.executable)} {shlex.quote(str(script))} \"$@\"\n")
    wrapper.chmod(0o700)
    return wrapper


def pages_cfg(*bases):
    return {str(b): page_bytes(b).hex() for b in bases}


def batches(tmp_path):
    log = tmp_path / "log.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


BASE = 0x100000000


def test_read_and_unreadable_items_do_not_fail_batch(tmp_path):
    helper = make_helper(tmp_path, pages=pages_cfg(BASE, BASE + 16384))
    with LiveMemory(42, helper=helper) as m:
        assert m.page_size == 16384 and m.executable == "/fake/FM"
        a = page_bytes(BASE)
        got = m.read_many([(BASE + 8, 8), (0x5000_0000, 8), (BASE + 16380, 8), (BASE + 40000, 4)])
        assert got[0] == a[8:16]
        assert got[1] is None
        assert got[2] == a[16380:] + page_bytes(BASE + 16384)[:4]
        assert got[3] is None
        assert m.stats.failed_items == 2 and m.stats.round_trips == 1 and m.stats.items == 4
        with pytest.raises(MemoryReadError) as info:
            m.read(0x5000_0000, 8)
        assert info.value.status == mem.ST_READ_FAILED
        assert m.read(BASE, 4) == a[:4]


def test_invalid_requests_rejected_before_sending(tmp_path):
    helper = make_helper(tmp_path)
    with LiveMemory(42, helper=helper) as m:
        for bad in [(0, 4), (BASE, 0), (BASE, -1), (2**64 - 1, 8)]:
            with pytest.raises(MemoryReadError):
                m.read_many([bad])
        assert batches(tmp_path) == []


def test_chunks_to_item_and_batch_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(mem, "MAX_BATCH_ITEMS", 3)
    monkeypatch.setattr(mem, "MAX_BATCH_BYTES", 100)
    monkeypatch.setattr(mem, "MAX_ITEM_BYTES", 40)
    helper = make_helper(tmp_path, pages=pages_cfg(BASE))
    with LiveMemory(42, helper=helper) as m:
        reqs = [(BASE + i * 10, 10) for i in range(7)] + [(BASE + 1000, 90)]
        out = m.read_many(reqs)
        page = page_bytes(BASE)
        assert out == [page[a - BASE:a - BASE + n] for a, n in reqs]
    sizes = batches(tmp_path)
    assert all(count <= 3 and total <= 100 for count, total in sizes)
    assert sum(c for c, _ in sizes) == 7 + 3  # the 90-byte item splits into 40+40+10


def test_oversize_item_with_failed_piece_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(mem, "MAX_ITEM_BYTES", 16384)
    helper = make_helper(tmp_path, pages=pages_cfg(BASE))
    with LiveMemory(42, helper=helper) as m:
        assert m.read_many([(BASE, 32768)]) == [None]
        assert len(m.read_many([(BASE, 16384)])[0]) == 16384


def test_page_cache_and_cached_read(tmp_path):
    helper = make_helper(tmp_path, pages=pages_cfg(BASE, BASE + 16384, BASE + 32768))
    with LiveMemory(42, helper=helper) as m:
        p = m.page(BASE + 5)
        assert p == page_bytes(BASE) and m.page(BASE + 16383) is p
        assert len(batches(tmp_path)) == 1
        # spans three pages; two are missing and fault in with ONE batched read
        data = m.cached_read(BASE + 16000, 17000)
        assert len(batches(tmp_path)) == 2 and batches(tmp_path)[1] == [2, 32768]
        full = page_bytes(BASE) + page_bytes(BASE + 16384) + page_bytes(BASE + 32768)
        assert data == full[16000:33000]
        m.cached_read(BASE + 100, 8)
        assert len(batches(tmp_path)) == 2
        assert m.stats.cache_hits >= 2
        m.invalidate()
        m.cached_read(BASE + 100, 8)
        assert len(batches(tmp_path)) == 3


def test_cache_reports_unreadable_pages_and_remembers_them(tmp_path):
    helper = make_helper(tmp_path, pages=pages_cfg(BASE))
    with LiveMemory(42, helper=helper) as m:
        with pytest.raises(MemoryReadError):
            m.cached_read(BASE + 16380, 8)  # second page missing
        n = len(batches(tmp_path))
        with pytest.raises(MemoryReadError):
            m.cached_read(BASE + 16380, 8)
        assert len(batches(tmp_path)) == n  # bad page not re-requested
        with pytest.raises(MemoryReadError):
            m.page(BASE + 16384)


def test_windows_skip_a_small_integer_where_a_pointer_was_expected(tmp_path):
    """One person record held a small integer in a pointer field. Its page is page 0, which the
    page route asked the helper for and the range check refused, so every snapshot build failed
    with "invalid read of 16384 bytes at 0" (12 November 2026). That window is unreadable; the
    others answer."""
    helper = make_helper(tmp_path, pages=pages_cfg(BASE))
    with LiveMemory(42, helper=helper) as m:
        payload, bad = m.windows([BASE + 8, 0x30, BASE + 64], 16)
        assert bad == [1]
        assert payload[:16] == page_bytes(BASE)[8:24] and payload[32:] == page_bytes(BASE)[64:80]
        assert payload[16:32] == bytes(16)
        assert all(0 not in [item[0] for item in batch.get('items', [])] for batch in batches(tmp_path)
                   if isinstance(batch, dict))


def test_cache_limit_evicts_oldest(tmp_path):
    bases = [BASE + i * 16384 for i in range(4)]
    helper = make_helper(tmp_path, pages=pages_cfg(*bases))
    with LiveMemory(42, helper=helper, max_cache_pages=2) as m:
        for b in bases:
            m.page(b)
        assert len(m._cache) == 2 and bases[-1] in m._cache and bases[0] not in m._cache


def test_prefetch_one_round_trip(tmp_path):
    bases = [BASE + i * 16384 for i in range(5)]
    helper = make_helper(tmp_path, pages=pages_cfg(*bases))
    with LiveMemory(42, helper=helper) as m:
        assert m.prefetch([(bases[0] + 5, 8), (bases[3], 20000), (BASE + 99 * 16384, 8)]) == 4
        assert len(batches(tmp_path)) == 1
        m.u32(bases[0] + 4)
        assert len(batches(tmp_path)) == 1


def test_decoders(tmp_path):
    data = struct.pack("<BHIQbhiqf", 200, 60000, 4_000_000_000, 2**63 + 5, -3, -300, -70000, -2**40, 1.5)
    page = bytearray(16384)
    page[16:16 + len(data)] = data
    helper = make_helper(tmp_path, pages={str(BASE): bytes(page).hex()})
    with LiveMemory(42, helper=helper) as m:
        a = BASE + 16
        offsets, sizes = [], [1, 2, 4, 8, 1, 2, 4, 8, 4]
        for n in sizes:
            offsets.append(a); a += n
        # struct.pack above is unaligned "<": fields are packed back to back
        u8, u16, u32, u64, i8, i16, i32, i64, f32 = offsets
        assert (m.u8(u8), m.u16(u16), m.u32(u32), m.u64(u64)) == (200, 60000, 4_000_000_000, 2**63 + 5)
        assert (m.i8(i8), m.i16(i16), m.i32(i32), m.i64(i64)) == (-3, -300, -70000, -2**40)
        assert m.f32(f32) == 1.5 and m.pointer(u64) == 2**63 + 5
    assert len(batches(tmp_path)) == 1


def test_regions(tmp_path):
    helper = make_helper(tmp_path, regions=[(0x1000, 0x4000, 1), (0x8000, 0x4000, 3)])
    with LiveMemory(42, helper=helper) as m:
        regions = m.regions()
        assert regions == [Region(0x1000, 0x4000, 1, 1, 0, 1), Region(0x8000, 0x4000, 3, 3, 0, 1)]
        assert regions[0].readable and not regions[0].writable and regions[1].writable
        assert regions[0].contains(0x1000, 0x4000) and not regions[0].contains(0x4fff, 2)


def test_expected_executable_mismatch_and_hello_failure(tmp_path):
    with pytest.raises(MemoryReadError, match="not the expected"):
        LiveMemory(42, helper=make_helper(tmp_path, path="/other/FM"), expected_executable="/fake/FM")
    LiveMemory(42, helper=make_helper(tmp_path, path="/fake/FM"), expected_executable="/fake/FM").close()
    with pytest.raises(MemoryReadError, match="attach_failed"):
        LiveMemory(42, helper=make_helper(tmp_path, hello_status=mem.ST_ATTACH_FAILED))
    with pytest.raises(ProcessGoneError):
        LiveMemory(42, helper=make_helper(tmp_path, hello_status=mem.ST_PROCESS_GONE))


def test_missing_helper_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.delenv("FM_FAST_READER", raising=False)
    with pytest.raises(MemoryReadError, match="build_fast_reader"):
        LiveMemory(42, helper=tmp_path / "nope")


def test_helper_lookup_order(tmp_path, monkeypatch):
    env_helper = make_helper(tmp_path)
    monkeypatch.setenv("FM_FAST_READER", str(env_helper))
    with LiveMemory(42) as m:
        assert m.helper == env_helper
    explicit = tmp_path / "explicit"
    explicit.write_bytes(env_helper.read_bytes()); explicit.chmod(0o700)
    with LiveMemory(42, helper=explicit) as m:
        assert m.helper == explicit
    assert mem.ROOT / "build" / "fm_fast_reader" == Path(mem.__file__).resolve().parents[2] / "build" / "fm_fast_reader"


def test_hang_times_out_and_reaps(tmp_path):
    helper = make_helper(tmp_path, mode="hang", pages=pages_cfg(BASE))
    m = LiveMemory(42, helper=helper, timeout=0.5)
    child = m._child
    started = time.monotonic()
    with pytest.raises(MemoryReadError, match="timed out"):
        m.read(BASE, 8)
    assert time.monotonic() - started < 5
    assert child.poll() is not None
    with pytest.raises(MemoryReadError, match="closed"):
        m.read(BASE, 8)
    m.close(); m.close()


def test_garbage_hello_times_out(tmp_path):
    with pytest.raises(MemoryReadError):
        LiveMemory(42, helper=make_helper(tmp_path, mode="garbage_hello"), timeout=1)


def test_helper_death_is_reported(tmp_path):
    helper = make_helper(tmp_path, mode="die_after", after=1, pages=pages_cfg(BASE))
    m = LiveMemory(42, helper=helper)
    assert m.read(BASE, 4)
    with pytest.raises(ProcessGoneError):
        m.read(BASE, 4)
    with pytest.raises(MemoryReadError):
        m.read(BASE, 4)


def test_process_gone_status_in_response(tmp_path):
    m = LiveMemory(42, helper=make_helper(tmp_path, mode="gone"))
    with pytest.raises(ProcessGoneError):
        m.read(BASE, 4)


def test_corrupt_response_header(tmp_path):
    m = LiveMemory(42, helper=make_helper(tmp_path, mode="bad_magic"))
    with pytest.raises(MemoryReadError, match="corrupt"):
        m.read(BASE, 4)
    assert m._child is None


def test_close_is_idempotent_and_reaps(tmp_path):
    m = LiveMemory(42, helper=make_helper(tmp_path))
    child = m._child
    assert m.ping()
    m.close(); m.close()
    assert child.poll() is not None


def test_snapshot_memory_matches_interface():
    snap = SnapshotMemory({BASE: page_bytes(BASE), BASE + 16384: page_bytes(BASE + 16384)})
    assert snap.read(BASE + 16380, 8) == page_bytes(BASE)[-4:] + page_bytes(BASE + 16384)[:4]
    assert snap.read_many([(BASE, 4), (0x9000_0000, 4)])[1] is None
    assert snap.cached_read(BASE, 4) == snap.read(BASE, 4) and snap.page(BASE + 3) == page_bytes(BASE)
    assert snap.u32(BASE) == struct.unpack("<I", page_bytes(BASE)[:4])[0]
    assert snap.regions() == [Region(BASE, 32768, 3, 3)]
    with pytest.raises(MemoryReadError):
        snap.read(0x9000_0000, 4)
    snap.load(0x20000, b"\x01\x02\x03\x04")
    assert snap.u32(0x20000) == 0x04030201
    snap.invalidate()


# ---- live-gated ------------------------------------------------------------

REPO_ROOT = Path(mem.__file__).resolve().parents[2]
FAST = Path(os.environ.get("FM_FAST_READER") or REPO_ROOT / "build" / "fm_fast_reader")
OLD_HELPER = Path(os.environ.get("FM_LIVE_HELPER_FOR_TEST",
                                 "/Volumes/4TB Private/Offloaded/FMCP 27/build/fm_live_helper"))


def _live_process():
    if sys.platform != "darwin" or not FAST.is_file() or not OLD_HELPER.is_file():
        return None
    try:
        return mem.find_fm_process()
    except Exception:
        return None


@pytest.mark.skipif(_live_process() is None, reason="FM not running or helpers not built")
def test_live_plugin_header_matches_bridge_read_path():
    from fm_live_mcp.bridge import Bridge

    process = _live_process()
    bridge = Bridge(OLD_HELPER)
    images = bridge._run("images", process)["images"]
    base = int(images[0]["address"], 16)
    with LiveMemory(process.pid, helper=FAST, expected_executable=process.executable) as m:
        fast = m.read(base, 4096)
        old = bridge._read_memory(process, base, 4096)
        assert fast == old
        assert fast[:4] in (b"\xcf\xfa\xed\xfe",)  # 64-bit little-endian Mach-O magic
        assert m.cached_read(base + 100, 64) == old[100:164]
        assert m.page_size == 16384
        regions = m.regions()
        assert any(r.contains(base, 4096) and r.readable for r in regions)
    with pytest.raises(MemoryReadError, match="not the expected"):
        LiveMemory(process.pid, helper=FAST, expected_executable="/bin/ls")


# ---- real fm_fast_reader attached to this test process (no game needed) -----

def _self_attach_ok():
    if sys.platform != "darwin" or not FAST.is_file():
        return False
    try:
        LiveMemory(os.getpid(), helper=FAST).close()
        return True
    except MemoryReadError:
        return False


needs_native = pytest.mark.skipif(not _self_attach_ok(), reason="fm_fast_reader not built or task_for_pid unavailable")


def _raw(child, op, items=()):
    import subprocess  # noqa: F401
    child.stdin.write(struct.pack("<3I", mem.REQ_MAGIC, op, len(items)) + b"".join(struct.pack("<QI", a, n) for a, n in items))
    child.stdin.flush()
    magic, status, count = struct.unpack("<3I", child.stdout.read(12))
    assert magic == mem.RESP_MAGIC
    return status, count


@needs_native
def test_native_reads_own_memory_and_isolates_failures():
    import ctypes
    buf = ctypes.create_string_buffer(bytes(range(256)) * 64)
    address = ctypes.addressof(buf)
    with LiveMemory(os.getpid(), helper=FAST) as m:
        got = m.read_many([(address, 256), (8, 8), (address + 5, 3), (2**63, 8)])
        assert got[0] == bytes(range(256)) and got[1] is None and got[2] == bytes([5, 6, 7]) and got[3] is None
        assert m.read(address, 4) == b"\x00\x01\x02\x03"
        assert any(r.contains(address, 256) and r.readable for r in m.regions())
        # a range that starts readable and runs off the end fails that item only
        regions = m.regions()
        edge = next(r for r, n in zip(regions, regions[1:] + [None])
                    if r.readable and r.size >= 8 and (n is None or n.start != r.end or not n.readable))
        tail = m.read_many([(edge.end - 8, 64), (address, 4)])
        assert tail[0] is None and tail[1] == b"\x00\x01\x02\x03"
        assert m.ping()


@needs_native
def test_native_enforces_limits_with_clear_statuses():
    import subprocess
    child = subprocess.Popen([str(FAST), "--pid", str(os.getpid())], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        hello = struct.unpack("<7I", child.stdout.read(28)); child.stdout.read(hello[6])
        assert hello[0] == mem.HELLO_MAGIC and hello[1] == 0 and hello[4] == 16384
        status, count = _raw(child, mem.OP_READV, [(4096, mem.MAX_ITEM_BYTES + 1), (4096, 0)])
        assert (status, count) == (0, 2)
        table = struct.unpack("<4I", child.stdout.read(16))
        assert table == (mem.ST_ITEM_TOO_LARGE, 0, mem.ST_BAD_LENGTH, 0)
        # 17 x 16 MiB exceeds the 256 MiB batch cap: refused whole, channel stays usable
        status, count = _raw(child, mem.OP_READV, [(4096, mem.MAX_ITEM_BYTES)] * 17)
        assert (status, count) == (mem.ST_BATCH_TOO_LARGE, 0)
        assert _raw(child, mem.OP_PING) == (0, 0)
        # too many items: refused and the process exits
        child.stdin.write(struct.pack("<3I", mem.REQ_MAGIC, mem.OP_READV, mem.MAX_BATCH_ITEMS + 1)); child.stdin.flush()
        assert struct.unpack("<3I", child.stdout.read(12))[1] == mem.ST_TOO_MANY_ITEMS
        assert child.wait(timeout=5) == 2
    finally:
        child.kill(); child.wait()


@needs_native
def test_native_exits_when_stdin_closes_and_rejects_bad_magic():
    import subprocess
    child = subprocess.Popen([str(FAST), "--pid", str(os.getpid())], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    child.stdout.read(28)
    child.stdin.close()
    child.stdout.read()
    assert child.wait(timeout=5) == 0
    child = subprocess.Popen([str(FAST), "--pid", str(os.getpid())], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    child.stdin.write(b"\x00" * 12); child.stdin.flush()
    out = child.stdout.read()
    assert child.wait(timeout=5) == 2 and struct.unpack("<I", out[-8:-4])[0] == mem.ST_BAD_MAGIC


@needs_native
def test_native_reports_target_exit():
    import subprocess
    target = subprocess.Popen(["/bin/sleep", "30"])
    try:
        m = LiveMemory(target.pid, helper=FAST)
    except MemoryReadError:
        target.kill(); target.wait()
        pytest.skip("cannot attach to a platform binary")
    target.kill(); target.wait()
    with pytest.raises(ProcessGoneError):
        for _ in range(20):
            m.regions(refresh=True)
            time.sleep(0.2)
