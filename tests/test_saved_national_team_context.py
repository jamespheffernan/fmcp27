"""National TEAM context through real compressed, file-local table fixtures."""
import os
import struct

import pytest

from fm_live_mcp import saved_nation_labels, saved_team_records
from test_saved_club_search import database, snapshot
from test_saved_national_containers import record as container_record
from test_saved_nations import body as nation_body
from test_saved_team_search import search, team
from test_saved_world_search import framed


def nation(index, native_id, secondary_id):
    body = nation_body(index)
    return b'\0' + body[:-12] + struct.pack('<III', index, native_id, secondary_id)


def container(index, native_id, secondary_id, *, nation_index, teams=()):
    body, _ = container_record(ordinal=index, native_id=native_id, secondary_id=secondary_id,
                               nation_index=0xffffffff if nation_index is None else nation_index & 0xffffffff,
                               team_indices=[-1 if value is None else value for value in teams])
    return b'\0' + body


def save(tmp_path, nations, containers, teams, *, filename='national.fm'):
    # CLUB, six intervening framed tables, NATION, NATIONAL_TEAM_CONTAINER,
    # three unframed generic name containers, five framed tables, TEAM.
    payload = (database([]) + framed([]) * 6 + framed(nations) + framed(containers)
               + bytes(12) + framed([]) * 5 + framed(teams))
    return snapshot(tmp_path / filename, payload)


@pytest.fixture(autouse=True)
def installed_labels(monkeypatch):
    response = {'status': 'available', 'reason': None,
                'metadata': {'source': 'installed_database_baseline', 'source_major': 3725,
                             'saved_name_equivalence': False},
                'labels': {100: {'name': 'First Nation', 'short_name': 'First', 'abbreviation': 'FST'},
                           200: {'name': 'Second Nation', 'short_name': 'Second', 'abbreviation': 'SND'}}}
    monkeypatch.setattr(saved_nation_labels, 'load_english_nation_labels', lambda: response)
    return response


@pytest.fixture
def national_snapshot(tmp_path):
    return save(tmp_path, [nation(0, 100, 0), nation(1, 200, 201)], [
        container(0, 9000, 9001, nation_index=1, teams=(None, 4, 0, 0, 2)),
        container(1, 100, 100, nation_index=0, teams=(0, 5)),
        container(2, 9002, 0, nation_index=None, teams=(1,)),
    ], [
        team(0, 8000, owner_kind=1, kind=11, owner=0),
        team(1, 8001, owner_kind=1, kind=11, owner=2),
        team(2, 8002, owner_kind=1, kind=11, owner=None),
        team(3, 8003, owner_kind=0, owner=None),
        team(4, 8004, owner_kind=1, kind=11, owner=0),
        team(5, 8005, owner_kind=1, kind=11, owner=1),
    ])


def test_default_projection_omits_optional_context_and_resource_load(national_snapshot, monkeypatch):
    def forbidden():
        pytest.fail('default query loaded optional installed labels')
    monkeypatch.setattr(saved_nation_labels, 'load_english_nation_labels', forbidden)
    result = search(national_snapshot)
    assert result['matched_count'] == result['total_team_slots'] == 6
    assert 'nation_name_source' not in result
    assert all('nation_context' not in row for row in result['teams'])


def test_primary_owner_drives_file_local_nation_join_and_labels(national_snapshot):
    result = search(national_snapshot, include_nation_context=True)
    first = result['teams'][0]['nation_context']
    assert first['state'] == 'saved_nation'
    assert first['container'] == {'database_index': 0, 'native_id': 9000, 'secondary_id': 9001}
    assert first['nation'] == {'database_index': 1, 'native_id': 200, 'secondary_id': 201}
    assert first['owner_team_slots'] == [2, 3]
    assert first['installed_english'] == {'name': 'Second Nation', 'short_name': 'Second', 'abbreviation': 'SND'}
    # Container1 also claims TEAM0; its nation100 must not replace primary owner0's nation200.
    if 'other_claiming_container_indices' in first:
        assert first['other_claiming_container_indices'] == [1]
    assert result['teams'][4]['nation_context']['owner_team_slots'] == [1]
    assert result['teams'][5]['nation_context']['nation']['native_id'] == 100
    assert result['nation_name_source']['status'] == 'available'
    assert result['nation_name_source']['metadata']['saved_name_equivalence'] is False
    assert 'nation_context' not in result['teams'][3]


def test_null_owner_stays_null_despite_inverse_claim_and_null_nation_is_distinct(national_snapshot):
    rows = search(national_snapshot, include_nation_context=True)['teams']
    no_nation = rows[1]['nation_context']
    assert no_nation['state'] == 'no_saved_nation'
    assert no_nation['container'] == {'database_index': 2, 'native_id': 9002, 'secondary_id': 0}
    assert no_nation['nation'] is no_nation['installed_english'] is None
    assert no_nation['owner_team_slots'] == [0]
    no_owner = rows[2]['nation_context']
    assert no_owner['state'] == 'no_saved_owner'
    assert no_owner['container'] is no_owner['nation'] is no_owner['installed_english'] is None
    assert no_owner['owner_team_slots'] == []


