import gzip
import json
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from fm_live_mcp import live_retained_shots as query

CONTROLS=json.loads(gzip.decompress((Path(__file__).parent/'fixtures/retained_shot_maps.json.gz').read_bytes()))


def values(key):
    c=next(c for c in CONTROLS if c['key']==key)
    return c,[bytes.fromhex(v)for v in c['vectors']],bytes.fromhex(c['events'])


def test_actual_eighteen_reconciled_attempts_have_raw_coordinates():
    c,v,e=values(132398);r=query.decode_attempts(v,e,c['teams'])
    assert r['state']=='available'and len(r['shots'])==18 and not r['own_goal_markers']
    assert all(s['state']=='available'and all(s['checks'].values())for s in r['side_coverage'])
    assert all(s['coordinate_units']is None and s['coordinate_viewpoint']is None for s in r['shots'])
    assert any(s['native_y']<0 for s in r['shots'])and any(s['native_y']>0 for s in r['shots'])
    assert all('shooter'not in s for s in r['shots'])


def test_real_southampton_forest_own_goal_is_a_separate_marker_not_a_thirteenth_shot():
    c,v,e=values(135904);r=query.decode_attempts(v,e,c['teams'])
    assert r['state']=='available'and len(r['shots'])==23
    home,away=r['side_coverage'];assert home['retained_record_count']==13 and home['shot_count']==12
    assert home['own_goal_marker_count']==1 and away['shot_count']==11
    marker,=r['own_goal_markers'];assert marker['native_category_code']==49
    assert(marker['event_side_index'],marker['beneficiary_side_index'],marker['stored_player_slot'])==(1,0,3)
    assert not marker['statistical_shot']


@pytest.mark.parametrize('cross_side',[False,True])
def test_duplicate_own_goal_event_reference_never_passes_on_zero_xg(cross_side):
    c,v,e=values(135904);ids={struct.unpack_from('<I',e,a+44)[0]:e[a:a+56]for a in range(0,len(e),56)}
    marker=next(v[0][a:a+48]for a in range(0,len(v[0]),48)if ids[struct.unpack_from('<I',v[0],a+36)[0]][42]==49)
    v[1 if cross_side else 0]+=marker;r=query.decode_attempts(v,e,c['teams'])
    assert r['state']=='available_partial'
    assert r['side_coverage'][0]['shot_count']is None
    assert r['side_coverage'][0]['own_goal_marker_count']is None
    assert not r['own_goal_markers']
    assert any(x['reason']=='duplicate_retained_event_reference'for x in r['side_coverage'][0]['link_errors'])
    if cross_side:assert r['side_coverage'][1]['shot_count']is None
    else:assert r['side_coverage'][1]['shot_count']==11


def test_one_bad_link_withholds_only_affected_side_and_preserves_unknown_counts():
    c,v,e=values(132398);bad=bytearray(v[0]);struct.pack_into('<I',bad,36,0xffffffff);v[0]=bytes(bad)
    r=query.decode_attempts(v,e,c['teams']);assert r['side_coverage'][0]['shot_count']is None
    assert r['side_coverage'][1]['shot_count']==7
    assert all(s['side_index']==1 for s in r['shots'])


def test_xg_tolerance_is_explicit_one_ulp_and_never_silently_widens():
    c,v,e=values(132398);teams=json.loads(json.dumps(c['teams']))
    bits=struct.unpack('<I',struct.pack('<f',teams[0]['expected_goals']))[0]
    teams[0]['expected_goals']=struct.unpack('<f',struct.pack('<I',bits+10))[0]
    r=query.decode_attempts(v,e,teams);assert r['side_coverage'][0]['shot_count']is None
    assert r['side_coverage'][0]['xg_float32_ulp_distance']>1


def test_known_retained_zero_is_available_but_absent_source_counts_are_null():
    teams=[dict(shots=0,shots_on_target=0,expected_goals=0.)]*2
    r=query.decode_attempts([b'',b''],b'',teams)
    assert all(s['state']=='available'and s['shot_count']==0 for s in r['side_coverage'])
    assert all(s['shot_count']is None for s in query._empty_sides({},'unavailable_not_retained'))


