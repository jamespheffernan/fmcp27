import struct

import pytest

from fm_live_mcp import teams, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import bind, database_memory
from test_players import memory
from test_teams import team_memory
from test_world import world_memory


def scan(m, *args):
    options = dict(zip(args[2::2], args[3::2]))
    start = int(options['--start-index']); maximum=int(options['--max-matches'])
    budget=int(options['--record-budget']);assignment=options['--team-assignment']
    selected=int(options['--competition']); info=teams.lookup(m['read'],m['base'])
    result=[];end=start;actual=national=unavailable=0
    while end < min(info['count'],start+budget) and len(result)<maximum:
        i=end;end+=1
        if i>=info['lookup_count']:unavailable+=1;continue
        row,binding=teams.by_index(m['read'],m['base'],i,info=info)
        actual+=1;national+=row['kind']=='national_team'
        pointer,_=teams.selection(m['read'],binding['address'],assignment)
        if pointer==selected and (assignment!='current' or binding['owner_address']):
            result.append({'address':hex(binding['address']),'database_index':i})
    return {'matches':result,'next_index':end,'scanned_records':end-start,
            'teams_examined':actual,'national_teams_examined':national,'lookup_unavailable_records':unavailable,
            'stop_reason':'table_end' if end==info['count'] else 'match_limit' if len(result)==maximum else 'record_budget'}


def setup(bridge,monkeypatch,m):
    bind(bridge,monkeypatch,m)
    monkeypatch.setattr(bridge,'_run',lambda *args:scan(m,*args))
    return bridge.find_competitions(bridge.session)['competitions'][0]['competition_ref']


def test_assignments_produce_usable_club_and_national_roster_refs(bridge,monkeypatch,team_memory):
    ref=setup(bridge,monkeypatch,team_memory)
    result=bridge.get_competition_teams(bridge.session,ref)
    assert result['count']==3 and result['complete_table_scan'] and result['next_cursor'] is None
    assert result['national_teams_examined']==1
    for row in result['teams']:
        roster=bridge.get_team_squad(bridge.session,row['team_ref'])
        assert roster['team']['native_id']==row['native_id']
        assert roster['count']==(0 if row['owner']['kind']=='league_body_club' else 1)
        if row['kind']=='national_team':
            assert roster['club'] is None and roster['team']['owner']['nation']['short_name']=='England'
        query=bridge.query_team_players(bridge.session,row['team_ref'])
        assert query['roster_count']==roster['count'] and query['team']==roster['team']
    next_=bridge.get_competition_teams(bridge.session,ref,assignment='next')
    assert all(r['used_current_assignment_fallback'] for r in next_['teams'])
    assert bridge.get_competition_teams(bridge.session,ref,assignment='secondary')['count']==0


def test_pagination_criteria_lookup_and_empty_pages(bridge,monkeypatch,team_memory):
    m=team_memory;ref=setup(bridge,monkeypatch,m)
    m['q'](m['team_addresses'][0]+0x50,0)
    first=bridge.get_competition_teams(bridge.session,ref,record_budget=1)
    assert first['count']==0 and first['next_index']==1 and first['next_cursor']
    with pytest.raises(BridgeError,match='different query'):
        bridge.get_competition_teams(bridge.session,ref,assignment='next',cursor=first['next_cursor'])
    last=bridge.get_competition_teams(bridge.session,ref,cursor=first['next_cursor'])
    assert last['count']==2 and last['next_cursor'] is None and not last['complete_table_scan']
    m['put'](m['base']+teams.LOOKUP_MODE,b'\x03');m['put'](m['roots']['teams']+0x68,bytes(24))
    with pytest.raises(BridgeError,match='cursor expired'):
        bridge.get_competition_teams(bridge.session,ref,cursor=first['next_cursor'])
    empty=bridge.get_competition_teams(bridge.session,ref)
    assert empty['count']==0 and empty['lookup_unavailable_records']==3 and empty['complete_table_scan']


@pytest.mark.parametrize('kwargs',[{'assignment':[]},{'assignment':'unknown'},{'max_matches':True},
                                   {'max_matches':101},{'record_budget':0},{'record_budget':200001},
                                   {'cursor':[]},{'cursor':''}])
def test_invalid_arguments(bridge,kwargs):
    with pytest.raises(BridgeError):bridge.get_competition_teams(bridge.session,'bad',**kwargs)


@pytest.mark.parametrize('change',[{'next_index':0},{'scanned_records':True},{'national_teams_examined':4},
                                   {'teams_examined':True},{'lookup_unavailable_records':1},
                                   {'stop_reason':'record_budget'},{'matches':[{'address':'0x1000','database_index':True}]},
                                   {'matches':[{'address':'0x1000','database_index':3}]}])
