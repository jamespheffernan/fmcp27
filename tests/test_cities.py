import struct

import pytest

from fm_live_mcp import cities,geography,world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import bind,database_memory
from test_geography import add_geography
from test_players import memory
from test_stadiums import stadium_memory
from test_world import world_memory


def add_cities(m):
    add_geography(m)
    for kind in ('language','local_region','weather'):
        getter,table_kind,_ = geography.FIELDS[kind]
        a = m['typed'](kind,0x60)
        m['put'](a+8,struct.pack('<III',0,500,500))
        m['q'](a+0x18,m['text'](kind.title()))
        m['q'](m['base']+world.TYPES[kind][0]+24,m['base']+getter)
        m['vec'](m['headers'][table_kind],[a])
        m['geography'][kind] = [a]
    addresses = []
    for index,name in enumerate(('Newcastle','Valence','Fußstadt')):
        a = m['typed']('city',0x58)
        m['put'](a+8,struct.pack('<III',index,index+300,index+300))
        m['q'](a+0x18,m['text'](name))
        for kind,offset in (('nation',0x20),('weather',0x28),('language',0x30),('local_region',0x38)):
            m['q'](a+offset,m['geography'][kind][1 if kind=='nation' and index==1 else 0])
        m['put'](a+0x48,struct.pack('<ff',54.98,-1.61))
        m['put'](a+0x50,struct.pack('<h',(-1312,16390,0)[index]))
        m['put'](a+0x52,struct.pack('<b',(8,5,0)[index]))
        m['put'](a+0x54,bytes([(12,18,0)[index],int(index==2)]))
        addresses.append(a)
    m['q'](m['base']+world.TYPES['city'][0]+24,m['base']+cities.PROPERTY_GETTER)
    m['vec'](m['headers']['cities'],addresses)
    m['city_addresses'] = addresses
    return m


@pytest.fixture
def city_memory(database_memory):
    return add_cities(database_memory)


@pytest.fixture
def linked_stadium_memory(stadium_memory):
    m=add_cities(stadium_memory)
    for i in range(2):
        m['q'](m['stadium_addresses'][i]+0x60,m['city_addresses'][i])
        m['q'](m['stadium_addresses'][i]+0x68,m['stadium_addresses'][1-i])
    m['q'](m['stadium_addresses'][0]+0x90,m['club'])
    return m


def test_city_fields_refresh_and_unverified_altitude(bridge,monkeypatch,city_memory):
    m=city_memory;bind(bridge,monkeypatch,m)
    page=bridge.find_cities(bridge.session)
    assert page['count']==3 and page['complete_table_scan']
    row=page['cities'][0]
    assert row['name']=='Newcastle' and row['nation']['short_name']=='England'
    assert row['population']=={'native_code':8,'name':'100001 - 250000','state':'decoded'}
    assert row['attraction']==12 and not row['is_deleted']
    assert row['altitude']=={'native_value':-1312,'unit':None,'state':'unit_unverified'}
    assert page['cities'][1]['altitude']['native_value']==16390
    for kind in ('language','local_region','weather'):
        assert row[kind]['name']==kind.title() and row[kind]['kind']==kind
    m['q'](m['city_addresses'][0]+0x18,m['text']('New Name'))
    m['q'](m['city_addresses'][0]+0x30,0)
    fresh=bridge.get_city(bridge.session,row['city_ref'])['city']
    assert fresh['name']=='New Name' and fresh['language'] is None and fresh['city_ref']==row['city_ref']


@pytest.mark.parametrize('args,indices',[
    ({'name':'FUSS'},[2]),({'native_id':301},[1]),({'nation':'eng'},[0,2]),
    ({'nation_native_id':201},[1]),({'minimum_attraction':15},[1]),({'is_deleted':True},[2]),
    ({'nation':'England','is_deleted':False,'minimum_attraction':10},[0]),
    ({'nation':'France','nation_native_id':200},[])])
def test_city_filters_combine(bridge,monkeypatch,city_memory,args,indices):
    bind(bridge,monkeypatch,city_memory)
    assert [r['database_index'] for r in bridge.find_cities(bridge.session,**args)['cities']]==indices


