"""Offline saved squad joins through real compressed FMF archives and readers."""
import inspect
import os
import struct

import pytest

from fm_live_mcp import saved_squad_search, snapshot_catalog
from test_saved_club_records import record
from test_saved_club_search import database, snapshot
from test_saved_database_header import text
from test_saved_world_search import framed


def club(index, native_id, *, team_indices=(), name='Newcastle United'):
    body = record(ordinal=index, name=name, short_name='Newcastle')
    # Replace only the independently constructed shared base with a minimal base.
    base = bytes(3) + bytes([len(team_indices)])
    base += b''.join(struct.pack('<i', -1 if value is None else value) for value in team_indices)
    base += bytes(10) + struct.pack('<III', index, native_id, native_id)
    return b'\0' + body[:-70] + base


def team(index, native_id, *, owner=0, owner_kind=0, team_type=0, people=(), kind=10):
    national = bytes(54) if kind == 11 else b''
    prefix = bytes(33) + struct.pack('<H', len(people))
    prefix += b''.join(struct.pack('<i', -1 if value is None else value) for value in people)
    prefix += bytes(18)
    common = struct.pack('<bB', team_type, owner_kind) + bytes(4)
    common += struct.pack('<I', 0xffffffff if owner is None else owner)
    common += text('') + b'\0' + text('') + b'\0'
    common += struct.pack('<III', index, native_id, native_id)
    return struct.pack('<b', kind) + national + prefix + common


def squads_database(clubs, teams, *, footer=None):
    # COMP through NATIONAL_TEAM_CONTAINER; three generic name containers;
    # REGION, LOCAL_REGION, STADIUM, STADIUM_CHANGE and STAGE_NAME precede TEAM.
    return database(clubs) + framed([]) * 8 + bytes(12) + framed([]) * 5 + framed(teams, footer=footer)


def save(tmp_path, clubs, teams, *, filename='squads.fm', footer=None):
    return snapshot(tmp_path / filename, squads_database(clubs, teams, footer=footer))


def query(path, club_native_id=688, **kwargs):
    return saved_squad_search.get_saved_club_squads(
        path.name, club_native_id, directory=path.parent, **kwargs)


@pytest.fixture
def squads_snapshot(tmp_path):
    return save(tmp_path,
                [club(0, 688, team_indices=(2, None, 0)),
                 club(1, 20000222, team_indices=(1,))],
                [team(0, 900, team_type=12, people=(4, None, 7)),
                 team(1, 901, owner=1, people=(8,)),
                 team(2, 902, team_type=9, people=(3, 3))])


def test_native_id_selects_one_duplicate_name_and_preserves_club_slot_order(squads_snapshot):
    result = query(squads_snapshot)
    assert result['source'] == 'on-disk save snapshot'
    assert result['club']['native_id'] == 688 and result['club']['database_index'] == 0
    assert result['club']['name'] == 'Newcastle United'
    assert result['team_count'] == 2
    assert result['team_indices'] == [2, None, 0]
    assert [row['database_index'] for row in result['teams']] == [2, 0]
    assert [row['native_id'] for row in result['teams']] == [902, 900]
    assert [row['team_type_code'] for row in result['teams']] == [9, 12]
    assert [row['roster_count'] for row in result['teams']] == [2, 3]
    assert [row['person_indices'] for row in result['teams']] == [[3, 3], [4, None, 7]]
    assert [row['owner_link_source'] for row in result['teams']] == ['team_backlink', 'team_backlink']
    other = query(squads_snapshot, 20000222)
    assert other['club']['database_index'] == 1 and other['team_count'] == 1
    assert other['teams'][0]['native_id'] == 901
    assert other['snapshot_id'] == result['snapshot_id']


def test_empty_club_vector_returns_no_teams(tmp_path):
    result = query(save(tmp_path, [club(0, 688)], []))
    assert result['team_count'] == 0 and result['teams'] == []


def test_all_null_team_slots_preserve_the_stored_vector(tmp_path):
    result = query(save(tmp_path, [club(0, 688, team_indices=(None, None))], []))
    assert result['team_count'] == 0 and result['teams'] == []
    assert result['team_indices'] == [None, None]


def test_missing_backlink_is_reconstructed_and_labelled(tmp_path):
    result = query(save(tmp_path, [club(0, 688, team_indices=(0,))],
                        [team(0, 900, owner=None, people=(7,))]))
    assert result['team_count'] == 1
    row = result['teams'][0]
    assert row['person_indices'] == [7]
    assert row['owner_link_source'] == 'club_vector_fixup'


