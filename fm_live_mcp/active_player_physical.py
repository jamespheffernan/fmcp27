"""Source-qualified resident MATCH_PLAYER physical readings, not clearance.

Caller supplies a freshly fixture-bound engine and official match ID, owns the
same ReadSet and process/date rechecks, and must never reuse private addresses.
Simulation readings can be ahead of displayed playback. No native functions.
"""
import struct
from . import active_match_people


def decode(condition_raw, sharpness_raw):
    if type(condition_raw) is not int or not -(1 << 31) <= condition_raw < 1 << 31:
        raise ValueError('Expected signed native condition word')
    if type(sharpness_raw) is not int or not -32768 <= sharpness_raw <= 32767:
        raise ValueError('Expected signed native sharpness halfword')
    condition_supported = 0 <= condition_raw <= 1_000_000
    sharpness_supported = 0 <= sharpness_raw <= 10000
    return {'condition_raw_i32': condition_raw,
            'condition_percent_native_integer': condition_raw // 10000 if condition_supported else None,
            'condition_percent_computed': condition_raw / 10000 if condition_supported else None,
            'condition_state': 'supported_native_range' if condition_supported else 'unsupported_native_range',
            'sharpness_raw_i16': sharpness_raw,
            'sharpness_percent_native_integer': sharpness_raw // 100 if sharpness_supported else None,
            'sharpness_percent_computed': sharpness_raw / 100 if sharpness_supported else None,
            'sharpness_state': 'supported_native_range' if sharpness_supported else 'unsupported_native_range',
            'fatigue': None, 'fatigue_state': 'not_mapped_for_match_player',
            'medical_minutes_recommendation': None, 'fixture_eligibility': 'not_evaluated'}


def inspect(read, base, engine, *, expected_match_unique_id):
    if type(expected_match_unique_id) is not int or not 0 < expected_match_unique_id < 1 << 64:
        raise ValueError('Checked official match identity required')
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError('Active player physical native binding changed')
    active_match_people._type(read, base, engine, 0x55FA258, b'10GAME_MATCH')
    if active_match_people._u64(read, engine + 0x20) != expected_match_unique_id:
        raise ValueError('Physical snapshot match identity changed')
    people = active_match_people.inspect_canonical(read, base, engine, identity_only=True)
    rows = []
    for actor in people['rows']:
        row = {key: actor[key] for key in ('side_index', 'engine_array_index', 'identity_state', 'person')}
        row['physical'] = None
        if actor['person'] is not None:
            side = active_match_people._u64(read, engine + 0x15370 + actor['side_index'] * 8)
            address = active_match_people._u64(read, side + 0x140 + actor['engine_array_index'] * 8)
            active_match_people._type(read, base, address, 0x569EE68, b'N7simatch12MATCH_PLAYERE')
            if (active_match_people._u64(read, address + 0x280) != engine
                    or active_match_people._u64(read, address + 0x288) != side):
                raise ValueError('Physical snapshot player owner changed')
            person = active_match_people._u64(read, address + 0x20)
            index, native = struct.unpack('<II', read(person + 8, 8))
            identity = actor['person']['native_identity']
            if (index, native) != (identity['database_index'], identity['native_id']):
                raise ValueError('Physical snapshot canonical PERSON changed')
            condition = struct.unpack('<i', read(address + 0x1C74, 4))[0]
            sharpness = struct.unpack('<h', read(address + 0xC88, 2))[0]
            row['physical'] = decode(condition, sharpness)
        rows.append(row)
    return {'state': 'available_engine_physical_snapshot',
            'official_match_unique_id': expected_match_unique_id, 'rows': rows,
            'scope': 'resident_engine_player_snapshot', 'displayed_time_verified': False,
            'participation_status': 'not_established_by_physical_values',
            'source': 'official_Condition_cndn_and_Sharpness_shrp_MATCH_PLAYER_getter_branches',
            'limits': 'Engine condition is not the pre-match PLAYER reading, displayed-time condition, '
                      'on-pitch status, injury clearance, medical minutes or future fixture eligibility.'}


NATIVE_SPANS = (
    (0x267e08, bytes.fromhex('f40300aa005c40f9c08d00b4896240f9')),
    (0x268320, bytes.fromhex('c98d8c52c96dac721f01096be01a0054')),
    (0x268688, bytes.fromhex('08749cb9a9759152691bad72087d299b09fd7fd308fd6cd30801090b013d001345000014')),
    (0x268204, bytes.fromhex('094e8e52096dae721f01096bc02c0054')),
    (0x2687a8, bytes.fromhex('0810d979698f8252087d091b097d1313217d480ba0e302d1c06d0695')),
    (0x2687bc, bytes.fromhex('a0e302d1c06d0695fc010014')),
    (0x4545494, bytes.fromhex('09488852e901a07269761cb9')),
    (0x456513c, bytes.fromhex('897eb40a6a06d9798b0c80524a7d0b1b6b765cb9292d151b5f01096b49b1891a69761cb9aa7591526a1bad72297d2a9b2afd7fd329fd6cd329010a0b09250239fd7b42a9')),
)
