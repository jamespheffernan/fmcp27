import struct

import pytest

from fm_live_mcp import geography,world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_cities import city_memory
from test_database import bind,database_memory
from test_players import memory
from test_world import world_memory


@pytest.fixture
def places_memory(city_memory):
    m=city_memory;langs=[];regions=[]
    for i,name in enumerate(('English','Français','Fußlang')):
        a=m['typed']('language',0x40)
        m['put'](a+8,struct.pack('<III',i,500+i,500+i));m['q'](a+0x18,m['text'](name))
        m['q'](a+0x28,m['geography']['nation'][int(i==1)])
        m['put'](a+0x34,struct.pack('<hhh',(44,0,-1)[i],(9,31,0)[i],(23,34,-1)[i]))
        m['put'](a+0x3b,struct.pack('<bb',(20,5,0)[i],(5,15,20)[i]));langs.append(a)
    m['vec'](m['headers']['languages'],langs)
    for i,name in enumerate(('North','Süd')):
        a=m['typed']('local_region',0x60)
        m['put'](a+8,struct.pack('<III',i,700+i,700+i));m['q'](a+0x18,m['text'](name))
        m['q'](a+0x48,m['geography']['nation'][i]);m['q'](a+0x50,0 if i else m['geography']['weather'][0])
        m['put'](a+0x58,struct.pack('<i',100000 if i==0 else 0));regions.append(a)
    entries=m['allocate'](48)
    for i,(a,pct) in enumerate(((langs[0],100),(langs[1],10),(langs[0],30))):
        m['q'](entries+i*16,a);m['put'](entries+i*16+8,struct.pack('<b',pct))
    m['put'](regions[0]+0x30,struct.pack('<QQQ',entries,entries+48,entries+48))
    m['vec'](m['headers']['local_regions'],regions)
    for i,a in enumerate(m['city_addresses']):
        m['q'](a+0x30,langs[i] if i<2 else 0);m['q'](a+0x38,regions[i] if i<2 else 0)
    m.update(languages=langs,regions=regions,language_entries=entries)
    return m


def test_language_fields_unknowns_deletion_and_refresh(bridge,monkeypatch,places_memory):
    m=places_memory;bind(bridge,monkeypatch,m)
    rows=bridge.find_languages(bridge.session)['languages']
    assert rows[0]['family']=={'native_code':44,'name':'Indo European','state':'decoded'}
    assert rows[0]['difficulty']==5 and rows[0]['influence']==20 and rows[0]['nation']['short_name']=='England'
    assert rows[1]['family']=={'native_code':0,'name':None,'state':'unmapped'}
    assert rows[1]['group']['native_code']==31 and rows[1]['group']['state']=='unmapped'
    assert rows[1]['subgroup']['native_code']==34 and rows[1]['subgroup']['state']=='unmapped'
    assert rows[2]['is_deleted'] and rows[2]['family']['native_code']==-1
    m['q'](m['languages'][0]+0x18,m['text']('Changed'));m['q'](m['languages'][0]+0x28,0)
    m['put'](m['languages'][0]+0x3c,b'\x12')
    row=bridge.get_language(bridge.session,rows[0]['language_ref'])['language']
    assert row['name']=='Changed' and row['nation'] is None and row['difficulty']==18


def test_region_vector_preserves_duplicate_and_overlapping_percentages(bridge,monkeypatch,places_memory):
    m=places_memory;bind(bridge,monkeypatch,m)
    rows=bridge.find_local_regions(bridge.session)['local_regions'];row=rows[0]
    assert row['population']==100000 and row['nation']['short_name']=='England' and row['weather']['name']=='Weather'
    assert row['complete_native_language_vector'] and row['language_count']==3
    assert [e['percentage_native'] for e in row['languages']]==[100,10,30]
    refs=[e['language']['language_ref'] for e in row['languages']]
    assert refs[0]==refs[2] and bridge.get_language(bridge.session,refs[0])['language']['name']=='English'
    assert rows[1]['population']==0 and rows[1]['languages']==[] and rows[1]['weather'] is None
    m['q'](m['language_entries'],m['languages'][2]);m['put'](m['regions'][0]+0x58,struct.pack('<i',123))
    fresh=bridge.get_local_region(bridge.session,row['local_region_ref'])['local_region']
    assert fresh['population']==123 and fresh['languages'][0]['language']['native_id']==502
    assert bridge.get_language(bridge.session,refs[0])['language']['native_id']==500


