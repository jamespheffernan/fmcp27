import struct

import pytest

from fm_live_mcp import fixtures, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import bind, database_memory
from test_players import memory
from test_teams import team_memory
from test_world import world_memory
from test_competition_stages import stage_memory
from test_stadiums import stadium_memory


@pytest.fixture
def fixture_memory(team_memory):
    m = team_memory
    def native(kind, size):
        rva, name = fixtures.TYPES[kind]
        a, ti, text = m['allocate'](size), m['allocate'](16), m['allocate'](len(name)+2)
        m['put'](text+1, name+b'\0')
        m['q'](ti+8, text+1)
        m['put'](m['base']+rva-16, struct.pack('<qQ', 0, ti))
        m['q'](a, m['base']+rva)
        return a
    root, store = native('root', 0x160), native('store', 0x50)
    m['q'](m['base']+0x56D57D0, root)
    m['q'](root+0x158, store)
    main = store+8
    groups = [m['allocate'](0xB78) for _ in range(3)]
    for g in groups[:2]:
        m['put'](g+0xB70, b'\x01')
    # This invalid pointer must never be followed in an unloaded group.
    m['q'](groups[2], 8)
    m['vec'](main+0x10, groups)
    m['put'](main+0x40, struct.pack('<H', 2030))
    archived, header = m['allocate'](0x48), m['allocate'](24)
    m['put'](archived+0x40, struct.pack('<H', 2025))
    m['vec'](header, [archived])
    m['q'](main+8, header)
    name = native('name', 0x48)
    m['put'](name+8, struct.pack('<III', 0, 900, 901))
    m['q'](name+0x18, m['competitions'][0])
    m['vec'](m['headers']['fixture_names'], [name])
    records = []
    for i in range(4):
        a = native('fixture' if i == 2 else 'result', 0x80)
        if i != 3:
            m['q'](a+8, m['team_addresses'][0])
            m['q'](a+16, m['team_addresses'][1])
            m['q'](a+0x20, name)
        m['put'](a+0x4C, struct.pack('<I', 2030 << 16 | (2 if i == 3 else 1)))
        m['put'](a+0x64, bytes([1, 2, 4, 5, 255, 1, 3, 5, 6, 255]))
        records.append(a)
    buckets = [m['allocate'](24) for _ in range(2)]
    m['vec'](buckets[0], records[:3])
    m['vec'](buckets[1], records[3:])
    m['q'](groups[0], buckets[0])
    m['q'](groups[1]+8, buckets[1])
    m.update(fixture_root=root, fixture_store=store, fixture_main=main, fixture_groups=groups,
             fixture_buckets=buckets, fixtures=records, fixture_name=name, fixture_archive=archived)
    return m


def query(bridge, monkeypatch, m, **kwargs):
    bind(bridge, monkeypatch, m)
    return bridge.find_fixtures(bridge.session, date_to='2030-01-02', **kwargs)


@pytest.fixture
def fixture_stadium_memory(fixture_memory, stadium_memory):
    assert fixture_memory is stadium_memory
    m = fixture_memory
    for index in range(3):
        m['q'](m['fixtures'][index]+0x28, m['stadium_addresses'][index])
    return m


def test_fixture_venues_open_details_and_refresh_names(bridge, monkeypatch, fixture_stadium_memory):
    m = fixture_stadium_memory
    rows = query(bridge, monkeypatch, m)['fixtures']
    assert rows[3]['stadium'] is None
    for index, row in enumerate(rows[:3]):
        venue = row['stadium']
        assert venue['native_id'] == 688+index
        detail = bridge.get_stadium(bridge.session, venue['stadium_ref'])['stadium']
        assert detail['name'] == venue['name'] and detail['capacities']['total']['value'] == 52305
    m['q'](m['stadium_addresses'][0]+0x40, m['text']('New stadium name'))
    fresh = bridge.get_fixture(bridge.session, rows[0]['fixture_ref'])['fixture']
    assert fresh['stadium']['name'] == 'New stadium name'
    assert bridge.get_stadium(bridge.session, fresh['stadium']['stadium_ref'])['stadium']['name'] == 'New stadium name'


