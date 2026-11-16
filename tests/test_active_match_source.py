import struct
import pytest
from fm_live_mcp import active_match_source as source


@pytest.fixture
def memory():
    cells={};base=0x100000000;root=0x10008
    def put(at,raw):cells.update({at+i:b for i,b in enumerate(raw)})
    def pack(at,fmt,*args):put(at,struct.pack(fmt,*args))
    def read(at,n):return bytes(cells[at+i]for i in range(n))
    info=0x20000
    def typed(at,vt,offset,name):
        nonlocal info
        pack(at,'<Q',base+vt);pack(base+vt-16,'<qQ',offset,info)
        pack(info+8,'<Q',info+0x20);put(info+0x20,name+b'\0');info+=0x100
    for rva,raw in (*source.NATIVE_SPANS,*source.FIXTURE_OWNER_SPANS):put(base+rva,raw)
    pack(base+source.ROOT,'<Q',root)
    typed(root,source.MANAGER_VTABLE,-8,source.MANAGER_NAME)
    typed(root-8,source.MANAGER_PRIMARY_VTABLE,0,source.MANAGER_NAME)
    pack(root+8,'<QQQ',0,0,0)
    return dict(base=base,root=root,put=put,pack=pack,read=read,typed=typed)


def inspect(m):return source.inspect(m['read'],m['base'])


def test_verified_empty_manager_is_narrow_negative_without_engine_reads(memory):
    r=inspect(memory)
    assert r['source_state']=='inactive'and r['physical_client_count']==0
    assert r['clients']==[]and r['native_viewable_client_predicate']is False
    assert r['gameplay_active']is None and r['halftime_state']is None


def test_missing_manager_is_unknown_not_no_match(memory):
    m=memory;m['pack'](m['base']+source.ROOT,'<Q',0)
    r=inspect(m)
    assert r['source_state']=='unknown'and r['physical_client_count']is None
    assert r['native_viewable_client_predicate']is None and r['clients']is None


def test_real_nonempty_shape_never_claims_active_fixture_or_halftime(memory):
    m=memory;client,vector,owner,engine=0x50000,0x60000,0x70000,0x80000
    m['typed'](client,0x55fac38,0,b'26GAME_VIEWABLE_MATCH_CLIENT')
    m['pack'](m['root']+8,'<QQQ',vector,vector+16,vector+16)
    m['pack'](vector,'<QQ',client,0)
    m['pack'](client+0xf8,'<Q',owner);m['pack'](owner+0x18,'<Q',engine)
    m['pack'](client+0x17c,'<H',0);m['pack'](client+0x138,'<Q',123)
    r=inspect(m)
    assert r['source_state']=='present_unbound'and r['native_viewable_client_predicate']is True
    assert r['bound_active_fixture']is None and r['gameplay_active']is None
    assert r['clients'][0]['period_binding_state']=='not_established'
    assert 'address'not in repr(r)and hex(client)not in repr(r)


@pytest.mark.parametrize('flags,expected',[(0,True),(0x80,False),(0x1000,False),(0x800,False),(0x1800,False),(0x20,True),(0xffff,False)])
def test_exact_numeric_native_flags_not_guessed_names(flags,expected):
    assert source.native_client_predicate(engine_present=True,flags=flags)is expected
    assert source.native_client_predicate(engine_present=False,flags=flags)is False


@pytest.mark.parametrize('header',[(0,1,2),(0x60000,0x5fff0,0x60000),(0x60000,0x60008,0x60010),(0x60000,0x60200,0x60200)])
def test_malformed_or_excessive_vectors_reject(memory,header):
    m=memory;m['pack'](m['root']+8,'<QQQ',*header)
    with pytest.raises(ValueError):inspect(m)


def test_type_native_and_displacement_changes_fail_closed(memory):
    m=memory;m['pack'](m['root'],'<Q',123)
    with pytest.raises(ValueError,match='type changed'):inspect(m)
    m=memory;m['pack'](m['root'],'<Q',m['base']+source.MANAGER_VTABLE)
    m['pack'](m['base']+source.MANAGER_VTABLE-16,'<q',0)
    with pytest.raises(ValueError,match='displacement'):inspect(m)
    m['put'](m['base']+source.NATIVE_SPANS[0][0],b'\0')
    with pytest.raises(ValueError,match='native source changed'):inspect(m)


