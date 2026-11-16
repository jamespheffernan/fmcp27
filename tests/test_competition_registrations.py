import struct

import pytest

from fm_live_mcp import competition_registrations as registrations, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import bind, database_memory
from test_players import memory
from test_teams import team_memory
from test_world import world_memory


@pytest.fixture
def registration_memory(team_memory):
    m=team_memory
    # Native nation selection is controlled by team +2F.
    m['q'](m['owners'][0]+0xD8,m['geography']['nation'][0])
    m['put'](m['team_addresses'][1]+0x2F,b'\x01')
    addresses=[]
    for team,year,info in ((m['team_addresses'][0],0,-1),(m['team_addresses'][1],2025,100),
                          (0,65535,-128),(m['team_addresses'][0],2026,0)):
        a=m['allocate'](16);m['put'](a,struct.pack('<QHb',team,year,info));addresses.append(a)
    slots=[addresses[0],0,addresses[1],addresses[2],addresses[3],addresses[0]]
    m['vec'](m['competitions'][0]+0x18,slots)
    m.update(registration_addresses=addresses,registration_slots=slots)
    return m


def setup(bridge,monkeypatch,m):
    bind(bridge,monkeypatch,m)
    return bridge.find_competitions(bridge.session)['competitions'][0]['competition_ref']


def test_stored_fields_null_slots_duplicates_and_roster_references(bridge,monkeypatch,registration_memory):
    m=registration_memory;ref=setup(bridge,monkeypatch,m)
    result=bridge.get_competition_registrations(bridge.session,ref)
    assert result['complete_native_list'] and result['stop_reason']=='list_end'
    assert result['total_registration_slots']==result['scanned_slots']==6
    assert result['count']==5 and result['null_record_slots']==1
    rows=result['registrations']
    assert [r['registration_index'] for r in rows]==[0,2,3,4,5]
    assert [r['year'] for r in rows]==[None,2025,None,2026,None]
    assert [r['native_year_code'] for r in rows]==[0,2025,65535,2026,0]
    assert [r['registration_identifier'] for r in rows]==[None,100,None,0,None]
    assert rows[0]['registration_identifier_state']=='unspecified' and rows[1]['registration_identifier_state']=='stored'
    assert rows[2]['team'] is None and rows[2]['nation'] is None
    assert rows[0]['team']['native_id']==rows[-1]['team']['native_id']
    assert rows[0]['team']['team_ref']!=rows[-1]['team']['team_ref']
    for row in (rows[0],rows[1]):
        assert row['nation']['short_name']=='England'
        roster=bridge.get_team_squad(bridge.session,row['team']['team_ref'])
        assert roster['count']==1 and roster['team']['native_id']==row['team']['native_id']


def test_year_filter_paginates_empty_pages_and_binds_criteria(bridge,monkeypatch,registration_memory):
    m=registration_memory;ref=setup(bridge,monkeypatch,m)
    first=bridge.get_competition_registrations(bridge.session,ref,year=2025,record_budget=2)
    assert first['count']==0 and first['null_record_slots']==1 and first['next_index']==2
    assert first['next_cursor'] and first['stop_reason']=='record_budget'
    for kwargs in ({},{'year':2026}):
        with pytest.raises(BridgeError,match='different query'):
            bridge.get_competition_registrations(bridge.session,ref,cursor=first['next_cursor'],**kwargs)
    last=bridge.get_competition_registrations(bridge.session,ref,year=2025,cursor=first['next_cursor'])
    assert last['count']==1 and not last['complete_native_list'] and last['next_cursor'] is None
    assert last['registrations'][0]['year']==2025 and last['scanned_slots']==4
    page=bridge.get_competition_registrations(bridge.session,ref,max_matches=1)
    assert page['stop_reason']=='match_limit' and page['next_index']==1
    m['vec'](m['competitions'][0]+0x18,m['registration_slots'])
    with pytest.raises(BridgeError,match='cursor expired'):
        bridge.get_competition_registrations(bridge.session,ref,cursor=page['next_cursor'])


@pytest.mark.parametrize('zero_header',[False,True])
def test_empty_vector_is_verified_empty(bridge,monkeypatch,registration_memory,zero_header):
    m=registration_memory;ref=setup(bridge,monkeypatch,m)
    if zero_header:m['put'](m['competitions'][0]+0x18,bytes(24))
    else:m['vec'](m['competitions'][0]+0x18,[])
    result=bridge.get_competition_registrations(bridge.session,ref)
    assert result['complete_native_list'] and result['count']==result['scanned_slots']==0
    assert result['next_cursor'] is None


