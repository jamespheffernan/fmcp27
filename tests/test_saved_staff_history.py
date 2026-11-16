import struct
import pytest
from fm_live_mcp import saved_staff_history as staff, saved_population as population, snapshot_catalog
from fm_live_mcp.person_wire import parse_record
import test_saved_player_history as prior
import test_saved_competition_state as archives
import test_saved_starting_career as playing
RESOLVE_TEAMS = staff.resolve_teams


def anchor(pairs=((9, 0),)):
    preceding = playing.anchor(((9, 0),))[:-4]
    return preceding + struct.pack('<I', len(pairs)) + b''.join(struct.pack('<ii', *p) for p in pairs)


def wire(job=5, team=688):
    return staff.ROW.pack(team, (2021 << 16) | 312, 0x076c0001, 0, 16, job, 255)


def index(values):
    previous = 0
    encoded = []
    for offset in values:
        previous = (offset - previous + 2**31) % 2**32 - 2**31
        encoded.append(previous)
    return (prior.history.LIST_HEADER + prior.vector(()) + struct.pack('<I', 1) + prior.vector(encoded)
            + prior.vector((0,) if not values else ()) + struct.pack('<IH', 20, 3))


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(population.saved_name_vectors, 'locate', lambda data: prior.Layout(data))
    monkeypatch.setattr(population, '_LAST_LAYOUT', None)
    population._PREFIXES.clear()
    staff._CONTEXT_COUNTS.clear()
    monkeypatch.setattr(staff.fixture, '_canonical_context', lambda data: ({'source_major': 3754, 'source_minor': 9}, [{}], [{}], 0))
    monkeypatch.setattr(staff, 'resolve_teams', lambda data, rows: None)
    yield
    population._PREFIXES.clear()


def save(tmp_path, monkeypatch, *, owner=0, values=(0, 20, 20), pairs=None, dt=None, ls=None):
    body = prior.player()
    identity = parse_record(body, 0, 0, limit=len(body))['identity']
    native = prior.history._signed(identity['native_id_word'])
    data = body + anchor(((native, owner),) if pairs is None else pairs)
    monkeypatch.setattr(archives, 'world_database', lambda comps: data)
    members = {'non_pl_hist_ls.dat': index(values) if ls is None else ls,
               'non_pl_hist_dt.cmt': b'\x03\x01tmc.\x03\x00' + wire() + wire(6) if dt is None else dt}
    path = archives.archive(tmp_path / 'staff.fm', [], members)
    pin = snapshot_catalog.inspect_snapshot(path.name, directory=tmp_path, limit=1)['snapshot_id']
    return path, pin


def query(source, **kwargs):
    path, pin = source
    return staff.get_staff_history(path.name, 0, pin, directory=path.parent, **kwargs)


def test_ordered_duplicate_paging_and_pinned_components(tmp_path, monkeypatch):
    src = save(tmp_path, monkeypatch)
    first = query(src, limit=1)
    assert first['state'] == 'available' and first['total_indexed_entries'] == 3
    assert first['owner']['owner_key'] == 0 and first['owner']['native_id'] != 0
    assert first['rows'][0]['job_type_raw_u16'] == 5
    second = query(src, offset=1)
    assert [r['entry_index'] for r in second['rows']] == [1, 2]
    assert second['rows'][0]['record_sha256'] == second['rows'][1]['record_sha256']
    assert second['rows'][0]['left_date']['state'] == 'native_default_marker'
    assert all(c['state'] == 'complete_frame_and_packed_bytes_rechecked' for c in first['components'].values())


@pytest.mark.parametrize('owner,values,state', [(0, (), 'available_empty'), (-1, (0,), 'no_history_index'), (1, (0,), 'unavailable')])
def test_owner_states(tmp_path, monkeypatch, owner, values, state):
    result = query(save(tmp_path, monkeypatch, owner=owner, values=values))
    assert result['state'] == state and result['rows'] == []
    if state == 'unavailable':
        assert result['total_indexed_entries'] is None


def test_map_absence_is_not_empty(tmp_path, monkeypatch):
    result = query(save(tmp_path, monkeypatch, pairs=((1, 0),)))
    assert result['state'] == 'unavailable' and result['selected_row_count'] is None
    assert result['owner']['state'] == 'native_ID_not_in_saved_map'


@pytest.mark.parametrize('pairs', [((9, 0), (9, 1)), ((10, 0), (9, 1))])
def test_bad_map_order(pairs):
    with pytest.raises(ValueError, match='unsorted or duplicated'):
        staff.locate_owner_map(anchor(pairs), competition_count=1, stage_name_count=1, native_id=9)


def test_signed_and_raw_dates_roles():
    row = staff.decode_row(staff.ROW.pack(-1, 0, 0x076c0001, 0xffffffff, 255, 0, 254))
    assert row['team_reference']['state'] == 'native_null_reference'
    assert row['native_getter_job_type'] == 11 and row['job_type_raw_u16'] == 0
    assert row['unmapped_byte_0x3c'] == 255 and row['unmapped_byte_0x3a'] == 254
    assert row['joined_date']['calendar_projection'] is None
    assert staff.decode_row(wire(65535))['baseline_english_role']['state'] == 'unmapped_job_code'
    assert staff.decode_row(wire())['joined_date']['calendar_projection'] == '2021-11-08'
    assert staff.decode_row(wire())['current_employment_assessed'] is False


@pytest.mark.parametrize('length', range(20))
def test_all_row_truncations(length):
    with pytest.raises(ValueError):
        staff.decode_row(wire()[:length])


@pytest.mark.parametrize('kwargs', [{'offset': True}, {'limit': False}, {'limit': 201}, {'offset': -1}])
def test_strict_controls(tmp_path, monkeypatch, kwargs):
    with pytest.raises(ValueError):
        query(save(tmp_path, monkeypatch), **kwargs)


def test_team_native_namespace_and_ambiguity(monkeypatch):
    monkeypatch.setattr(staff.saved_database_header, 'read_header', lambda r: None)
    monkeypatch.setattr(staff.saved_database_tables, 'reach_clubs', lambda r: None)
    monkeypatch.setattr(staff.saved_squad_tables, 'reach_teams_after_clubs', lambda r: None)
    clubs = [dict(database_index=4, native_id=88, secondary_id=88, name='Canonical Club', short_name='Club', team_indices=[3])]
    teams = [dict(database_index=3, native_id=688, secondary_id=688, owner_kind='club', owner_index=4, name=None, short_name=None)]
    monkeypatch.setattr(staff.saved_database, 'table', lambda r, label, decoder: iter(clubs if label == 'CLUB' else teams))
    row = staff.decode_row(wire())
    RESOLVE_TEAMS(b'', [row])
    assert row['team_reference']['state'] == 'available'
    assert row['team_reference']['display_name'] == 'Canonical Club'
    assert row['team_reference']['matches'][0]['database_index'] == 3  #688 is not ordinal.
    teams.append(dict(teams[0], database_index=5, owner_index=9))
    row = staff.decode_row(wire())
    RESOLVE_TEAMS(b'', [row])
    assert row['team_reference']['state'] == 'ambiguous_native_ID'
    assert row['team_reference']['display_name'] is None and len(row['team_reference']['matches']) == 2


def test_public_tool_read_schema():
    from fm_live_mcp import server
    assert callable(server.fm_get_saved_staff_history)
    assert server.fm_get_saved_staff_history.__annotations__['person_index']


def test_unproved_negative_owner_fails_closed(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='only -1 sentinel proved'):
        query(save(tmp_path, monkeypatch, owner=-2))
