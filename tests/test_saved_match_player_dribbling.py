import json
from pathlib import Path
import pytest
from fm_live_mcp.saved_match_player_dribbling import decode_player_dribbling, dribbling_field_registry, verify_native, NATIVE_SPANS
from fm_live_mcp.live_match_player_ranking import metric_catalog, metric_normalizations
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


def test_forest_all40_against_independent_events():
    packet=json.loads((Path(__file__).parent/'fixtures/player_dribbling_137388.json').read_text())
    counts=[]
    for row in packet['rows']:
        n=decode_player_dribbling(bytes.fromhex(row['raw_child_hex']))['dribbles_made']
        assert n==row['independent_CBE34_count']
        counts.append(n)
    assert len(counts)==40 and sum(counts)==22
    assert sum(n>0 for n in counts)==14 and sum(n==0 for n in counts)==26

def test_narrow_wide_and_unsigned_domain():
    for mode,offset in [(2,58),(0,62)]:
        raw=child(mode)
        assert decode_player_dribbling(bytes(raw))=={'dribbles_made':0}
        raw[offset]=255
        assert decode_player_dribbling(bytes(raw))=={'dribbles_made':255}

def test_boundaries_fail_closed():
    raw=bytes(child())
    for n in range(len(raw)):
        with pytest.raises(ValueError): decode_player_dribbling(raw[:n])
    with pytest.raises(ValueError):decode_player_dribbling(raw+b'\0')

def test_native_source_guards():
    spans=dict(NATIVE_SPANS);base=0x100000000
    verify_native(lambda address,size:spans[address-base],base)
    with pytest.raises(ValueError):verify_native(lambda address,size:bytes(size),base)

def test_catalog_has_no_attempt_or_carry_inference():
    row=metric_catalog()['metrics']['dribbles_made']
    assert row['provenance']==dribbling_field_registry()['dribbles_made']
    assert metric_normalizations('dribbles_made')==('total','per90')


def test_sqlite_preserves_new_field_and_older_capture_unknown(tmp_path, monkeypatch):
    from fm_live_mcp.match_dataset import build_connection
    from fm_live_mcp.captured_match_query import CapturedMatchQueries
    from fm_live_mcp import captured_match_sources as sources
    from test_captured_match_query import original, SOURCE
    from fm_live_mcp.match_data_query import MatchDataQueries
    fixture={'date':'2030-11-11','home_team':{'native_id':688},'away_team':{'native_id':692},'competition':{'native_id':11}}
    captured={'capture':{'save':{},'fixtures':[{'native_match_key':1,'fixture':fixture}]},'retained_players':[{'fixture_key':1,'side_index':0,'stored_player_slot':0,'person_index_word':1,'dribbles_made':3}]}
    db=build_connection(captured['capture'],retained_players=captured['retained_players'])
    table_columns=[row[1] for row in db.execute('pragma table_info(retained_players)')]
    view_columns=[row[1] for row in db.execute('pragma table_info(player_match_analysis)')]
    assert table_columns[-5:]==['pressure_completion_state','dribbles_made','distance_metres','sprints','open_play_final_third_passes']
    assert view_columns[-8:]==['stored_match_position_mask','stored_match_position','stored_match_position_state','direct_free_kick_goals','dribbles_made','distance_metres','sprints','open_play_final_third_passes']
    assert db.execute('select dribbles_made from retained_players').fetchone()==(3,)
    assert db.execute('select dribbles_made from player_match_analysis').fetchone()==(3,)
    db.close()
    page=MatchDataQueries(capture=lambda *a,**kw:captured,epoch=lambda *a:'epoch').query(None,'session',['ref'],'retained_players',fields=['dribbles_made'])
    assert page['rows']==[{'dribbles_made':3}]
    path,pin=original(tmp_path,monkeypatch)
    import sqlite3
    old=sqlite3.connect(path)
    old.execute('drop view player_match_analysis')
    old.execute('alter table retained_players drop column dribbles_made')
    old.commit();old.close()
    with sources.open_source(SOURCE) as (_,provenance):pass
    page=CapturedMatchQueries().query(SOURCE,provenance['capture_id'],table='retained_players',fields=['dribbles_made'])
    assert all(row['dribbles_made'] is None for row in page['rows'])
    assert page['dribbling_field_availability']=='unknown_not_in_registered_capture'


def test_rank_count_preserves_zeros_and_missing_is_unknown():
    from fm_live_mcp.live_match_player_ranking import rank_capture
    from test_live_match_player_ranking import data,fixture,player
    packet=data([fixture(1)],[player(1,person=1,dribbles_made=2),player(1,person=2,dribbles_made=0),player(1,person=3)])
    result=rank_capture(packet,'dribbles_made','total',0)
    assert [r['observed_total']for _,r in result['ranked']]==[2,0]
    assert result['unclassified_reason_counts']['missing_selected_metric']==1
