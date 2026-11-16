"""The official kicking-upfield predicate from one already cached exact frame.

Capture after canonical fixture/playback binding. After the caller's final
ReadSet and process/career checks, refresh its bound playback and verify_capture.
Project only that verified result. No native frame construction is invoked.
"""
import struct

NATIVE_SPANS = (
    (0x22444, bytes.fromhex("680240f9086140f9e00313aae10316aae20315aae30314aa00013fd6")),
    (0x7358C0, bytes.fromhex("f44fbea9fd7b01a9fd430091e10200b4e80300aa002c40f9800000b4090c40f93f0101ebc0000054003140f9000200b4080c40f91f0101eb01020054f30303aae10302aad40c0094200100b408f040391f110071a1010054611e0013fd7b41a9f44fc2a81cf6051500008052fd7b41a9f44fc2a8c0035fd600008052fd7b41a9f44fc2a8c0035fd622f605951f00136be0179f1afd7b41a9f44fc2a8c0035fd6")),
    (0x738C54, bytes.fromhex("00044af9400000b405230114c0035fd6")),
    (0x781870, bytes.fromhex("f44fbea9fd7b01a9fd430091131041f9d30700b4e20301aa683a40b91f01016ba1000054e00313aafd7b41a9f44fc2a8c0035fd6685a44b91f01026ba100005460821091fd7b41a9f44fc2a8c0035fd6e80300aa60022191697a48b93f01026b40feff54699a4cb93f01026ba100005460823191fd7b41a9f44fc2a8c0035fd669ba50b93f01026bc1000054081082526002088bfd7b41a9f44fc2a8c0035fd669da54b93f01026bc1000054089482526002088bfd7b41a9f44fc2a8c0035fd669624cf90a84805221010a9b00e10091f40301aa0300805204008052050080d28fcd04952001003468c258b9080500110805409268620cf9e00314aafd7b41a9f44fc2a8c0035fd6000080d2fd7b41a9f44fc2a8c0035fd6")),
    (0x48B3194, bytes.fromhex("08d0218b00d54f39c0035fd6")),
    (0x48B31D0, bytes.fromhex("0008c239c0035fd6")),
)
_OWNER_FIELDS = ("playback_address", "frame_provider_address", "source_match_address",
                 "local_playback_handle", "official_match_unique_id")


def _read(read, address, size):
    raw = read(address, size)
    if len(raw) != size:
        raise ValueError("Incomplete frame attack-direction read")
    return raw


def _q(read, address):
    return struct.unpack('<Q', _read(read, address, 8))[0]


def _pointer(value):
    if type(value) is not int or not 4096 <= value < 1 << 48 or value % 4:
        raise ValueError("Invalid frame attack-direction pointer")
    return value


def verify_native(read, base):
    for at, expected in NATIVE_SPANS:
        if _read(read, base+at, len(expected)) != expected:
            raise ValueError("Native frame kicking-upfield source changed")
    if _q(read, base+0x54EC0C8+0xC0) != base+0x7358C0:
        raise ValueError("Named frame kicking-upfield virtual route changed")


def _project_fields(period, fields):
    branch = 'native_period_4_per_side_byte' if period == 4 else 'native_signed_upfield_team'
    rows = []
    for side in (0, 1):
        raw = fields[side] if period == 4 else fields[0]
        known = raw in (0, 1)
        rows.append({'side_index': side,
                     'native_kicking_upfield': bool(raw) if period == 4 and known else
                         raw == side if known else None,
                     'state': 'available_native_predicate' if known else 'unavailable_unmapped_native_orientation'})
    count = sum(row['native_kicking_upfield'] is not None for row in rows)
    return {'state': 'available' if count == 2 else 'available_partial' if count else 'unavailable_native_orientation',
            'native_period_code': period, 'native_branch': branch, 'teams': rows}


