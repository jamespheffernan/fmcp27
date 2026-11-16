"""Synthetic source controls against complete unchanged native cache-hit calls.

These tests execute original instructions in owned memory; they are not live
game observations. Missing/cache-construction paths stay unavailable in the port.
"""
import hashlib
from pathlib import Path
import struct

import pytest
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_LR, UC_ARM64_REG_SP, UC_ARM64_REG_PC

from fm_live_mcp import frame_attack_direction as direction

BASE = 0x100000000
PRIMARY, PLAYBACK, PROVIDER, MATCH, CACHE = (0x30000000, 0x31000000, 0x32000000, 0x33000000, 0x34000000)
STACK, STOP = 0x80000000, 0x90000000
TICK = 700
import _pinned_build
PLUGIN = _pinned_build.PLUGIN


@pytest.fixture(scope='module')
def native_spans():
    with PLUGIN.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
    result = {}
    with PLUGIN.open('rb') as stream:
        for at, expected in direction.NATIVE_SPANS:
            stream.seek(0x5ED4000+at)
            raw = stream.read(len(expected))
            assert raw == expected
            result[at] = raw
        stream.seek(0x5ED4000+0x54EC0C8+0xC0)
        assert struct.unpack('<Q', stream.read(8))[0] & ((1 << 48)-1) == 0x7358C0
    return result


class Source:
    def __init__(self, native, slot=0):
        self.values = {}
        self.reads = []
        for at, raw in native.items():
            self.put(BASE+at, raw)
        for address, size in ((PRIMARY, 0x70), (PLAYBACK, 0x1410), (PROVIDER, 0x228),
                              (MATCH, 0x28), (CACHE, 6*0x420)):
            self.put(address, bytes(size))
        for address, value in ((BASE+0x54EC0C8+0xC0, BASE+0x7358C0),
                               (PRIMARY+0x58, PLAYBACK), (PLAYBACK, BASE+0x54EC490),
                               (PLAYBACK+0x10, PLAYBACK), (PLAYBACK+0x18, 123),
                               (PLAYBACK+0x1408, PROVIDER), (PROVIDER+0x28, MATCH),
                               (PROVIDER+0x220, CACHE), (MATCH, BASE+0x55FA258),
                               (MATCH+0x20, 456)):
            self.put(address, struct.pack('<Q', value))
        for index in range(6):
            self.put(CACHE+index*0x420+0x38, struct.pack('<I', TICK if index == slot else TICK+index+1))
        self.frame = CACHE+slot*0x420
        self.fields(0, 0, (0, 1))
        self.bound = dict(playback_address=PLAYBACK, frame_provider_address=PROVIDER,
                          source_match_address=MATCH, local_playback_handle=123,
                          official_match_unique_id=456, current_time_slice=TICK)

    def put(self, address, raw):
        self.values.update({address+i: byte for i, byte in enumerate(raw)})

    def read(self, address, size):
        self.reads.append((address, size))
        return bytes(self.values[address+i] for i in range(size))

    def fields(self, period, normal, per_side):
        self.put(self.frame+0x3C, bytes([period]))
        self.put(self.frame+0x82, bytes([normal & 255]))
        for side, value in enumerate(per_side):
            self.put(self.frame+0x3F5+side*16, bytes([value]))

    def public(self):
        captured = direction.capture(self.read, BASE, self.bound, fixed_tick=TICK)
        verified = direction.verify_capture(self.read, BASE, captured, self.bound)
        return direction.project(verified)


class OriginalNative:
    """Execute full virtual method7358C0 and its actual cache-hit callees."""
    def __init__(self, source):
        self.source = source
        self.uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        pages = {a & ~4095 for a in source.values}
        for at in sorted(pages):
            self.uc.mem_map(at, 4096)
        self.uc.mem_map(STACK, 0x10000)
        self.uc.mem_map(STOP, 4096)
        self.sync()
        self.data_reads, self.stack_writes = [], []

        def read(uc, kind, address, size, value, extra):
            if STACK <= address and address+size <= STACK+0x10000:
                return
            assert bytes(uc.mem_read(address, size)) == source.read(address, size)
            self.data_reads.append((address, size))

        def write(uc, kind, address, size, value, extra):
            assert STACK <= address and address+size <= STACK+0x10000, 'Native reconstruction/nonstack mutation attempted'
            self.stack_writes.append((address, size))

        self.uc.hook_add(UC_HOOK_MEM_READ, read)
        self.uc.hook_add(UC_HOOK_MEM_WRITE, write)

    def sync(self):
        addresses = sorted(self.source.values)
        if not addresses:
            return
        start = previous = addresses[0]
        raw = bytearray([self.source.values[start]])
        for address in addresses[1:]:
            if address != previous+1:
                self.uc.mem_write(start, bytes(raw))
                start, raw = address, bytearray()
            raw.append(self.source.values[address])
            previous = address
        self.uc.mem_write(start, bytes(raw))

    def call(self, side):
        for reg, value in ((UC_ARM64_REG_X0, PRIMARY), (UC_ARM64_REG_X1, 123),
                           (UC_ARM64_REG_X2, TICK), (UC_ARM64_REG_X3, side),
                           (UC_ARM64_REG_SP, STACK+0x10000-16), (UC_ARM64_REG_LR, STOP)):
            self.uc.reg_write(reg, value)
        self.uc.emu_start(BASE+0x7358C0, STOP, count=500)
        assert self.uc.reg_read(UC_ARM64_REG_PC) == STOP
        return self.uc.reg_read(UC_ARM64_REG_X0)


