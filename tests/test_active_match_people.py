import struct
import pytest
from fm_live_mcp.active_match_people import inspect


def fixture():
    memory = {}
    def put(a, b):
        memory.update((a+i, v) for i, v in enumerate(b))
    def q(a, n): put(a, struct.pack('<Q', n))
    def typed(a, table, name):
        q(a, table); put(table-16, struct.pack('<qQ', 0, table+0x1000))
        q(table+0x1008, table+0x2000); put(table+0x2000, name+b'\0')
    def read(a, n): return bytes(memory.get(a+i, 0) for i in range(n))
    engine=0x10000; side=0x20000; other=0x30000; player=0x40000
    typed(engine, 0x55FA258, b'10GAME_MATCH')
    typed(player, 0x569EE68, b'N7simatch12MATCH_PLAYERE')
    q(engine+0x15370,side);q(engine+0x15378,other);q(side+0x140,player)
    q(player+0x280,engine);q(player+0x288,side);q(player+0x20,0x60000)
    put(player+0x1E26,b'\x01');put(player+0x1E51,b'\x09')
    return read,q,put,engine,player


def test_join_keeps_participation_unknown_and_slots_separate():
    read,q,put,engine,player=fixture()
    r=inspect(read,0,engine,{0:{0x60000:{'native_id':49037698}}})['rows']
    assert len(r)==52
    assert r[0]['person']=={'native_id':49037698}
    assert r[0]['engine_array_index']==0 and r[0]['tactics_index_raw']==9
    assert r[0]['on_pitch'] is None and r[0]['display_time_participation'] is None
    assert r[1]['identity_state']=='null_object'


def test_cross_side_and_unmatched_do_not_acquire_an_identity():
    read,q,put,engine,player=fixture()
    r=inspect(read,0,engine,{1:{0x60000:{'native_id':123}}})['rows'][0]
    assert r['person'] is None and r['identity_state']=='unmatched_canonical_roster_pointer'
    q(player+0x288,0)
    r=inspect(read,0,engine,{0:{0x60000:{'native_id':123}}})['rows'][0]
    assert r['person'] is None and r['identity_state']=='side_owner_absent_unclassified'


def test_wrong_engine_fails_closed():
    read,q,put,engine,player=fixture();q(player+0x280,0x70000)
    with pytest.raises(ValueError,match='engine mismatch'):
        inspect(read,0,engine,{})


def test_compact_route_checks_table_and_team_without_profile_api(monkeypatch):
    from fm_live_mcp import active_match_people as source, database, players, world
    read,q,put,engine,mp=fixture()
    person=0x60000; primary=person-0x388; table_start=0x80000
    q(0x20000+0xB8,0x90000);q(0x30000+0xB8,0xA0000)
    q(primary,players.RVA[0]);q(person,players.RVA[2]);put(person+8,struct.pack('<III',3,49037698,49037698))
    put(players.RVA[2]-16,struct.pack('<q',-0x388));q(table_start+3*8,person)
    monkeypatch.setattr(database,'table',lambda *a:{'start':table_start,'count':4})
    monkeypatch.setattr(world,'typed',lambda *a:None)
    monkeypatch.setattr(world,'vector',lambda r,a,n:[primary] if a==0x90000+0x38 else [])
    monkeypatch.setattr(players,'name_part',lambda *a:'')
    monkeypatch.setattr(players,'common_name',lambda *a:'Adli')
    result=source.inspect_canonical(read,0,engine)['rows'][0]
    assert result['person']['name']=='Adli'
    assert result['person']['native_identity']=={'database_index':3,'native_id':49037698,'random_id':None}
    # Same typed PERSON/header at a different table slot must not become a name join.
    q(table_start+3*8,person+8)
    assert source.inspect_canonical(read,0,engine)['rows'][0]['person'] is None


def test_compact_virtual_identity_does_not_require_name_or_profile(monkeypatch):
    from fm_live_mcp import active_match_people as source, database, virtual_identity, world
    read,q,put,engine,mp=fixture()
    person=0x60000; primary=person-0x20; table_start=0x80000
    q(0x20000+0xB8,0x90000);q(0x30000+0xB8,0xA0000);put(0x90000+8,struct.pack('<I',17))
    q(primary,world.TYPES['virtual_player'][0]);q(person,virtual_identity.PERSON_RVA)
    put(person+8,struct.pack('<III',3,20021111,0));put(virtual_identity.PERSON_RVA-16,struct.pack('<q',-0x20));q(table_start+3*8,person)
    monkeypatch.setattr(database,'table',lambda *a:{'start':table_start,'count':4})
    monkeypatch.setattr(world,'typed',lambda *a:None)
    monkeypatch.setattr(world,'vector',lambda r,a,n:[primary] if a==0x90000+0x38 else [])
    monkeypatch.setattr(virtual_identity,'inspect',lambda *a:{'stored_team_index':17})
    row=source.inspect_canonical(read,0,engine)['rows'][0]
    assert row['person']['record_kind']=='virtual'
    assert row['person']['name'] is None
    assert row['person']['native_identity']['native_id']==20021111


