"""Saved TEAM search through real compressed archives and native wire fixtures."""
import inspect
import os
import struct

import pytest

from fm_live_mcp import saved_database, saved_team_records, snapshot_catalog
from test_saved_database_header import text
from test_saved_squad_search import club, save, team as stored_team


def module():
    # Production module lands independently; importing this test file must not
    # make unrelated tools/tests unimportable during coordinated implementation.
    from fm_live_mcp import saved_team_search
    return saved_team_search


def team(index, native_id, *, secondary_id=None, name='', short_name='', **kwargs):
    raw = stored_team(index, native_id, **kwargs)
    # The shared builder ends with two stored empty strings and identity.
    return (raw[:-22] + text(name) + b'\0' + text(short_name) + b'\0'
            + struct.pack('<III', index, native_id, native_id if secondary_id is None else secondary_id))


def search(path, **kwargs):
    return module().find_teams(path.name, directory=path.parent, **kwargs)


def filtered(path, people, **kwargs):
    pin = search(path, limit=1)['snapshot_id']
    return search(path, person_indices=people, expected_snapshot_id=pin, **kwargs)


@pytest.fixture
def teams_snapshot(tmp_path):
    return save(tmp_path, [club(i, 688 + i) for i in range(4)], [
        team(0, 900, secondary_id=0, name='Stored Senior', short_name='S', people=(4, None, 7, 4)),
        team(1, 901, secondary_id=123, owner_kind=1, kind=11, owner=2, team_type=1, people=(7, 9, None)),
        team(2, 902, owner=1, team_type=9, people=(3, 3, 7)),
        team(3, 903, owner_kind=2, kind=11, owner=None, team_type=-1, people=(4, (1 << 31) - 1), name='Étude'),
        team(4, 0, secondary_id=99, owner=None, team_type=127),
        team(5, 900, secondary_id=42, owner=3, team_type=-128, people=(None, 42)),
    ])


def test_complete_enumeration_preserves_native_order_and_raw_projection(teams_snapshot):
    result = search(teams_snapshot)
    assert result['filename'] == teams_snapshot.name
    assert result['source'] == 'on-disk save snapshot'
    assert result['total_team_slots'] == result['matched_count'] == 6
    assert result['next_offset'] is None
    assert result['saved_metadata']['status'] == 'unknown'
    assert result['database_format'] == {'serializer_version': 4000, 'source_major': 3754, 'source_minor': 9}
    rows = result['teams']
    assert [row['database_index'] for row in rows] == list(range(6))
    assert rows[0] == {'database_index': 0, 'native_id': 900, 'secondary_id': 0,
                       'team_type_code': 0, 'owner_kind': 'club', 'owner_index': 0,
                       'name': 'Stored Senior', 'short_name': 'S', 'roster_count': 4}
    assert rows[1]['secondary_id'] == 123 and rows[1]['owner_kind'] == 'national'
    assert rows[1]['name'] == rows[1]['short_name'] == ''
    assert rows[3]['owner_index'] is None and rows[3]['name'] == 'Étude'
    assert rows[4]['native_id'] == 0 and rows[4]['secondary_id'] == 99
    assert rows[4]['roster_count'] == 0
    assert all('person_indices' not in row and 'matched_person_slots' not in row for row in rows)
    assert not {'session_id', 'team_ref'} & result.keys()


@pytest.mark.parametrize('criteria,indices', [
    ({'native_id': 900}, [0, 5]),
    ({'native_id': 0}, [4]),
    ({'native_id': 123456}, []),
    ({'owner_kind': 'national'}, [1, 3]),
    ({'owner_kind': 'club'}, [0, 2, 4, 5]),
    ({'team_type_code': -128}, [5]),
    ({'team_type_code': 127}, [4]),
    ({'owner_kind': 'national', 'team_type_code': 1}, [1]),
    ({'native_id': 900, 'team_type_code': -128, 'owner_kind': 'club'}, [5]),
    ({'native_id': 900, 'owner_kind': 'national'}, []),
])
def test_id_owner_and_type_filters_intersect(teams_snapshot, criteria, indices):
    result = search(teams_snapshot, **criteria)
    assert [row['database_index'] for row in result['teams']] == indices
    assert result['matched_count'] == len(indices) and result['total_team_slots'] == 6


