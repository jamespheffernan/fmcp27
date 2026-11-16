"""Live-gated checks of the save-code reader (docs/fmdb/PERSIST.md).

The game's own save functions run inside the VM on copied pages; nothing is written to the game or a file.
"""
import sys

import pytest


def _live_available():
    if sys.platform != 'darwin':
        return False
    try:
        from fm_live_mcp.bridge import Bridge, discover_processes
        return Bridge().helper.is_file() and len(discover_processes()) == 1
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _live_available(), reason='FM27 not running or helper missing')


@pytest.fixture(scope='module')
def engine():
    from fm_live_mcp.fmdb.engine import Engine
    e = Engine.open()
    try:
        yield e
    finally:
        e.close()


def test_small_roots_save_completely(engine):
    from fm_live_mcp.fmdb import persist
    for root in ('AGENT_MANAGER', 'FINE_MANAGER', 'FINANCE_MANAGER', 'CONTRACT_MANAGER'):
        rec = persist.record(engine, persist.find_route(root), provenance=True, use_cache=False)
        assert rec.status == 'ok', (root, rec.refusal)
        assert rec.writes and rec.calls and rec.calls[0].function == int(persist.find_route(root)['function'], 16)
        assert rec.root_class == root
        assert all(s.tag[:4] == b'LLUN' for s in rec.streams)       # 'NULL' chunk tag, version word 0x0801


def test_proven_offsets_hold_the_written_bytes(engine):
    """Every value whose offset is proven by `buffer` or `load` equals the live bytes at that offset of the
    object (or of the named caller's object) on every instance."""
    from fm_live_mcp.fmdb import persist
    rec = persist.record(engine, persist.find_route('FINE_MANAGER'), provenance=True, use_cache=False)
    an = persist.Analysis(engine, rec)
    vm = engine._persist_vm_p
    checked = 0
    for fn, calls in an.by_fn.items():
        for call in calls:
            owners = dict(an.owners(call))
            seen = set()
            for key, entry in an.keys_of(call):
                if key[0] != 'w' or key in seen:
                    continue
                seen.add(key)
                where, how = an.offset(fn, key)
                if where is None or len(where) != 2 or how not in ('buffer', 'load') or where[0] not in owners:
                    continue
                live = vm.read(owners[where[0]] + where[1], len(entry.data))
                if how == 'buffer':
                    assert live == entry.data, (hex(fn), key, how)
                else:   # a load may be narrower than the store (zero-extended byte or half-word)
                    n = min(len(live), len(entry.data))
                    assert int.from_bytes(entry.data, 'little') == int.from_bytes(live[:n], 'little') or \
                        entry.data[:n] == live[:n], (hex(fn), key, how)
                checked += 1
    assert checked >= 20


def test_person_reference_is_the_unique_id(engine):
    """CONTRACT_MANAGER writes people through save function 0x1104334: its first u32 is loaded from
    person +0x8, the record's unique id (the same field the snapshot's people.uid reads)."""
    from fm_live_mcp.fmdb import persist
    rec = persist.record(engine, persist.find_route('CONTRACT_MANAGER'), provenance=True, use_cache=False)
    an = persist.Analysis(engine, rec)
    calls = an.by_fn.get(0x1104334, [])
    assert calls
    first = an.keys_of(calls[0])[0]
    assert first[0][0] == 'w' and len(first[1].data) == 4
    where, how = an.offset(0x1104334, first[0])
    assert where == (0, 0x8) and how.startswith('load')
    vm = engine._persist_vm_p
    assert vm.read(calls[0].obj + 8, 4) == first[1].data


def test_native_read_tool_path(engine):
    from fm_live_mcp.fmdb import persist_tools
    out = persist_tools.native_read(engine, 'AGENT_MANAGER', depth=2, limit=50)
    assert out['status'] == 'ok' and out['class'] == 'AGENT_MANAGER'
    assert out['fields'] and out['streams'][0]['item'] == '.dat'
