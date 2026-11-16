"""`match_state.momentum_series` on both builds: the momentum builder keeps the interface the reader uses.

The reader runs the game's own builder (0x4898A94 on 27.0.0, 0x4953288 on 27.0.1, re-compiled with
helpers inlined). What it assumes: the manager in x0, the event store in x1, the result vector returned
through x8 as 8-byte <f32 value, u32 end tick> segments. This test runs each build's unmodified code
from the preserved plugins over the same synthetic managers (the live 27.0.1 table layout: sorted
<u8 kind, u8 zone, u8 zone, pad, i32 weight>) and event stores (0x38-byte events: +0x18/+0x1C point,
+0x22 tick, +0x28 side, +0x2A kind, +0x30 flags; store +0x100/+0x104 pitch size, +0x108..+0x114 period
ticks) and compares the returned vectors."""
from __future__ import annotations

import hashlib
import random
import struct

import pytest

from fm_live_mcp.fmdb.sources import match_state as ms
from test_match_rating_builds import NEW, OLD, _static_vm, needs_builds

EV = 0x38
# the builder, its manager global and vtable, and its static allocator (global, guard, object) per build
ADDRESSES = {
    'old': dict(FN=(0x4898A94, 0x4899854), MOMENTUM=0x56A66E0, VT=0x56A06E8,
                ALLOC_PTR=0x56A4A90, GUARD=0x56C1668, ALLOC=0x56C1630),
    'new': dict(FN=(0x4953288, 0x4953ED8), MOMENTUM=0x57426E0, VT=0x573C6E8,
                ALLOC_PTR=0x5740A90, GUARD=0x575D668, ALLOC=0x575D630),
}
SHA1 = {'old': 'fcb28cf69af14f0ba9bd1bfa476b33f7eaa3914f', 'new': '324ccea30365d1414d585fe2dc5b82e74afc8c4d'}


def test_both_builders_are_accepted_and_nothing_else():
    assert set(ms.VERIFIED_MOMENTUM) == set(SHA1.values())


class _Builder:
    def __init__(self, build):
        import unicorn
        from unicorn import arm64_const as R
        self.a = a = ADDRESSES[build]
        self.v, self.base, b = _static_vm(OLD if build == 'old' else NEW)
        start, end = a['FN']
        assert hashlib.sha1(b.image.file_bytes(start, end - start)).hexdigest() == SHA1[build]
        v = self.v
        self.at = {'mgr': v._static(bytes(0x40)), 'table': v._static(bytes(8 * 256)), 'store': v._static(bytes(0x200)),
                   'events': v._static(bytes(EV * 400)), 'sub': v._static(bytes(0x400)), 'out': v._static(bytes(0x18))}
        v.set_overlay(self.base + a['MOMENTUM'], struct.pack('<Q', self.at['mgr']))
        # the builder's static allocator as after its one-time initialisation, pool off (+0x34 = 0)
        v.set_overlay(self.base + a['ALLOC_PTR'], struct.pack('<Q', self.base + a['ALLOC']))
        v.set_overlay(self.base + a['GUARD'], b'\x01')
        entry = self.base + start

        def sret(uc, addr, size, _):
            if addr == entry:
                uc.reg_write(R.UC_ARM64_REG_X8, self.at['out'])
        v.uc.hook_add(unicorn.UC_HOOK_CODE, sret, begin=entry, end=entry + 4)

    def run(self, table, events, store):
        at, put = self.at, self.v.uc.mem_write
        put(at['mgr'], struct.pack('<QQQQ', self.base + self.a['VT'], at['table'], at['table'] + 8 * len(table),
                                   at['table'] + 8 * len(table)))
        put(at['table'], b''.join(struct.pack('<BBBxi', *w) for w in table))
        blob = b''.join(e(at['sub']) for e in events)
        put(at['events'], blob)
        st = bytearray(store)
        struct.pack_into('<QQQ', st, 8, at['events'], at['events'] + len(blob), at['events'] + len(blob))
        put(at['store'], bytes(st))
        put(at['out'], bytes(0x18))
        self.v.call(self.base + self.a['FN'][0], (at['mgr'], at['store']))
        s, e, _ = struct.unpack('<QQQ', self.v.read(at['out'], 24))
        raw = self.v.read(s, e - s) if e > s else b''
        return [(t, val) for val, t in struct.iter_unpack('<fI', raw)]


def _case(rng):
    keys = sorted({(rng.choice((1, 2, 3, 7, 9, 14, 0x36, rng.randint(0, 60))), rng.randint(0, 5), rng.randint(0, 5))
                   for _ in range(rng.randint(1, 60))})
    table = [(a, b, c, rng.randint(-40, 40)) for a, b, c in keys]
    kinds = sorted({k[0] for k in keys} | {7, 9, 14, 0x36})
    sub_bytes = bytes(rng.getrandbits(8) for _ in range(0x400))
    events, tick = [], 0
    for _ in range(rng.choice([0, 1, 2, rng.randint(3, 40), rng.randint(40, 300)])):
        tick += rng.randint(0, 200)
        e = bytearray(rng.getrandbits(8) for _ in range(EV))
        e[0:0x18] = bytes(0x18)
        sub = rng.randint(1, 4) if rng.random() < 0.2 else 0
        struct.pack_into('<H', e, 0x22, min(tick, 0xFFFF))
        e[0x2A] = rng.choice(kinds) if rng.random() < 0.8 else rng.randint(0, 80)
        if rng.random() < 0.9:
            struct.pack_into('<ff', e, 0x18, rng.uniform(-70, 70), rng.uniform(-45, 45))
            struct.pack_into('<H', e, 0x30, rng.getrandbits(16))
            e[0x28] = rng.choice([0, 1])

        def make(sub_at, e=bytes(e), sub=sub):
            e = bytearray(e)
            if sub:
                e[0:0x18] = struct.pack('<QQQ', sub_at, sub_at + 8 * sub, sub_at + 8 * sub)
            return bytes(e)
        events.append(make)
    st = bytearray(0x200)
    struct.pack_into('<ff', st, 0x100, rng.uniform(90, 120), rng.uniform(55, 80))
    struct.pack_into('<iii', st, 0x108, rng.choice([-1, 10800, rng.randint(9000, 13000)]),
                     rng.choice([-1, 21600, rng.randint(20000, 26000)]), rng.choice([-1, rng.randint(25000, 33000)]))
    st[0x114] = rng.choice([0, 1, 2])
    return table, events, bytes(st), sub_bytes


@pytest.mark.slow
@needs_builds
def test_both_builders_return_the_same_segments():
    """600 synthetic matches (0 to 300 events, kinds from the table and others, both sides, periods with
    and without extra time, events with sub-item vectors): the same segment vector on both builds."""
    old, new = _Builder('old'), _Builder('new')
    rng = random.Random(5)
    values, segments = set(), 0
    for _ in range(600):
        table, events, store, sub = _case(rng)
        for b in (old, new):
            b.v.uc.mem_write(b.at['sub'], sub)
        a, c = old.run(table, events, store), new.run(table, events, store)
        assert a == c
        segments += len(a)
        values.update(round(v, 4) for _, v in a)
    assert segments > 3000 and len(values) > 100
