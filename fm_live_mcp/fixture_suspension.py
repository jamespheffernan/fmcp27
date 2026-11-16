"""Narrow passive ordinary-suspension check for a caller-bound fixture/player.

The caller owns canonical PLAYER/fixture membership, fixture participation and
save/manager context in one ReadSet; call verify_native once, then verify that
ReadSet before publishing. Never execute the native evaluator. Nonempty sources
and RESULT records are deliberately unsupported, not negative decisions.
"""
import struct

from . import fixtures, players

MANAGER_ROOT = 0x56D2D08
MANAGER_VTABLE = 0x55DEF88
EVIDENCE_SCOPE = 'native_ordinary_suspension_check_empty_source'


def _read(read, address, size):
    raw = read(address, size)
    if not isinstance(raw, bytes) or len(raw) != size:
        raise ValueError('Incomplete fixture suspension source read')
    return raw


def _pointer(value, *, nullable=False):
    if type(value) is not int:
        raise ValueError('Invalid fixture suspension source pointer')
    if nullable and value == 0:
        return value
    if not 4096 <= value < 1 << 48 or value % 8:
        raise ValueError('Invalid fixture suspension source pointer')
    return value


def _u64(read, address):
    return struct.unpack('<Q', _read(read, address, 8))[0]


def verify_native(read, base):
    """Pin the exact activation, empty-source and named-reason paths."""
    _pointer(base)
    for rva, expected in NATIVE_SPANS:
        if _read(read, base + rva, len(expected)) != expected:
            raise ValueError('Fixture suspension native branch changed')


def _result(reason, *, source_state=None, count=None, ruled_out=False):
    return {
        'state': 'ruled_out' if ruled_out else 'unavailable',
        'reason': reason,
        'evidence_scope': EVIDENCE_SCOPE,
        'applies': False if ruled_out else None,
        'personal_ban_source_state': source_state,
        'physical_record_count': count,
        'overall_eligibility': 'not_assessed',
    }


def check(read, base, primary, record_kind, *, fixture_address, manager_address):
    """Rule out only the checked empty-source ordinary suspension branch.

    An absent secondary and an allocated empty vector follow separate native
    branches with the same false return; their public source states/counts stay
    distinct. No record pointer, rule, date-dependent applicability, global ban
    queue, TEAM+98/A0, or native function is read/executed on this path.
    """
    if record_kind not in ('actual', 'player_staff', 'virtual'):
        raise ValueError('Unknown fixture suspension player kind')
    if record_kind != 'actual':
        return _result('unsupported_player_kind')
    for address in (base, primary, fixture_address):
        _pointer(address)
    if _u64(read, primary) != base + players.RVA[0]:
        raise ValueError('Fixture suspension PLAYER type changed')

    fixture_vtable = _u64(read, fixture_address)
    if fixture_vtable == base + fixtures.TYPES['result'][0]:
        fixtures.typed(read, base, fixture_address, 'result')
        return _result('unsupported_result_fixture_branch')
    if fixture_vtable != base + fixtures.TYPES['fixture'][0]:
        raise ValueError('Fixture suspension fixture type changed')
    fixtures.typed(read, base, fixture_address, 'fixture')
    if _u64(read, fixture_vtable + 0x108) != base + 0x3D030D8:
        raise ValueError('Fixture suspension activation dispatch changed')

    _pointer(manager_address, nullable=True)
    resident_manager = _u64(read, base + MANAGER_ROOT)
    _pointer(resident_manager, nullable=True)
    if resident_manager != manager_address:
        raise ValueError('Fixture suspension manager context changed')
    if not resident_manager:
        return _result('native_eligibility_manager_absent')
    manager_vtable = _u64(read, resident_manager)
    if manager_vtable != base + MANAGER_VTABLE:
        raise ValueError('Fixture suspension manager type changed')
    for slot, target in ((0x230, 0x1F8AF7C), (0x260, 0x1F8DB6C)):
        if _u64(read, manager_vtable + slot) != base + target:
            raise ValueError('Fixture suspension manager dispatch changed')

    secondary = _u64(read, primary + 0xF0)
    _pointer(secondary, nullable=True)
    if not secondary:
        return _result('personal_ban_secondary_absent', source_state='secondary_absent', ruled_out=True)
    start, end, capacity = struct.unpack('<QQQ', _read(read, secondary + 0x18, 24))
    if (start, end, capacity) != (0, 0, 0):
        for pointer in (start, end, capacity):
            _pointer(pointer)
        if not start <= end <= capacity:
            raise ValueError('Invalid fixture suspension ban vector geometry')
    count = (end - start) // 8
    if count:
        return _result('nonempty_personal_ban_applicability_unsupported',
                       source_state='present_records', count=count)
    return _result('no_stored_personal_bans', source_state='present_empty', count=0, ruled_out=True)


# Build-pinned ARM64 bytes; no evidence files or runtime game calls are needed.
NATIVE_SPANS = (
    (0x1f8af7c, bytes.fromhex('ff8304d1e9230b6dfc6f0ca9fa670da9f85f0ea9f6570fa9f44f10a9fd7b11a9fd430491f90306aaf80305aaf50304aafa0303aaf30302aaf70301aa040600b4a80240f9088540f9e00315aa00013fd66005003448ba01f008e943f908ad40f9680000b4143940f902000014140080d2a8bc01f0000545f9200100b4a11240f9e10000b4080040f908e940f900013fd6600000b4085840f902000014080080d289aa46a94b0109eba00200540a0080d26bfd43937f0500f16c859f9a2d0080522e796af8df0117eba10000548e4240f9ce796af8df0108ebc00000544a0500915f010bebed279f1a9f010aeba1feff546d0000363600805294030014e87a40f9287200b409a941a95f0109ebc0710054290140f9897100b43a0100b4')),
    (0x1f8bec0, bytes.fromhex('16008052c0020012fd7b51a9f44f50a9f6574fa9f85f4ea9fa674da9fc6f4ca9e9234b6dff830491c0035fd6')),
    (0x1f8e7d8, bytes.fromhex('9cbc01f0800745f9a40357f8200100b4811040f9e10000b4080040f908e940f900013fd6e30300aaa40357f802000014030080d228ba0190008546f9080040f9081941f9e10314aae20316aae50319aa2600805200013fd6800000341b008052a800805259010014800745f9a40357f8200100b4811040f9e10000b4080040f908e940f900013fd6e30300aaa40357f802000014030080d219b901f039e33691e10314aae20316aae50319aa8f170094600100b4081440391f950071c00f00541f7d0071e1270054e8af40b9a80f00361b008052c80180523c010014')),
    (0x3d030d8, bytes.fromhex('00008052c0035fd6')),
    (0x14e35e0, bytes.fromhex('2800805258000014')),
    (0x5397fdc, bytes.fromhex('6f')),
    (0x2094be8, bytes.fromhex('2bc34039e90000b5')),
    (0x2094c08, bytes.fromhex('7f05007101050054e8cf44a9f41f40f9680100b4a82302d1e00314aa011483524101a072231b8d94a08302d1a12302d18a138d94a02302d1a3f38c94e82340f9680100b4a82302d1e00314aa211483524101a072171b8d94a0e302d1a12302d17e138d94a02302d197f38c94')),
)