def test_person_any_match_preserves_all_source_slot_positions_and_null_gaps(teams_snapshot):
    result = filtered(teams_snapshot, [7, 4])
    rows = result['teams']
    assert [row['database_index'] for row in rows] == [0, 1, 2, 3]
    assert result['matched_count'] == 4 and result['total_team_slots'] == 6
    assert [row['matched_person_slots'] for row in rows] == [
        [{'slot_index': 0, 'person_index': 4}, {'slot_index': 2, 'person_index': 7}, {'slot_index': 3, 'person_index': 4}],
        [{'slot_index': 0, 'person_index': 7}],
        [{'slot_index': 2, 'person_index': 7}],
        [{'slot_index': 0, 'person_index': 4}],
    ]
    assert all('person_indices' not in row for row in rows)
    assert [row['roster_count'] for row in rows] == [4, 3, 3, 2]


def test_duplicate_membership_is_not_collapsed_or_counted_as_extra_teams(teams_snapshot):
    result = filtered(teams_snapshot, [3])
    assert result['matched_count'] == 1
    assert result['teams'][0]['database_index'] == 2
    assert result['teams'][0]['matched_person_slots'] == [
        {'slot_index': 0, 'person_index': 3}, {'slot_index': 1, 'person_index': 3}]


def test_person_or_filter_is_anded_with_other_filters(teams_snapshot):
    result = filtered(teams_snapshot, [4, 7], owner_kind='national', team_type_code=1, native_id=901)
    assert result['matched_count'] == 1 and result['teams'][0]['database_index'] == 1
    absent = filtered(teams_snapshot, [4], owner_kind='national', native_id=901)
    assert absent['matched_count'] == 0 and absent['teams'] == []


def test_valid_person_integer_endpoints_and_500_element_population(teams_snapshot):
    high = filtered(teams_snapshot, [(1 << 31) - 1])
    assert [row['database_index'] for row in high['teams']] == [3]
    assert high['teams'][0]['matched_person_slots'] == [{'slot_index': 1, 'person_index': (1 << 31) - 1}]
    low = filtered(teams_snapshot, [0])
    assert low['matched_count'] == 0
    population = filtered(teams_snapshot, list(range(500)))
    assert [row['database_index'] for row in population['teams']] == [0, 1, 2, 3, 5]


def test_filtered_paging_requires_same_pin_and_counts_full_match_population(teams_snapshot):
    pin = search(teams_snapshot, limit=1)['snapshot_id']
    first = search(teams_snapshot, person_indices=[4, 7], expected_snapshot_id=pin, limit=2)
    second = search(teams_snapshot, person_indices=[4, 7], expected_snapshot_id=pin, offset=first['next_offset'], limit=2)
    assert first['next_offset'] == 2 and second['next_offset'] is None
    assert first['matched_count'] == second['matched_count'] == 4
    assert first['total_team_slots'] == second['total_team_slots'] == 6
    assert [r['database_index'] for r in first['teams'] + second['teams']] == [0, 1, 2, 3]
    assert first['snapshot_id'] == second['snapshot_id'] == pin
    terminal = search(teams_snapshot, person_indices=[4, 7], expected_snapshot_id=pin, offset=4)
    assert terminal['matched_count'] == 4 and terminal['teams'] == [] and terminal['next_offset'] is None


def test_full_enumeration_page_union_and_valid_empty_terminal(teams_snapshot):
    first = search(teams_snapshot, limit=2)
    second = search(teams_snapshot, limit=2, offset=2, expected_snapshot_id=first['snapshot_id'])
    third = search(teams_snapshot, limit=2, offset=4, expected_snapshot_id=first['snapshot_id'])
    assert [r['database_index'] for r in first['teams'] + second['teams'] + third['teams']] == list(range(6))
    assert [r['next_offset'] for r in (first, second, third)] == [2, 4, None]
    assert all(r['matched_count'] == r['total_team_slots'] == 6 for r in (first, second, third))
    terminal = search(teams_snapshot, offset=6)
    assert terminal['matched_count'] == 6 and terminal['teams'] == [] and terminal['next_offset'] is None