@pytest.mark.parametrize('fault', ['pointer', 'id', 'duplicate_id', 'membership'])
def test_fixture_venue_identity_changes_expire_reference(bridge, monkeypatch, fixture_stadium_memory, fault):
    m = fixture_stadium_memory
    ref = query(bridge, monkeypatch, m)['fixtures'][0]['fixture_ref']
    if fault == 'pointer': m['q'](m['fixtures'][0]+0x28, m['stadium_addresses'][1])
    if fault == 'id': m['put'](m['stadium_addresses'][0]+12, struct.pack('<I', 123))
    if fault == 'duplicate_id': m['put'](m['stadium_addresses'][0]+16, struct.pack('<I', 123))
    if fault == 'membership': m['vec'](m['headers']['stadiums'], list(reversed(m['stadium_addresses'])))
    with pytest.raises(BridgeError): bridge.get_fixture(bridge.session, ref)
    assert ref not in bridge.fixture_refs


def test_malformed_fixture_venue_publishes_no_references(bridge, monkeypatch, fixture_stadium_memory):
    m = fixture_stadium_memory
    m['q'](m['fixtures'][1]+0x28, 8)
    with pytest.raises(BridgeError): query(bridge, monkeypatch, m)
    assert not any((bridge.fixture_refs, bridge.stadium_refs, bridge.team_refs, bridge.competition_refs))


def test_fixture_venue_cache_eviction_keeps_current_page(bridge, monkeypatch, fixture_stadium_memory):
    bridge.stadium_refs = {str(i): {} for i in range(10000)}
    rows = query(bridge, monkeypatch, fixture_stadium_memory)['fixtures']
    assert len(bridge.stadium_refs) == 3
    for row in rows[:3]:
        assert bridge.get_stadium(bridge.session, row['stadium']['stadium_ref'])['stadium']['native_id'] == row['stadium']['native_id']


@pytest.fixture
def fixture_stage_memory(fixture_memory, stage_memory):
    m = fixture_memory
    assert m is stage_memory
    for address in m['fixtures']:
        m['put'](address+0x30, struct.pack('<H', 2030))
    return m


def test_optional_fixture_stage_links_open_standings(bridge, monkeypatch, fixture_stage_memory):
    m = fixture_stage_memory
    basic = query(bridge, monkeypatch, m)
    assert 'stage_link' not in basic['fixtures'][0] and not bridge.stage_refs
    page = bridge.find_fixtures(bridge.session, date_to='2030-01-02', include_stage=True)
    link = page['fixtures'][0]['stage_link']
    assert link['state'] == 'decoded' and link['native_stage_index'] == 0
    assert link['fixture_season_code'] == link['runtime_season_code'] == 2030
    assert link['stage']['kind'] == 'league' and link['stage']['path'] == [0]
    assert bridge.get_standings(bridge.session, link['stage']['stage_ref'])['count'] == 3
    assert page['fixtures'][3]['stage_link']['state'] == 'no_competition'
    fresh = bridge.get_fixture(bridge.session, basic['fixtures'][0]['fixture_ref'], include_stage=True)
    assert fresh['fixture']['stage_link']['state'] == 'decoded'
    assert fresh['fixture']['fixture_ref'] == basic['fixtures'][0]['fixture_ref']


@pytest.mark.parametrize('index,state,kind', [(-1,'unassigned_stage',None), (127,'stage_index_out_of_range',None),
    (1,'null_stage_slot',None), (4,'empty_stage',None), (2,'decoded','group'),
    (3,'decoded','cup'), (5,'decoded','cup_group')])
def test_fixture_stage_states(bridge, monkeypatch, fixture_stage_memory, index, state, kind):
    m = fixture_stage_memory
    m['put'](m['fixtures'][0]+0x38, struct.pack('<b', index))
    row = query(bridge, monkeypatch, m, include_stage=True)['fixtures'][0]
    assert row['stage_link']['state'] == state
    if kind is None:
        assert row['stage_link']['stage'] is None
    else:
        stage = row['stage_link']['stage']
        assert stage['kind'] == kind and stage['path'] == [index]
        assert not stage['standings_available']
        with pytest.raises(BridgeError, match='no decoded league table'):
            bridge.get_standings(bridge.session, stage['stage_ref'])


@pytest.mark.parametrize('state', ['runtime_absent', 'different_season'])
def test_fixture_stage_unavailable_never_follows_invalid_stage_vector(bridge, monkeypatch, fixture_stage_memory, state):
    m = fixture_stage_memory
    m['put'](m['runtime']+0x1D8, struct.pack('<QQQ', 8, 16, 24))
    if state == 'runtime_absent':
        m['q'](m['competitions'][0]+0xB0, 0)
    else:
        m['put'](m['runtime']+0x3B0, struct.pack('<H', 2031))
    page = query(bridge, monkeypatch, m, include_stage=True)
    assert all(r['stage_link']['state'] == state for r in page['fixtures'][:3])
    assert not bridge.stage_refs


