import struct

import pytest

from fm_live_mcp import stadiums,world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import bind,database_memory
from test_players import memory
from test_world import world_memory


@pytest.fixture
def stadium_memory(database_memory):
    m=database_memory
    addresses=[]
    for index,name in enumerate(('St. James\' Park','Fußball Arena','Training Ground')):
        a=m['typed']('stadium',0xC0)
        m['put'](a+8,struct.pack('<III',index,688+index,688+index))
        m['q'](a+0x40,m['text'](name))
        m['q'](a+0x48,m['text']('Alternate Ground') if index==1 else 0)
        m['put'](a+0x7C,struct.pack('<5i',52305,0,0,-1,65000))
        m['put'](a+0x70,struct.pack('<2f',54.975,-1.621))
        m['put'](a+0x98,struct.pack('<8h',1050,680,-1,-10,900,550,1100,730))
        m['put'](a+0xA8,struct.pack('<hb',200,5))
        m['put'](a+0xAB,bytes([5 if index==2 else 64]))
        m['put'](a+0xAC,bytes([2,8,15,1,3,0,1,2,1]))
        m['put'](a+0xB6,struct.pack('<H',67))
        for off,year,day in ((0x30,1807,182),(0x34,1900,1),(0x2C,2032,366)):
            m['put'](a+off,struct.pack('<I',year<<16|day))
        addresses.append(a)
    m['q'](m['base']+world.TYPES['stadium'][0]+24,m['base']+stadiums.PROPERTY_GETTER)
    m['vec'](m['headers']['stadiums'],addresses)
    m['stadium_addresses']=addresses
    return m


def search(bridge,monkeypatch,m,**args):
    bind(bridge,monkeypatch,m)
    return bridge.find_stadiums(bridge.session,**args)


def test_stadium_search_fields_and_refresh(bridge,monkeypatch,stadium_memory):
    m=stadium_memory
    page=search(bridge,monkeypatch,m)
    assert page['count']==3 and page['complete_table_scan']
    row=page['stadiums'][0]
    assert row['native_id']==688 and row['name']=="St. James' Park"
    assert row['capacities']['seated']['value']==0
    assert row['capacities']['used']['value'] is None and row['capacities']['all_seater_competitions']['value'] is None
    assert row['capacities']['expansion']['value']==65000
    assert row['pitch']['type']['name']=='Grass/Synthetic Mix'
    assert row['pitch']['dimension_unit']=='metres'
    assert row['pitch']['dimensions']['default']['length']['value']==105
    assert row['pitch']['dimensions']['international']['length']['state']=='not_specified'
    assert row['pitch']['dimensions']['international']['width']['state']=='not_specified'
    assert all(row['facilities'].values())
    assert row['dates']['built']['date']=='1807-07-01'
    assert row['dates']['rebuilt']['state']=='not_specified'
    assert row['dates']['pitch_relay_required']['date']=='2032-12-31'
    m['put'](m['stadium_addresses'][0]+0x7C,struct.pack('<i',55000))
    fresh=bridge.get_stadium(bridge.session,row['stadium_ref'])['stadium']
    assert fresh['capacities']['total']['value']==55000 and fresh['stadium_ref']==row['stadium_ref']


@pytest.mark.parametrize('args,indices',[
    ({'name':'FUSSBALL'},[1]),({'name':'alternate'},[1]),({'native_id':690},[2]),
    ({'is_extinct':True},[2]),({'is_training_ground':False},[0,1]),
    ({'minimum_capacity':52306},[]),({'name':'ground','is_extinct':True},[2])])
def test_stadium_selectors_combine(bridge,monkeypatch,stadium_memory,args,indices):
    page=search(bridge,monkeypatch,stadium_memory,**args)
    assert [r['database_index'] for r in page['stadiums']]==indices


def test_stadium_cursors_empty_pages_and_changes(bridge,monkeypatch,stadium_memory):
    m=stadium_memory
    page=search(bridge,monkeypatch,m,name='Training',record_budget=1)
    assert page['count']==0 and page['next_cursor']
    with pytest.raises(BridgeError,match='different query'):
        bridge.find_stadiums(bridge.session,name='other',cursor=page['next_cursor'])
    fresh=bridge.find_stadiums(bridge.session,name='Training',cursor=page['next_cursor'],record_budget=2)
    assert fresh['count']==1 and fresh['next_cursor'] is None
    m['vec'](m['headers']['stadiums'],m['stadium_addresses'])
    with pytest.raises(BridgeError,match='expired'):
        bridge.find_stadiums(bridge.session,name='Training',cursor=page['next_cursor'])


@pytest.mark.parametrize('args',[{'name':''},{'name':'\n'},{'name':'\ud800'}, {'name':'é'*100},
    {'native_id':True},{'native_id':0},{'minimum_capacity':-1},{'minimum_capacity':True},
    {'is_extinct':1},{'is_training_ground':'true'},{'record_budget':1001},{'max_matches':0},{'cursor':0}])
def test_stadium_invalid_selectors(bridge,args):
    with pytest.raises(BridgeError):bridge.find_stadiums(bridge.session,**args)