@pytest.mark.parametrize('method,args,expected',[
    ('find_languages',{'name':'FUSS'},[502]),('find_languages',{'nation':'fra'},[501]),
    ('find_languages',{'native_id':501},[501]),('find_languages',{'nation_native_id':200},[500,502]),
    ('find_languages',{'maximum_difficulty':5,'minimum_influence':20,'is_deleted':False},[500]),
    ('find_languages',{'is_deleted':True},[502]),('find_languages',{'nation':'England','nation_native_id':201},[]),
    ('find_local_regions',{'name':'SÜD'},[701]),('find_local_regions',{'nation':'eng','minimum_population':1},[700]),
    ('find_local_regions',{'native_id':701,'minimum_population':0},[701]),
    ('find_local_regions',{'nation_native_id':201},[701]),('find_local_regions',{'minimum_population':100001},[]),
    ('find_cities',{'language_native_id':501},[301]),('find_cities',{'local_region_native_id':700},[300]),
    ('find_cities',{'local_region_native_id':700,'language_native_id':501},[])])
def test_combined_queries(bridge,monkeypatch,places_memory,method,args,expected):
    bind(bridge,monkeypatch,places_memory)
    key={'find_languages':'languages','find_local_regions':'local_regions','find_cities':'cities'}[method]
    rows=getattr(bridge,method)(bridge.session,**args)[key]
    assert [r['native_id'] for r in rows]==expected


def test_city_links_open_region_languages_and_reverse_city_lookup(bridge,monkeypatch,places_memory):
    m=places_memory;bind(bridge,monkeypatch,m)
    city=bridge.find_cities(bridge.session,native_id=300)['cities'][0]
    assert bridge.get_language(bridge.session,city['language']['language_ref'])['language']['native_id']==500
    region=bridge.get_local_region(bridge.session,city['local_region']['local_region_ref'])['local_region']
    assert region['native_id']==700
    assert bridge.find_cities(bridge.session,local_region_native_id=700)['cities'][0]['native_id']==300
    m['q'](m['city_addresses'][0]+0x38,m['regions'][1])
    fresh=bridge.get_city(bridge.session,city['city_ref'])['city']
    assert fresh['local_region']['native_id']==701
    assert bridge.get_local_region(bridge.session,region['local_region_ref'])['local_region']['native_id']==700
    # A null direct language is not filled from the region list.
    m['q'](m['city_addresses'][0]+0x30,0)
    assert bridge.find_cities(bridge.session,local_region_native_id=701,language_native_id=500)['count']==0


@pytest.mark.parametrize('method,name,kind', [('find_languages','Fuss','languages'),('find_local_regions','Süd','local_regions')])
def test_cursors_empty_pages_query_and_table_identity(bridge,monkeypatch,places_memory,method,name,kind):
    m=places_memory;bind(bridge,monkeypatch,m);find=getattr(bridge,method)
    page=find(bridge.session,name=name,record_budget=1)
    assert page['count']==0 and page['next_cursor']
    with pytest.raises(BridgeError,match='different query'):find(bridge.session,name='different',cursor=page['next_cursor'])
    fresh=find(bridge.session,name=name,cursor=page['next_cursor'],record_budget=3)
    assert fresh['count']==1 and fresh['next_cursor'] is None
    m['vec'](m['headers'][kind],m['languages'] if kind=='languages' else m['regions'])
    with pytest.raises(BridgeError,match='expired'):find(bridge.session,name=name,cursor=page['next_cursor'])


@pytest.mark.parametrize('method,args',[
    ('find_languages',{'maximum_difficulty':True}),('find_languages',{'maximum_difficulty':21}),
    ('find_languages',{'minimum_influence':-1}),('find_languages',{'is_deleted':1}),
    ('find_languages',{'native_id':0}),('find_languages',{'name':'\ud800'}),
    ('find_languages',{'name':'é'*100}),('find_languages',{'nation':'\n'}),
    ('find_local_regions',{'minimum_population':True}),('find_local_regions',{'minimum_population':-1}),
    ('find_local_regions',{'minimum_population':2**31}),('find_local_regions',{'nation_native_id':0}),
    ('find_local_regions',{'max_matches':101}),('find_local_regions',{'record_budget':1001}),
    ('find_local_regions',{'cursor':0}),('find_local_regions',{'nation':''}),
    ('find_cities',{'language_native_id':True}),('find_cities',{'local_region_native_id':-1})])