def test_fixture_stage_preserves_shared_runtime_owner(bridge, monkeypatch, fixture_stage_memory):
    m = fixture_stage_memory
    m['q'](m['fixture_name']+0x18, m['competitions'][1])
    row = query(bridge, monkeypatch, m, include_stage=True)['fixtures'][0]
    assert row['competition']['native_id'] == 101
    assert row['stage_link']['shared_runtime']
    assert row['stage_link']['runtime_competition']['native_id'] == 100
    table = bridge.get_standings(bridge.session, row['stage_link']['stage']['stage_ref'])
    assert table['shared_runtime'] and table['competition']['native_id'] == 101


def test_season_change_expires_stage_link_but_keeps_fixture(bridge, monkeypatch, fixture_stage_memory):
    m = fixture_stage_memory
    row = query(bridge, monkeypatch, m, include_stage=True)['fixtures'][0]
    m['put'](m['runtime']+0x3B0, struct.pack('<H', 2031))
    with pytest.raises(BridgeError, match='identity or membership changed'):
        bridge.get_standings(bridge.session, row['stage_link']['stage']['stage_ref'])
    fresh = bridge.get_fixture(bridge.session, row['fixture_ref'], include_stage=True)['fixture']
    assert fresh['stage_link']['state'] == 'different_season' and fresh['fixture_ref'] == row['fixture_ref']


def test_stage_season_change_during_query_publishes_nothing(bridge, monkeypatch, fixture_stage_memory):
    m = fixture_stage_memory
    bind(bridge, monkeypatch, m)
    original, calls = m['read'], 0
    def read(address, size):
        nonlocal calls
        if address == m['runtime']+0x3B0:
            calls += 1
            if calls == 2:
                m['put'](address, struct.pack('<H', 2031))
        return original(address, size)
    monkeypatch.setattr(bridge, '_read_memory', lambda p,a,n: read(a,n))
    with pytest.raises(BridgeError, match='changed during read'):
        bridge.find_fixtures(bridge.session, date_to='2030-01-02', include_stage=True)
    assert not bridge.fixture_refs and not bridge.stage_refs and not bridge.team_refs and not bridge.competition_refs


def test_stage_option_is_bound_to_fixture_cursor(bridge, monkeypatch, fixture_stage_memory):
    page = query(bridge, monkeypatch, fixture_stage_memory, include_stage=True, max_matches=1)
    with pytest.raises(BridgeError, match='different query'):
        bridge.find_fixtures(bridge.session, date_to='2030-01-02', cursor=page['next_cursor'])


@pytest.mark.parametrize('route', ['search', 'readback'])
def test_fixture_stage_cache_limit_keeps_new_references_usable(bridge, monkeypatch, fixture_stage_memory, route):
    basic = query(bridge, monkeypatch, fixture_stage_memory)
    bridge.stage_refs = {str(i): {} for i in range(10000)}
    if route == 'search':
        row = bridge.find_fixtures(bridge.session, date_to='2030-01-02', include_stage=True)['fixtures'][0]
    else:
        row = bridge.get_fixture(bridge.session, basic['fixtures'][0]['fixture_ref'], include_stage=True)['fixture']
    assert len(bridge.stage_refs) <= 3
    assert bridge.get_standings(bridge.session, row['stage_link']['stage']['stage_ref'])['count'] == 3


@pytest.mark.parametrize('value', [1, 'true', None])
def test_fixture_stage_option_requires_boolean(bridge, value):
    with pytest.raises(BridgeError, match='boolean'):
        bridge.find_fixtures(bridge.session, include_stage=value)
    with pytest.raises(BridgeError, match='boolean'):
        bridge.get_fixture(bridge.session, 'anything', include_stage=value)


