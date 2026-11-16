"""One PLAYER_BAN vector18 row, not a polymorphic factory or eligibility test.

Current writer405DAD0/405DD28: inner version5, optional-extra version1.
The explicit F0 full-loader reference profile is conditional and stays raw.
"""
import struct
PROFILE = {'stream_flags': 2, 'root_80a': 0, 'global_3522': 0, 'global_3523': 1, 'global_2c98': 1}

class UnsupportedBanWire(ValueError):

    def __init__(self, native, offset, reason):
        self.native, self.offset = (hex(native), offset)
        super().__init__(f'Unsupported ban wire {native:#x} at {offset}: {reason}')

def parse(data, start, *, source_major=3754, minor=9, reference_profile=PROFILE, limit=None):
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported PLAYER_BAN source')
    if not isinstance(reference_profile, dict) or reference_profile != PROFILE or any((type(reference_profile.get(k)) is not int for k in PROFILE)):
        raise ValueError('Explicit supported conditional F0 reference profile required')
    limit = len(data) if limit is None else limit
    if type(start) is not int or type(limit) is not int or (not 0 <= start <= limit <= len(data)):
        raise ValueError('Invalid bounded PLAYER_BAN cursor')
    at = start

    def take(n):
        nonlocal at
        if n < 0 or n > limit - at:
            raise ValueError('Truncated PLAYER_BAN wire')
        old = at
        at += n
        return bytes(data[old:at])

    def num(code):
        return struct.unpack('<' + code, take(struct.calcsize('<' + code)))[0]

    def compact(width, namespace, native):
        p = at
        value = num('b' if width == 1 else 'h')
        initial = value
        if value == -2:
            value = num('i')
        if value < 0 and initial != -1:
            raise ValueError('Negative nonnull compact ban reference reaches native failure')
        return {'start': p, 'end': at, 'namespace': namespace, 'native_reader': hex(native), 'transport': 'compact8' if width == 1 else 'compact16', 'raw_hex': bytes(data[p:at]).hex(), 'raw_index': None if initial == -1 else value, 'state': 'native_null' if initial == -1 else 'unresolved_index'}

    def team():
        p = at
        marker = num('B')
        if marker != 0:
            raise UnsupportedBanWire(17832352, p, 'Only current-writer mode4 marker0 is proved; inline/type2 branch unsupported')
        value = num('I')
        return {'start': p, 'end': at, 'namespace': 'TEAM', 'transport': 'mode4_marker0_index32', 'raw_word_u32': value, 'raw_hex': bytes(data[p:at]).hex(), 'identity_resolved': False}
    fixed_start = at
    values = struct.unpack('<Hbbhbh', take(9))
    raw_date = take(4)
    fields = dict(zip(('0x14_u16', '0x1c_i8', '0x1d_i8', '0x16_i16', '0x1a_i8', '0x18_i16'), values))
    scope_start = at
    version = num('B')
    if version != 5:
        raise UnsupportedBanWire(67491888, scope_start, 'Only current paired-writer version5 is supported; signed legacy branches remain explicit')
    kind = num('B')
    raw_04 = num('B')
    if kind in (1, 31):
        scope = compact(2, 'COMP', 17832956)
    elif kind in (5, 6, 10):
        scope = compact(2, 'NATION', 17924796)
    elif kind == 15:
        scope = compact(1, 'CONTINENT', 17923680)
    elif kind in (34, 35, 40):
        scope = team()
    else:
        p = at
        scope = {'start': p, 'end': p + 4, 'namespace': None, 'transport': 'raw_u32', 'raw_word_u32': num('I'), 'identity_resolved': False}
    raw_1b = num('B')
    marker_at = at
    presence = num('B')
    if presence not in (0, 1):
        raise ValueError('Invalid current-writer PLAYER_BAN extra presence')
    extra = None
    if presence:
        p = at
        v = num('B')
        if v != 1:
            raise UnsupportedBanWire(66670528, p, 'Only paired-writer extra version1 supported')
        date = take(4)
        person_start = at
        person = num('I')
        raw22 = num('B')
        team1 = team()
        team2 = team()
        raw20 = num('B')
        raw21 = num('B')
        raw1c = num('I')
        extra = {'start': p, 'end': at, 'version': v, 'native_18_1b_raw_hex': date.hex(), 'native_00_person_reference': {'start': person_start, 'end': person_start + 4, 'raw_word_u32': person, 'identity_resolved': False}, 'native_22_u8': raw22, 'native_08_team_reference': team1, 'native_10_team_reference': team2, 'native_20_u8': raw20, 'native_21_u8': raw21, 'native_1c_u32': raw1c, 'semantic_fields_resolved': False}
    return {'start': start, 'end': at, 'native_reader': '0x405d598', 'native_writer': '0x405dad0', 'source_record_kind': 'PLAYER_BAN', 'native_fields': fields, 'native_10_13_raw_hex': raw_date.hex(), 'scope': {'start': scope_start, 'end': scope['end'], 'version': version, 'native_kind_u8': kind, 'native_04_u8': raw_04, 'context': scope, 'identity_resolved': False}, 'native_1b_u8': raw_1b, 'extra_presence': {'offset': marker_at, 'value': presence}, 'extra': extra, 'raw_hex': bytes(data[start:at]).hex(), 'reference_profile': dict(reference_profile), 'native_globals_observed': False, 'complete_row_wire': True, 'eligibility_evaluated': False, 'record_meanings_or_service_not_inferred': True}

def rebuild(result):
    return bytes.fromhex(result['raw_hex'])