def test_valid_empty_team_table_and_empty_rosters(tmp_path):
    empty = search(save(tmp_path, [], []))
    assert empty['total_team_slots'] == empty['matched_count'] == 0
    assert empty['teams'] == [] and empty['next_offset'] is None
    empty_roster = save(tmp_path, [club(0, 688)], [team(0, 900, people=(None, None))], filename='nulls.fm')
    result = filtered(empty_roster, [0, 4])
    assert result['total_team_slots'] == 1 and result['matched_count'] == 0 and result['teams'] == []


def test_unrelated_negative_source_words_do_not_hide_positive_matches(tmp_path):
    path = save(tmp_path, [], [team(0, 900, people=(-2, None, 4, -2147483648, 4))])
    summary = search(path)
    row = summary['teams'][0]
    assert row['roster_count'] == 5
    assert 'person_indices' not in row and 'unverified_negative_person_indices' not in row
    result = search(path, person_indices=[4], expected_snapshot_id=summary['snapshot_id'])
    assert result['matched_count'] == 1
    assert result['teams'][0]['matched_person_slots'] == [
        {'slot_index': 2, 'person_index': 4}, {'slot_index': 4, 'person_index': 4}]
    assert 'person_indices' not in result['teams'][0]


@pytest.mark.parametrize('kwargs', [
    {'person_indices': []}, {'person_indices': True}, {'person_indices': [True]},
    {'person_indices': [False]}, {'person_indices': [-1]}, {'person_indices': [1 << 31]},
    {'person_indices': [1.0]}, {'person_indices': ['1']}, {'person_indices': [None]},
    {'person_indices': [4, 4]}, {'person_indices': list(range(501))},
    {'person_indices': (1, 2)}, {'person_indices': {1, 2}}, {'person_indices': '1'},
    {'person_indices': {'person': 1}}, {'person_indices': [4], 'expected_snapshot_id': None},
    {'person_indices': [4], 'expected_snapshot_id': ''},
    {'person_indices': [4], 'expected_snapshot_id': '   '},
    {'person_indices': [4], 'expected_snapshot_id': True},
    {'native_id': True}, {'native_id': -1}, {'native_id': 1 << 32},
    {'owner_kind': 'National'}, {'owner_kind': ''}, {'owner_kind': 0},
    {'team_type_code': True}, {'team_type_code': -129}, {'team_type_code': 128},
    {'offset': True}, {'offset': -1}, {'limit': True}, {'limit': 0}, {'limit': 501},
])
def test_invalid_arguments_fail_before_source_open(tmp_path, monkeypatch, kwargs):
    kwargs = dict(kwargs)
    if 'person_indices' in kwargs and 'expected_snapshot_id' not in kwargs:
        kwargs['expected_snapshot_id'] = 'a' * 64
    def forbidden(*args, **kw):
        pytest.fail('invalid query attempted to open a saved source')
    monkeypatch.setattr(saved_database, 'open_at_clubs', forbidden)
    with pytest.raises(ValueError):
        module().find_teams('missing.fm', directory=tmp_path, **kwargs)


def test_first_person_filtered_page_requires_pin_even_for_existing_source(teams_snapshot):
    with pytest.raises(ValueError):
        search(teams_snapshot, person_indices=[4], offset=0)


def test_stale_pin_rejected_before_roster_match(teams_snapshot):
    with pytest.raises(ValueError, match='identity changed'):
        search(teams_snapshot, person_indices=[4], expected_snapshot_id='0' * 64)


def test_replacement_invalidates_filtered_page_pin(teams_snapshot):
    pin = search(teams_snapshot, limit=1)['snapshot_id']
    replacement = save(teams_snapshot.parent, [], [], filename='replacement.fm')
    os.replace(replacement, teams_snapshot)
    with pytest.raises(ValueError, match='identity changed'):
        search(teams_snapshot, person_indices=[4], expected_snapshot_id=pin, offset=1)


@pytest.mark.parametrize('damage', ['ordinal', 'subtype', 'truncated_row', 'truncated_footer', 'large_footer'])
def test_late_corruption_prevents_early_selected_page(tmp_path, damage):
    rows = [team(0, 900, people=(4,)), team(1, 901, owner=1)]
    footer = None
    if damage == 'ordinal':
        rows[1] = team(9, 901)
    elif damage == 'subtype':
        rows[1] = b'\x7f' + rows[1][1:]
    elif damage == 'truncated_row':
        rows[1] = rows[1][:-4]
        footer = b''
    elif damage == 'truncated_footer':
        footer = b'\0\0'
    else:
        footer = struct.pack('<I', 100001)
    path = save(tmp_path, [club(0, 688), club(1, 689)], rows, footer=footer)
    with pytest.raises(ValueError):
        search(path, native_id=900, limit=1)