@pytest.mark.parametrize('code,clock,state', [
    (0, None, 'no_time_code'), (1, '06:00', 'decoded'), (4, '06:45', 'decoded'),
    (5, '07:00', 'decoded'), (27, '12:30', 'decoded'), (37, '15:00', 'decoded'),
    (57, '20:00', 'decoded'), (72, '23:45', 'decoded'),
    (73, None, 'unmapped_time_code'), (126, None, 'unmapped_time_code'),
    (127, '17:55', 'decoded'),
])
def test_kickoff_codes_through_query_and_readback(bridge, monkeypatch, fixture_memory, code, clock, state):
    m = fixture_memory
    m['put'](m['fixtures'][0]+0x4C, struct.pack('<I', 2030 << 16 | code << 9 | 1))
    row = query(bridge, monkeypatch, m)['fixtures'][0]
    assert row['date'] == '2030-01-01'
    assert row['kickoff_time'] == {'time': clock, 'state': state, 'native_code': code, 'timezone': None}
    fresh = bridge.get_fixture(bridge.session, row['fixture_ref'])['fixture']
    assert fresh['kickoff_time'] == row['kickoff_time']


def test_unset_native_date_does_not_invent_kickoff():
    assert fixtures.kickoff_time(1900 << 16 | 37 << 9 | 1) == {
        'time': None, 'state': 'unset_date', 'native_code': 37, 'timezone': None}


def test_rescheduled_time_expires_fixture_reference(bridge, monkeypatch, fixture_memory):
    m = fixture_memory
    row = query(bridge, monkeypatch, m)['fixtures'][0]
    m['put'](m['fixtures'][0]+0x4C, struct.pack('<I', 2030 << 16 | 37 << 9 | 1))
    with pytest.raises(BridgeError, match='identity'):
        bridge.get_fixture(bridge.session, row['fixture_ref'])


@pytest.mark.parametrize('year,day,expected', [(2029,365,1), (2030,1,0), (2030,2,-1),
                                            (2031,1,-365), (2028,60,672)])
def test_fixture_relative_days_follow_current_date(bridge, monkeypatch, fixture_memory, year, day, expected):
    m = fixture_memory
    m['put'](m['base']+world.CURRENT_DATE, struct.pack('<I', year << 16 | day))
    page = query(bridge, monkeypatch, m)
    row = page['fixtures'][0]
    assert row['days_from_current_date'] == expected
    assert page['save']['last_saved_date'] == '2030-09-18'
    assert bridge.get_fixture(bridge.session, row['fixture_ref'])['fixture']['days_from_current_date'] == expected


def test_fixture_reference_survives_date_progression_and_refreshes_relative_days(bridge, monkeypatch, fixture_memory):
    m = fixture_memory
    page = query(bridge, monkeypatch, m)
    row = page['fixtures'][0]
    m['put'](m['base']+world.CURRENT_DATE, struct.pack('<I', 2030 << 16 | 263))
    fresh = bridge.get_fixture(bridge.session, row['fixture_ref'])
    assert fresh['save']['current_date'] == '2030-09-20'
    assert fresh['fixture']['fixture_ref'] == row['fixture_ref']
    assert fresh['fixture']['days_from_current_date'] == row['days_from_current_date']-1


def test_date_changes_during_fixture_query_publish_no_references(bridge, monkeypatch, fixture_memory):
    m = fixture_memory
    bind(bridge, monkeypatch, m)
    calls, original = 0, m['read']
    def read(address, size):
        nonlocal calls
        if address == m['base']+world.CURRENT_DATE:
            calls += 1
            if calls == 3:
                m['put'](address, struct.pack('<I', 2030 << 16 | 263))
        return original(address, size)
    monkeypatch.setattr(bridge, '_read_memory', lambda p,a,n: read(a,n))
    with pytest.raises(BridgeError, match='changed during read'):
        bridge.find_fixtures(bridge.session, date_to='2030-01-02')
    assert not bridge.fixture_refs and not bridge.team_refs and not bridge.competition_refs


def test_dates_scores_links_and_roster_references(bridge, monkeypatch, fixture_memory):
    result = query(bridge, monkeypatch, fixture_memory)
    assert result['count'] == 4 and result['next_cursor'] is None
    assert result['coverage']['unavailable_group_indices'] == [2]
    assert [r['date'] for r in result['fixtures']] == ['2030-01-01']*3+['2030-01-02']
    first = result['fixtures'][0]
    assert first['scores'] == {'normal_time': {'home': 1, 'away': 1},
        'extra_time': {'home': 2, 'away': 3}, 'penalties': {'home': 4, 'away': 5},
        'aggregate': {'home': 5, 'away': 6}, 'final_score': {'home': 2, 'away': 3}}
    assert result['fixtures'][2]['scores'] is None
    assert result['fixtures'][3]['home_team'] is None and result['fixtures'][3]['competition'] is None
    for field in ('home_team', 'away_team'):
        roster = bridge.get_team_squad(bridge.session, first[field]['team_ref'])
        assert roster['count'] == 1
    comp = bridge.get_competition(bridge.session, first['competition']['competition_ref'])
    assert comp['competition']['native_id'] == 100
    fresh = bridge.get_fixture(bridge.session, first['fixture_ref'])['fixture']
    assert fresh['scores'] == first['scores'] and fresh['fixture_ref'] == first['fixture_ref']
    assert fresh['home_team']['team_ref'] != first['home_team']['team_ref']