@pytest.mark.parametrize('header',[(0,8,8),(4096,4097,4144),(4096,4144,4096),(4096,4144,4096+48*1025)])
def test_native_geometry_rejects_invalid_or_excessive_vectors(header):
    with pytest.raises(ValueError,match='geometry'):
        query._records(lambda *_:struct.pack('<QQQ',*header),4096,48,1024)


def test_private_epoch_reuse_rejects_reload_before_touching_source(monkeypatch):
    monkeypatch.setattr(query,'capture_epoch',lambda *_:('new-load',))
    monkeypatch.setattr(query,'capture_source',lambda *_:pytest.fail('must reject before CBE read'))
    with pytest.raises(ValueError,match='another native load epoch'):
        query.capture_retained_shot_maps(None,'s',['ref'],fixture_captures={'_live_capture_epoch':('old-load',)})


def test_paging_requires_source_pin_and_rejects_changed_capture(monkeypatch):
    with pytest.raises(ValueError,match='requires expected_source_id'):
        query.get_retained_shot_map(None,'s','ref',offset=1)
    monkeypatch.setattr(query,'capture_retained_shot_maps',lambda *a,**k:{'records':[{'source_id':'b'*64,'shots':[]}]})
    with pytest.raises(ValueError,match='source changed'):
        query.get_retained_shot_map(None,'s','ref',expected_source_id='a'*64)


def test_native_guard_and_catalog_discovery_need_no_game():
    assert query.NATIVE_SPANS
    from fm_live_mcp.match_scope_query import column_catalog
    c=column_catalog();assert 'fm_get_retained_shot_map'in c['goal_crossings']['how_to_query']
    assert 'not all attempts'in c['goal_crossings']['limitations']


def test_team_oracle_requires_both_canonical_fixture_side_identities():
    f={'home_team':{'database_index':5,'native_id':10},'away_team':{'database_index':6,'native_id':20}}
    teams=[{'team_index':5,'team_identity_word':10},{'team_index':6,'team_identity_word':20}]
    query._validate_team_oracle(f,teams)
    for field in ('team_index','team_identity_word'):
        bad=json.loads(json.dumps(teams));bad[1][field]+=1
        with pytest.raises(ValueError,match='canonical fixture TEAM'):
            query._validate_team_oracle(f,bad)


def test_wrong_actor_team_withholds_person_identity_without_inventing_a_name():
    teams=[{'team_index':5,'team_identity_word':10},{'team_index':6,'team_identity_word':20}]
    row=dict(side_index=0,stored_player_slot=3,team_index_word=5,canonical_team_id=10,
             person_index_word=7,canonical_person_id=77,person_name='Proved Actor',identity_state='canonical')
    assert query._validated_actors([row],teams)[0,3]['person_name']=='Proved Actor'
    for field in ('team_index_word','canonical_team_id'):
        bad=dict(row);bad[field]+=1
        assert query._validated_actors([bad],teams)=={}


def test_reused_raw_tampering_rejects_before_native_shot_read(monkeypatch):
    monkeypatch.setattr(query,'capture_epoch',lambda *_:('load',))
    monkeypatch.setattr(query,'capture_source',lambda *_:pytest.fail('must not read CBE'))
    b=SimpleNamespace(get_save=lambda *_:{'save':{}})
    packet={'_live_capture_epoch':('load',),'capture':{'fixtures':[{'fixture':{'fixture_ref':'ref'},'native_match_key':1}]},
            'raw_frames':[{'fixture_ref':'ref','key':1,'raw':b'tampered','raw_sha256':'a'*64}]}
    with pytest.raises(ValueError,match='byte hash differs'):
        query.capture_retained_shot_maps(b,'s',['ref'],fixture_captures=packet)


def test_structured_tool_schema_and_no_address_or_path_arguments():
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp.retained_shot_tools import register_retained_shot_tools
    async def check():
        m=FastMCP('Retained shot test');register_retained_shot_tools(m,None)
        tools = await m.list_tools()
        assert {tool.name for tool in tools} == {'fm_get_retained_shot_map', 'fm_report_retained_shot_quality'}
        for tool in tools:
            assert tool.outputSchema['type'] == 'object'
            assert not {'path', 'address', 'raw', 'sql'} & tool.inputSchema['properties'].keys()
            assert tool.annotations.readOnlyHint
    asyncio.run(check())