def test_city_cursors_preserve_empty_pages_and_bind_query(bridge,monkeypatch,city_memory):
    m=city_memory;bind(bridge,monkeypatch,m)
    first=bridge.find_cities(bridge.session,name='Fuss',record_budget=1)
    assert first['count']==0 and first['next_cursor']
    with pytest.raises(BridgeError,match='different query'):
        bridge.find_cities(bridge.session,name='Newcastle',cursor=first['next_cursor'])
    last=bridge.find_cities(bridge.session,name='Fuss',cursor=first['next_cursor'],record_budget=2)
    assert last['cities'][0]['native_id']==302 and last['next_cursor'] is None
    m['vec'](m['headers']['cities'],m['city_addresses'])
    with pytest.raises(BridgeError,match='expired'):
        bridge.find_cities(bridge.session,name='Fuss',cursor=first['next_cursor'])


@pytest.mark.parametrize('args',[{'name':''},{'name':'\n'},{'name':'\ud800'},{'name':'é'*100},
    {'nation':''},{'nation':'\ud800'},{'nation':1},{'native_id':True},{'native_id':0},
    {'nation_native_id':False},{'nation_native_id':-1},{'minimum_attraction':True},
    {'minimum_attraction':21},{'is_deleted':1},{'record_budget':1001},{'max_matches':0},{'cursor':0}])
def test_invalid_city_selectors(bridge,args):
    with pytest.raises(BridgeError):bridge.find_cities(bridge.session,**args)


@pytest.mark.parametrize('fault',['type','getter','index','id','membership','string','empty_string','rtti'])
def test_bad_city_records_publish_nothing(bridge,monkeypatch,city_memory,fault):
    m=city_memory;bind(bridge,monkeypatch,m);a=m['city_addresses'][0];vt=m['base']+world.TYPES['city'][0]
    if fault=='type':m['q'](a,m['base']+world.TYPES['stadium'][0])
    if fault=='getter':m['q'](vt+24,0)
    if fault=='index':m['put'](a+8,struct.pack('<I',99))
    if fault=='id':m['put'](a+12,bytes(4))
    if fault=='membership':m['vec'](m['headers']['cities'],list(reversed(m['city_addresses'])))
    if fault=='string':m['q'](a+0x18,m['text']('bad\nname'))
    if fault=='empty_string':
        text=m['text']('');m['put'](text+4,b'x');m['q'](a+0x18,text)
    if fault=='rtti':m['q'](vt-16,8)
    with pytest.raises(BridgeError):bridge.find_cities(bridge.session)
    assert not bridge.city_refs


@pytest.mark.parametrize('kind', ['nation','language','local_region','weather'])
@pytest.mark.parametrize('fault', ['type','getter','membership','zero_id','string'])
def test_bad_city_geographic_link_rejects_page(bridge,monkeypatch,city_memory,kind,fault):
    m=city_memory;bind(bridge,monkeypatch,m);a=m['geography'][kind][0]
    getter,table_kind,fields=geography.FIELDS[kind]
    if fault=='type':m['q'](a,m['base']+world.TYPES['city'][0])
    if fault=='getter':m['q'](m['base']+world.TYPES[kind][0]+24,0)
    if fault=='membership':m['vec'](m['headers'][table_kind],[m['club']])
    if fault=='zero_id':m['put'](a+12,bytes(4))
    if fault=='string':m['q'](a+fields[0][1],m['text']('bad\nname'))
    with pytest.raises(BridgeError):bridge.find_cities(bridge.session)
    assert not bridge.city_refs


@pytest.mark.parametrize('fault',['id','duplicate','membership','save','detach'])
def test_city_reference_expiry(bridge,monkeypatch,city_memory,fault):
    m=city_memory;bind(bridge,monkeypatch,m);ref=bridge.find_cities(bridge.session)['cities'][0]['city_ref']
    if fault=='id':m['put'](m['city_addresses'][0]+12,struct.pack('<I',999))
    if fault=='duplicate':m['put'](m['city_addresses'][0]+16,struct.pack('<I',999))
    if fault=='membership':m['vec'](m['headers']['cities'],list(reversed(m['city_addresses'])))
    if fault=='save':m['q'](m['save']+0x28,m['text']('Another save'))
    if fault=='detach':bridge.detach()
    with pytest.raises(BridgeError):bridge.get_city(bridge.session,ref)
    assert ref not in bridge.city_refs


