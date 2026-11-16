import struct

import pytest

from fm_live_mcp import weather, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_cities import city_memory
from test_database import bind, database_memory
from test_language_regions import places_memory
from test_players import memory
from test_world import world_memory


@pytest.fixture
def weather_memory(places_memory):
    m = places_memory
    addresses = []
    for i, name in enumerate(('Coastal', 'Fußland', '')):
        a = m['typed']('weather', 0x80)
        m['put'](a + 8, struct.pack('<III', i, 900 + i, 900 + i))
        m['q'](a + 0x18, m['text'](name))
        for period in range(4):
            weights = [period * 20 + j for j in range(20)]
            m['put'](a + 0x20 + period * 24, struct.pack('<h21b', period * 90, *weights, 100 if i == 0 else period))
        addresses.append(a)
    m['vec'](m['headers']['weather'], addresses)
    for i, a in enumerate(m['city_addresses']):
        m['q'](a + 0x28, addresses[i] if i < 2 else 0)
    m['q'](m['regions'][0] + 0x50, addresses[0])
    m['weather_addresses'] = addresses
    return m


def test_all_period_offsets_labels_weights_and_unspecified(weather_memory):
    m = weather_memory
    row, _ = weather.record(m['read'], m['base'], m['weather_addresses'][0], include_details=True)
    assert row['period_count'] == 4 and row['complete_native_periods']
    for index, period in enumerate(row['periods']):
        assert period['native_index'] == index and period['start_day']['native_value'] == index * 90
        assert period['day_night_variance'] == {'native_value': 100, 'value': None, 'state': 'not_specified', 'unit': None}
        for kind, offset, count in (('wind', 0, 5), ('precipitation', 5, 5), ('temperature', 10, 10)):
            weights = list(range(index * 20 + offset, index * 20 + offset + count))
            group = period[kind]
            assert [c['native_weight'] for c in group['categories']] == weights
            assert group['native_weight_total'] == sum(weights)
            assert group['label_source'] == 'installed_editor'
    assert row['periods'][0]['temperature']['categories'][0]['label'].startswith('Extremely Freezing')


@pytest.mark.parametrize('value', [-128, -1, 0, 50, 99, 100, 101, 127])
def test_variance_only_100_is_unspecified(weather_memory, value):
    m = weather_memory; a = m['weather_addresses'][0]
    m['put'](a + 0x36, struct.pack('<b', value))
    row, _ = weather.record(m['read'], m['base'], a, include_details=True)
    variance = row['periods'][0]['day_night_variance']
    assert variance['native_value'] == value and variance['unit'] is None
    assert variance['value'] == (None if value == 100 else value)


@pytest.mark.parametrize('day', [-32768, -1, 0, 365, 366, 32767])
def test_start_day_preserves_unverified_encoding(weather_memory, day):
    m = weather_memory; a = m['weather_addresses'][0]
    m['put'](a + 0x20, struct.pack('<h', day))
    m['put'](a + 0x22, struct.pack('<bb', -1, 127))
    row, _ = weather.record(m['read'], m['base'], a, include_details=True)
    period = row['periods'][0]
    assert period['start_day'] == {'native_value': day, 'state': 'calendar_encoding_unverified' if 0 <= day <= 365 else 'out_of_range'}
    assert [c['state'] for c in period['wind']['categories'][:2]] == ['out_of_range', 'out_of_range']


def test_queries_links_refresh_and_no_fallback(bridge, monkeypatch, weather_memory):
    m = weather_memory; bind(bridge, monkeypatch, m)
    page = bridge.find_weather_profiles(bridge.session)
    assert page['count'] == 3 and page['complete_table_scan'] and page['unnamed_records_examined'] == 1
    assert bridge.find_weather_profiles(bridge.session, name='FUSS', native_id=901)['count'] == 1
    assert bridge.find_weather_profiles(bridge.session, name='FUSS', native_id=900)['count'] == 0
    city = bridge.find_cities(bridge.session, weather_native_id=900)['cities'][0]
    region = bridge.find_local_regions(bridge.session, weather_native_id=900)['local_regions'][0]
    for row in (city, region):
        assert bridge.get_weather_profile(bridge.session, row['weather']['weather_ref'])['weather_profile']['native_id'] == 900
    ref = page['weather_profiles'][0]['weather_ref']; a = m['weather_addresses'][0]
    m['q'](a + 0x18, m['text']('Updated')); m['put'](a + 0x36, b'\x09')
    fresh = bridge.get_weather_profile(bridge.session, ref)['weather_profile']
    assert fresh['name'] == 'Updated' and fresh['periods'][0]['day_night_variance']['value'] == 9
    m['q'](m['city_addresses'][0] + 0x28, 0)
    assert bridge.find_cities(bridge.session, weather_native_id=900)['count'] == 0
    assert bridge.find_local_regions(bridge.session, weather_native_id=900)['count'] == 1
    m['q'](m['regions'][0] + 0x50, m['weather_addresses'][1])
    fresh = bridge.get_local_region(bridge.session, region['local_region_ref'])['local_region']
    assert fresh['weather']['native_id'] == 901
    assert bridge.get_weather_profile(bridge.session, region['weather']['weather_ref'])['weather_profile']['native_id'] == 900


def test_empty_pages_bound_cursors_and_type(bridge, monkeypatch, weather_memory):
    m = weather_memory; bind(bridge, monkeypatch, m)
    page = bridge.find_weather_profiles(bridge.session, name='fuss', record_budget=1)
    assert page['count'] == 0 and page['next_cursor']
    with pytest.raises(BridgeError, match='different query'):
        bridge.find_weather_profiles(bridge.session, name='Coastal', cursor=page['next_cursor'])
    fresh = bridge.find_weather_profiles(bridge.session, name='fuss', cursor=page['next_cursor'])
    assert fresh['count'] == 1 and fresh['next_cursor'] is None
    ref = fresh['weather_profiles'][0]['weather_ref']
    with pytest.raises(BridgeError, match='Unknown language'):
        bridge.get_language(bridge.session, ref)
    m['vec'](m['headers']['weather'], list(reversed(m['weather_addresses'])))
    with pytest.raises(BridgeError, match='different query'):
        bridge.find_weather_profiles(bridge.session, name='fuss', cursor=page['next_cursor'])


