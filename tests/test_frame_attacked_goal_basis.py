"""Owned original-native controls for the named xG goal-target sign chain."""
import hashlib
import struct
import pytest
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X9,
    UC_ARM64_REG_X12, UC_ARM64_REG_X13, UC_ARM64_REG_X14, UC_ARM64_REG_X19,
    UC_ARM64_REG_X20, UC_ARM64_REG_X21, UC_ARM64_REG_X28, UC_ARM64_REG_X30, UC_ARM64_REG_S0, UC_ARM64_REG_S3,
    UC_ARM64_REG_Q0, UC_ARM64_REG_SP, UC_ARM64_REG_PC)
from fm_live_mcp import frame_attacked_goal_basis as basis
from test_frame_attack_direction import Source, PLUGIN, BASE, TICK, OriginalNative

ENGINE, HOME, AWAY, PLAYER, STACK, OUTPUT, FEATURES, WEIGHTS = (
    0x41000000, 0x42000000, 0x43000000, 0x44000000,
    0x45000000, 0x46000000, 0x47000000, 0x48000000)
bits = lambda value: struct.unpack('<I', struct.pack('<f', value))[0]


@pytest.fixture(scope='module')
def native():
    spans = dict(basis.direction.NATIVE_SPANS + basis.NATIVE_SPANS)
    with PLUGIN.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
        for at, raw in spans.items():
            stream.seek(0x5ED4000 + at)
            assert stream.read(len(raw)) == raw
    with PLUGIN.open('rb') as stream:
        stream.seek(0x5ED4000 + 0x54EC0C8 + 0xD8)
        assert struct.unpack('<Q', stream.read(8))[0] & ((1 << 48) - 1) == 0x7359B0
    spans[0x54EC0C8 + 0xD8] = struct.pack('<Q', BASE + 0x7359B0)
    return spans


def machine(native):
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    for page in {BASE + (at & ~4095) for at in native} | {
        ENGINE + 0x15000, PLAYER, STACK, OUTPUT, FEATURES, WEIGHTS}:
        uc.mem_map(page, 4096)
    for at, raw in native.items():
        uc.mem_write(BASE + at, raw)
    return uc


@pytest.mark.parametrize('period', [6, 7])
@pytest.mark.parametrize('upfield', [HOME, AWAY])
@pytest.mark.parametrize('length', [100.0, 105.0, 111.5])
def test_original_frame_setter_player_setter_and_named_goal_target_chain(native, period, upfield, length):
    uc = machine(native)
    uc.mem_write(ENGINE + 0x15370, struct.pack('<2Q', HOME, AWAY))
    uc.mem_write(ENGINE + 0x15418, struct.pack('<Q', upfield))
    uc.mem_write(PLAYER + 0x280, struct.pack('<Q', ENGINE))
    uc.reg_write(UC_ARM64_REG_SP, STACK + 0x800)
    uc.reg_write(UC_ARM64_REG_X0, ENGINE)
    uc.reg_write(UC_ARM64_REG_X1, STACK + 0x878)
    uc.emu_start(BASE + 0x4ABD804, BASE + 0x4ABD81C, count=10)
    uc.reg_write(UC_ARM64_REG_X20, OUTPUT)
    uc.emu_start(BASE + 0x4AB35F4, BASE + 0x4AB3604, count=10)
    frame_upfield_slot = bytes(uc.mem_read(OUTPUT + 0x82, 1))[0]
    assert frame_upfield_slot == int(upfield == AWAY)
    source = Source(native)
    source.fields(period, frame_upfield_slot, (0, 1))
    official = OriginalNative(source)
    for side, owner in enumerate((HOME, AWAY)):
        uc.mem_write(PLAYER + 0x288, struct.pack('<Q', owner))
        uc.reg_write(UC_ARM64_REG_X0, PLAYER)
        uc.reg_write(UC_ARM64_REG_X30, BASE + 0x4548664)
        uc.emu_start(BASE + 0x4548640, BASE + 0x4548664, count=15)
        assert bytes(uc.mem_read(PLAYER + 0x2CD, 1))[0] == official.call(side)
        # Exact original goal-point construction. The earlier producer slice
        # supplies +/-PITCH+27C; no native lookup table is replaced or called.
        uc.reg_write(UC_ARM64_REG_X9, 0)
        uc.reg_write(UC_ARM64_REG_X19, PLAYER)
        uc.reg_write(UC_ARM64_REG_S0, bits(length / 2))
        uc.reg_write(UC_ARM64_REG_S3, bits(-length / 2))
        uc.emu_start(BASE + 0x48DB5F0, BASE + 0x48DB610, count=15)
        target = struct.unpack('<3f', uc.reg_read(UC_ARM64_REG_Q0).to_bytes(16, 'little')[:12])
        assert target == (0.0, length / 2 if owner == upfield else -length / 2, 0.0)
        assert (target[1] > 0) == bool(official.call(side))