def test_valid_private_packet_reuse_avoids_a_second_backing_read(monkeypatch):
    import hashlib
    c,v,e=values(132398)
    raw=gzip.decompress((Path(__file__).parent/'fixtures/saved_match_stats_132398.bin.gz').read_bytes())
    f={'fixture_ref':'ref','date':c['fixture']['date'],'competition':{'native_id':11},
       'home_team':{'database_index':c['teams'][0]['team_index'],'native_id':c['teams'][0]['team_identity_word']},
       'away_team':{'database_index':c['teams'][1]['team_index'],'native_id':c['teams'][1]['team_identity_word']}}
    packet={'_live_capture_epoch':('load',),'capture':{'fixtures':[{'fixture':f,'native_match_key':132398}]},
            'raw_frames':[{'fixture_ref':'ref','key':132398,'raw':raw,'raw_sha256':hashlib.sha256(raw).hexdigest()}],
            'retained_players':[]}
    monkeypatch.setattr(query,'capture_epoch',lambda *_:('load',))
    monkeypatch.setattr(query,'read_selected_matches',lambda *_a,**_k:pytest.fail('must reuse checked oracle'))
    monkeypatch.setattr(query,'capture_source',lambda *_a,**_k:dict(state='available',events=e,vectors=v,coach_index=0,coach_name='Coach',owner_team_native_id=688))
    b=SimpleNamespace(get_save=lambda *_:{'save':{'current_date':'2030-11-02'}})
    result=query.capture_retained_shot_maps(b,'s',['ref'],fixture_captures=packet)
    row,=result['records'];assert row['state']=='available'and len(row['shots'])==18
    assert '_live_capture_epoch'not in row and row['fixture_ref']=='ref'
    assert row['reconciliation_policy']['expected_goals_max_float32_ulps']==1
    observed=query.capture_retained_shot_maps(b,'s',['ref'],fixture_captures=packet,include_source_observed=True)['records'][0]
    assert '_candidates_by_side' not in observed and '_marker_candidates_by_side' not in observed
    assert observed['shots'] == row['shots']


def test_missing_backing_packet_is_preserved_with_two_unknown_sides(monkeypatch):
    monkeypatch.setattr(query,'capture_epoch',lambda *_:('load',))
    monkeypatch.setattr(query,'read_selected_matches',lambda *_a,**_k:{'records':[dict(fixture_ref='ref',fixture_native={},key=1,state='not_in_active_match_banks')]})
    monkeypatch.setattr(query,'capture_source',lambda *_:pytest.fail('no independent oracle'))
    b=SimpleNamespace(get_save=lambda *_:{'save':{}})
    row,=query.capture_retained_shot_maps(b,'s',['ref'])['records']
    assert row['state']=='unavailable_team_oracle'and not row['shots']
    assert len(row['side_coverage'])==2 and all(s['shot_count']is None for s in row['side_coverage'])


def test_saved_penalty_uses_proved_type_not_xg_or_location_threshold():
    c,v,e=values(136157);r=query.decode_attempts(v,e,c['teams'])
    penalties=[s for s in r['shots']if s['is_penalty']]
    row,=penalties
    assert row['event_id']==1984 and row['side_index']==0 and row['stored_player_slot']==4
    assert row['native_shot_type']==4 and row['shot_situation']=='penalty'
    assert row['expected_goals']==0.8267761468887329
    assert row['native_category_code']==4  # saved; not all penalties are goals
    assert r['side_coverage'][0]['state']=='available'
    # Real Southampton three-shot source remains2ULP from the independent aggregate.
    assert r['side_coverage'][1]['xg_float32_ulp_distance']==2
    assert r['side_coverage'][1]['shot_count']is None


def test_non_penalty_does_not_claim_open_play_or_other_situation():
    c,v,e=values(132398);r=query.decode_attempts(v,e,c['teams'])
    assert all(not s['is_penalty']and s['shot_situation']=='non_penalty_unspecified'for s in r['shots'])
    c,v,e=values(135904);marker,=query.decode_attempts(v,e,c['teams'])['own_goal_markers']
    assert marker['is_penalty']is None and marker['shot_situation']is None