def test_invalid_selectors(bridge,method,args):
    with pytest.raises(BridgeError):getattr(bridge,method)(bridge.session,**args)


@pytest.mark.parametrize('kind',['language','local_region'])
@pytest.mark.parametrize('fault',['type','getter','id','index','membership','string','rtti','pointer'])
def test_bad_parent_records_publish_no_references(bridge,monkeypatch,places_memory,kind,fault):
    m=places_memory;bind(bridge,monkeypatch,m);a=m['languages' if kind=='language' else 'regions'][0]
    table=geography.FIELDS[kind][1];vt=m['base']+world.TYPES[kind][0]
    if fault=='type':m['q'](a,m['base']+world.TYPES['club'][0])
    if fault=='getter':m['q'](vt+24,0)
    if fault=='id':m['put'](a+12,bytes(8))
    if fault=='index':m['put'](a+8,struct.pack('<I',999))
    if fault=='membership':m['vec'](m['headers'][table],[m['club']])
    if fault=='string':m['q'](a+0x18,m['text']('bad\nname'))
    if fault=='rtti':m['q'](vt-16,8)
    if fault=='pointer':m['vec'](m['headers'][table],[1])
    with pytest.raises(BridgeError):getattr(bridge,'find_'+table)(bridge.session)
    assert not bridge.geographic_refs


@pytest.mark.parametrize('fault',['partial_null','reverse','misaligned','partial_entry','over_capacity','oversized','bad_language','wrong_type','bad_membership'])
def test_region_bad_vectors_and_targets_reject_without_partial_results(bridge,monkeypatch,places_memory,fault):
    m=places_memory;bind(bridge,monkeypatch,m);a=m['regions'][0]+0x30;start=m['language_entries']
    header={'partial_null':(0,start,start),'reverse':(start,start-16,start),
            'misaligned':(start+1,start+17,start+17),'partial_entry':(start,start+8,start+16),
            'over_capacity':(start,start+48,start+16),'oversized':(start,start,start+16016)}
    if fault in header:m['put'](a,struct.pack('<QQQ',*header[fault]))
    if fault=='bad_language':m['q'](start,1)
    if fault=='wrong_type':m['q'](start,m['club'])
    if fault=='bad_membership':m['vec'](m['headers']['languages'],list(reversed(m['languages'])))
    with pytest.raises(BridgeError):bridge.find_local_regions(bridge.session)
    assert not bridge.geographic_refs


@pytest.mark.parametrize('percentage',[-128,-1,0,100,101,127])
def test_null_language_and_native_percentage_states(bridge,monkeypatch,places_memory,percentage):
    m=places_memory;bind(bridge,monkeypatch,m);m['q'](m['language_entries'],0)
    m['put'](m['language_entries']+8,struct.pack('<b',percentage))
    row=bridge.find_local_regions(bridge.session,max_matches=1)['local_regions'][0]['languages'][0]
    assert row['language'] is None and row['percentage_native']==percentage
    assert row['percentage_state']==('stored' if 0<=percentage<=100 else 'out_of_range')


@pytest.mark.parametrize('kind',['language','local_region'])
@pytest.mark.parametrize('fault',['identity','membership','save','detach'])
def test_reference_expiry(bridge,monkeypatch,places_memory,kind,fault):
    m=places_memory;bind(bridge,monkeypatch,m);table=geography.FIELDS[kind][1]
    ref=getattr(bridge,'find_'+table)(bridge.session)[table][0][kind+'_ref']
    if fault=='identity':m['put'](m['languages' if kind=='language' else 'regions'][0]+12,struct.pack('<II',999,999))
    if fault=='membership':m['vec'](m['headers'][table],[m['club']])
    if fault=='save':m['q'](m['save']+0x28,m['text']('Other save'))
    if fault=='detach':bridge.detach()
    with pytest.raises(BridgeError):getattr(bridge,'get_'+kind)(bridge.session,ref)
    assert ref not in bridge.geographic_refs