def test_nation_filter_is_implicit_context_and_applies_before_paging(national_snapshot):
    first = search(national_snapshot, nation_native_id=200, limit=1)
    second = search(national_snapshot, nation_native_id=200, offset=first['next_offset'], limit=1,
                    expected_snapshot_id=first['snapshot_id'])
    assert first['matched_count'] == second['matched_count'] == 2
    assert first['total_team_slots'] == second['total_team_slots'] == 6
    assert [first['teams'][0]['database_index'], second['teams'][0]['database_index']] == [0, 4]
    assert first['next_offset'] == 1 and second['next_offset'] is None
    assert first['teams'][0]['nation_context']['nation']['native_id'] == 200
    assert first['nation_name_source']['status'] == 'available'
    terminal = search(national_snapshot, nation_native_id=200, offset=2)
    assert terminal['matched_count'] == 2 and terminal['teams'] == []


def test_nation_filter_intersects_existing_team_criteria(national_snapshot):
    result = search(national_snapshot, nation_native_id=200, native_id=8004, owner_kind='national')
    assert result['matched_count'] == 1 and result['teams'][0]['database_index'] == 4
    missing = search(national_snapshot, nation_native_id=100, native_id=8000)
    assert missing['matched_count'] == 0 and missing['teams'] == []


@pytest.mark.parametrize('status,reason', [('unavailable', 'Resource missing'), ('unsupported', 'Resource changed')])
def test_optional_resource_failure_preserves_saved_context(national_snapshot, installed_labels, status, reason):
    installed_labels.update(status=status, reason=reason, labels={})
    result = search(national_snapshot, nation_native_id=200)
    assert result['matched_count'] == 2
    assert result['nation_name_source']['status'] == status
    assert result['nation_name_source']['reason'] == reason
    for row in result['teams']:
        assert row['nation_context']['nation']['native_id'] == 200
        assert row['nation_context']['installed_english'] is None


@pytest.mark.parametrize('criteria', [{'native_id': 8001}, {'native_id': 8002},
                                     {'owner_kind': 'club'}, {'native_id': 123456}])
def test_resource_not_needed_without_selected_saved_nation(national_snapshot, monkeypatch, criteria):
    def forbidden():
        pytest.fail('query without selected saved nation loaded resource')
    monkeypatch.setattr(saved_nation_labels, 'load_english_nation_labels', forbidden)
    result = search(national_snapshot, include_nation_context=True, **criteria)
    assert result['nation_name_source']['status'] == 'not_needed'
    assert set(result['nation_name_source']) == {'status', 'reason', 'metadata'}


@pytest.mark.parametrize('owner,nation_index', [(3, 0), (0, 2), (0, -2)])
def test_invalid_primary_container_or_nation_index_rejected(tmp_path, owner, nation_index):
    path = save(tmp_path, [nation(0, 100, 101)],
                [container(0, 9000, 9000, nation_index=nation_index)],
                [team(0, 8000, owner_kind=1, kind=11, owner=owner)])
    with pytest.raises(ValueError):
        search(path, include_nation_context=True)


def test_snapshot_replacement_rejects_context_pin(national_snapshot):
    pin = search(national_snapshot, include_nation_context=True)['snapshot_id']
    replacement = save(national_snapshot.parent, [], [], [], filename='replacement.fm')
    os.replace(replacement, national_snapshot)
    with pytest.raises(ValueError, match='identity changed'):
        search(national_snapshot, nation_native_id=200, expected_snapshot_id=pin)


def test_replacement_during_final_team_rejects_context_page(national_snapshot, monkeypatch):
    original = saved_team_records.read_team
    replacement = save(national_snapshot.parent, [], [], [], filename='replacement.fm')
    def replace_after_read(reader, ordinal, kind, **kwargs):
        row = original(reader, ordinal, kind, **kwargs)
        if ordinal == 5:
            os.replace(replacement, national_snapshot)
        return row
    monkeypatch.setattr(saved_team_records, 'read_team', replace_after_read)
    with pytest.raises(ValueError, match='changed during request'):
        search(national_snapshot, nation_native_id=200, limit=1)


@pytest.mark.parametrize('kwargs', [{'include_nation_context': 1}, {'include_nation_context': None},
                                   {'nation_native_id': True}, {'nation_native_id': -1},
                                   {'nation_native_id': 1 << 32}])
def test_invalid_nation_arguments_fail_before_source_open(tmp_path, monkeypatch, kwargs):
    from fm_live_mcp import saved_database
    monkeypatch.setattr(saved_database, 'open_at_clubs', lambda *a, **kw: pytest.fail('invalid query opened source'))
    with pytest.raises(ValueError):
        search(tmp_path / 'missing.fm', **kwargs)
