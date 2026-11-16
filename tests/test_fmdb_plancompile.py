"""plancompile.py: plans from the getter's code on a synthetic record.

Offline: the synthetic memory model and plan-form fitting. Live (FM27 running): compiled plans
reproduce traced plans of the shipped set, and verified compiled plans agree with the getter on
real records. Nothing writes to the game or to the plan cache.
"""
from __future__ import annotations

import gzip
import json
import random
import sys
from pathlib import Path

import pytest

from fm_live_mcp.fmdb import plancompile
from fm_live_mcp.fmdb.bulkplans import Missing, Ref

ROOT = Path(__file__).resolve().parent.parent


def test_synthetic_chains():
    synth = plancompile.SynthMemory()
    record = synth.base(0) + plancompile.RECORD_OFFSET
    assert synth.chain(record + 0x2C, record) == [0x2C]
    assert synth.chain(record - 0x388 + 0x25C, record) == [-0x388 + 0x25C]
    child = synth.new_region(record + 0x100)
    grandchild = synth.new_region(child + 0x10)
    assert synth.chain(child + 0x75, record) == [0x100, 0x75]
    assert synth.chain(grandchild + 4, record) == [0x100, 0x10, 4]
    synth.write(child + 0xFFE, b'\x01\x02\x03\x04')          # crosses a page boundary
    assert synth.read(child + 0xFFE, 4) == b'\x01\x02\x03\x04'
    assert synth.read(grandchild, 8) == bytes(8)


def test_probe_equality():
    assert plancompile.eq(Missing('x'), Missing('x')) and not plancompile.eq(Missing('x'), Missing('y'))
    assert plancompile.eq(None, None) and not plancompile.eq(None, 0)
    assert not plancompile.eq(True, 1)
    assert plancompile.eq(Ref(1, 2), Ref(1, 2))


@pytest.mark.parametrize('plan,samples', [
    ({'width': 1, 'signed': False, 'type': 'int', 'transform': 'identity'}, [(0, 0), (0xFF, 255)]),
    ({'width': 2, 'signed': True, 'type': 'int', 'transform': 'identity'}, [(0x8000, -32768), (1, 1)]),
    ({'width': 4, 'signed': False, 'type': 'bool', 'transform': 'bit:12'}, [(1 << 12, True), (1, False)]),
    ({'width': 2, 'signed': False, 'type': 'float', 'transform': 'div10'}, [(100, 10.0)]),
    ({'width': 4, 'signed': False, 'type': 'sidate', 'transform': 'identity'}, [(0x0FD06400, '2024-04-09')]),
    ({'width': 1, 'signed': False, 'type': 'int', 'transform': 'identity', 'zero_null': True}, [(0, None), (3, 3)]),
])
def test_plan_forms(plan, samples):
    plan = {'chain': [0], **plan}
    assert all(plancompile.Compiler._agrees(plan, n, got) for n, got in samples)


def _live_available():
    if sys.platform != 'darwin':
        return False
    try:
        from fm_live_mcp.bridge import Bridge, discover_processes
        return Bridge().helper.is_file() and len(discover_processes()) == 1
    except Exception:  # noqa: BLE001
        return False


needs_live = pytest.mark.skipif(not _live_available(), reason='FM27 not running or helper missing')


@pytest.fixture(scope='module')
def engine():
    from fm_live_mcp.fmdb.engine import Engine
    e = Engine.open()
    yield e
    e.close()


def _shipped():
    from fm_live_mcp import players
    path = ROOT / 'fm_live_mcp/fmdb/data' / f'plans-{players.SHA256}.v2.json.gz'
    return json.loads(gzip.decompress(path.read_bytes()))['plans']


@needs_live
@pytest.mark.parametrize('cls', ['CLUB', 'ACTUAL_PLAYER'])
def test_compiled_plans_reproduce_traced_plans(engine, cls):
    """On fields the tracer already planned, the compiler (which never saw a record) mostly finds
    the same offset chain and value type. It compiles fewer of them: it refuses a plan whose
    chain gives a value other than None when a pointer on it is null (the traced plan assumes
    the pointer is set because every sampled record had it set)."""
    shipped = {c: p for c, p in _shipped()[cls].items() if p.get('status') == 'direct' and p['type'] != 'rating_blob'}
    codes = random.Random(cls).sample(sorted(shipped), 25)
    compiler = plancompile.Compiler(engine, cls)
    same = compiled = 0
    for code in codes:
        result = compiler.compile(code)
        if result.plan:
            compiled += 1
            same += result.plan['chain'] == shipped[code]['chain'] and result.plan['type'] == shipped[code]['type']
            assert result.plan['paths']
    assert compiled >= 4 and same >= 0.6 * compiled, (same, compiled)


@needs_live
def test_verified_compiled_plans_agree_with_the_getter(engine):
    from fm_live_mcp.fmdb import tables
    from fm_live_mcp.fmdb.snapshot import enumerate_table
    live = enumerate_table(engine, 'competitions')
    records = [p for p, c in zip(live.pointers, live.classes) if p and c == 'COMP']
    # COMP fields emulated in the shipped set that compiled on 11 November
    emulated = 'Pat0 Pat1 Pcsc Pfq4 Pmn4 Pmx4 Pob0 VARf WpBn cuae culn'.split()
    compiler = plancompile.Compiler(engine, 'COMP')
    compiled = {c: compiler.compile(c) for c in emulated}
    plans = {c: r.plan for c, r in compiled.items() if r.plan}
    assert len(plans) >= 5
    check = random.Random('COMP').sample(records, min(50, len(records)))
    verdicts = plancompile.verify(engine, check, plans, compiler=compiler)
    verified = [c for c, v in verdicts.items() if v[0] == 'verified']
    assert len(verified) >= 5
    # WpBn: values differ on records whose branch path the compile did not see
    if 'WpBn' in verdicts:
        assert verdicts['WpBn'][0] in ('demoted', 'uncovered path')
    assert tables.CLASSES                       # (module loaded; nothing written anywhere)
