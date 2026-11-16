import struct
import pytest
from fm_live_mcp import active_match_score as source


def incident(tick,side=0,kind=1):
    raw=bytearray(32);struct.pack_into('<i',raw,0x18,tick);raw[0x1d]=side;raw[0x1f]=kind
    return bytes(raw)


def test_goal_cursor_before_equal_after_and_inclusive_multiple_ties():
    rows=[incident(10),incident(10,1),incident(11,0,3)]
    assert source.project_incidents(rows,9)['native_u8_score']=={'home':0,'away':0}
    assert source.project_incidents(rows,10)['native_u8_score']=={'home':1,'away':1}
    assert source.project_incidents(rows,11)['native_u8_score']=={'home':2,'away':1}


def test_own_goal_reverses_side_and_shootout_or_non_goal_records_do_not_count():
    rows=[incident(1,0,2),incident(2,1,2),incident(2,0,7),incident(2,1,8),incident(2,0,38)]
    assert source.project_incidents(rows,2)['native_u8_score']=={'home':1,'away':1}


def test_physical_order_stops_at_first_future_like_native_not_sorted_or_deduped():
    row=incident(3)
    assert source.project_incidents([row,row,incident(10),incident(2,1)],5)['native_u8_score']=={'home':2,'away':0}


def test_empty_zero_negative_cursor_and_unsigned_wrap_are_distinct():
    assert source.project_incidents([],0)['home_goals']==0
    assert source.project_incidents([], -1)['home_goals']is None
    r=source.project_incidents([incident(0)]*256,0)
    assert r['home_goals']is None and r['native_u8_score']['home']==0
    with pytest.raises(ValueError):source.project_incidents([bytes(31)],0)


@pytest.fixture
def memory():
    cells={};base=0x100000000;backing=0x10000;provider=0x20000;match=0x30000;owner=0x40000;stats=0x50000;vector=0x60000
    def put(at,raw):cells.update({at+i:b for i,b in enumerate(raw)})
    def pack(at,fmt,*args):put(at,struct.pack(fmt,*args))
    def read(at,n):return bytes(cells[at+i]for i in range(n))
    for rva,raw in source.NATIVE_SPANS:put(base+rva,raw)
    pack(base+0x5721eb0,'<Q',0xa0000);pack(0xa0000,'<Q',base+0x54ec0c8)
    pack(0xa0000+0x58,'<Q',backing);pack(0xa0000+0x60,'<Q',0)
    pack(backing,'<Q',base+0x54ec490);pack(backing+0x10,'<Q',backing)
    pack(backing+0x1408,'<Q',provider);pack(provider+0x28,'<Q',match)
    pack(match,'<Q',base+0x55fa258);pack(match+0x20,'<Q',123)
    pack(backing+0x1dc0,'<i',50);pack(provider,'<Q',owner);pack(owner+0x58,'<Q',stats)
    pack(stats,'<Q',base+0x55fa850);pack(stats+0x38,'<QQQ',vector,vector+24,vector+24)
    pack(vector,'<QQQ',0x70000,0x80000,0x90000)
    put(0x70000,incident(20));put(0x80000,incident(40,1,2));put(0x90000,incident(55,1))
    bound={'playback_address':backing,'frame_provider_address':provider,'source_match_address':match,
           'official_match_unique_id':123,'current_time_slice':50}
    half={'state':'verified_first_half_boundary','official_match_unique_id':123,
          'period':'FirstHalf','time_slice_domain':'native_playback_time_slice',
          'start_tick':0,'end_tick':30,'time_slice':30,'second_half_start_tick':31}
    return locals()


def capture(m,**kw):return source.capture(m['read'],m['base'],bound_playback=m['bound'],**kw)


def test_exact_bound_score_and_historical_half_do_not_use_result_score(memory):
    m=memory;r=capture(m,trusted_first_half_boundary=m['half'])
    assert r['current_score']['native_u8_score']=={'home':2,'away':0}
    assert r['first_half_score']['native_u8_score']=={'home':1,'away':0}
    assert r['current_time_slice']==50 and r['first_half_score']['at_time_slice']==30
    assert r['engine_result_score_used']is False
    assert 'address'not in repr(r)and hex(m['stats'])not in repr(r)