@pytest.mark.parametrize('status,flags,on,off,sent,expected',[
    (1,0,0,0,0,('on_pitch',True)),
    (1,32,78,0,0,('substitute_on_pitch',True)),
    (3,0,0,78,0,('substituted_off',False)),
    (2,0,0,0,62,('sent_off',False)),
    (8,32,0,0,0,('unused_substitute',False)),
    (3,0,0,0,0,('unknown',None)),
    (1,0,0,78,0,('unknown',None)),
    (8,32,78,0,0,('unknown',None)),
    (5,0,0,59,0,('unknown',None)),
    (9,0,0,0,0,('unknown',None)),
])
def test_guarded_engine_states(status,flags,on,off,sent,expected):
    from fm_live_mcp.active_match_people import engine_participation
    assert engine_participation(status,flags,on,off,sent)==expected


def test_participation_requires_matching_stats_person_and_leaves_display_unknown(monkeypatch):
    from fm_live_mcp import active_match_people as source
    read,q,put,engine,mp=fixture();stats=0xB0000;table=0x55FA800
    q(mp+0x1880,stats);q(stats,table);put(table-16,struct.pack('<qQ',0,table+0x1000))
    q(table+0x1008,table+0x2000);put(table+0x2000,b'23GAME_MATCH_PLAYER_STATS\0')
    put(stats+0x18,struct.pack('<I',3));put(stats+0x5C,b'\x20');put(stats+0xAF,b'\x4e')
    monkeypatch.setattr(source,'PARTICIPATION_SPANS',())
    result=source.inspect(read,0,engine,{0:{0x60000:{'native_identity':{'database_index':3}}}})
    r=source.add_engine_participation(read,0,engine,result)['rows'][0]
    assert r['engine_participation']=='substitute_on_pitch' and r['engine_on_pitch'] is True
    assert r['on_pitch'] is None and r['display_time_participation'] is None
    put(stats+0x18,struct.pack('<I',4))
    r=source.add_engine_participation(read,0,engine,result)['rows'][0]
    assert r['engine_on_pitch'] is None and r['engine_participation_source']=='stats_person_index_mismatch'


def test_changed_native_participation_pin_fails_closed():
    from fm_live_mcp import active_match_people as source
    read,q,put,engine,mp=fixture()
    with pytest.raises(ValueError,match='native source changed'):
        source.add_engine_participation(read,0,engine,{'rows':[]})


def test_actor_join_uses_original_slot_not_tactical_position(monkeypatch):
    from fm_live_mcp import active_match_people as source
    read,q,put,engine,mp=fixture();stats=0xB0000;table=0x55FA800
    q(engine+0x20,12345);q(mp+0x1880,stats);q(stats,table)
    put(table-16,struct.pack('<qQ',0,table+0x1000));q(table+0x1008,table+0x2000)
    put(table+0x2000,b'23GAME_MATCH_PLAYER_STATS\0');put(stats+0x18,struct.pack('<I',3))
    put(mp+0x1E27,b'\x00');put(mp+0x1E51,b'\x09')
    row={'side_index':0,'engine_array_index':0,'person':{'name':'Adli','native_identity':{'database_index':3,'native_id':49037698}},'identity_state':'canonical'}
    monkeypatch.setattr(source,'_inspect_canonical_team',lambda *a,**kw:{'rows':[row]})
    monkeypatch.setattr(source,'ACTOR_SLOT_SPANS',())
    result=source.inspect_actor_bindings(read,0,engine,expected_match_unique_id=12345)
    assert result['players'][0]['stored_player_slot']==0
    assert result['players'][0]['canonical_person_id']==49037698
    # A different stored roster slot cannot be silently relabelled to array or tactics index.
    put(mp+0x1E27,b'\x09')
    result=source.inspect_actor_bindings(read,0,engine,expected_match_unique_id=12345)
    assert not result['players']
    assert result['unresolved'][0]['reason']=='native_original_roster_slot_differs_from_checked_array_index'
    with pytest.raises(ValueError,match='official match identity changed'):
        source.inspect_actor_bindings(read,0,engine,expected_match_unique_id=54321)


def test_identity_only_does_not_consume_current_role_or_status_bytes():
    read,q,put,engine,mp=fixture()
    forbidden={mp+0x1E51,mp+0xCD8,mp+0xDB0,mp+0x1E26}
    def guarded(a,n):
        assert a not in forbidden
        return read(a,n)
    result=inspect(guarded,0,engine,{0:{0x60000:{'native_id':49037698}}},identity_only=True)
    assert result['rows'][0]['person']=={'native_id':49037698}
    assert 'tactics_index_raw' not in result['rows'][0]
