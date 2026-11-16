import struct

import pytest

from fm_live_mcp import competition_stages as stages, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import bind, database_memory
from test_players import memory
from test_teams import team_memory
from test_world import world_memory


@pytest.fixture
def stage_memory(team_memory):
    m = team_memory
    def native(expected, size):
        rva, name = expected
        a, ti, text = m['allocate'](size), m['allocate'](16), m['allocate'](len(name)+2)
        # RTTI text need not be aligned.
        m['put'](text+1, name+b'\0')
        m['q'](ti+8, text+1)
        m['put'](m['base']+rva-16, struct.pack('<qQ', 0, ti))
        m['q'](a, m['base']+rva)
        return a
    rva = next(iter(stages.RUNTIME_TYPES))
    runtime = native((rva, stages.RUNTIME_TYPES[rva]), 0x3C0)
    m['put'](runtime+0x3B0, struct.pack('<H', 2030))
    m['q'](runtime+0x138, m['competitions'][0])
    for comp in m['competitions']:
        m['q'](comp+0xB0, runtime)
    objects = {}
    for kind, expected in stages.STAGE_TYPES.items():
        a = native(expected, 0x110)
        m['q'](a+0x70, m['competitions'][0])
        m['put'](a+0x48, b'identity')
        objects[kind] = a
    league = objects['league']
    settings = native(stages.SETTINGS, 0xA0)
    m['q'](league+0xF0, settings)
    m['put'](settings+0x98, struct.pack('<6b', 3, 0, 2, 1, 0, 1))
    rows = []
    for index, team in enumerate([*m['team_addresses'][:2], 0]):
        a = m['allocate'](0xF8)
        m['q'](a+0x88, team)
        m['put'](a+0xF7, bytes([index]))
        for offset, values in ((0, (9, 4, -2, 4, 2, 1, 0, 1)),
                               (0x18, (5, 0, 3, 1, 1, 0, 0, 0)),
                               (0x30, (4, 4, 3, 3, 1, 1, 0, 1))):
            gf, ga, pts, played, win, draw, loss, pens = values
            m['put'](a+offset+8, struct.pack('<hhhbb4b', gf, ga, pts, played, 0, win, draw, loss, pens))
        rows.append(a)
    m['vec'](league+0xC0, rows)
    m['put'](league+0x100, b'\x03\x00')
    m['vec'](objects['group']+0xD0, [league])
    slots = [league, 0, objects['group'], objects['cup'], objects['empty'], objects['cup_group']]
    m['vec'](runtime+0x1D8, slots)
    m.update(runtime=runtime, stages=objects, stage_slots=slots, league_rows=rows, settings=settings)
    return m


def setup(bridge, monkeypatch, m, index=0):
    bind(bridge, monkeypatch, m)
    ref = bridge.find_competitions(bridge.session)['competitions'][index]['competition_ref']
    return ref, bridge.get_competition_stages(bridge.session, ref)


def test_aliases_group_paths_null_slots_and_native_table(bridge, monkeypatch, stage_memory):
    m = stage_memory
    _, catalog = setup(bridge, monkeypatch, m, index=1)
    assert catalog['shared_runtime'] and catalog['runtime_competition']['native_id'] == 100
    assert catalog['competition']['native_id'] == 101
    assert catalog['count'] == 7 and catalog['league_table_count'] == 2
    assert [s['path'] for s in catalog['stages']] == [[0], [1], [2], [3], [4], [5], [2, 0]]
    assert catalog['stages'][1]['stage_ref'] is None
    assert catalog['stages'][5]['contents_state'] == 'not_decoded'
    for stage in (catalog['stages'][0], catalog['stages'][-1]):
        result = bridge.get_standings(bridge.session, stage['stage_ref'])
        assert result['shared_runtime'] and result['ordering'] == 'native_stored_overall'
        assert result['count'] == 3 and result['unassigned_team_rows'] == 1
        assert [r['position'] for r in result['rows']] == [1, 2, 3]
        first = result['rows'][0]
        assert first['overall'] == dict(played=4, wins=2, draws_or_penalty_wins=1,
            losses=0, penalty_losses=1, goals_for=9, goals_against=4, goal_difference=5, points=-2)
        assert first['home']['goals_for'] == 5 and first['away']['goals_for'] == 4
        assert result['point_rules']['penalty_win'] == 2
        assert result['point_rules']['penalty_loss'] == 1
        assert result['rows'][2]['team'] is None
        for row in result['rows'][:2]:
            roster = bridge.get_team_squad(bridge.session, row['team']['team_ref'])
            assert roster['team']['native_id'] == row['team']['native_id'] and roster['count'] == 1


