import pytest
from fm_live_mcp import saved_match_player_defensive as query
from fm_live_mcp import saved_match_statistics_wire as wire

def child(mode=2):
    # Minimal valid variable group/footer profile, no nested records.
    raw=bytearray(252 if mode==2 else 256)
    raw[0]=mode
    # Exact minimal geometry determined by the accepted native player reader.
    width=4 if mode==2 else 8
    base=1+width+sum((2,5,5,8,4,4,4,4,12,2,1,15,5,4,6,3,3,3,2,2,1,1,8,5,8,5,8))+sum((1,4,4,16,4,12,9,6,4,4,2,2,2,2,2,2,4,1))
    raw=raw[:base+1+4+1]
    assert wire.player(bytes(raw),0)['end']==len(raw)
    return raw

def test_fields_independent_and_zero_preserved():
    raw=child()
    for off,value in ((95,10),(96,7),(100,3),(153,255)):raw[off]=value
    assert query.decode_player_defensive(bytes(raw))==dict(aerial_duels_attempted=10,aerial_duels_completed=7,interceptions=3,clearances=255)
    assert all(v==0 for v in query.decode_player_defensive(bytes(child())).values())

def test_wide_reference_shifts_all_fields():
    raw=child(0)
    for off in (95,96,100,153):raw[off+4]=9
    assert set(query.decode_player_defensive(bytes(raw)).values())=={9}

def test_truncated_and_trailing_children_rejected():
    raw=bytes(child())
    for end in range(len(raw)):
        with pytest.raises(ValueError):query.decode_player_defensive(raw[:end])
    with pytest.raises(ValueError,match='extent'):query.decode_player_defensive(raw+b'\x00')
