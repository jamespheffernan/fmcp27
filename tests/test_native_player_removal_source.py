"""Original native constructors, selectors, status requests and eligibility."""
import hashlib
import struct
import pytest
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X5,
    UC_ARM64_REG_X19, UC_ARM64_REG_X21, UC_ARM64_REG_X23, UC_ARM64_REG_X25,
    UC_ARM64_REG_X30, UC_ARM64_REG_PC, UC_ARM64_REG_W5)
from fm_live_mcp import native_player_removal_source as removal
from test_frame_attack_direction import PLUGIN
from test_native_player_changes import source as change_source, BASE, ENGINE, ARRAY, SUB, SIDE, PLAYERS

OBJECTS = (0x38000000, 0x38001000, 0x38002000, 0x38003000)


@pytest.fixture(scope='module')
def native():
    spans = dict(removal.changes.NATIVE_SPANS + removal.NATIVE_SPANS)
    with PLUGIN.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
        for at, raw in spans.items():
            stream.seek(0x5ED4000 + at)
            assert stream.read(len(raw)) == raw
    return spans


def source(native):
    obj = change_source(native)
    for index, (table, (_, name, apply, _)) in enumerate(removal.TYPES.items()):
        info, text = 0x39000000 + 4096 * index, 0x3A000000 + 4096 * index
        obj.put(BASE + table - 16, struct.pack('<qQ', 0, info))
        obj.put(info + 8, struct.pack('<Q', text))
        obj.put(text, name + b'\0')
        obj.put(BASE + table + 0x20, struct.pack('<Q', BASE + apply))
    for address, table, code, tick, side, slot in zip(OBJECTS,
        (0x569F6D8, 0x569F6D8, 0x569F788, 0x569F578), (18, 6, 12, 11),
        (100, 101, 102, -1), (0, 1, 0, 1), (0, 25, 7, 9)):
        obj.put(address, struct.pack('<QiBbbb', BASE + table, tick, 0, code, side, slot))
    pointers = OBJECTS + (SUB, 0)
    obj.put(ENGINE + 0x147F0, struct.pack('<3Q', ARRAY, ARRAY + 8 * len(pointers), ARRAY + 8 * len(pointers)))
    obj.put(ARRAY, struct.pack('<6Q', *pointers))
    return obj


def machine(spans, extra_pages=()):
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    for page in {BASE + (at & ~4095) for at in spans} | set(extra_pages):
        uc.mem_map(page, 4096)
    for at, raw in spans.items():
        uc.mem_write(BASE + at, raw)
    return uc


def test_removal_requests_do_not_become_executed_participation(native):
    obj = source(native)
    result = removal.capture(obj.read, BASE, obj.bound)
    assert [r['native_apply_requested_status'] for r in result['rows']] == [3, 5, 2, None, None, None]
    assert [r['native_apply_body_noop'] for r in result['rows']] == [False, False, False, True, None, None]
    assert result['rows'][3]['native_change_tick'] is None
    assert result['rows'][4]['state'] == 'outside_typed_removal_request_scope'
    assert result['rows'][5]['state'] == 'unavailable_null_change_object'
    assert result['history_complete'] is None
    assert result['pending_vs_executed_verified'] is result['fixed_frame_participation_verified'] is False
    with pytest.raises(ValueError, match='Final'):
        removal.project(result)
    verified = removal.verify_capture(obj.read, BASE, obj.bound, result)
    assert removal.project(verified)['rows'] == result['rows']
    assert not any(key.startswith('_') for key in removal.project(verified))


@pytest.mark.parametrize('start,kind,expected_table,expected_code', [
    (0x4A7A414, 1, 0x569F6D8, 1), (0x4A7A414, 6, 0x569F6D8, 6),
    (0x4A7A814, 0, 0x569F788, 12), (0x4A796D0, 0, 0x569F578, 11)])
def test_complete_original_native_constructors(native, start, kind, expected_table, expected_code):
    uc = machine({start: native[start]}, (OBJECTS[0],))
    uc.reg_write(UC_ARM64_REG_X0, OBJECTS[0])
    uc.reg_write(UC_ARM64_REG_X1, kind)
    end = BASE + start + len(native[start])
    uc.reg_write(UC_ARM64_REG_X30, end)
    uc.emu_start(BASE + start, end, count=20)
    raw = bytes(uc.mem_read(OBJECTS[0], 16))
    assert struct.unpack_from('<Q', raw)[0] == BASE + expected_table
    assert struct.unpack_from('<i', raw, 8)[0] == -1
    assert raw[13] == expected_code and raw[14:16] == b'\xff\xff'


@pytest.mark.parametrize('side,slot', [(0, 0), (0, 25), (1, 0), (1, 25)])
@pytest.mark.parametrize('start,end,register', [
    (0x4A7A45C, 0x4A7A47C, UC_ARM64_REG_X21),
    (0x4A7A85C, 0x4A7A87C, UC_ARM64_REG_X23)])