@pytest.mark.parametrize('state', ['absent', 'empty', 'nulls'])
def test_absent_empty_and_null_stages_remain_distinct(bridge, monkeypatch, stage_memory, state):
    m = stage_memory
    if state == 'absent': m['q'](m['competitions'][0]+0xB0, 0)
    else: m['vec'](m['runtime']+0x1D8, [] if state == 'empty' else [0, 0])
    _, result = setup(bridge, monkeypatch, m)
    assert result['runtime_state'] == ('absent' if state == 'absent' else 'decoded')
    assert result['count'] == (2 if state == 'nulls' else 0)
    assert result['league_table_count'] == 0 and not bridge.stage_refs


def test_unknown_sort_view_never_claims_overall_positions(bridge, monkeypatch, stage_memory):
    m = stage_memory
    _, catalog = setup(bridge, monkeypatch, m)
    m['put'](m['stages']['league']+0x101, b'\x03')
    m['put'](m['league_rows'][0]+0xF7, b'\x02')
    result = bridge.get_standings(bridge.session, catalog['stages'][0]['stage_ref'])
    assert result['ordering'] == 'native_other_view_unmapped'
    assert result['native_order_view_code'] == 3
    assert all(row['position'] is None for row in result['rows'])


@pytest.mark.parametrize('kind', ['cup', 'empty', 'group', 'cup_group'])
def test_non_league_selection_rejects(bridge, monkeypatch, stage_memory, kind):
    _, catalog = setup(bridge, monkeypatch, stage_memory)
    ref = next(s['stage_ref'] for s in catalog['stages'] if s['kind'] == kind)
    with pytest.raises(BridgeError, match='no decoded league table'):
        bridge.get_standings(bridge.session, ref)
    assert not bridge.team_refs


@pytest.mark.parametrize('fault', ['runtime_type', 'runtime_rtti', 'runtime_displacement', 'owner',
    'vector_bounds', 'vector_pointer', 'stage_type', 'stage_rtti', 'backlink', 'group_cycle', 'group_child_type', 'limit'])
def test_bad_catalog_fails_without_publishing_refs(bridge, monkeypatch, stage_memory, fault):
    m = stage_memory
    runtime, league, group = m['runtime'], m['stages']['league'], m['stages']['group']
    if fault == 'runtime_type': m['q'](runtime, m['base']+1)
    elif fault in ('runtime_rtti', 'runtime_displacement'):
        vt = m['base']+next(iter(stages.RUNTIME_TYPES))
        if fault == 'runtime_displacement': m['q'](vt-16, 8)
        else:
            ti = int.from_bytes(m['read'](vt-8, 8), 'little')
            text = int.from_bytes(m['read'](ti+8, 8), 'little')
            m['put'](text, b'!')
    elif fault == 'owner': m['q'](runtime+0x138, m['club'])
    elif fault == 'vector_bounds': m['q'](runtime+0x1E8, 1)
    elif fault == 'vector_pointer': m['vec'](runtime+0x1D8, [3])
    elif fault == 'stage_type': m['q'](league, m['base']+1)
    elif fault == 'stage_rtti': m['q'](m['base']+stages.STAGE_TYPES['league'][0]-16, 8)
    elif fault == 'backlink': m['q'](league+0x70, m['competitions'][1])
    elif fault == 'group_cycle': m['vec'](group+0xD0, [group])
    elif fault == 'group_child_type': m['vec'](group+0xD0, [m['stages']['cup']])
    else:
        m['vec'](runtime+0x1D8, [group]*5)
        m['vec'](group+0xD0, [league]*256)
    with pytest.raises(BridgeError): setup(bridge, monkeypatch, m)
    assert not bridge.stage_refs and not bridge.team_refs