@pytest.mark.parametrize('teams,clubs', [
    ([team(0, 900, owner=1)], [club(0, 688, team_indices=(0,)), club(1, 9)]),
    ([team(0, 900, owner_kind=1, kind=11)], [club(0, 688, team_indices=(0,))]),
    ([team(0, 900)], [club(0, 688)]),
    ([team(0, 900)], [club(0, 688, team_indices=(0,)), club(1, 9, team_indices=(0,))]),
])
def test_conflicting_owner_inverse_extra_or_shared_team_fails(tmp_path, teams, clubs):
    with pytest.raises(ValueError):
        query(save(tmp_path, clubs, teams))


@pytest.mark.parametrize('indices,people', [((3,), ()), ((-2,), ()), ((0,), (-2,))])
def test_invalid_club_or_person_reference_fails(tmp_path, indices, people):
    path = save(tmp_path, [club(0, 688, team_indices=indices)], [team(0, 900, people=people)])
    with pytest.raises(ValueError):
        query(path)


@pytest.mark.parametrize('clubs', [[club(0, 99)], [club(0, 688), club(1, 688)]])
def test_missing_or_nonunique_native_id_fails(tmp_path, clubs):
    with pytest.raises(ValueError):
        query(save(tmp_path, clubs, []))


def test_snapshot_pin_rejects_replacement(squads_snapshot):
    first = query(squads_snapshot)
    replacement = save(squads_snapshot.parent, [club(0, 688)], [], filename='next.fm')
    os.replace(replacement, squads_snapshot)
    with pytest.raises(ValueError, match='identity changed'):
        query(squads_snapshot, expected_snapshot_id=first['snapshot_id'])


@pytest.mark.parametrize('damage', ['truncated', 'ordinal', 'subtype', 'footer'])
def test_malformed_trailing_team_prevents_selected_club_result(tmp_path, damage):
    rows = [team(0, 900), team(1, 901, owner=1)]
    footer = None
    if damage == 'truncated':
        rows[1] = rows[1][:-4]
        footer = b''
    elif damage == 'ordinal':
        rows[1] = team(9, 901, owner=1)
    elif damage == 'subtype':
        rows[1] = b'\x7f' + rows[1][1:]
    else:
        footer = b'\0\0'
    path = save(tmp_path, [club(0, 688, team_indices=(0,)), club(1, 9, team_indices=(1,))],
                rows, footer=footer)
    with pytest.raises(ValueError):
        query(path)


@pytest.mark.parametrize('native_id', [True, -1, 1 << 32, None])
def test_bad_native_id_fails_before_opening_snapshot(tmp_path, native_id):
    with pytest.raises(ValueError):
        saved_squad_search.get_saved_club_squads('missing.fm', native_id, directory=tmp_path)


def test_duplicate_team_slot_is_rejected(tmp_path):
    path = save(tmp_path, [club(0, 688, team_indices=(0, 0))], [team(0, 900)])
    with pytest.raises(ValueError, match='duplicate'):
        query(path)


def test_source_replacement_during_final_team_rejects_whole_result(squads_snapshot, monkeypatch):
    from fm_live_mcp import saved_team_records
    original = saved_team_records.read_team
    replacement = save(squads_snapshot.parent, [club(0, 688)], [], filename='replacement.fm')

    def replace_after_decode(reader, ordinal, kind, **kwargs):
        result = original(reader, ordinal, kind, **kwargs)
        if ordinal == 2:
            os.replace(replacement, squads_snapshot)
        return result

    monkeypatch.setattr(saved_team_records, 'read_team', replace_after_decode)
    with pytest.raises(ValueError, match='changed during request'):
        query(squads_snapshot)


def test_public_wrapper_never_accesses_live_session(squads_snapshot, monkeypatch):
    from fm_live_mcp import server
    monkeypatch.setattr(snapshot_catalog, 'DEFAULT_DIRECTORY', squads_snapshot.parent)

    def forbidden(*args, **kwargs):
        pytest.fail('saved squad query accessed the live game')

    monkeypatch.setattr(server.bridge, '_current', forbidden)
    monkeypatch.setattr(server.bridge, '_run', forbidden)
    monkeypatch.setattr(server.bridge, 'attach', forbidden)
    assert 'session_id' not in inspect.signature(server.fm_get_saved_club_squads).parameters
    result = server.fm_get_saved_club_squads(squads_snapshot.name, 688)
    assert result['team_count'] == 2 and 'session_id' not in result