def test_later_malformed_table_rejected_even_when_no_team_matches(tmp_path):
    path = save(tmp_path, [], [team(9, 900)])
    with pytest.raises(ValueError):
        search(path, native_id=123456)


def test_source_change_during_last_team_rejects_early_page(teams_snapshot, monkeypatch):
    original = saved_team_records.read_team
    replacement = save(teams_snapshot.parent, [], [], filename='next.fm')
    def change_after_read(reader, ordinal, kind, **kwargs):
        row = original(reader, ordinal, kind, **kwargs)
        if ordinal == 5:
            os.replace(replacement, teams_snapshot)
        return row
    monkeypatch.setattr(saved_team_records, 'read_team', change_after_read)
    with pytest.raises(ValueError, match='changed during request'):
        search(teams_snapshot, native_id=900, limit=1)


def test_public_wrapper_has_no_live_session_dependency(teams_snapshot, monkeypatch):
    from fm_live_mcp import server
    monkeypatch.setattr(snapshot_catalog, 'DEFAULT_DIRECTORY', teams_snapshot.parent)
    def forbidden(*args, **kwargs):
        pytest.fail('saved team search accessed the live game')
    for name in ('_current', '_run', 'attach'):
        monkeypatch.setattr(server.bridge, name, forbidden)
    assert 'session_id' not in inspect.signature(server.fm_find_saved_teams).parameters
    pin = search(teams_snapshot, limit=1)['snapshot_id']
    result = server.fm_find_saved_teams(teams_snapshot.name, person_indices=[4], expected_snapshot_id=pin)
    assert result['matched_count'] == 2 and result['total_team_slots'] == 6
    assert 'session_id' not in result


def test_exact_response_budget_preserves_every_matching_slot(tmp_path):
    budget = 16_384
    path = save(tmp_path, [], [team(0, 900, people=(4,) * budget)])
    result = filtered(path, [4], limit=1)
    slots = result['teams'][0]['matched_person_slots']
    assert result['matched_count'] == result['total_team_slots'] == 1
    assert len(slots) == budget
    assert slots[0] == {'slot_index': 0, 'person_index': 4}
    assert slots[-1] == {'slot_index': budget - 1, 'person_index': 4}
    assert 'person_indices' not in result['teams'][0]


def test_single_team_over_response_budget_fails_instead_of_truncating_slots(tmp_path):
    path = save(tmp_path, [], [team(0, 900, people=(4,) * 16_385)])
    pin = search(path, limit=1)['snapshot_id']
    with pytest.raises(ValueError, match='response budget'):
        search(path, person_indices=[4], expected_snapshot_id=pin, limit=1)
    # The unfiltered summary itself carries no roster slot response population.
    summary = search(path)
    assert summary['teams'][0]['roster_count'] == 16_385
    assert 'matched_person_slots' not in summary['teams'][0]


@pytest.mark.parametrize('second_count,over_budget', [(8192, False), (8193, True)])
def test_response_budget_counts_selected_page_slots_across_teams_only(tmp_path, second_count, over_budget):
    path = save(tmp_path, [], [team(0, 900, people=(4,) * 8192),
                              team(1, 901, people=(4,) * second_count)])
    pin = search(path, limit=1)['snapshot_id']
    if over_budget:
        with pytest.raises(ValueError, match='response budget'):
            search(path, person_indices=[4], expected_snapshot_id=pin, limit=2)
    else:
        full = search(path, person_indices=[4], expected_snapshot_id=pin, limit=2)
        assert sum(len(row['matched_person_slots']) for row in full['teams']) == 16_384
    first = search(path, person_indices=[4], expected_snapshot_id=pin, limit=1)
    second = search(path, person_indices=[4], expected_snapshot_id=pin, offset=1, limit=1)
    assert first['matched_count'] == second['matched_count'] == 2
    assert len(first['teams'][0]['matched_person_slots']) == 8192
    assert len(second['teams'][0]['matched_person_slots']) == second_count
    assert first['next_offset'] == 1 and second['next_offset'] is None
