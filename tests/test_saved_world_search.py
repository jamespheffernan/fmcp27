"""Public world queries through genuine compressed, independent saved files."""
import inspect
import os
import struct

import pytest

from fm_live_mcp import saved_world_search, snapshot_catalog
from test_saved_club_search import database as club_database, snapshot


def framed(rows, *, footer=None, flags=0):
    """Frame serialized records without replacing any production table reader."""
    if footer is None:
        footer = struct.pack('<IBI', 0, 1, 17)
    return struct.pack('<IB', len(rows), flags) + b''.join(rows) + footer


def world_database(competitions=(), continents=(), currencies=(), *, competition_footer=None,
                   currency_footer=None):
    return (club_database([]) + framed(competitions, footer=competition_footer)
            + framed(continents) + framed(currencies, footer=currency_footer))


def search_competitions(path, **kwargs):
    return saved_world_search.find_competitions(path.name, directory=path.parent, **kwargs)


def search_currencies(path, **kwargs):
    return saved_world_search.find_currencies(path.name, directory=path.parent, **kwargs)


@pytest.mark.parametrize('query,kwargs', [
    ('competitions', {'native_id': True}), ('competitions', {'native_id': -1}),
    ('competitions', {'native_id': 1 << 32}), ('competitions', {'type_code': True}),
    ('competitions', {'type_code': -129}), ('competitions', {'type_code': 128}),
    ('competitions', {'gender': 'unknown'}), ('competitions', {'is_extinct': 1}),
    ('currencies', {'name': ''}), ('currencies', {'name': '   '}),
    ('currencies', {'native_id': True}), ('currencies', {'include_history': 1}),
    ('competitions', {'offset': -1}), ('currencies', {'limit': 0}),
    ('competitions', {'offset': True}), ('currencies', {'limit': 501}),
])
def test_invalid_arguments_fail_before_opening_a_file(tmp_path, query, kwargs):
    find = getattr(saved_world_search, 'find_' + query)
    with pytest.raises(ValueError):
        find('missing.fm', directory=tmp_path, **kwargs)


def competition(index=0, native_id=1, **kwargs):
    from test_saved_competition_records import record
    return b'\0' + record(ordinal=index, native_id=native_id, **kwargs)


@pytest.fixture
def world_snapshot(tmp_path):
    from test_saved_currency_records import continent, currency
    comps = [
        competition(0, 10, branch=4, name='Northern League', short_name='NL', type_code=-3,
                    gender_code=0, level=2, reputation=177),
        competition(1, 11, branch=4, name='Northern Women', short_name='NW', type_code=-3,
                    gender_code=1, is_extinct=True),
        competition(2, 12, branch=0, type_code=4, gender_code=0),
    ]
    rates = [
        currency(index=0, native=20, name='Straße Pound', rate_raw=struct.pack('<f', 1.25),
                 history=((0, 2025, struct.pack('<f', 2)),
                          (0, 2025, struct.pack('<f', 0)),
                          (0, 0, bytes.fromhex('0000807f')))),
        currency(index=1, native=21, name='Other Currency', rate_raw=bytes.fromhex('0000c07f')),
    ]
    return snapshot(tmp_path / 'world.fm', world_database(comps, [continent()], rates))


def test_same_file_inline_competition_names_and_context(world_snapshot):
    result = search_competitions(world_snapshot)
    rows = result['competitions']
    assert result['source'] == 'on-disk save snapshot'
    assert result['total_competition_slots'] == result['matched_count'] == 3
    assert rows[0]['name'] == 'Northern League' and rows[0]['short_name'] == 'NL'
    assert rows[0]['stored_name_state'] == 'serialized_branch4'
    assert rows[0]['reputation'] == 177 and rows[0]['level'] == 3
    assert rows[2]['name'] is None and rows[2]['short_name'] is None
    assert rows[2]['stored_name_state'] == 'not_serialized_by_this_record'
    assert result['saved_metadata']['status'] == 'unknown'
    assert result['database_format'] == {'serializer_version': 4000, 'source_major': 3754, 'source_minor': 9}