@pytest.mark.parametrize('fault', ['type', 'getter', 'id', 'index', 'membership', 'name', 'rtti'])
def test_malformed_records_reject_without_partial_results(bridge, monkeypatch, weather_memory, fault):
    m = weather_memory; bind(bridge, monkeypatch, m); a = m['weather_addresses'][1]
    if fault == 'type': m['q'](a, m['base'] + world.TYPES['club'][0])
    elif fault == 'getter': m['q'](m['base'] + world.TYPES['weather'][0] + 24, 0)
    elif fault == 'id': m['put'](a + 12, bytes(8))
    elif fault == 'index': m['put'](a + 8, struct.pack('<I', 0))
    elif fault == 'membership': m['vec'](m['headers']['weather'], [m['weather_addresses'][0], m['club']])
    elif fault == 'name': m['q'](a + 0x18, m['text']('bad\nname'))
    else: m['put'](m['base'] + world.TYPES['weather'][0] - 16, struct.pack('<q', 1))
    with pytest.raises(BridgeError): bridge.find_weather_profiles(bridge.session)
    assert bridge.geographic_refs == {}


@pytest.mark.parametrize('fault', ['id', 'slot', 'detach', 'cache'])
def test_weather_reference_expiry(bridge, monkeypatch, weather_memory, fault):
    m = weather_memory; bind(bridge, monkeypatch, m)
    ref = bridge.find_weather_profiles(bridge.session)['weather_profiles'][0]['weather_ref']
    if fault == 'id': m['put'](m['weather_addresses'][0] + 12, struct.pack('<II', 44, 44))
    elif fault == 'slot': m['vec'](m['headers']['weather'], list(reversed(m['weather_addresses'])))
    elif fault == 'detach': bridge.detach()
    else: bridge.geographic_refs.clear()
    with pytest.raises(BridgeError): bridge.get_weather_profile(bridge.session, ref)


@pytest.mark.parametrize('method', ['find_cities', 'find_local_regions'])
def test_weather_filter_bound_to_cursor(bridge, monkeypatch, weather_memory, method):
    bind(bridge, monkeypatch, weather_memory); find = getattr(bridge, method)
    page = find(bridge.session, weather_native_id=901, record_budget=1)
    assert page['count'] == 0 and page['next_cursor']
    with pytest.raises(BridgeError): find(bridge.session, weather_native_id=900, cursor=page['next_cursor'])
    fresh = find(bridge.session, weather_native_id=901, cursor=page['next_cursor'])
    assert fresh['count'] == (1 if method == 'find_cities' else 0)


@pytest.mark.parametrize('method, args', [
    ('find_weather_profiles', {'native_id': True}), ('find_weather_profiles', {'name': ''}),
    ('find_weather_profiles', {'name': 'x\n'}), ('find_weather_profiles', {'record_budget': 1001}),
    ('find_weather_profiles', {'max_matches': 101}), ('find_weather_profiles', {'cursor': False}),
    ('find_cities', {'weather_native_id': 0}), ('find_cities', {'weather_native_id': True}),
    ('find_local_regions', {'weather_native_id': 2**32}), ('find_local_regions', {'weather_native_id': -1})])
def test_invalid_selectors(bridge, method, args):
    with pytest.raises(BridgeError): getattr(bridge, method)(bridge.session, **args)


def test_cache_reservation_keeps_all_city_and_region_children(bridge, monkeypatch, weather_memory):
    m = weather_memory; bind(bridge, monkeypatch, m)
    for method, key in (('find_cities', 'cities'), ('find_local_regions', 'local_regions')):
        bridge.geographic_refs = {str(i): {} for i in range(10000)}
        rows = getattr(bridge, method)(bridge.session)[key]
        for row in rows:
            if row['weather']:
                assert bridge.get_weather_profile(bridge.session, row['weather']['weather_ref'])['weather_profile']['native_id'] == row['weather']['native_id']


def test_concurrent_period_change_rejects_whole_result(bridge, monkeypatch, weather_memory):
    m = weather_memory; bind(bridge, monkeypatch, m)
    target = m['weather_addresses'][0] + 0x20; hits = 0
    def read(address, size):
        nonlocal hits
        if (address, size) == (target, 23):
            hits += 1
            if hits == 2: m['put'](address + 2, b'\x09')
        return m['read'](address, size)
    monkeypatch.setattr(bridge, '_read_memory', lambda p, a, n: read(a, n))
    with pytest.raises(BridgeError, match='changed during read'):
        bridge.find_weather_profiles(bridge.session)
    assert bridge.geographic_refs == {}


def test_city_readback_refreshes_weather_and_retains_old_target(bridge, monkeypatch, weather_memory):
    m = weather_memory; bind(bridge, monkeypatch, m)
    city = bridge.find_cities(bridge.session, native_id=300)['cities'][0]
    ref = city['weather']['weather_ref']
    m['q'](m['city_addresses'][0] + 0x28, m['weather_addresses'][1])
    fresh = bridge.get_city(bridge.session, city['city_ref'])['city']
    assert bridge.get_weather_profile(bridge.session, fresh['weather']['weather_ref'])['weather_profile']['native_id'] == 901
    assert bridge.get_weather_profile(bridge.session, ref)['weather_profile']['native_id'] == 900
