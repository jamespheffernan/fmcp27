import struct

import pytest

from fm_live_mcp import active_match_period as period


@pytest.fixture
def source():
    cells = {}
    def put(a, raw):
        cells.update({a + i: x for i, x in enumerate(raw)})
    def read(a, n):
        return bytes(cells[a + i] for i in range(n))
    base, playback, provider, state = 0x10000000, 0x20000000, 0x30000000, 0x40000000
    for a, raw in period.NATIVE_SPANS:
        put(base + a, raw)
    for a, value in ((playback, base + 0x54EC490), (playback + 0x10, playback),
                     (playback + 0x1408, provider), (provider + 0x220, state)):
        put(a, struct.pack('<Q', value))
    put(playback + 0x1DC0, struct.pack('<i', 11544))
    put(state + 0x38, struct.pack('<iB', 11544, 1))
    return dict(read=read, put=put, base=base, playback=playback, provider=provider, state=state,
                context={'playback_address': playback, 'frame_provider_address': provider,
                         'current_time_slice': 11544})


def inspect(s):
    return period.inspect(s['read'], s['base'], s['context'])


def test_normal_halftime_requires_current_period_state(source):
    result = inspect(source)
    assert result['source_state'] == 'available'
    assert result['simulation_period'] == 'HalfTime'
    assert result['is_normal_halftime'] is True
    assert result['is_extra_time_halftime'] is False
    assert result['period_state_matches_current_time_slice'] is True


@pytest.mark.parametrize('value,name,normal,extra', [
    (0, 'KickOff', False, False), (3, 'ExtraTimeHalfTime', False, True),
    (5, 'FullTime', False, False), (6, 'FirstHalf', False, False),
    (7, 'SecondHalf', False, False), (9, 'ExtraTimeSecondHalf', False, False)])
def test_official_period_domains_remain_distinct(source, value, name, normal, extra):
    source['put'](source['state'] + 0x3C, bytes([value]))
    result = inspect(source)
    assert result['simulation_period'] == name
    assert result['is_normal_halftime'] is normal
    assert result['is_extra_time_halftime'] is extra


@pytest.mark.parametrize('value', [255, 10])
def test_invalid_or_unknown_period_withholds_halftime(source, value):
    source['put'](source['state'] + 0x3C, bytes([value]))
    result = inspect(source)
    assert result['source_state'] == 'partial'
    assert result['is_normal_halftime'] is None


def test_stale_state_does_not_claim_halftime(source):
    source['put'](source['state'] + 0x38, struct.pack('<iB', 11543, 1))
    result = inspect(source)
    assert result['source_state'] == 'partial'
    assert result['reason'] == 'period_state_time_mismatch'
    assert result['simulation_period'] == 'HalfTime'
    assert result['is_normal_halftime'] is None


def test_missing_state_is_unknown(source):
    source['put'](source['provider'] + 0x220, bytes(8))
    result = inspect(source)
    assert result['source_state'] == 'unavailable'
    assert result['is_normal_halftime'] is None


@pytest.mark.parametrize('fault', ['native', 'type', 'shim', 'provider', 'time'])
def test_broken_context_or_native_guard_rejects(source, fault):
    if fault == 'native':
        source['put'](source['base'] + period.NATIVE_SPANS[0][0], b'\0')
    elif fault == 'type':
        source['put'](source['playback'], bytes(8))
    elif fault == 'shim':
        source['put'](source['playback'] + 0x10, bytes(8))
    elif fault == 'provider':
        source['context']['frame_provider_address'] += 8
    else:
        source['context']['current_time_slice'] -= 1
    with pytest.raises(ValueError):
        inspect(source)