@pytest.mark.parametrize('criteria,ids', [
    ({'type_code': -3}, [10, 11]), ({'gender': 'male'}, [10, 12]),
    ({'gender': 'female', 'is_extinct': True}, [11]),
    ({'native_id': 10, 'type_code': -3, 'gender': 'male', 'is_extinct': False}, [10]),
    ({'native_id': 10, 'gender': 'female'}, []),
])
def test_competition_context_filters_intersect(world_snapshot, criteria, ids):
    result = search_competitions(world_snapshot, **criteria)
    assert [row['native_id'] for row in result['competitions']] == ids
    assert result['matched_count'] == len(ids)


def test_currency_search_exact_units_complete_history_and_nonfinite(world_snapshot):
    default = search_currencies(world_snapshot, name='STRASSE')
    row = default['currencies'][0]
    assert default['matched_count'] == 1 and default['total_currency_slots'] == 2
    assert row['native_id'] == 20 and row['history_count'] == 3 and 'history' not in row
    assert row['exchange_rate'] == {'value': 1.25, 'native_float32_hex': '0000a03f',
                                    'state': 'stored', 'basis': 'currency_units_per_GBP'}
    full = search_currencies(world_snapshot, native_id=20, include_history=True)['currencies'][0]
    assert len(full['history']) == full['history_count'] == 3
    assert [entry['native_year'] for entry in full['history']] == [2025, 2025, 0]
    assert [entry['exchange_rate']['value'] for entry in full['history']] == [2.0, 0.0, None]
    assert full['history'][2]['year'] is None
    assert full['history'][2]['exchange_rate']['native_float32_hex'] == '0000807f'
    nonfinite = search_currencies(world_snapshot, native_id=21)['currencies'][0]['exchange_rate']
    assert nonfinite['value'] is None and nonfinite['state'] == 'non_finite'
    assert nonfinite['native_float32_hex'] == '0000c07f'


@pytest.mark.parametrize('query,key', [(search_competitions, 'competitions'), (search_currencies, 'currencies')])
def test_native_order_paging_and_snapshot_pin(world_snapshot, query, key):
    first = query(world_snapshot, limit=1)
    second = query(world_snapshot, offset=first['next_offset'], limit=1,
                   expected_snapshot_id=first['snapshot_id'])
    assert first[key][0]['database_index'] == 0 and second[key][0]['database_index'] == 1
    assert first['matched_count'] == second['matched_count']
    replacement = snapshot(world_snapshot.with_name('replacement.fm'), world_database())
    os.replace(replacement, world_snapshot)
    with pytest.raises(ValueError, match='identity changed'):
        query(world_snapshot, offset=1, expected_snapshot_id=first['snapshot_id'])


@pytest.mark.parametrize('target', ['competition', 'currency'])
@pytest.mark.parametrize('corruption', ['truncated_row', 'wrong_ordinal', 'bad_subtype', 'truncated_footer'])
def test_later_corruption_prevents_early_page(tmp_path, target, corruption):
    from test_saved_currency_records import currency
    comps = [competition(0, 10), competition(1, 11)]
    rates = [currency(index=0, native=20), currency(index=1, native=21)]
    rows = comps if target == 'competition' else rates
    footer = None
    if corruption == 'truncated_row':
        rows[1] = rows[1][:-4]
        footer = b''
    elif corruption == 'wrong_ordinal':
        rows[1] = (competition(9, 11) if target == 'competition' else currency(index=9, native=21))
    elif corruption == 'bad_subtype':
        rows[1] = b'\x7f' + rows[1][1:]
    else:
        footer = b'\0\0'
    options = {target + '_footer': footer}
    payload = world_database(comps, (), rates, **options)
    if target == 'competition' and corruption in ('truncated_row', 'truncated_footer'):
        payload = club_database([]) + framed(comps, footer=footer)
    path = snapshot(tmp_path / 'bad.fm', payload)
    query = search_competitions if target == 'competition' else search_currencies
    with pytest.raises(ValueError):
        query(path, native_id=10 if target == 'competition' else 20, limit=1)