@pytest.mark.parametrize('slot', range(6))
def test_each_exact_cached_frame_matches_complete_native_lookup(native_spans, slot):
    source = Source(native_spans, slot)
    native = OriginalNative(source)
    for normal in (0, 1):
        source.fields(2, normal, (0, 1))
        native.sync()
        result = source.public()
        assert [row['native_kicking_upfield'] for row in result['teams']] == [bool(native.call(s)) for s in (0, 1)]
    assert native.data_reads and native.stack_writes


def test_all_signed_team_bytes_preserve_unknowns_against_original_native(native_spans):
    source = Source(native_spans, 2)
    native = OriginalNative(source)
    for raw in range(256):
        source.fields(2, raw, (0, 1))
        native.sync()
        result = source.public()
        signed = struct.unpack('<b', bytes([raw]))[0]
        for side, row in enumerate(result['teams']):
            original = native.call(side)
            assert original == (signed == side)
            assert row['native_kicking_upfield'] is (bool(original) if signed in (0, 1) else None)
    assert result['state'] == 'unavailable_native_orientation'


def test_native_period4_has_independent_per_side_bytes_not_complement(native_spans):
    source = Source(native_spans, 5)
    native = OriginalNative(source)
    for side in (0, 1):
        for raw in range(256):
            values = [1, 1]
            values[side] = raw
            source.fields(4, 99, values)
            native.sync()
            result = source.public()
            assert result['native_branch'] == 'native_period_4_per_side_byte'
            for index, row in enumerate(result['teams']):
                original = native.call(index)
                assert original == values[index]
                assert row['native_kicking_upfield'] is (bool(original) if original in (0, 1) else None)
    source.fields(4, 0, (1, 1))
    assert [row['native_kicking_upfield'] for row in source.public()['teams']] == [True, True]


@pytest.mark.parametrize('span', range(6))
def test_each_native_span_drift_refuses(native_spans, span):
    source = Source(native_spans)
    at, _ = direction.NATIVE_SPANS[span]
    source.values[BASE+at] ^= 1
    with pytest.raises(ValueError, match='source changed'):
        source.public()


def test_named_route_drift_refuses(native_spans):
    source = Source(native_spans)
    source.put(BASE+0x54EC0C8+0xC0, struct.pack('<Q', BASE+0x7358C4))
    with pytest.raises(ValueError, match='virtual route changed'):
        source.public()


@pytest.mark.parametrize('change', ['owner', 'provider', 'match', 'unique_id', 'local_handle'])
def test_each_ownership_join_refuses(native_spans, change):
    source = Source(native_spans)
    at = {'owner': PLAYBACK, 'provider': PLAYBACK+0x1408, 'match': PROVIDER+0x28,
          'unique_id': MATCH+0x20, 'local_handle': PLAYBACK+0x18}[change]
    source.put(at, struct.pack('<Q', 4096))
    with pytest.raises(ValueError, match='ownership changed'):
        source.public()


@pytest.mark.parametrize('kind', ['empty_cache', 'absent_tick', 'duplicate_tick'])
def test_missing_or_ambiguous_exact_frame_has_null_directions(native_spans, kind):
    source = Source(native_spans)
    if kind == 'empty_cache':
        source.put(PROVIDER+0x220, bytes(8))
    elif kind == 'absent_tick':
        source.put(source.frame+0x38, struct.pack('<I', TICK+100))
    else:
        source.put(CACHE+0x420+0x38, struct.pack('<I', TICK))
    result = source.public()
    assert result['state'].startswith('unavailable_') and result['teams'] is None
    assert result['same_session_fixed_frame_direction_verified'] is False


def test_projection_requires_final_verification_and_strips_private_owner_fields(native_spans):
    source = Source(native_spans)
    captured = direction.capture(source.read, BASE, source.bound, fixed_tick=TICK)
    with pytest.raises(ValueError, match='Final'):
        direction.project(captured)
    out = source.public()
    assert not any(key.startswith('_') for key in out)
    assert out['physical_units'] is None and out['penalty_area_occupation'] is None
    assert out['positive_world_y_mapping_verified'] is out['on_pitch_population_verified'] is False


@pytest.mark.parametrize('before,after', [(0, 1), (2, 3)])
def test_late_consumed_byte_change_rejects_even_when_both_mean_unknown(native_spans, before, after):
    source = Source(native_spans)
    source.fields(2, before, (0, 1))
    captured = direction.capture(source.read, BASE, source.bound, fixed_tick=TICK)
    source.fields(2, after, (0, 1))
    with pytest.raises(ValueError, match='consumed source changed'):
        direction.verify_capture(source.read, BASE, captured, source.bound)


def test_monotonic_cursor_allows_fixed_frame_reselection_but_rewind_refuses(native_spans):
    source = Source(native_spans)
    captured = direction.capture(source.read, BASE, source.bound, fixed_tick=TICK)
    advanced = source.bound | {'current_time_slice': TICK+1}
    out = direction.project(direction.verify_capture(source.read, BASE, captured, advanced))
    assert out['frame_tick'] == TICK and out['verification_cursor'] == TICK+1
    with pytest.raises(ValueError, match='rewound'):
        direction.verify_capture(source.read, BASE, captured, source.bound | {'current_time_slice': TICK-1})


def test_no_future_tick_or_boolean_tick(native_spans):
    source = Source(native_spans)
    for tick in (TICK+1, True, -1, 1 << 32):
        with pytest.raises(ValueError, match='tick exceeds'):
            direction.capture(source.read, BASE, source.bound, fixed_tick=tick)


@pytest.mark.parametrize('field', ['official_match_unique_id', 'local_playback_handle'])
def test_match_identity_cannot_be_zero_boolean_or_out_of_range(native_spans, field):
    source = Source(native_spans)
    for value in (0, True, -1, 1 << 64):
        with pytest.raises(ValueError, match='match identity'):
            direction.capture(source.read, BASE, source.bound | {field: value}, fixed_tick=TICK)