def test_coverage_distinguishes_absent_unloaded_and_empty_years(bridge, monkeypatch, fixture_memory):
    m = fixture_memory
    bind(bridge, monkeypatch, m)
    coverage = bridge.get_fixture_coverage(bridge.session)
    assert coverage['main_year'] == 2030
    assert [r['year'] for r in coverage['years']] == [2030, 2025]
    assert coverage['years'][0]['loaded_group_count'] == 2
    empty = bridge.find_fixtures(bridge.session, year=2025)
    assert empty['count'] == 0 and empty['reached_resident_range_end']
    with pytest.raises(BridgeError, match='no resident'):
        bridge.find_fixtures(bridge.session, year=2027)


@pytest.mark.parametrize('limit', ['max_matches', 'record_budget', 'bucket_budget'])
def test_pagination_is_lossless_including_empty_pages(bridge, monkeypatch, fixture_memory, limit):
    m = fixture_memory
    first = query(bridge, monkeypatch, m, **{limit: 1})
    rows = list(first['fixtures'])
    cursor = first['next_cursor']
    pages = 1
    while cursor:
        page = bridge.find_fixtures(bridge.session, date_to='2030-01-02', cursor=cursor, **{limit: 1})
        rows.extend(page['fixtures'])
        cursor = page['next_cursor']
        pages += 1
        assert pages <= 8
    assert len(rows) == 4 and rows[-1]['date'] == '2030-01-02'
    assert [r['record_kind'] for r in rows] == ['result_record', 'result_record', 'fixture_record', 'result_record']


@pytest.mark.parametrize('filters,count', [({'team_native_id': 50}, 3), ({'team_native_id': 51}, 3),
    ({'competition_native_id': 100}, 3), ({'record_kind': 'fixture'}, 1), ({'record_kind': 'result'}, 3),
    ({'record_kind': 'result', 'competition_native_id': 100}, 2), ({'team_native_id': 999}, 0),
    ({'date_from': '2030-01-02'}, 1)])
def test_filters_combine(bridge, monkeypatch, fixture_memory, filters, count):
    assert query(bridge, monkeypatch, fixture_memory, **filters)['count'] == count


@pytest.mark.parametrize('fault', ['type', 'date', 'rtti', 'team_membership', 'name_membership',
    'competition_membership', 'bucket_bounds', 'group_pointer', 'duplicate_year', 'duplicate_manager'])
def test_malformed_state_fails_without_partial_results_or_refs(bridge, monkeypatch, fixture_memory, fault):
    m = fixture_memory
    if fault == 'type': m['q'](m['fixtures'][1], 4096)
    elif fault == 'date': m['put'](m['fixtures'][1]+0x4C, struct.pack('<I', 2030 << 16 | 2))
    elif fault == 'rtti': m['q'](m['base']+fixtures.TYPES['result'][0]-16, 8)
    elif fault == 'team_membership': m['vec'](m['headers']['teams'], list(reversed(m['team_addresses'])))
    elif fault == 'name_membership': m['vec'](m['headers']['fixture_names'], [m['club']])
    elif fault == 'competition_membership': m['vec'](m['headers']['competitions'], list(reversed(m['competitions'])))
    elif fault == 'bucket_bounds': m['put'](m['fixture_buckets'][0], struct.pack('<QQQ', 4096, 4095, 8192))
    elif fault == 'group_pointer': m['q'](m['fixture_groups'][0], 8)
    elif fault == 'duplicate_year': m['put'](m['fixture_archive']+0x40, struct.pack('<H', 2030))
    else:
        h = m['allocate'](24);m['vec'](h, [m['fixture_main']]);m['q'](m['fixture_main'],h)
    with pytest.raises(BridgeError): query(bridge, monkeypatch, m)
    assert not bridge.fixture_refs and not bridge.team_refs and not bridge.competition_refs