def test_original_named_feature3_selector_reads_goal_angle_field(native):
    # The exact parser's unchanged literal comparison selects feature3, and
    # the original entire per-feature selector loop selects XG packet+10.
    assert native[0x52DB5CF] == b'transformed_angle_from_shot_location_to_centre_of_goal\0'
    uc = machine(native)
    uc.mem_write(FEATURES, b'\x03')
    uc.mem_write(WEIGHTS, struct.pack('<f', 1.0))
    uc.mem_write(OUTPUT + 0x10, struct.pack('<f', 0.625))
    reads = []
    def rd(machine, access, address, size, value, extra):
        assert (address, size) in ((FEATURES, 1), (WEIGHTS, 4), (OUTPUT + 0x10, 4))
        reads.append((address, size))
    def wr(*args):
        raise AssertionError('Native angular-feature selector unexpectedly writes')
    uc.hook_add(UC_HOOK_MEM_READ, rd)
    uc.hook_add(UC_HOOK_MEM_WRITE, wr)
    uc.reg_write(UC_ARM64_REG_X1, OUTPUT)
    uc.reg_write(UC_ARM64_REG_X12, FEATURES)
    uc.reg_write(UC_ARM64_REG_X13, WEIGHTS)
    uc.reg_write(UC_ARM64_REG_X14, 1)
    uc.reg_write(UC_ARM64_REG_S0, 0)
    uc.emu_start(BASE + 0x495D9E4, BASE + 0x495DA84, count=35)
    assert uc.reg_read(UC_ARM64_REG_PC) == BASE + 0x495DA84
    assert uc.reg_read(UC_ARM64_REG_S0) == bits(0.625)
    assert (OUTPUT + 0x10, 4) in reads


@pytest.mark.parametrize('period', [6, 7])
@pytest.mark.parametrize('upfield_slot', [0, 1])
def test_exact_frame_goal_basis_projects_checked_normal_period_only(native, period, upfield_slot):
    obj = Source(native)
    obj.fields(period, upfield_slot, (0, 1))
    captured = basis.capture(obj.read, BASE, obj.bound, fixed_tick=TICK)
    with pytest.raises(ValueError, match='Final'):
        basis.project(captured)
    verified = basis.verify_capture(obj.read, BASE, captured, obj.bound)
    projected = basis.project(verified)
    assert projected['state'] == 'available_native_attacked_goal_basis'
    assert projected['native_period_name'] == {6:'FirstHalf',7:'SecondHalf'}[period]
    assert [row['attacked_end_positive_native_y'] for row in projected['teams']] == [upfield_slot == 0, upfield_slot == 1]
    assert projected['physical_units'] is projected['penalty_area_occupation'] is projected['sustained_box_support'] is None
    assert projected['active_participation_verified'] is False


@pytest.mark.parametrize('period,normal,per_side', [(p, 0, (1, 0)) for p in [0,1,2,3,4,5,8,9,255,10,254]] + [(6, -1, (0, 1)), (7, -1, (0, 1))])
def test_shootout_unmapped_period_or_unknown_orientation_stays_unavailable(native, period, normal, per_side):
    obj = Source(native)
    obj.fields(period, normal, per_side)
    captured = basis.capture(obj.read, BASE, obj.bound, fixed_tick=TICK)
    projected = basis.project(basis.verify_capture(obj.read, BASE, captured, obj.bound))
    assert projected['state'] == 'unavailable_native_attacked_goal_basis'
    assert all(row['attacked_end_positive_native_y'] is None for row in projected['teams'])


def test_native_source_changes_final_eviction_and_rewind_refuse(native):
    obj = Source(native)
    obj.fields(6, 0, (0, 1))
    captured = basis.capture(obj.read, BASE, obj.bound, fixed_tick=TICK)
    obj.put(obj.frame + 0x82, b'\x01')
    with pytest.raises(ValueError, match='changed or was evicted'):
        basis.verify_capture(obj.read, BASE, captured, obj.bound)
    obj = Source(native)
    obj.values[BASE + 0x4548640] ^= 1
    with pytest.raises(ValueError, match='goal Y source changed'):
        basis.capture(obj.read, BASE, obj.bound, fixed_tick=TICK)


def test_missing_exact_frame_has_no_orientation_rows(native):
    obj = Source(native)
    obj.put(obj.frame + 0x38, struct.pack('<I', TICK + 1))
    captured = basis.capture(obj.read, BASE, obj.bound, fixed_tick=TICK)
    result = basis.project(basis.verify_capture(obj.read, BASE, captured, obj.bound))
    assert result['state'] == 'unavailable_native_attacked_goal_basis' and result['teams'] == []