def capture(read, base, bound, *, fixed_tick):
    """Read the native predicate operands from an exact pre-existing cache hit.

    Native cache misses can construct frames. This passive adapter instead
    returns unavailable; duplicate exact frames are deliberately not selected.
    Caller must already have canonical fixture/client/source ownership binding.
    """
    verify_native(read, base)
    cursor = bound['current_time_slice']
    if type(cursor) is not int or type(fixed_tick) is not int or not 0 <= fixed_tick <= cursor <= 0xFFFFFFFF:
        raise ValueError("Frame attack-direction tick exceeds checked playback")
    if any(type(bound[k]) is not int or not 0 < bound[k] < 1 << 64
           for k in ('official_match_unique_id', 'local_playback_handle')):
        raise ValueError("Invalid frame attack-direction match identity")
    playback = _pointer(bound['playback_address'])
    provider = _pointer(bound['frame_provider_address'])
    source = _pointer(bound['source_match_address'])
    if (_q(read, playback) != base+0x54EC490 or _q(read, playback+0x10) != playback
            or _q(read, playback+0x1408) != provider or _q(read, provider+0x28) != source
            or _q(read, source) != base+0x55FA258
            or _q(read, source+0x20) != bound['official_match_unique_id']
            or _q(read, playback+0x18) != bound['local_playback_handle']):
        raise ValueError("Frame attack-direction playback ownership changed")
    result = {'state': 'unavailable_frame_cache', 'frame_tick': fixed_tick,
              'teams': None, '_binding': tuple(bound[k] for k in _OWNER_FIELDS),
              '_observed_cursor': cursor, 'same_session_fixed_frame_direction_verified': False}
    cache = _q(read, provider+0x220)
    if not cache:
        return result
    _pointer(cache)
    matches = [cache+i*0x420 for i in range(6)
               if struct.unpack('<I', _read(read, cache+i*0x420+0x38, 4))[0] == fixed_tick]
    if len(matches) != 1:
        return result | {'state': 'unavailable_unique_exact_frame'}
    frame = matches[0]
    period = _read(read, frame+0x3C, 1)[0]
    if period == 4:
        fields = tuple(_read(read, frame+0x3F5+16*side, 1)[0] for side in (0, 1))
    else:
        fields = (struct.unpack('<b', _read(read, frame+0x82, 1))[0],)
    if struct.unpack('<I', _read(read, frame+0x38, 4))[0] != fixed_tick:
        raise ValueError("Frame attack-direction tick changed during capture")
    return result | _project_fields(period, fields) | {'_native_fields': (period, fields)}


def verify_capture(read, base, captured, bound):
    """Reselect unchanged operands after the caller's last lifetime callback."""
    if (tuple(bound[k] for k in _OWNER_FIELDS) != captured['_binding']
            or bound['current_time_slice'] < captured['_observed_cursor']):
        raise ValueError("Frame attack-direction owner changed or playback rewound")
    again = capture(read, base, bound, fixed_tick=captured['frame_tick'])
    if (again['state'] != captured['state'] or again.get('_native_fields') != captured.get('_native_fields')):
        raise ValueError("Frame attack-direction consumed source changed or was evicted")
    return captured | {'same_session_source_reselection_verified': True,
                       'same_session_fixed_frame_direction_verified': '_native_fields' in captured,
                       'observed_cursor': captured['_observed_cursor'],
                       'verification_cursor': bound['current_time_slice']}


def project(verified):
    if verified.get('same_session_source_reselection_verified') is not True:
        raise ValueError("Final frame attack-direction verification is required")
    result = {k: v for k, v in verified.items() if not k.startswith('_')}
    return result | {
        'source': 'official_native_is_team_kicking_upfield_at_exact_cached_frame',
        'physical_units': None, 'positive_world_y_mapping_verified': False,
        'on_pitch_population_verified': False, 'penalty_area_occupation': None,
        'interpretation': 'The native kicking-upfield predicate at one exact cached frame. '
            'Its relation to positive world Y, human screen direction and penalty-area geometry '
            'is not established here. It does not establish active participation, box arrivals or a displayed minute.'}