@pytest.mark.parametrize('fault', ['criteria', 'inventory', 'bucket_reorder', 'bucket_reallocation'])
def test_cursor_rejects_changed_query_and_membership(bridge, monkeypatch, fixture_memory, fault):
    m = fixture_memory
    first = query(bridge, monkeypatch, m, max_matches=1)
    kw = {}
    if fault == 'criteria': kw['team_native_id'] = 50
    elif fault == 'inventory': m['put'](m['fixture_groups'][2]+0xB70, b'\x01')
    elif fault == 'bucket_reorder':
        a = int.from_bytes(m['read'](m['fixture_buckets'][0],8),'little')
        m['q'](a+8,m['fixtures'][2]);m['q'](a+16,m['fixtures'][1])
    else: m['vec'](m['fixture_buckets'][0],m['fixtures'][:3])
    with pytest.raises(BridgeError):
        bridge.find_fixtures(bridge.session,date_to='2030-01-02',cursor=first['next_cursor'],**kw)


@pytest.mark.parametrize('fault', ['identity', 'bucket', 'name', 'team_id', 'detach'])
def test_reference_rejects_reused_or_changed_records(bridge, monkeypatch, fixture_memory, fault):
    m = fixture_memory
    ref = query(bridge, monkeypatch, m)['fixtures'][0]['fixture_ref']
    if fault == 'identity':m['put'](m['fixtures'][0]+0x30,b'\x01')
    elif fault == 'bucket':m['vec'](m['fixture_buckets'][0],m['fixtures'][1:3])
    elif fault == 'name':m['put'](m['fixture_name']+12,struct.pack('<I',902))
    elif fault == 'team_id':m['put'](m['team_addresses'][0]+12,struct.pack('<I',888))
    else:bridge.detach()
    with pytest.raises(BridgeError):bridge.get_fixture(bridge.session,ref)
    assert ref not in bridge.fixture_refs


def test_missing_score_categories_and_partial_pairs_stay_explicit(bridge, monkeypatch, fixture_memory):
    m = fixture_memory
    m['put'](m['fixtures'][0]+0x64,bytes([3,255,255,255,255,255,2,4,255,255]))
    s=query(bridge,monkeypatch,m)['fixtures'][0]['scores']
    assert s['normal_time']=={'home':3,'away':None}
    assert s['penalties']=={'home':None,'away':4}
    assert s['aggregate']=={'home':None,'away':None}
    assert s['final_score']=={'home':3,'away':2}


def test_score_refresh_keeps_reference_when_identity_is_unchanged(bridge, monkeypatch, fixture_memory):
    m=fixture_memory;ref=query(bridge,monkeypatch,m)['fixtures'][0]['fixture_ref']
    m['put'](m['fixtures'][0]+0x65,b'\x04')
    assert bridge.get_fixture(bridge.session,ref)['fixture']['scores']['final_score']['home']==4


def test_mutation_during_consumed_byte_recheck_publishes_nothing(bridge,monkeypatch,fixture_memory):
    m=fixture_memory;bind(bridge,monkeypatch,m);calls=0
    original=m['read'];target=m['fixtures'][1]
    def read(address,size):
        nonlocal calls
        if address==target and size==0x58:
            calls+=1
            if calls==2:m['put'](target+0x30,b'\x01')
        return original(address,size)
    monkeypatch.setattr(bridge,'_read_memory',lambda p,a,n:read(a,n))
    with pytest.raises(BridgeError,match='changed during read'):
        bridge.find_fixtures(bridge.session,date_to='2030-01-02')
    assert not bridge.fixture_refs and not bridge.team_refs and not bridge.competition_refs


@pytest.mark.parametrize('kwargs', [{'year':True},{'year':10000},{'team_native_id':False},
    {'competition_native_id':0},{'record_budget':0},{'bucket_budget':4097},{'max_matches':101},
    {'record_kind':'completed'},{'cursor':''},{'date_from':'2030-1-1'},
    {'date_from':'20300101'},{'date_from':'2029-01-01'},{'date_from':'2030-02-30'},
    {'date_from':'2030-02-01','date_to':'2030-01-01'}])
def test_invalid_query_inputs_fail(bridge,monkeypatch,fixture_memory,kwargs):
    bind(bridge,monkeypatch,fixture_memory)
    with pytest.raises(BridgeError):bridge.find_fixtures(bridge.session,**kwargs)


