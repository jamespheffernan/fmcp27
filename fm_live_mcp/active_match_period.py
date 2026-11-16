"""Official simulation period from a caller's checked resident playback context.

No root discovery or game functions. Caller must obtain context from the typed
playback owner, bind its fixture separately, and verify one shared ReadSet.
A named period alone does not prove live gameplay or first-half counter scope.
"""
import struct

PERIODS = {255: 'Invalid', 0: 'KickOff', 1: 'HalfTime', 2: 'ExtraTimeKickOff',
           3: 'ExtraTimeHalfTime', 4: 'Penalties', 5: 'FullTime', 6: 'FirstHalf',
           7: 'SecondHalf', 8: 'ExtraTimeFirstHalf', 9: 'ExtraTimeSecondHalf'}


def _pointer(value):
    if type(value) is not int or value < 4096 or value % 8 or value >= 1 << 48:
        raise ValueError('Invalid checked playback context pointer')
    return value


def _read(read, address, size):
    raw = read(address, size)
    if not isinstance(raw, bytes) or len(raw) != size:
        raise ValueError('Incomplete match period source')
    return raw


def inspect(read, base, playback_context):
    """Consume capture()['bound_playback']; preserve unknown/stale periods explicitly."""
    for rva, expected in NATIVE_SPANS:
        if _read(read, base + rva, len(expected)) != expected:
            raise ValueError('Official match period native getter changed')
    if not isinstance(playback_context, dict):
        raise ValueError('A checked bound_playback context is required')
    playback = _pointer(playback_context.get('playback_address'))
    provider = _pointer(playback_context.get('frame_provider_address'))
    if struct.unpack('<Q', _read(read, playback, 8))[0] != base + 0x54EC490:
        raise ValueError('Unexpected match playback type')
    if struct.unpack('<Q', _read(read, playback + 0x10, 8))[0] != playback:
        raise ValueError('Match playback shim backing changed')
    if struct.unpack('<Q', _read(read, playback + 0x1408, 8))[0] != provider:
        raise ValueError('Match playback frame provider changed')
    current = struct.unpack('<i', _read(read, playback + 0x1DC0, 4))[0]
    if current != playback_context.get('current_time_slice'):
        raise ValueError('Checked playback time slice changed')
    state = struct.unpack('<Q', _read(read, provider + 0x220, 8))[0]
    result = {'source': 'official_native_get_simulation_period', 'source_state': 'unavailable',
              'simulation_period_raw_u8': None, 'simulation_period': None,
              'is_normal_halftime': None, 'is_extra_time_halftime': None,
              'period_state_time_slice': None, 'current_time_slice': current,
              'period_state_matches_current_time_slice': None,
              'scope': 'Named current playback simulation period only. Fixture identity, live/replay distinction, caught-up state and cumulative-stat scope require the caller shared observation.'}
    if not state:
        result['reason'] = 'period_state_absent'
        return result
    _pointer(state)
    raw = _read(read, state + 0x38, 5)
    state_time, period = struct.unpack('<iB', raw)
    name = PERIODS.get(period)
    aligned = state_time == current
    available = aligned and name is not None and period != 255
    result.update(source_state='available' if available else 'partial',
                  reason=None if available else 'period_state_time_mismatch' if not aligned
                         else 'invalid_native_period' if period == 255 else 'unmapped_native_period',
                  simulation_period_raw_u8=period, simulation_period=name,
                  is_normal_halftime=period == 1 if available else None,
                  is_extra_time_halftime=period == 3 if available else None,
                  period_state_time_slice=state_time,
                  period_state_matches_current_time_slice=aligned)
    return result


# Native export virtual-slot selection, named getter, backing getter and state pointer.
NATIVE_SPANS = (
    (0x2279c, bytes.fromhex('680240f9086d40f9e00313aae10314aa00013fd6')),
    (0x7359b0, bytes.fromhex('010300b4fd7bbfa9fd030091e80300aa002c40f9800000b4090c40f93f0101ebc0000054003140f9400100b4080c40f91f0101ebe1000054970c0094a00000b408f04039fd7bc1a8001d0013c0035fd6e81f8052fd7bc1a8001d0013c0035fd6e81f8052001d0013c0035fd6')),
    (0x738c44, bytes.fromhex('00044af9400000b44f230114c0035fd6')),
    (0x781988, bytes.fromhex('001041f9c0035fd6')),
)
