import pytest
from fm_live_mcp.active_player_physical import decode, inspect


@pytest.mark.parametrize('raw,integer,fraction', [(0,0,0),(1,0,.0001),(769999,76,76.9999),(1000000,100,100)])
def test_native_integer_and_explicit_fractional_condition(raw,integer,fraction):
    row=decode(raw,9999)
    assert row['condition_percent_native_integer']==integer
    assert row['condition_percent_computed']==pytest.approx(fraction)
    assert row['sharpness_percent_native_integer']==99
    assert row['sharpness_percent_computed']==99.99
    assert row['fixture_eligibility']=='not_evaluated'
    assert row['medical_minutes_recommendation']is None


@pytest.mark.parametrize('raw',[-1,1000001])
def test_unsupported_condition_is_not_clamped_or_clearance(raw):
    row=decode(raw,0)
    assert row['condition_raw_i32']==raw
    assert row['condition_percent_computed']is None
    assert row['sharpness_percent_computed']==0


@pytest.mark.parametrize('raw',[-1,10001])
def test_unsupported_sharpness_remains_unknown(raw):
    assert decode(1000000,raw)['sharpness_percent_computed']is None


def test_guard_rejects_missing_id_and_native_code_drift():
    with pytest.raises(ValueError,match='identity'):
        inspect(lambda a,n:b'\0'*n,0x100000,0x200000,expected_match_unique_id=0)
    with pytest.raises(ValueError,match='native binding'):
        inspect(lambda a,n:b'\0'*n,0x100000,0x200000,expected_match_unique_id=1)


def test_bound_player_identity_and_owners_rechecked(monkeypatch):
    import struct
    from fm_live_mcp import active_player_physical as module
    base,engine,side,player,person=0x10000000,0x20000000,0x30000000,0x40000000,0x50000000
    memory={base+a:raw for a,raw in module.NATIVE_SPANS}
    for address,value in ((engine+0x20,99),(engine+0x15370,side),(side+0x140,player),
                          (player+0x280,engine),(player+0x288,side),(player+0x20,person)):
        memory[address]=struct.pack('<Q',value)
    memory[person+8]=struct.pack('<II',10,123)
    memory[player+0x1c74]=struct.pack('<i',765432)
    memory[player+0xc88]=struct.pack('<h',9876)
    def read(address,length):
        value=memory[address]
        assert len(value)==length
        return value
    monkeypatch.setattr(module.active_match_people,'_type',lambda *a:None)
    monkeypatch.setattr(module.active_match_people,'inspect_canonical',lambda *a,**k:{'rows':[
        {'side_index':0,'engine_array_index':0,'identity_state':'canonical',
         'person':{'name':'Example','native_identity':{'database_index':10,'native_id':123}}}]})
    result=module.inspect(read,base,engine,expected_match_unique_id=99)
    assert result['rows'][0]['physical']['condition_percent_computed']==76.5432
    assert result['displayed_time_verified']is False
    memory[person+8]=struct.pack('<II',10,456)
    with pytest.raises(ValueError,match='canonical PERSON changed'):
        module.inspect(read,base,engine,expected_match_unique_id=99)
    memory[person+8]=struct.pack('<II',10,123)
    memory[player+0x288]=struct.pack('<Q',side+8)
    with pytest.raises(ValueError,match='owner changed'):
        module.inspect(read,base,engine,expected_match_unique_id=99)
    with pytest.raises(ValueError,match='match identity changed'):
        module.inspect(read,base,engine,expected_match_unique_id=100)