def test_missing_or_unproved_boundary_stays_unknown_not_zero(memory):
    assert capture(memory)['first_half_score']['home_goals']is None
    half={**memory['half'],'state':'unproved'}
    assert capture(memory,trusted_first_half_boundary=half)['first_half_score']['home_goals']is None


@pytest.mark.parametrize('change',[{'time_slice':60,'end_tick':60},{'end_tick':31},
    {'second_half_start_tick':30},{'period':'SecondHalf'},{'start_tick':-1}])
def test_half_boundary_future_or_ambiguous_or_wrong_period_unknown(memory,change):
    result=capture(memory,trusted_first_half_boundary={**memory['half'],**change})
    assert result['first_half_score']['home_goals']is None


def test_wrong_source_boundary_rejected(memory):
    with pytest.raises(ValueError,match='another playback source'):
        capture(memory,trusted_first_half_boundary={**memory['half'],'official_match_unique_id':456})


@pytest.mark.parametrize('target', ['provider','match_id','cursor','native','backing'])
def test_source_or_native_drift_rejected(memory,target):
    m=memory
    if target=='provider':m['pack'](m['backing']+0x1408,'<Q',0x123400)
    elif target=='match_id':m['pack'](m['match']+0x20,'<Q',999)
    elif target=='cursor':m['pack'](m['backing']+0x1dc0,'<i',51)
    elif target=='native':m['put'](m['base']+source.NATIVE_SPANS[0][0],b'\0')
    else:m['pack'](m['backing']+0x10,'<Q',999)
    with pytest.raises(ValueError):capture(m)


def test_future_or_past_user_cursor_is_not_current_bound_score(memory):
    with pytest.raises(ValueError,match='differs'):capture(memory,current_time_slice=49)
    with pytest.raises(ValueError,match='differs'):capture(memory,current_time_slice=51)


def test_malformed_or_excessive_vector_not_zero_score(memory):
    m=memory;m['pack'](m['stats']+0x38,'<QQQ',0x60000,0x60001,0x60008)
    with pytest.raises(ValueError):capture(m)
    m['pack'](m['stats']+0x38,'<QQQ',0x60000,0x68000,0x68000)
    with pytest.raises(ValueError):capture(m)


def test_actual_verified_running_match_ledger_cursor_and_goal_boundary_controls():
    import json
    from pathlib import Path
    packet=json.loads((Path(__file__).parent/'fixtures/playback_score_incidents.json').read_text())
    assert packet['readset_epoch_verified']is True
    rows=[bytes.fromhex(row)for row in packet['records']]
    assert source.project_incidents(rows,packet['current_time_slice'])['native_u8_score']=={'home':3,'away':1}
    # Equal-time goal+non-goal incident pairs must not double the score.
    for tick,expected in [(5617,(0,0)),(5618,(1,0)),(5619,(1,0)),
                          (11711,(1,0)),(11712,(2,0)),(13209,(2,0)),
                          (13210,(2,1)),(19322,(2,1)),(19323,(3,1))]:
        r=source.project_incidents(rows,tick)
        assert (r['home_goals'],r['away_goals'])==expected
    #11544 is an independently observed native boundary, not45minutes. This
    # frozen replay verifies selection only, not a new same-epoch runtime read.
    assert source.project_incidents(rows,11544)['native_u8_score']=={'home':1,'away':0}


def test_unknown_native_goal_side_is_ignored_exactly_like_native_selector():
    assert source.project_incidents([incident(1,2,1),incident(1,255,2)],1)['native_u8_score']=={'home':0,'away':0}


def test_stale_readable_backing_removed_from_current_primary_owner_rejected(memory):
    m=memory;m['pack'](0xa0000+0x58,'<Q',0)
    with pytest.raises(ValueError,match='no longer a unique current owner'):capture(m)
    m['pack'](0xa0000+0x58,'<Q',m['backing']);m['pack'](0xa0000+0x60,'<Q',m['backing'])
    with pytest.raises(ValueError,match='no longer a unique current owner'):capture(m)
