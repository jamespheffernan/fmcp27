"""Offline tests for the market manager walker and tables (no game)."""
import struct

import pytest

from fm_live_mcp.fmdb import mgr_walk as W
from fm_live_mcp.fmdb.sources import managers_market as M
from fm_live_mcp.fmdb.sources import _common as C


class FakeEngine:
    """Sparse memory: {address: bytes}; reads of unknown bytes return zeros."""

    def __init__(self, base=0x100000000):
        self.base = base
        self.mem = {}

    def put(self, addr, data):
        for i, b in enumerate(data):
            self.mem[addr + i] = b

    def q(self, addr, *values):
        self.put(addr, struct.pack(f'<{len(values)}Q', *values))

    def read_many(self, requests):
        return [bytes(self.mem.get(a + i, 0) for i in range(n)) for a, n in requests]

    def read(self, a, n):
        return self.read_many([(a, n)])[0]


def date(y, d, flags=0):
    return (y << 16) | (flags << 9) | d


def test_packed_date_ignores_flag_bits():
    assert W.packed_date(date(2030, 347)) == '2030-12-13'
    assert W.packed_date(date(2030, 347, flags=21)) == '2030-12-13'
    assert W.packed_date(0xFFFFFFFF) is None
    assert W.packed_date(date(1900, 1)) == '1900-01-01'
    assert W.packed_date(date(2030, 366)) is None          # 2030 has 365 days


def test_root_checks_vtable():
    e = FakeEngine()
    rva, vt = 0x56A57A0, 0x55F66D0
    e.q(e.base + rva, 0x7000000000)
    e.q(0x7000000000, e.base + vt)
    assert W.root(e, rva, vt) == 0x7000000000
    with pytest.raises(W.WalkError):
        W.root(e, rva, vt + 8)
    e.q(e.base + rva, 0)
    with pytest.raises(W.WalkError):
        W.root(e, rva, vt)


def test_vector_checks():
    e = FakeEngine()
    e.q(0x7000000100, 0x7000001000, 0x7000001010, 0x7000001020)
    assert W.vector(e, 0x7000000100) == (0x7000001000, 2)
    e.q(0x7000001000, 0x7000002000, 0x7000003000)
    assert W.pointers(e, 0x7000000100) == [0x7000002000, 0x7000003000]
    assert W.inline(e, 0x7000000100, 8) == [0x7000001000, 0x7000001008]
    e.q(0x7000000200, 0x7000001010, 0x7000001000, 0x7000001020)      # end before begin
    with pytest.raises(W.WalkError):
        W.vector(e, 0x7000000200)
    e.q(0x7000000300, 0x7000001000, 0x7000001010, 0x7000001020)
    with pytest.raises(W.WalkError):                                   # 16 bytes is not a multiple of 0x30
        W.vector(e, 0x7000000300, stride=0x30)
    assert W.vector(e, 0x7000000400) == (0, 0)                         # all-zero header: empty


def test_decode_kinds():
    e = FakeEngine()
    team, comp = 0x7000005000, 0x7000006000
    C.cache(e)[('index', 'teams')] = {team: 545}
    C.cache(e)[('index', 'competitions')] = {comp: 7}
    elem = 0x7000004000
    raw = bytearray(0x40)
    struct.pack_into('<QQ', raw, 0x20, team, comp)
    struct.pack_into('<HHII', raw, 0x30, 25, 3, date(2030, 346), 0xFFFFFFFF)
    raw[0x3C], raw[0x3D], raw[0x3E] = 16, 0, 2
    struct.pack_into('<QQQ', raw, 0x08, 0x7000007000, 0x7000007010, 0x7000007010)
    e.put(elem, bytes(raw))
    [row] = W.decode(e, [elem], M.JOB_ADVERT)
    named = dict(zip([f[0] for f in M.JOB_ADVERT], row))
    assert named == {'team_idx': 545, 'competition_idx': 7, 'competition_u16_30': 25, 'league_position': 3,
                     'created': '2030-12-12', 'closing_date': None, 'job_code': 16, 'human_placed': 0, 'status_code': 2,
                     'list_count': 2}
    # a pointer that is not a record of the declared table decodes as -1
    struct.pack_into('<Q', raw, 0x20, 0x7000009000)
    e.put(elem, bytes(raw))
    assert W.decode(e, [elem], M.JOB_ADVERT)[0][0] == -1


def test_layouts_fit_their_elements():
    sizes = {'JOB_ADVERT': 0x40, 'SCOUT_80': 0x40, 'CONTRACT_78': 0x10, 'CONTRACT_18': 0x08, 'TAKEOVER': 0x60,
             'CAMP': 0x50, 'ADVICE': 0x30, 'FINANCE': 0x40}
    for name, size in sizes.items():
        assert W.layout_span(getattr(M, name)) <= size, name


def test_inventory_names_every_manager():
    assert {c[0] for c in M.CONTAINERS} == set(M.MANAGERS)
    decoded = {c[4] for c in M.CONTAINERS if c[4]}
    names = {t.name for t in M.tables(FakeEngine())}
    assert decoded <= names
    for t in M.tables(FakeEngine()):
        assert t.manager.get('scope') in ('public', 'own_club', 'never'), t.name
        if t.manager['scope'] == 'own_club':
            assert t.manager['own_club_column'] in {c.name for c in t.columns}, t.name
        assert t.build_mode == 'lazy' and t.refresh == 'content' and t.fingerprint, t.name