@pytest.mark.parametrize('fault', ['root_vector', 'runtime', 'tag', 'child_vector', 'stage_slot', 'owner_id'])
def test_stage_reference_binds_route_and_owner(bridge, monkeypatch, stage_memory, fault):
    m = stage_memory
    _, catalog = setup(bridge, monkeypatch, m)
    ref = catalog['stages'][-1]['stage_ref']
    if fault == 'root_vector': m['vec'](m['runtime']+0x1D8, m['stage_slots'])
    elif fault == 'runtime': m['q'](m['competitions'][0]+0xB0, 0)
    elif fault == 'tag': m['put'](m['stages']['league']+0x48, b'changed!')
    elif fault == 'child_vector': m['vec'](m['stages']['group']+0xD0, [m['stages']['league']])
    elif fault == 'stage_slot': m['vec'](m['stages']['group']+0xD0, [])
    else: m['put'](m['competitions'][0]+12, struct.pack('<II', 800, 800))
    with pytest.raises(BridgeError): bridge.get_standings(bridge.session, ref)
    assert not bridge.team_refs


@pytest.mark.parametrize('fault', ['settings', 'settings_type', 'row_count', 'row_null', 'row_bounds',
                                  'position', 'team_pointer', 'team_identity', 'team_membership'])
def test_bad_table_fails_without_publishing_team_refs(bridge, monkeypatch, stage_memory, fault):
    m = stage_memory
    _, catalog = setup(bridge, monkeypatch, m)
    league, row = m['stages']['league'], m['league_rows'][0]
    if fault == 'settings': m['q'](league+0xF0, 0)
    elif fault == 'settings_type': m['q'](m['settings'], 0)
    elif fault == 'row_count': m['put'](league+0x100, b'\x04')
    elif fault == 'row_null': m['vec'](league+0xC0, [0, *m['league_rows'][1:]])
    elif fault == 'row_bounds': m['q'](league+0xD0, 1)
    elif fault == 'position': m['put'](row+0xF7, b'\x02')
    elif fault == 'team_pointer': m['q'](row+0x88, 3)
    elif fault == 'team_identity': m['put'](m['team_addresses'][0]+12, bytes(4))
    else: m['vec'](m['headers']['teams'], list(reversed(m['team_addresses'])))
    with pytest.raises(BridgeError): bridge.get_standings(bridge.session, catalog['stages'][0]['stage_ref'])
    assert not bridge.team_refs


@pytest.mark.parametrize('target', ['points', 'position', 'runtime_vector'])
def test_consumed_byte_mutation_rejects_entire_table(bridge, monkeypatch, stage_memory, target):
    m = stage_memory
    _, catalog = setup(bridge, monkeypatch, m)
    address = {'points':m['league_rows'][0], 'position':m['league_rows'][0],
               'runtime_vector':m['runtime']+0x1D8}[target]
    original = m['read']; seen = 0
    def changing(a, n):
        nonlocal seen
        data = original(a, n)
        if a == address:
            seen += 1
            if seen == 2:
                changed = bytearray(data)
                changed[12 if target == 'points' else 0xF7 if target == 'position' else 0] ^= 1
                return bytes(changed)
        return data
    monkeypatch.setattr(bridge, '_read_memory', lambda p,a,n: changing(a,n))
    with pytest.raises(BridgeError, match='changed during read'):
        bridge.get_standings(bridge.session, catalog['stages'][0]['stage_ref'])
    assert not bridge.team_refs


def test_live_stat_changes_do_not_expire_stage_ref_and_detach_does(bridge, monkeypatch, stage_memory):
    m = stage_memory
    _, catalog = setup(bridge, monkeypatch, m)
    ref = catalog['stages'][0]['stage_ref']
    m['put'](m['league_rows'][0]+12, struct.pack('<h', 15))
    assert bridge.get_standings(bridge.session, ref)['rows'][0]['overall']['points'] == 15
    bridge.detach()
    assert not bridge.stage_refs
    with pytest.raises(BridgeError): bridge.get_standings('old', ref)