def test_public_wrappers_never_attach_or_run_game_helper(world_snapshot, monkeypatch):
    from fm_live_mcp import server
    monkeypatch.setattr(snapshot_catalog, 'DEFAULT_DIRECTORY', world_snapshot.parent)
    def forbidden(*args, **kwargs):
        pytest.fail('offline saved query accessed the live game')
    monkeypatch.setattr(server.bridge, '_current', forbidden)
    monkeypatch.setattr(server.bridge, '_run', forbidden)
    monkeypatch.setattr(server.bridge, 'attach', forbidden)
    for find, key in [(server.fm_find_saved_competitions, 'competitions'),
                      (server.fm_find_saved_currencies, 'currencies')]:
        assert 'session_id' not in inspect.signature(find).parameters
        result = find(world_snapshot.name, limit=1)
        assert len(result[key]) == 1 and 'session_id' not in result


def test_two_saved_files_keep_their_own_inline_names_and_currency_rates(tmp_path):
    from test_saved_currency_records import currency
    first = snapshot(tmp_path / 'first.fm', world_database(
        [competition(0, 10, branch=4, name='First League', short_name='FL')], (),
        [currency(index=0, native=20, name='First Pound', rate_raw=struct.pack('<f', 1))]))
    second = snapshot(tmp_path / 'second.fm', world_database(
        [competition(0, 10, branch=4, name='Second League', short_name='SL')], (),
        [currency(index=0, native=20, name='Second Pound', rate_raw=struct.pack('<f', 2))]))
    a = search_competitions(first); b = search_competitions(second)
    assert a['competitions'][0]['name'] == 'First League'
    assert b['competitions'][0]['name'] == 'Second League'
    assert a['snapshot_id'] != b['snapshot_id']
    assert a['filename'] == 'first.fm' and b['filename'] == 'second.fm'
    a = search_currencies(first); b = search_currencies(second)
    assert a['currencies'][0]['name'] == 'First Pound'
    assert b['currencies'][0]['name'] == 'Second Pound'
    assert a['currencies'][0]['exchange_rate']['value'] == 1
    assert b['currencies'][0]['exchange_rate']['value'] == 2


@pytest.mark.parametrize('target', ['competition', 'currency'])
def test_change_during_final_row_rejects_early_matching_page(world_snapshot, monkeypatch, target):
    from fm_live_mcp import saved_competition_records, saved_currency_records
    module = saved_competition_records if target == 'competition' else saved_currency_records
    name = 'read_' + target
    original = getattr(module, name)
    replacement = snapshot(world_snapshot.with_name('next.fm'), world_database())

    def replace_after_decode(reader, ordinal, kind, **kwargs):
        result = original(reader, ordinal, kind, **kwargs)
        if ordinal == (2 if target == 'competition' else 1):
            os.replace(replacement, world_snapshot)
        return result

    monkeypatch.setattr(module, name, replace_after_decode)
    query = search_competitions if target == 'competition' else search_currencies
    with pytest.raises(ValueError, match='changed during request'):
        query(world_snapshot, native_id=10 if target == 'competition' else 20, limit=1)


def test_currency_combined_filters_and_terminal_page(world_snapshot):
    missing = search_currencies(world_snapshot, name='Pound', native_id=21)
    assert missing['matched_count'] == 0 and missing['currencies'] == []
    terminal = search_currencies(world_snapshot, name='Pound', offset=1)
    assert terminal['matched_count'] == 1 and terminal['currencies'] == []
    assert terminal['next_offset'] is None