def test_bad_native_receipts_never_publish_refs(bridge,monkeypatch,team_memory,change):
    m=team_memory;ref=setup(bridge,monkeypatch,m)
    monkeypatch.setattr(bridge,'_run',lambda *args:{**scan(m,*args),**change})
    with pytest.raises(BridgeError):bridge.get_competition_teams(bridge.session,ref)
    assert not bridge.team_refs


@pytest.mark.parametrize('fault',['assignment','mode','team_vector','owner_backlink','competition_id'])
def test_changes_during_scan_reject_all_results(bridge,monkeypatch,team_memory,fault):
    m=team_memory;ref=setup(bridge,monkeypatch,m)
    def changing(*args):
        receipt=scan(m,*args)
        if fault=='assignment':m['q'](m['team_addresses'][0]+0x50,0)
        elif fault=='mode':m['put'](m['base']+teams.LOOKUP_MODE,b'\x00')
        elif fault=='team_vector':m['vec'](m['headers']['teams'],m['team_addresses'])
        elif fault=='owner_backlink':m['vec'](m['owners'][0]+0x18,[m['team']])
        else:m['put'](m['competitions'][0]+12,struct.pack('<II',999,999))
        return receipt
    monkeypatch.setattr(bridge,'_run',changing)
    with pytest.raises(BridgeError):bridge.get_competition_teams(bridge.session,ref)
    assert not bridge.team_refs and not bridge.database_cursors


@pytest.mark.parametrize('fault',['identity','random_id','owner','owner_identity','membership'])
def test_stale_team_references_evicted(bridge,monkeypatch,team_memory,fault):
    m=team_memory;ref=setup(bridge,monkeypatch,m)
    result=bridge.get_competition_teams(bridge.session,ref)
    team_ref=result['teams'][1]['team_ref'];a=m['team_addresses'][1]
    if fault=='identity':m['put'](a+12,struct.pack('<I',999))
    elif fault=='random_id':m['put'](a+16,struct.pack('<I',999))
    elif fault=='owner':m['q'](a+0x30,0)
    elif fault=='owner_identity':m['put'](m['owners'][1]+16,struct.pack('<I',999))
    else:m['vec'](m['headers']['teams'],[m['team_addresses'][1],m['team_addresses'][0],m['team_addresses'][2]])
    with pytest.raises(BridgeError):bridge.get_team_squad(bridge.session,team_ref)
    assert team_ref not in bridge.team_refs


def test_assignment_may_change_after_reference_without_changing_team_identity(bridge,monkeypatch,team_memory):
    m=team_memory;ref=setup(bridge,monkeypatch,m)
    team_ref=bridge.get_competition_teams(bridge.session,ref)['teams'][0]['team_ref']
    m['q'](m['team_addresses'][0]+0x50,m['competitions'][1])
    assert bridge.get_team_squad(bridge.session,team_ref)['count']==1


def test_unaligned_stored_name(bridge,monkeypatch,team_memory):
    m=team_memory;ref=setup(bridge,monkeypatch,m)
    a=m['allocate'](32)+1;data=b'Unaligned';m['put'](a,struct.pack('<I',len(data))+data+b'\0')
    m['q'](m['owners'][0]+0xC0,a)
    assert bridge.get_competition_teams(bridge.session,ref)['teams'][0]['owner']['name']=='Unaligned'


def test_null_owner_matches_next_but_not_current(bridge,monkeypatch,team_memory):
    m=team_memory;ref=setup(bridge,monkeypatch,m)
    m['q'](m['team_addresses'][0]+0x30,0)
    assert bridge.get_competition_teams(bridge.session,ref)['count']==2
    next_=bridge.get_competition_teams(bridge.session,ref,assignment='next')
    assert next_['count']==3
    roster=bridge.get_team_squad(bridge.session,next_['teams'][0]['team_ref'])
    assert roster['club'] is None and roster['team']['owner'] is None and roster['count']==1


def test_changed_team_kind_invalidates_reference(bridge,monkeypatch,team_memory):
    m=team_memory;ref=setup(bridge,monkeypatch,m)
    team_ref=bridge.get_competition_teams(bridge.session,ref)['teams'][0]['team_ref']
    m['q'](m['team_addresses'][0],m['base']+world.TYPES['national_team'][0])
    with pytest.raises(BridgeError,match='identity changed'):
        bridge.get_team_squad(bridge.session,team_ref)
    assert team_ref not in bridge.team_refs


def test_save_change_clears_assignment_references_and_cursors(bridge,monkeypatch,team_memory):
    m=team_memory;ref=setup(bridge,monkeypatch,m)
    page=bridge.get_competition_teams(bridge.session,ref,max_matches=1)
    assert bridge.team_refs and bridge.database_cursors
    m['q'](m['save']+0x28,m['text']('Different save'))
    with pytest.raises(BridgeError,match='identity changed'):
        bridge.get_team_squad(bridge.session,page['teams'][0]['team_ref'])
    assert not bridge.team_refs and not bridge.database_cursors and not bridge.competition_refs