def test_concurrent_vector_change_and_cache_eviction(bridge,monkeypatch,places_memory):
    m=places_memory;bind(bridge,monkeypatch,m);target=m['language_entries'];hits=0
    def read(a,n):
        nonlocal hits
        if (a,n)==(target,16):
            hits+=1
            if hits==2:m['put'](a+8,b'\x09')
        return m['read'](a,n)
    monkeypatch.setattr(bridge,'_read_memory',lambda p,a,n:read(a,n))
    with pytest.raises(BridgeError,match='changed during read'):bridge.find_local_regions(bridge.session)
    assert not bridge.geographic_refs
    bind(bridge,monkeypatch,m)
    bridge.geographic_refs={str(i):{} for i in range(10000)}
    region=bridge.find_local_regions(bridge.session)['local_regions'][0]
    for entry in region['languages']:
        assert bridge.get_language(bridge.session,entry['language']['language_ref'])['language']['native_id']==entry['language']['native_id']
    bridge.geographic_refs.update({str(i):{} for i in range(10000)})
    fresh=bridge.get_local_region(bridge.session,region['local_region_ref'])['local_region']
    assert bridge.get_local_region(bridge.session,fresh['local_region_ref'])['local_region']['native_id']==700
    assert bridge.get_language(bridge.session,fresh['languages'][0]['language']['language_ref'])['language']['native_id']==500
    with pytest.raises(BridgeError,match='Unknown'):bridge.get_language(bridge.session,fresh['local_region_ref'])


@pytest.mark.parametrize('kind,offset',[('nation',0x48),('weather',0x50)])
@pytest.mark.parametrize('fault',['pointer','type','membership','identity'])
def test_region_bad_geographic_links(bridge,monkeypatch,places_memory,kind,offset,fault):
    m=places_memory;bind(bridge,monkeypatch,m);target=m['geography'][kind][0]
    if fault=='pointer':m['q'](m['regions'][0]+offset,1)
    if fault=='type':m['q'](m['regions'][0]+offset,m['club'])
    if fault=='membership':m['vec'](m['headers'][geography.FIELDS[kind][1]],[m['club']])
    if fault=='identity':m['put'](target+12,bytes(4))
    with pytest.raises(BridgeError):bridge.find_local_regions(bridge.session)
    assert not bridge.geographic_refs


def test_allocated_empty_vector_and_city_reference_reservation(bridge,monkeypatch,places_memory):
    m=places_memory;bind(bridge,monkeypatch,m);start=m['language_entries']
    m['put'](m['regions'][0]+0x30,struct.pack('<QQQ',start,start,start+48))
    row=bridge.find_local_regions(bridge.session,max_matches=1)['local_regions'][0]
    assert row['languages']==[] and row['complete_native_language_vector']
    bridge.geographic_refs={str(i):{} for i in range(10000)}
    city=bridge.find_cities(bridge.session,max_matches=1)['cities'][0]
    assert bridge.get_language(bridge.session,city['language']['language_ref'])['language']['native_id']==500
    assert bridge.get_local_region(bridge.session,city['local_region']['local_region_ref'])['local_region']['native_id']==700
    bridge.geographic_refs.update({str(i):{} for i in range(10000)})
    fresh=bridge.get_city(bridge.session,city['city_ref'])['city']
    assert bridge.get_language(bridge.session,fresh['language']['language_ref'])['language']['native_id']==500
    assert bridge.get_local_region(bridge.session,fresh['local_region']['local_region_ref'])['local_region']['native_id']==700


def test_city_new_selectors_bind_cursors(bridge,monkeypatch,places_memory):
    bind(bridge,monkeypatch,places_memory)
    page=bridge.find_cities(bridge.session,local_region_native_id=701,record_budget=1)
    assert not page['cities'] and page['next_cursor']
    with pytest.raises(BridgeError,match='different query'):
        bridge.find_cities(bridge.session,local_region_native_id=700,cursor=page['next_cursor'])
    with pytest.raises(BridgeError,match='different query'):
        bridge.find_cities(bridge.session,local_region_native_id=701,language_native_id=500,cursor=page['next_cursor'])
    last=bridge.find_cities(bridge.session,local_region_native_id=701,cursor=page['next_cursor'])
    assert last['cities'][0]['native_id']==301 and last['next_cursor'] is None