@pytest.mark.parametrize('year',[1,1899,2101,65534])
def test_native_year_values_outside_editor_range_are_preserved(registration_memory,year):
    m=registration_memory;a=m['registration_addresses'][0]
    m['put'](a+8,struct.pack('<H',year))
    row,_=registrations.record(m['read'],m['base'],a)
    assert row['year']==year and row['year_state']=='stored'


@pytest.mark.parametrize('kwargs',[{'year':0},{'year':65535},{'year':True},{'year':'2025'},
                                   {'max_matches':True},{'max_matches':101},{'record_budget':0},
                                   {'record_budget':1001},{'cursor':[]},{'cursor':''}])
def test_invalid_query_arguments(bridge,kwargs):
    with pytest.raises(BridgeError):bridge.get_competition_registrations(bridge.session,'bad',**kwargs)


@pytest.mark.parametrize('fault',['bounds','capacity','pointer','team_pointer','team_membership','nation_pointer','nation_type'])
def test_bad_records_reject_whole_page(bridge,monkeypatch,registration_memory,fault):
    m=registration_memory;ref=setup(bridge,monkeypatch,m);a=m['registration_addresses'][1]
    if fault=='bounds':m['q'](m['competitions'][0]+0x20,1)
    elif fault=='capacity':
        start=int.from_bytes(m['read'](m['competitions'][0]+0x18,8),'little')
        m['q'](m['competitions'][0]+0x28,start+(registrations.MAX_RECORDS+1)*8)
    elif fault=='pointer':m['vec'](m['competitions'][0]+0x18,[m['registration_addresses'][0],1])
    elif fault=='team_pointer':m['q'](a,1)
    elif fault=='team_membership':m['put'](m['team_addresses'][1]+8,struct.pack('<I',0))
    elif fault=='nation_pointer':m['q'](m['owners'][0]+0xD8,1)
    else:m['q'](m['owners'][0]+0xD8,m['club'])
    with pytest.raises(BridgeError):bridge.get_competition_registrations(bridge.session,ref)
    assert not bridge.team_refs and not bridge.database_cursors


@pytest.mark.parametrize('fault',['year','info','team','nation','vector','slot'])
def test_mutation_rejects_all_rows_and_refs(bridge,monkeypatch,registration_memory,fault):
    m=registration_memory;ref=setup(bridge,monkeypatch,m);original=registrations.record;calls=0
    def changing(*args,**kwargs):
        nonlocal calls
        row=original(*args,**kwargs);calls+=1
        if calls==2:
            a=m['registration_addresses'][0]
            if fault=='year':m['put'](a+8,struct.pack('<H',2020))
            elif fault=='info':m['put'](a+10,b'\x01')
            elif fault=='team':m['q'](a,0)
            elif fault=='nation':m['q'](m['owners'][0]+0xD8,0)
            elif fault=='vector':m['vec'](m['competitions'][0]+0x18,m['registration_slots'])
            else:
                start=int.from_bytes(m['read'](m['competitions'][0]+0x18,8),'little');m['q'](start,0)
        return row
    monkeypatch.setattr(registrations,'record',changing)
    with pytest.raises(BridgeError):bridge.get_competition_registrations(bridge.session,ref)
    assert not bridge.team_refs and not bridge.database_cursors


def test_native_nation_flag_selects_link_and_preserves_null(registration_memory):
    m=registration_memory;a=m['registration_addresses'][0];team=m['team_addresses'][0]
    # Use the exact nonzero test, including values other than one.
    m['put'](team+0x2F,b'\x02');m['q'](m['owners'][0]+0x170,0)
    row,_=registrations.record(m['read'],m['base'],a)
    assert row['nation'] is None
    m['q'](m['owners'][0]+0x170,m['geography']['nation'][1])
    row,_=registrations.record(m['read'],m['base'],a)
    assert row['nation']['short_name']=='France'


def test_year_filter_rechecks_excluded_record_predicate(bridge,monkeypatch,registration_memory):
    m=registration_memory;ref=setup(bridge,monkeypatch,m);original=registrations.record
    def changing(*args,**kwargs):
        result=original(*args,**kwargs)
        m['put'](m['registration_addresses'][0]+8,struct.pack('<H',2025))
        return result
    monkeypatch.setattr(registrations,'record',changing)
    with pytest.raises(BridgeError,match='changed during read'):
        bridge.get_competition_registrations(bridge.session,ref,year=2025)
    assert not bridge.team_refs
