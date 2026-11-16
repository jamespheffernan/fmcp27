import struct
import pytest
from fm_live_mcp import current_cup_history as source
from test_competition_scorers import Memory, census


def test_phase_matches_native_round_and_retains_zero_flags(monkeypatch):
    m=Memory();base=0x100000000;runtime=0x10000;stage=0x20000;fixture=0x30000
    m.put(runtime+0x49,bytes.fromhex('01ffff00'));m.put(runtime+0x3be,b'\x03')
    m.put(fixture+0x38,b'\x00\x03');m.put(fixture+0x54,b'\xff')
    m.pack(stage,'<Q',base+0x5671128);m.pack(stage+0x90,'<Q',0x40000)
    methods=((0x2f8,0x3c9c284),(0x2d8,0x3b8c0a0),(0x2c8,0x3b8c090),
             (0x2c0,0x3c9c27c),(0x360,0x3c6c498),(0x368,0x3c9c290))
    for slot,rva in methods:m.pack(base+0x5671128+slot,'<Q',base+rva)
    m.put(0x50100+0x137,b'\x01');m.pack(runtime+0x388,'<Q',0x60000)
    m.pack(0x60000+0x1f0,'<Q',0x70000);m.pack(0x80000+0x70,'<Q',0x90000)
    m.put(0x90000+0x18,b'\x01\x01')
    monkeypatch.setattr(source.competition_stages,'typed',lambda *a:None)
    monkeypatch.setattr(source.competition_stages,'vector',lambda read,at,limit:
        ((stage,),())if at==runtime+0x1d8 else ((0,0,0,0x50100),())if at==0x40058 else ((0,0x80000),()))
    call=lambda:source.phase(m.read,base,runtime,fixture,stage)
    assert call()['phase_index']==1 and call()['rule_flags']==[1]
    m.put(0x90018,b'\0');assert call()['rule_flags']==[]
    m.put(runtime+0x4c,b'\x08')
    with pytest.raises(source.UnsupportedHistory,match='override'):call()
    m.put(runtime+0x4c,b'\0');m.put(fixture+0x39,b'\x7f')
    with pytest.raises(source.UnsupportedHistory,match='round'):call()


@pytest.fixture
def pool(census,monkeypatch):
    c=census
    monkeypatch.setattr(source,'verify_native',lambda *a:None)
    monkeypatch.setattr(source,'phase',lambda *a:{'rule_flags':[1]})
    monkeypatch.setattr(source.teams,'lookup',lambda *a:{'count':1000})
    monkeypatch.setattr(source.teams,'by_index',lambda r,b,i,**k:({'database_index':i,'native_id':688},{}))
    return c


def collect(c):
    return source.collect(c['memory'].read,c['base'],{},0,{'season_code':2030},
                          {'kind':'cup','address':0x12300},{0,1,2})


def test_present_same_team_absent_and_raw_zero_are_distinct(pool):
    c=pool;c['memory'].put(0x5000a,b'\0');c['memory'].put(0x500b6,b'\x03')
    coverage,rows=collect(c)
    assert coverage['complete_resident_lookup'] and coverage['physical_row_count']==2
    assert rows[0]['stored_appearance_counter_raw_u8']==0 and rows[0]['state']=='present'
    assert rows[2]['stored_appearance_counter_raw_u8']is None and rows[2]['state']=='absent'
    a=source.condition(rows[0],545,[1]);b=source.condition(rows[2],545,[1])
    assert a['native_other_team_cup_history_condition']is False
    assert b['native_other_team_cup_history_condition']is False
    assert a['historical_other_team_appearance']is None
    assert b['historical_other_team_appearance']is None


def test_other_team_flag1_does_not_require_positive_appearances(pool):
    pool['memory'].pack(0x50004,'<I',460)
    _,rows=collect(pool);row=source.condition(rows[0],545,[1])
    assert row['stored_appearance_counter_raw_u8']==0
    assert row['native_other_team_cup_history_condition']is True
    assert row['historical_other_team_appearance']is None
    assert '_team_index'not in row
    assert source.condition(rows[0],545,[6])['native_other_team_cup_history_condition']is None


def test_missing_empty_duplicate_and_unassigned(pool):
    c=pool;c['memory'].pack(c['stats']+0x1278,'<QQQ',0,0,0)
    coverage,rows=collect(c);assert coverage['source_state']=='available'
    assert all(row['state']=='absent'for row in rows.values())
    c['memory'].pack(c['runtime']+0x390,'<Q',0)
    coverage,rows=collect(c);assert rows is None and coverage['physical_row_count']is None
    c['memory'].pack(c['runtime']+0x390,'<Q',c['stats'])
    c['memory'].pack(c['stats']+0x1278,'<QQQ',0x40000,0x40010,0x40010)
    c['memory'].pack(0x500ac,'<I',0)
    _,rows=collect(c);assert rows[0]['state']=='unavailable'
    assert source.condition(rows[0],545,[1])['native_other_team_cup_history_condition']is None
    c['memory'].pack(0x500ac,'<I',1);c['memory'].pack(0x50004,'<I',0xffffffff)
    _,rows=collect(c);assert rows[0]['last_associated_team']is None
    assert source.condition(rows[0],545,[1])['native_other_team_cup_history_condition']is True


def test_wrong_season_and_shared_runtime_not_current_absence(pool):
    c=pool;c['context']['shared_runtime']=True
    assert collect(c)[1]is None
    c['context']['shared_runtime']=False;c['context']['native_season_code']=2029
    assert collect(c)[0]['unavailable_reason']=='fixture_runtime_season_mismatch'


def test_every_additional_native_guard_required(monkeypatch):
    import json
    from pathlib import Path
    m=Memory();base=0x100000000
    for row in json.loads((Path(__file__).parent/'fixtures/current_cup_history_native.json').read_text()):
        m.put(base+row['rva'],bytes.fromhex(row['hex']))
    monkeypatch.setattr(source.competition_scorers,'verify_native',lambda *a:None)
    source.verify_native(m.read,base)
    for at,size,expected in (*source.NATIVE_GUARDS,*source.PRODUCER_GUARDS):
        old=m.read(base+at,1);m.put(base+at,bytes([old[0]^1]))
        with pytest.raises(ValueError,match='native context'):source.verify_native(m.read,base)
        m.put(base+at,old)


def test_raw_counter_255_and_malformed_pool(pool):
    pool['memory'].put(0x5000a,b'\xff')
    _,rows=collect(pool)
    assert rows[0]['stored_appearance_counter_raw_u8']==255
    pool['memory'].pack(pool['stats']+0x1278,'<QQQ',0x40000,0x40011,0x40018)
    coverage,rows=collect(pool)
    assert rows is None and coverage['physical_row_count']is None


def test_current_source_requires_cup_runtime_and_preserves_epoch(pool):
    c=pool
    c['memory'].put(c['runtime']+0x3be,b'\x03')
    call=lambda:source.collect_current(c['memory'].read,c['base'],{},{0,1,2})
    coverage,rows=call()
    assert coverage['native_season_code']==2030 and coverage['phase'] is None
    assert rows[0]['state']=='present' and rows[2]['state']=='absent'
    c['memory'].put(c['runtime']+0x3be,b'\x00')
    coverage,rows=call()
    assert rows is None and coverage['unavailable_reason']=='unsupported_or_shared_cup_runtime'
    c['memory'].put(c['runtime']+0x3be,b'\x03')
    c['context']['shared_runtime']=True
    assert call()[1] is None