@pytest.fixture
def fixture_names_memory(fixture_memory):
    from fm_live_mcp import stage_names
    m = fixture_memory
    names = []
    for index, text in enumerate(('League Phase', 'Third Round', 'Second Leg')):
        address = m['typed']('stage_name', 0x40)
        m['put'](address+8, struct.pack('<II', index, 2000000000+index))
        m['q'](address+0x18, m['text'](text))
        names.append(address)
    m['q'](m['base']+world.TYPES['stage_name'][0]+24, m['base']+stage_names.PROPERTY_GETTER)
    m['vec'](m['headers']['stage_names'], names)
    for offset, address in zip((0x20, 0x28, 0x30), names):
        m['q'](m['fixture_name']+offset, address)
    m['stage_name_addresses'] = names
    return m


def test_fixture_names_preserve_three_slots_secondary_competition_and_readback(bridge, monkeypatch, fixture_names_memory):
    m = fixture_names_memory
    m['q'](m['fixture_name']+0x40, m['competitions'][1])
    page = query(bridge, monkeypatch, m)
    row = page['fixtures'][0]
    name = row['fixture_name']
    assert name['native_id'] == 900 and name['database_index'] == 0
    assert name['name_source'] == 'stored_native_components'
    assert [n['name'] for n in name['stage_names']] == ['League Phase', 'Third Round', 'Second Leg']
    assert [n['native_id'] for n in name['stage_names']] == [2000000000, 2000000001, 2000000002]
    assert all(n['short_name'] is None and n['plural_name'] is None for n in name['stage_names'])
    assert name['secondary_competition']['database_index'] == 1
    assert bridge.get_fixture(bridge.session, row['fixture_ref'])['fixture']['fixture_name'] == name
    assert page['fixtures'][3]['fixture_name'] is None


def test_fixture_name_missing_components_are_explicit(bridge, monkeypatch, fixture_memory):
    rows = query(bridge, monkeypatch, fixture_memory)['fixtures']
    assert rows[0]['fixture_name']['stage_names'] == [None, None, None]
    assert rows[0]['fixture_name']['secondary_competition'] is None
    assert rows[3]['fixture_name'] is None


def test_stage_names_keep_empty_unicode_unaligned_and_plural_strings(bridge, monkeypatch, fixture_names_memory):
    m = fixture_names_memory
    address = m['stage_name_addresses'][0]
    value = 'Éliminatoires 女子'
    encoded = value.encode()
    pointer = m['allocate'](len(encoded)+6)+1
    m['put'](pointer, struct.pack('<I',len(encoded))+encoded+b'\0')
    m['q'](address+0x18, pointer)
    m['q'](address+0x20, m['text'](''))
    m['q'](address+0x28, m['text']('Qualifying rounds'))
    name = query(bridge, monkeypatch, m)['fixtures'][0]['fixture_name']['stage_names'][0]
    assert (name['name'], name['short_name'], name['plural_name']) == (value, '', 'Qualifying rounds')


@pytest.mark.parametrize('fault', ['pointer', 'type', 'rtti', 'getter', 'index', 'id', 'membership',
                                   'string_length', 'string_terminator', 'empty_terminator', 'control', 'utf8',
                                   'secondary_membership', 'secondary_type'])
def test_bad_fixture_name_links_publish_nothing(bridge, monkeypatch, fixture_names_memory, fault):
    m = fixture_names_memory
    address = m['stage_name_addresses'][0]
    vt = m['base']+world.TYPES['stage_name'][0]
    if fault == 'pointer': m['q'](m['fixture_name']+0x20, 9)
    if fault == 'type': m['q'](address, m['base']+world.TYPES['club'][0])
    if fault == 'rtti': m['q'](vt-16, 8)
    if fault == 'getter': m['q'](vt+24, 0)
    if fault == 'index': m['put'](address+8, struct.pack('<I', 999))
    if fault == 'id': m['put'](address+12, bytes(4))
    if fault == 'membership': m['vec'](m['headers']['stage_names'], list(reversed(m['stage_name_addresses'])))
    if fault.startswith('string_') or fault in ('empty_terminator', 'control', 'utf8'):
        pointer = m['text']('valid')
        m['q'](address+0x18, pointer)
        if fault == 'string_length': m['put'](pointer, struct.pack('<I', 513))
        if fault == 'string_terminator': m['put'](pointer+9, b'x')
        if fault == 'empty_terminator': m['put'](pointer, bytes(4)+b'x')
        if fault == 'control': m['put'](pointer+4, b'\n')
        if fault == 'utf8': m['put'](pointer+4, b'\xff')
    if fault.startswith('secondary_'):
        other = m['allocate'](0x200)
        m['put'](other, m['read'](m['competitions'][1], 20))
        m['q'](m['fixture_name']+0x40, other)
        if fault == 'secondary_type':
            m['q'](m['fixture_name']+0x40, m['club'])
    with pytest.raises(BridgeError): query(bridge, monkeypatch, m)
    assert not bridge.fixture_refs and not bridge.team_refs and not bridge.competition_refs