@pytest.mark.parametrize('fault',['type','getter','index','id','membership','string','rtti'])
def test_stadium_bad_records_fail_without_refs(bridge,monkeypatch,stadium_memory,fault):
    m=stadium_memory;a=m['stadium_addresses'][0];vt=m['base']+world.TYPES['stadium'][0]
    if fault=='type':m['q'](a,m['base']+world.TYPES['club'][0])
    if fault=='getter':m['q'](vt+24,0)
    if fault=='index':m['put'](a+8,struct.pack('<I',3))
    if fault=='id':m['put'](a+12,bytes(4))
    if fault=='membership':m['vec'](m['headers']['stadiums'],list(reversed(m['stadium_addresses'])))
    if fault=='string':m['q'](a+0x40,m['text']('invalid\nname'))
    if fault=='rtti':m['q'](vt-16,8)
    with pytest.raises(BridgeError):search(bridge,monkeypatch,m)
    assert not bridge.stadium_refs


@pytest.mark.parametrize('fault',['id','duplicate_id','membership','save','detach'])
def test_stadium_refs_expire(bridge,monkeypatch,stadium_memory,fault):
    m=stadium_memory
    ref=search(bridge,monkeypatch,m)['stadiums'][0]['stadium_ref']
    if fault=='id':m['put'](m['stadium_addresses'][0]+12,struct.pack('<I',123))
    if fault=='duplicate_id':m['put'](m['stadium_addresses'][0]+16,struct.pack('<I',123))
    if fault=='membership':m['vec'](m['headers']['stadiums'],list(reversed(m['stadium_addresses'])))
    if fault=='save':m['q'](m['save']+0x28,m['text']('Another save'))
    if fault=='detach':bridge.detach()
    with pytest.raises(BridgeError):bridge.get_stadium(bridge.session,ref)
    assert ref not in bridge.stadium_refs


def test_stadium_missing_and_unmapped_fields(bridge,monkeypatch,stadium_memory):
    m=stadium_memory;a=m['stadium_addresses'][0]
    m['q'](a+0x40,0);m['q'](a+0x48,m['text'](''))
    m['put'](a+0xAD,b'\x7f');m['put'](a+0xB0,b'\0');m['put'](a+0xB4,b'\0')
    m['put'](a+0x70,struct.pack('<ff',float('nan'),181))
    m['put'](a+0x30,struct.pack('<I',2932<<16|92))
    row=search(bridge,monkeypatch,m)['stadiums'][0]
    assert row['name'] is None and row['continental_name']==''
    assert row['pitch']['type']=={'native_code':127,'name':None,'state':'unmapped'}
    assert row['environment']['state']=='not_specified' and row['owner_type']['state']=='not_specified'
    assert row['coordinates']['state']=='invalid_native_coordinates' and row['coordinates']['latitude'] is None
    assert row['dates']['built']['date']=='2932-04-01'


@pytest.mark.parametrize('packed,state',[(0,'invalid_native_date'),(2030<<16|366,'invalid_native_date'),
    (1900<<16|1,'not_specified'),(65535<<16|1,'invalid_native_date'),(2032<<16|366,'stored')])
def test_stadium_date_policy_preserves_invalid_and_unset(packed,state):
    assert stadiums._date(struct.pack('<I',packed))['state']==state


@pytest.mark.parametrize('code,label', [(0,'No Matches'),(1,'All Matches'),(2,'Major Matches'),
    (3,'Medium Matches'),(4,'Minor Matches'),(5,'Major Matches And Some Medium Matches'),
    (6,'Minor Matches and Some Medium Matches'),(-1,None),(127,None)])
def test_stadium_national_usage_is_a_stored_category(bridge,monkeypatch,stadium_memory,code,label):
    m=stadium_memory
    m['put'](m['stadium_addresses'][0]+0xB1,struct.pack('<3b',code,code,code))
    row=search(bridge,monkeypatch,m,max_matches=1)['stadiums'][0]
    assert all(value=={'native_code':code,'name':label,'state':'decoded' if label else 'unmapped'}
               for value in row['national_team_usage'].values())


def test_stadium_change_during_recheck_publishes_nothing(bridge,monkeypatch,stadium_memory):
    m=stadium_memory;bind(bridge,monkeypatch,m);hits=0;target=m['stadium_addresses'][0]+0x7C
    def read(a,n):
        nonlocal hits
        if (a,n)==(target,4):
            hits+=1
            if hits==2:m['put'](a,struct.pack('<i',60000))
        return m['read'](a,n)
    monkeypatch.setattr(bridge,'_read_memory',lambda p,a,n:read(a,n))
    with pytest.raises(BridgeError,match='changed during read'):bridge.find_stadiums(bridge.session)
    assert not bridge.stadium_refs


def test_stadium_reference_eviction_keeps_new_results_usable(bridge,monkeypatch,stadium_memory):
    bind(bridge,monkeypatch,stadium_memory)
    bridge.stadium_refs={str(i):{} for i in range(10000)}
    page=bridge.find_stadiums(bridge.session,max_matches=1)
    assert len(bridge.stadium_refs)==1
    assert bridge.get_stadium(bridge.session,page['stadiums'][0]['stadium_ref'])['stadium']['native_id']==688