@pytest.fixture
def bound_context(memory,monkeypatch):
    from fm_live_mcp import players,world
    from fm_live_mcp import fixtures
    m=memory;base=m['base'];client=0x50000;engine=0x80000;owner=0x70000;stats=0x90000
    m['pack'](m['root']+8,'<QQQ',0x60000,0x60010,0x60010);m['pack'](0x60000,'<QQ',client,0)
    m['typed'](client,0x55fac38,0,b'26GAME_VIEWABLE_MATCH_CLIENT')
    m['typed'](engine,0x55fa258,0,b'10GAME_MATCH')
    m['typed'](stats,0x55fa850,0,b'16GAME_MATCH_STATS')
    m['typed'](client+8,0x56a2380,0,b'N13simatchshared11MATCH_STATSE')
    m['pack'](client+0xf8,'<Q',owner);m['pack'](owner+0x18,'<Q',engine)
    m['pack'](client+0x17c,'<H',19);m['pack'](client+0x138,'<Q',123)
    m['pack'](engine+0x20,'<Q',123);m['pack'](engine+0x14e90,'<Q',stats)
    m['pack'](stats+0x18,'<Q',0xa0000);m['pack'](client+8+0x18,'<Q',0xb0000)
    m['pack'](engine+0x15370,'<Q',0xc0000);m['pack'](engine+0x15378,'<Q',0xd0000)
    m['pack'](0xc0000+0xb8,'<Q',0xe0000);m['pack'](0xd0000+0xb8,'<Q',0xf0000)
    m['pack'](base+world.CURRENT_DATE,'<HH',306,2030)
    fixture={'date':'2030-11-02','home_team':{'native_id':688},'away_team':{'native_id':713}}
    decoded={'team_ids':[(545,688),(570,713)],'teams':[0xe0000,0xf0000]}
    data={'signature':('native fixture identity',),'fixture':fixture,'decoded':decoded}
    monkeypatch.setattr(source,'_fixture',lambda *args:(data['signature'],data['fixture'],data['decoded'],2030,306))
    monkeypatch.setattr(source,'_resident_day',lambda *args:({'state':'unique_semantic_match'},0x110000))
    return m,data,client,engine


def test_typed_copied_inputs_current_day_and_private_contract(bound_context):
    m,data,client,engine=bound_context
    public,private=source.inspect_context(m['read'],m['base'],expected_current_date='2030-11-02')
    assert public['source_state']=='available_fixture_bound'
    assert public['bound_active_fixture']['date']=='2030-11-02'
    assert private['client']==client and private['engine']==engine and private['team_indices']==[545,570]
    assert public['gameplay_active']is None and public['halftime_state']is None
    assert 'address'not in repr(public) and hex(engine)not in repr(public)


def test_previous_day_client_never_becomes_current_match(bound_context):
    m,data,_,_=bound_context;data['fixture']['date']='2030-11-01'
    public,private=source.inspect_context(m['read'],m['base'])
    assert private is None and public['reason']=='viewable_fixture_not_current_career_date'


def test_handle_or_side_mismatch_rejects_not_merely_unknown(bound_context):
    m,data,client,engine=bound_context
    m['pack'](engine+0x20,'<Q',999)
    with pytest.raises(ValueError,match='handle disagree'):source.inspect_context(m['read'],m['base'])
    m['pack'](engine+0x20,'<Q',123);m['pack'](0xc0000+0xb8,'<Q',0xf0000)
    with pytest.raises(ValueError,match='canonical TEAM disagrees'):source.inspect_context(m['read'],m['base'])


def test_ambiguous_or_unloaded_resident_lookup_stays_unknown(bound_context,monkeypatch):
    m,*_=bound_context
    monkeypatch.setattr(source,'_resident_day',lambda *a:({'state':'absent_or_ambiguous'},None))
    public,private=source.inspect_context(m['read'],m['base'])
    assert private is None and public['source_state']=='present_unbound'


def test_client_engine_fixture_disagreement_rejected(bound_context,monkeypatch):
    m,data,*_=bound_context
    def fixture(*args):
        sig=('other identity',)if args[-1]==0xb0000 else data['signature']
        return sig,data['fixture'],data['decoded'],2030,306
    monkeypatch.setattr(source,'_fixture',fixture)
    with pytest.raises(ValueError,match='fixture identities disagree'):source.inspect_context(m['read'],m['base'])


def test_resident_day_requires_unique_complete_native_identity(monkeypatch):
    from fm_live_mcp import fixtures
    binding={'groups':[1,2],'flags':[1,1]}
    decoded={'team_ids':[(545,688),(570,713)],'name_identity':('same canonical name',1,2,3),
             'competition':{'database_index':7,'native_id':11},'season_code':2030,'stage_index':0}
    signature=(2030,306,tuple(decoded['team_ids']),7,11,2030,0,decoded['name_identity'][:4])
    monkeypatch.setattr(fixtures,'catalog',lambda *a:({}, {2030:binding},None))
    monkeypatch.setattr(fixtures,'bucket',lambda r,b,d,g:([0x10000]if g==0 else[],None))
    monkeypatch.setattr(fixtures,'record',lambda *a,**kw:decoded)
    result,address=source._resident_day(None,0,signature,2030,306,(1,2))
    assert address==0x10000 and result['state']=='unique_semantic_match'
    monkeypatch.setattr(fixtures,'bucket',lambda *a:([0x10000,0x20000],None))
    result,address=source._resident_day(None,0,signature,2030,306,(1,2))
    assert address is None and result['matching_records']==2
    binding['flags']=[1,0]
    assert source._resident_day(None,0,signature,2030,306,(1,2))[1]is None


def test_missing_input_stats_is_unknown_and_wrong_save_date_rejects(bound_context):
    m,_,_,engine=bound_context
    m['pack'](engine+0x14e90,'<Q',0)
    public,private=source.inspect_context(m['read'],m['base'])
    assert private is None and public['reason']=='owned_engine_statistics_absent'

    m['pack'](engine+0x14e90,'<Q',0x90000)
    with pytest.raises(ValueError,match='date differs'):
        source.inspect_context(m['read'],m['base'],expected_current_date='2030-11-01')