@pytest.mark.parametrize('offset', [0x20, 0x28, 0x30, 0x40])
def test_changed_fixture_name_components_expire_fixture_reference(bridge, monkeypatch, fixture_names_memory, offset):
    m = fixture_names_memory
    row = query(bridge, monkeypatch, m)['fixtures'][0]
    m['q'](m['fixture_name']+offset, m['competitions'][1] if offset == 0x40 else 0)
    with pytest.raises(BridgeError, match='identity changed'):
        bridge.get_fixture(bridge.session, row['fixture_ref'])


def test_stage_name_text_can_refresh_without_replacing_fixture(bridge, monkeypatch, fixture_names_memory):
    m = fixture_names_memory
    row = query(bridge, monkeypatch, m)['fixtures'][0]
    m['q'](m['stage_name_addresses'][0]+0x18, m['text']('Updated stage'))
    fresh = bridge.get_fixture(bridge.session, row['fixture_ref'])['fixture']
    assert fresh['fixture_name']['stage_names'][0]['name'] == 'Updated stage'
    assert fresh['fixture_ref'] == row['fixture_ref']


def test_stage_name_mutation_during_recheck_publishes_nothing(bridge, monkeypatch, fixture_names_memory):
    m = fixture_names_memory
    bind(bridge, monkeypatch, m)
    target = m['stage_name_addresses'][0]+0x18
    hits = 0
    def read(a,n):
        nonlocal hits
        if (a,n) == (target,8):
            hits += 1
            if hits == 2: m['q'](target, m['text']('Changed during query'))
        return m['read'](a,n)
    monkeypatch.setattr(bridge, '_read_memory', lambda p,a,n: read(a,n))
    with pytest.raises(BridgeError, match='changed during read'):
        bridge.find_fixtures(bridge.session, date_to='2030-01-02')
    assert not bridge.fixture_refs and not bridge.team_refs and not bridge.competition_refs


def test_selector_prefilter_matches_full_selected_rows(bridge, monkeypatch, fixture_memory):
    m=fixture_memory
    # Select using the canonical identity returned by the ordinary query.
    rows=query(bridge,monkeypatch,m)['fixtures']
    team_id=rows[0]['home_team']['native_id']
    ordinary=query(bridge,monkeypatch,m,team_native_id=team_id,record_kind='result')
    fast=query(bridge,monkeypatch,m,team_native_id=team_id,record_kind='result',selector_prefilter=True)
    assert len(ordinary['fixtures'])==len(fast['fixtures'])==2
    # Ref tokens are session observations, while selected native identities agree.
    for first,second in zip(ordinary['fixtures'],fast['fixtures']):
        assert first['date']==second['date']
        assert first['scores']==second['scores']
        assert first['home_team']['native_id']==second['home_team']['native_id']
    assert ordinary['scanned_records']==fast['scanned_records']


def test_prefilter_still_validates_selected_venue(bridge, monkeypatch, fixture_stadium_memory):
    m=fixture_stadium_memory
    m['q'](m['stadiums'][0] if 'stadiums' in m else m['stadium_addresses'][0],0)
    with pytest.raises(BridgeError):
        query(bridge,monkeypatch,m,selector_prefilter=True)


def test_ordered_match_filter_checks_type_and_date_before_skipping_other_teams(fixture_memory):
    m = fixture_memory
    address = m['fixtures'][0]
    read, base = m['read'], m['base']
    teams = tuple(m['team_addresses'][:2])
    assert fixtures.record(read, base, address, 2030, 1, {}, ordered_team_addresses=teams)['teams'] == teams
    assert fixtures.record(read, base, address, 2030, 1, {}, ordered_team_addresses=teams[::-1]) == {'filter_match': False}
    with pytest.raises(ValueError, match='date disagrees'):
        fixtures.record(read, base, address, 2030, 2, {}, ordered_team_addresses=teams[::-1])
    m['q'](address, 0)
    with pytest.raises(ValueError, match='Unsupported fixture record'):
        fixtures.record(read, base, address, 2030, 1, {}, ordered_team_addresses=teams[::-1])