@pytest.mark.parametrize('code,label,state',[(0,'Not Set','not_specified'),(15,'20000001 +','decoded'),(-1,None,'unmapped'),(127,None,'unmapped')])
def test_city_nulls_invalid_coordinates_and_population(bridge,monkeypatch,city_memory,code,label,state):
    m=city_memory;bind(bridge,monkeypatch,m);a=m['city_addresses'][0]
    m['q'](a+0x18,0)
    for offset in (0x20,0x28,0x30,0x38):m['q'](a+offset,0)
    m['put'](a+0x48,struct.pack('<ff',float('inf'),181))
    m['put'](a+0x52,struct.pack('<b',code))
    row=bridge.find_cities(bridge.session,max_matches=1)['cities'][0]
    assert row['name'] is None and all(row[k] is None for k in ('nation','weather','language','local_region'))
    assert row['coordinates']['latitude'] is None and row['coordinates']['state']=='invalid_native_coordinates'
    assert row['population']=={'native_code':code,'name':label,'state':state}


def test_city_concurrent_change_publishes_no_refs(bridge,monkeypatch,city_memory):
    m=city_memory;bind(bridge,monkeypatch,m);target=m['city_addresses'][0]+0x50;hits=0
    def read(a,n):
        nonlocal hits
        if (a,n)==(target,2):
            hits+=1
            if hits==2:m['put'](a,struct.pack('<h',99))
        return m['read'](a,n)
    monkeypatch.setattr(bridge,'_read_memory',lambda p,a,n:read(a,n))
    with pytest.raises(BridgeError,match='changed during read'):bridge.find_cities(bridge.session)
    assert not bridge.city_refs


def test_stadium_links_open_city_club_and_cyclic_nearby_records(bridge,monkeypatch,linked_stadium_memory):
    m=linked_stadium_memory;bind(bridge,monkeypatch,m)
    page=bridge.find_stadiums(bridge.session)
    row=page['stadiums'][0]
    assert row['owner_club']['native_id']==688
    assert bridge.get_city(bridge.session,row['city']['city_ref'])['city']['name']=='Newcastle'
    assert bridge.get_club_squads(bridge.session,club_ref=row['owner_club']['club_ref'])['club']['name']=='Test United'
    assert 'nearby_stadium' not in row['nearby_stadium']
    other=bridge.get_stadium(bridge.session,row['nearby_stadium']['stadium_ref'])['stadium']
    assert other['native_id']==689 and other['nearby_stadium']['native_id']==688
    assert all(page['stadiums'][2][k] is None for k in ('city','owner_club','nearby_stadium'))
    m['q'](m['stadium_addresses'][0]+0x60,m['city_addresses'][1])
    fresh=bridge.get_stadium(bridge.session,row['stadium_ref'])['stadium']
    assert fresh['city']['name']=='Valence'
    assert bridge.get_city(bridge.session,row['city']['city_ref'])['city']['name']=='Newcastle'


@pytest.mark.parametrize('kind,offset',[('city',0x60),('owner_club',0x90),('nearby_stadium',0x68)])
@pytest.mark.parametrize('fault',['pointer','type','membership'])
def test_bad_stadium_links_publish_no_partial_references(bridge,monkeypatch,linked_stadium_memory,kind,offset,fault):
    m=linked_stadium_memory;bind(bridge,monkeypatch,m);a=m['stadium_addresses'][0]
    if fault=='pointer':m['q'](a+offset,1)
    elif fault=='type':m['q'](a+offset,m['team'])
    else:
        table={'city':'cities','owner_club':'clubs','nearby_stadium':'stadiums'}[kind]
        m['vec'](m['headers'][table],[m['team']])
    with pytest.raises(BridgeError):bridge.find_stadiums(bridge.session)
    assert not bridge.stadium_refs and not bridge.city_refs and not bridge.club_refs


def test_link_cache_eviction_preserves_every_returned_reference(bridge,monkeypatch,linked_stadium_memory):
    m=linked_stadium_memory;bind(bridge,monkeypatch,m)
    bridge.city_refs={str(i):{} for i in range(10000)}
    bridge.stadium_refs={str(i):{} for i in range(10000)}
    bridge.club_refs={str(i):{} for i in range(1000)}
    row=bridge.find_stadiums(bridge.session,max_matches=1)['stadiums'][0]
    assert bridge.get_city(bridge.session,row['city']['city_ref'])['city']['native_id']==300
    assert bridge.get_club_squads(bridge.session,club_ref=row['owner_club']['club_ref'])['squads']
    bridge.stadium_refs.update({str(i):{} for i in range(10000)})
    fresh=bridge.get_stadium(bridge.session,row['stadium_ref'])['stadium']
    assert bridge.get_stadium(bridge.session,fresh['stadium_ref'])['stadium']['native_id']==688
    assert bridge.get_stadium(bridge.session,fresh['nearby_stadium']['stadium_ref'])['stadium']['native_id']==689