@pytest.mark.parametrize('period', [6, 7])
@pytest.mark.parametrize('upfield_slot', [0, 1])
def test_original_getter_reads_original_engine_to_frame_period_copy(native, period, upfield_slot):
    # Original engine producer emits record+8 from ENGINE+1555A. The exact
    # constructor copy overlaps record[5:13] into FRAME[39:41], including3C.
    uc = machine(native)
    uc.mem_write(ENGINE + 0x1555A, bytes([period]))
    uc.mem_write(STACK + 0x98, bytes(range(13)))
    uc.reg_write(UC_ARM64_REG_X19, STACK + 0x98)
    uc.reg_write(UC_ARM64_REG_X21, ENGINE + 0x152A0)
    uc.emu_start(BASE + 0x4ABCE24, BASE + 0x4ABCE2C, count=3)
    assert bytes(uc.mem_read(STACK + 0xA0, 1)) == bytes([period])
    uc.reg_write(UC_ARM64_REG_X20, OUTPUT)
    uc.reg_write(UC_ARM64_REG_X28, STACK + 0x98)
    uc.reg_write(UC_ARM64_REG_SP, STACK)
    uc.emu_start(BASE + 0x4AB33FC, BASE + 0x4AB3418, count=8)
    assert bytes(uc.mem_read(OUTPUT + 0x34, 13)) == bytes(uc.mem_read(STACK + 0x98, 13))
    copied = bytes(uc.mem_read(OUTPUT + 0x3C, 1))[0]
    source = Source(native)
    source.fields(copied, upfield_slot, (0, 1))
    oracle = OriginalNative(source)
    oracle.uc.reg_write(UC_ARM64_REG_X0, 0x30000000)
    oracle.uc.reg_write(UC_ARM64_REG_X1, 123)
    oracle.uc.reg_write(UC_ARM64_REG_SP, 0x80000000 + 0x8000)
    oracle.uc.reg_write(UC_ARM64_REG_X30, 0x90000000)
    oracle.uc.emu_start(BASE + 0x7359B0, 0x90000000, count=100)
    assert oracle.uc.reg_read(UC_ARM64_REG_X0) == period
    assert [bool(oracle.call(side)) for side in (0, 1)] == [upfield_slot == 0, upfield_slot == 1]


def test_original_metadata_names_the_admitted_ordinary_halves():
    from pathlib import Path
    path = PLUGIN.parents[4] / 'Resources/Data/il2cpp_data/Metadata/global-metadata.dat'
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == 'ff4780c66f37e088f363d0c4365110dd0d7968204cb36283a6262055badab21d'
    headers = [struct.unpack_from('<III', data, 8 + i * 12) for i in range(31)]
    strings = data[headers[2][0]:sum(headers[2][:2])]
    def text(index):
        return strings[index:strings.index(0, index)].decode()
    owner = struct.unpack_from('<19I', data, headers[19][0] + 19058 * 76)
    assert (text(owner[1]), text(owner[0])) == ('SI.Match', 'MatchPeriod')
    assert (owner[5], owner[14] & 65535) == (87918, 12)
    defaults = {}
    for i in range(headers[7][2]):
        field, kind, offset = struct.unpack_from('<IHI', data, headers[7][0] + i * 10)
        if 87919 <= field <= 87929:
            defaults[field] = data[headers[8][0] + offset]
    actual = {}
    for field in range(87919, 87930):
        name, kind, token = struct.unpack_from('<IHI', data, headers[11][0] + field * 10)
        actual[text(name)] = defaults[field]
    assert actual == {'Invalid':255, 'KickOff':0, 'HalfTime':1, 'ExtraTimeKickOff':2,
        'ExtraTimeHalfTime':3, 'Penalties':4, 'FullTime':5, 'FirstHalf':6,
        'SecondHalf':7, 'ExtraTimeFirstHalf':8, 'ExtraTimeSecondHalf':9}
    assert basis.ORDINARY_PLAYING_PERIODS == {actual['FirstHalf']:'FirstHalf', actual['SecondHalf']:'SecondHalf'}


@pytest.mark.parametrize('at', [0x2279C, 0x7359B0, 0x738C44, 0x781988, 0x4ABCE24, 0x4AB33FC])
def test_new_period_route_producer_and_copy_source_guards_refuse_mutation(native, at):
    obj = Source(native)
    obj.fields(7, 0, (0, 1))
    obj.values[BASE + at] ^= 1
    with pytest.raises(ValueError, match='goal Y source changed'):
        basis.capture(obj.read, BASE, obj.bound, fixed_tick=TICK)


def test_named_period_getter_virtual_route_refuses_rebinding(native):
    obj = Source(native)
    obj.fields(7, 0, (0, 1))
    obj.put(BASE + 0x54EC0C8 + 0xD8, struct.pack('<Q', BASE + 0x7358C0))
    with pytest.raises(ValueError, match='period virtual route changed'):
        basis.capture(obj.read, BASE, obj.bound, fixed_tick=TICK)
