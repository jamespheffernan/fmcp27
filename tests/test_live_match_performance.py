import math,struct
import pytest
from fm_live_mcp import live_match_performance as q


def side(team=545,shots=4,target=3,xg=.5935614109039307,attempts=91,completed=75):
    b=bytearray(0x1a0);struct.pack_into('<I',b,0x5c,team);b[0x16f]=shots;b[0x170]=target
    struct.pack_into('<f',b,0x60,xg);struct.pack_into('<hh',b,0xd8,attempts,completed)
    return bytes(b)


def test_side_known_counters_and_true_zero_preserve_unknown_units():
    r=q.decode_side(side(),545)
    assert(r['shots'],r['shots_on_target'],r['passes_attempted'],r['passes_completed'])==(4,3,91,75)
    z=q.decode_side(side(shots=0,target=0,xg=0,attempts=0,completed=0),545)
    assert z['shots']==0 and z['pass_completion_percentage_computed']is None
    assert z['possession_time_units']is None and z['chances']is None


@pytest.mark.parametrize('kwargs',[{'team':570},{'target':5},{'xg':math.nan},{'xg':-1},{'completed':92},{'attempts':-1}])
def test_wrong_team_and_invalid_counter_sources_reject(kwargs):
    with pytest.raises(ValueError):q.decode_side(side(**kwargs),545)


def fixture(team=545):
    return {'date':'2030-11-02','competition':{'native_id':11},'home_team':{'database_index':team,'native_id':688,'native_type_code':0},'away_team':{'database_index':570,'native_id':713,'native_type_code':0}}


def source(monkeypatch,wrong_fixture=False):
    base=0x100000000;client=0x200000000;engine=0x300000000;owner=0x400000000;stats=0x500000000
    memory={}
    def put(at,b):
        for i,v in enumerate(b):memory[at+i]=v
    def pointer(at,v):put(at,struct.pack('<Q',v))
    for at,b in q.NATIVE_SPANS:put(base+at,bytes.fromhex(b))
    pointer(client,base+0x55fac38);pointer(engine,base+0x55fa258);pointer(client+0xf8,owner);pointer(owner+0x18,engine);pointer(engine+0x14e90,stats)
    for at,vt,fptr,count in[(stats,0x55fa850,10,4),(client+8,0x56a2380,20,3)]:
        b=bytearray(0x78);struct.pack_into('<Q',b,0,base+vt);struct.pack_into('<Q',b,0x18,fptr)
        for index,team in enumerate((545,570)):
            ptr=at+0x1000+index*0x1000;struct.pack_into('<Q',b,0x68+8*index,ptr);put(ptr,side(team=team,shots=count))
        put(at,b)
    monkeypatch.setattr(q,'_fixture',lambda r,b,p:fixture(999 if wrong_fixture and p==20 else 545))
    read=lambda at,n:bytes(memory[at+i]for i in range(n))
    return read,base,client,engine,memory


def test_real_engine_ahead_pattern_never_claims_displayed_statistics(monkeypatch):
    r,b,c,e,_=source(monkeypatch);out=q.inspect(r,b,c,e)
    assert out['sides'][0]['shots']==4 and out['client_statistics_snapshot']['sides'][0]['shots']==3
    assert not out['engine_client_statistics_equal']and not out['displayed_time_statistics_verified']
    assert not out['archive_or_saved_fixture_fallback']


def test_wrong_owner_and_changed_native_binding_fail(monkeypatch):
    r,b,c,e,m=source(monkeypatch);m[c+0xf8+4]=0
    with pytest.raises(ValueError):q.inspect(r,b,c,e)
    r,b,c,e,m=source(monkeypatch);m[b+q.NATIVE_SPANS[0][0]]^=1
    with pytest.raises(ValueError,match='native binding'):q.inspect(r,b,c,e)


def test_mismatched_fixture_side_fails_before_publication(monkeypatch):
    r,b,c,e,_=source(monkeypatch,True)
    with pytest.raises(ValueError,match='TEAM'):q.inspect(r,b,c,e)