def test_original_removal_selector_uses_original_side_slot(native, side, slot, start, end, register):
    uc = machine({start: native[start]}, (OBJECTS[0], ENGINE + 0x15000, SIDE, SIDE + 0x1000))
    uc.mem_write(OBJECTS[0] + 14, struct.pack('<2b', side, slot))
    uc.mem_write(ENGINE + 0x15370, struct.pack('<2Q', SIDE, SIDE + 0x1000))
    for index in (0, 1):
        uc.mem_write(SIDE + index * 0x1000 + 0x140,
            struct.pack('<26Q', *(PLAYERS + (26 * index + n) * 4096 for n in range(26))))
    def rd(machine, access, address, size, value, extra):
        assert (OBJECTS[0] + 14 <= address and address + size <= OBJECTS[0] + 16) or \
            (ENGINE + 0x15370 <= address and address + size <= ENGINE + 0x15380) or \
            any(SIDE + i * 0x1000 + 0x140 <= address and address + size <= SIDE + i * 0x1000 + 0x210 for i in (0, 1))
    def wr(*args):
        raise AssertionError('Original removal selector unexpectedly writes')
    uc.hook_add(UC_HOOK_MEM_READ, rd)
    uc.hook_add(UC_HOOK_MEM_WRITE, wr)
    uc.reg_write(UC_ARM64_REG_X0, OBJECTS[0])
    uc.reg_write(UC_ARM64_REG_X5, ENGINE)
    uc.emu_start(BASE + start, BASE + end, count=20)
    assert uc.reg_read(UC_ARM64_REG_PC) == BASE + end
    assert uc.reg_read(register) == PLAYERS + (26 * side + slot) * 4096


@pytest.mark.parametrize('kind,status', [(1, 3), (6, 5)])
def test_original_taken_off_requested_status_before_original_dispatch(native, kind, status):
    start, end = 0x4A7A4B4, 0x4A7A4E4
    uc = machine({start: native[start]})
    uc.reg_write(UC_ARM64_REG_X25, kind)
    uc.emu_start(BASE + start, BASE + end, count=20)
    assert uc.reg_read(UC_ARM64_REG_W5) == status
    assert uc.reg_read(UC_ARM64_REG_PC) == BASE + end


def test_original_send_off_requested_status_before_original_dispatch(native):
    start, end = 0x4A7A89C, 0x4A7A8BC
    uc = machine({start: native[start]})
    uc.emu_start(BASE + start, BASE + end, count=20)
    assert uc.reg_read(UC_ARM64_REG_W5) == 2


def test_original_injury_apply_is_noop_not_removal(native):
    start = 0x4A7979C
    uc = machine({start: native[start]})
    def memory(*args):
        raise AssertionError('Original injury apply unexpectedly touches memory')
    uc.hook_add(UC_HOOK_MEM_READ, memory)
    uc.hook_add(UC_HOOK_MEM_WRITE, memory)
    uc.reg_write(UC_ARM64_REG_X30, BASE + start + 4)
    uc.emu_start(BASE + start, BASE + start + 4, count=2)
    assert uc.reg_read(UC_ARM64_REG_PC) == BASE + start + 4


def test_complete_original_kind_gate_including_side_flags_and_unknown_kind(native):
    start = 0x4A64F9C
    uc = machine({start: native[start]}, (SIDE + 0x3000,))
    for flags in (0, 1, 2, 0x1000, 0x1001, 0xFFFF):
        uc.mem_write(SIDE + 0x30D0, struct.pack('<H', flags))
        for kind in (-1, *range(29), 0xFFFFFFFF):
            uc.reg_write(UC_ARM64_REG_X0, SIDE)
            uc.reg_write(UC_ARM64_REG_X1, kind & 0xFFFFFFFF)
            uc.reg_write(UC_ARM64_REG_X30, BASE + start + len(native[start]))
            uc.emu_start(BASE + start, BASE + start + len(native[start]), count=25)
            assert bool(uc.reg_read(UC_ARM64_REG_X0)) == removal.current_kind_allowed(flags, kind)
    assert removal.current_kind_allowed(0, 6) is False
    assert removal.current_kind_allowed(1, 6) is True


@pytest.mark.parametrize('side,slot', [(-1, 0), (2, 0), (0, -1), (1, 26)])
def test_invalid_native_owner_fields_remain_unavailable(native, side, slot):
    obj = source(native)
    obj.put(OBJECTS[0] + 14, struct.pack('<2b', side, slot))
    row = removal.capture(obj.read, BASE, obj.bound)['rows'][0]
    assert row['state'] == 'unavailable_typed_removal_side_or_original_slot'
    assert row['side_index'] is row['player_original_slot'] is row['native_change_tick'] is None
    assert row['native_apply_requested_status'] is row['native_apply_body_noop'] is None


def test_changed_native_source_type_tick_and_final_snapshot_refuse(native):
    obj = source(native)
    captured = removal.capture(obj.read, BASE, obj.bound)
    obj.put(OBJECTS[0] + 8, struct.pack('<i', 999))
    with pytest.raises(ValueError, match='storage changed'):
        removal.verify_capture(obj.read, BASE, obj.bound, captured)
    obj.put(OBJECTS[0] + 13, b'\x04')
    with pytest.raises(ValueError, match='constructor'):
        removal.capture(obj.read, BASE, obj.bound)
    obj = source(native)
    obj.put(BASE + 0x569F788 + 0x20, struct.pack('<Q', BASE + 0x4A7979C))
    with pytest.raises(ValueError, match='route changed'):
        removal.capture(obj.read, BASE, obj.bound)
    obj = source(native)
    obj.values[BASE + 0x4A7979C] ^= 1
    with pytest.raises(ValueError, match='source changed'):
        removal.capture(obj.read, BASE, obj.bound)


def test_empty_and_budget_preserve_unavailable_distinction(native):
    obj = source(native)
    obj.put(ENGINE + 0x147F0, bytes(24))
    assert removal.capture(obj.read, BASE, obj.bound)['rows'] == []
    obj.put(ENGINE + 0x147F0, struct.pack('<3Q', ARRAY, ARRAY + 8 * 4097, ARRAY + 8 * 4097))
    result = removal.capture(obj.read, BASE, obj.bound)
    assert result['state'] == 'unavailable_native_removal_request_budget' and result['rows'] is None
