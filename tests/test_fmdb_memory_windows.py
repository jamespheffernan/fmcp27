"""WindowsMemory against a child Python process that holds a known buffer. Windows only."""
import subprocess
import sys
import time

import pytest

from fm_live_mcp.fmdb.memory import MemoryReadError, ProcessGoneError
from fm_live_mcp.fmdb.memory_windows import (
    MEM_IMAGE, WindowsMemory, find_processes, processes, protection_bits,
)

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="reads a Windows process")

# Holds 16 KiB of a known pattern, prints its pid and the buffer's address, then changes one byte
# per line on stdin. The pid is printed because a virtual environment's python.exe is a launcher:
# the interpreter that owns the buffer is its child, not the process Popen started.
CHILD = r'''
import ctypes, os, sys
data = bytes(range(256)) * 64
buffer = ctypes.create_string_buffer(data, len(data))
print(os.getpid(), ctypes.addressof(buffer), len(data), flush=True)
for line in sys.stdin:
    offset, value = (int(x) for x in line.split())
    buffer[offset] = bytes([value])
    print("ok", flush=True)
'''

PATTERN = bytes(range(256)) * 64
UNMAPPED = 0x1000      # inside the first 64 KiB, which Windows never maps


@pytest.fixture
def target():
    child = subprocess.Popen([sys.executable, "-c", CHILD], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
    try:
        pid, address, length = (int(x) for x in child.stdout.readline().split())
        assert length == len(PATTERN)
        yield child, pid, address
    finally:
        child.kill()
        child.wait()


def poke(child, offset, value):
    child.stdin.write(f"{offset} {value}\n")
    child.stdin.flush()
    assert child.stdout.readline().strip() == "ok"


def test_protection_bits():
    assert protection_bits(0x02) == 1
    assert protection_bits(0x04) == 3
    assert protection_bits(0x20) == 5
    assert protection_bits(0x40) == 7
    assert protection_bits(0x01) == 0
    assert protection_bits(0x104) == 0      # a guard page is not readable


def test_refuses_to_run_off_windows():
    if sys.platform == "win32":
        pytest.skip("checks the refusal on other systems")
    with pytest.raises(MemoryReadError, match="needs Windows"):
        WindowsMemory(1)


@windows_only
def test_reads_the_exact_bytes(target):
    child, pid, address = target
    with WindowsMemory(pid) as memory:
        assert memory.page_size == 4096
        assert memory.route == "read_process_memory"
        assert memory.executable.lower().endswith('python.exe')
        assert memory.read(address, len(PATTERN)) == PATTERN
        assert memory.read(address + 300, 5) == PATTERN[300:305]
        assert memory.stats.items == 2 and memory.stats.bytes == len(PATTERN) + 5


@windows_only
def test_unreadable_items_are_none_and_read_raises(target):
    child, pid, address = target
    with WindowsMemory(pid) as memory:
        got = memory.read_many([(address, 16), (UNMAPPED, 16), (address + 16, 16)])
        assert got == [PATTERN[:16], None, PATTERN[16:32]]
        assert memory.stats.failed_items == 1
        with pytest.raises(MemoryReadError, match="cannot read 16 bytes"):
            memory.read(UNMAPPED, 16)
        with pytest.raises(MemoryReadError, match="invalid read"):
            memory.read(0, 16)


@windows_only
def test_decoders_use_the_page_cache(target):
    child, pid, address = target
    with WindowsMemory(pid) as memory:
        assert memory.u8(address + 7) == 7
        assert memory.u32(address) == 0x03020100
        assert memory.u64(address + 8) == 0x0F0E0D0C0B0A0908
        trips = memory.stats.round_trips
        assert memory.u16(address + 2) == 0x0302
        assert memory.stats.round_trips == trips          # served from the cached page
        with pytest.raises(MemoryReadError, match="unreadable"):
            memory.u32(UNMAPPED)


@windows_only
def test_cached_bytes_stay_until_reread_or_invalidate(target):
    child, pid, address = target
    with WindowsMemory(pid) as memory:
        assert memory.cached_read(address, 4) == PATTERN[:4]
        poke(child, 1, 0xEE)
        assert memory.cached_read(address, 4) == PATTERN[:4]        # still the cached page
        assert memory.read(address, 4) == b"\x00\xee\x02\x03"       # read is never cached
        base = memory.page_base(address)
        assert memory.reread([base]) == {base}
        assert memory.reread([base]) == set()
        assert memory.cached_read(address, 4) == b"\x00\xee\x02\x03"
        poke(child, 1, 0x01)
        memory.invalidate()
        assert memory.cached_read(address, 4) == PATTERN[:4]


@windows_only
def test_windows_returns_one_buffer_and_the_bad_positions(target):
    child, pid, address = target
    with WindowsMemory(pid, max_cache_pages=64) as memory:
        addresses = [address + 256 * k for k in range(8)]
        payload, bad = memory.windows(addresses, 4)
        assert payload == b"\x00\x01\x02\x03" * 8 and bad == []
    with WindowsMemory(pid) as memory:
        payload, bad = memory.windows([address, UNMAPPED, address + 4], 4)
        assert payload == b"\x00\x01\x02\x03" + bytes(4) + b"\x04\x05\x06\x07"
        assert bad == [1]


@windows_only
def test_regions_cover_the_buffer(target):
    child, pid, address = target
    with WindowsMemory(pid) as memory:
        regions = memory.regions()
        assert regions == sorted(regions, key=lambda r: r.start)
        assert all(r.start % memory.page_size == 0 and r.size > 0 for r in regions)
        holder = [r for r in regions if r.contains(address, len(PATTERN))]
        assert len(holder) == 1 and holder[0].readable and holder[0].writable
        assert not any(r.contains(UNMAPPED) for r in regions)
        assert any(r.executable and r.user_tag == MEM_IMAGE for r in regions)


@windows_only
def test_modules_have_readable_pe_headers(target):
    child, pid, address = target
    with WindowsMemory(pid) as memory:
        modules = memory.modules()
        assert modules[0].path.lower() == memory.executable.lower()
        python_dll = next(m for m in modules if m.name.lower().startswith("python3") and m.name.lower().endswith(".dll"))
        assert memory.module(python_dll.name.upper()) == python_dll
        assert memory.module("no_such_module.dll") is None
        for module in (modules[0], python_dll, memory.module("kernel32.dll")):
            assert module.size > 0 and memory.read(module.base, 2) == b"MZ"
            assert any(r.start == module.base and r.user_tag == MEM_IMAGE for r in memory.regions())


@windows_only
def test_process_lookup(target):
    child, pid, address = target
    listed = dict(processes())
    assert listed[pid].lower().endswith("python.exe")
    name = listed[pid].rsplit("\\", 1)[-1]
    assert pid in dict(find_processes(name.upper()))
    assert find_processes("no_such_program.exe") == []
    with pytest.raises(MemoryReadError, match="no running process"):
        WindowsMemory.attach("no_such_program.exe")
    with pytest.raises(MemoryReadError, match="not"):
        WindowsMemory(pid, expected_executable=r"C:\elsewhere\other.exe")


@windows_only
def test_a_dead_process_raises_process_gone(target):
    child, pid, address = target
    memory = WindowsMemory(pid)
    try:
        assert memory.ping()
        child.kill()
        child.wait()
        deadline = time.monotonic() + 10      # the launcher's job object ends the interpreter
        while memory.ping() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not memory.ping()
        with pytest.raises(ProcessGoneError):
            memory.read(address, 16)
    finally:
        memory.close()
        memory.close()                                   # idempotent
    with pytest.raises(MemoryReadError, match="closed"):
        memory.read(address, 16)