@pytest.mark.parametrize('ref', [None, [], '', 'invented'])
def test_invalid_stage_refs(bridge, ref):
    with pytest.raises(BridgeError): bridge.get_standings(bridge.session, ref)


def test_empty_table_retains_rules_without_invented_rows(bridge, monkeypatch, stage_memory):
    m = stage_memory
    m['vec'](m['stages']['league']+0xC0, [])
    m['put'](m['stages']['league']+0x100, b'\x00')
    _, catalog = setup(bridge, monkeypatch, m)
    result = bridge.get_standings(bridge.session, catalog['stages'][0]['stage_ref'])
    assert result['count'] == 0 and result['rows'] == []
    assert result['point_rules']['win'] == 3 and not bridge.team_refs


def test_duplicate_stages_and_null_group_child_keep_paths(bridge, monkeypatch, stage_memory):
    m = stage_memory
    m['vec'](m['stages']['group']+0xD0, [m['stages']['league'], 0, m['stages']['league']])
    _, catalog = setup(bridge, monkeypatch, m)
    children = catalog['stages'][-3:]
    assert [s['path'] for s in children] == [[2, 0], [2, 1], [2, 2]]
    assert children[1]['state'] == 'null_slot' and children[1]['stage_ref'] is None
    assert children[0]['stage_ref'] != children[2]['stage_ref']
    for child in (children[0], children[2]):
        assert bridge.get_standings(bridge.session, child['stage_ref'])['count'] == 3


def test_signed_native_goal_difference(bridge, monkeypatch, stage_memory):
    m = stage_memory
    m['put'](m['league_rows'][0]+8, struct.pack('<hh', 32767, -1))
    _, catalog = setup(bridge, monkeypatch, m)
    result = bridge.get_standings(bridge.session, catalog['stages'][0]['stage_ref'])
    assert result['rows'][0]['overall']['goal_difference'] == -32768


def test_catalog_mutation_publishes_no_stage_refs(bridge, monkeypatch, stage_memory):
    m = stage_memory
    bind(bridge, monkeypatch, m)
    ref = bridge.find_competitions(bridge.session)['competitions'][0]['competition_ref']
    original = m['read']; seen = 0
    def changing(a, n):
        nonlocal seen
        data = original(a, n)
        if a == m['stages']['league']+0x48:
            seen += 1
            if seen == 2: return b'changed!'
        return data
    monkeypatch.setattr(bridge, '_read_memory', lambda p,a,n: changing(a,n))
    with pytest.raises(BridgeError, match='changed during read'):
        bridge.get_competition_stages(bridge.session, ref)
    assert not bridge.stage_refs


def test_save_change_expires_stage_and_competition_references(bridge, monkeypatch, stage_memory):
    m = stage_memory
    _, catalog = setup(bridge, monkeypatch, m)
    session = bridge.session
    m['q'](m['save']+0x28, m['text']('Another career'))
    with pytest.raises(BridgeError, match='identity changed'):
        bridge.get_standings(session, catalog['stages'][0]['stage_ref'])
    assert bridge.session is None and not bridge.stage_refs and not bridge.competition_refs


@pytest.mark.parametrize('fault', ['negative_count', 'oversized_capacity'])
def test_table_limits_reject_invalid_native_storage(bridge, monkeypatch, stage_memory, fault):
    m = stage_memory
    _, catalog = setup(bridge, monkeypatch, m)
    league = m['stages']['league']
    if fault == 'negative_count': m['put'](league+0x100, b'\xff')
    else:
        start = int.from_bytes(m['read'](league+0xC0, 8), 'little')
        m['q'](league+0xD0, start+1025*8)
    with pytest.raises(BridgeError):
        bridge.get_standings(bridge.session, catalog['stages'][0]['stage_ref'])
    assert not bridge.team_refs
