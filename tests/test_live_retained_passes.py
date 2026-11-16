import copy
import gzip
import json
from pathlib import Path
import struct
import pytest

from fm_live_mcp.live_retained_passes import decode_pass_network,summarize_pass_network


def event(sender=0,receiver=1,*,side=0,flags=0,identity=1,category=7):
    raw=bytearray(56);raw[39:43]=bytes((sender,side,receiver,category))
    struct.pack_into('<I',raw,44,identity);raw[48]=flags
    return bytes(raw)


def player(slot=0,*,side=0,completed=1):
    return dict(side_index=side,stored_player_slot=slot,canonical_person_id=100+side*10+slot,
                person_name=f'Player{side}-{slot}',passes_completed=completed,passes_attempted=completed+1)


def test_named_map_counts_remain_distinct_from_counter_reconciled_subset():
    raw=event()+event(flags=8,identity=2)
    decoded=decode_pass_network(raw,[player(),player(1,completed=0)])['sides'][0]
    assert decoded['official_map_record_count']==2
    assert decoded['counter_reconciled_completed_passes']==1
    assert decoded['edges'][0]['official_map_count']==2
    assert decoded['edges'][0]['counter_reconciled_completed_passes']==1
    assert decoded['excluded_unlabelled_mask8_count']==1


def test_every_player_counter_must_match_not_just_team_total():
    decoded=decode_pass_network(event(),[player(completed=0),player(1)])['sides'][0]
    assert decoded['state']=='unavailable_completed_counter_reconciliation'
    assert decoded['counter_reconciled_completed_passes'] is None
    assert decoded['edges'][0]['official_map_count']==1
    assert decoded['edges'][0]['counter_reconciled_completed_passes'] is None


def test_individual_attempts_remain_counters_not_invented_failed_pass_events():
    decoded=decode_pass_network(event(),[player(),player(1,completed=0)])['sides'][0]
    assert decoded['official_player_not_completed_sum']==2
    assert decoded['player_counters'][0]=={
        'person_native_id':100,'person_name':'Player0-0','stored_player_slot':0,
        'state':'available_official_player_counters','passes_attempted':2,
        'passes_completed':1,'passes_not_completed':1,'completion_events_reconciled':True}
    assert not {'failed_event_count','failed_receivers','coordinates','phase'} & decoded['player_counters'][0].keys()
    # Counter facts survive a map disagreement, but lose event reconciliation.
    mismatch=decode_pass_network(event(),[player(completed=0),player(1)])['sides'][0]
    assert mismatch['player_counters'][0]['passes_attempted']==1
    assert mismatch['player_counters'][1]['passes_completed']==1
    assert all(not p['completion_events_reconciled'] for p in mismatch['player_counters'])


@pytest.mark.parametrize('attempted',[None,True,-1,0])
def test_invalid_or_incoherent_attempt_counters_never_become_zero_failures(attempted):
    p=player();p['passes_attempted']=attempted
    decoded=decode_pass_network(event(),[p,player(1,completed=0)])['sides'][0]
    assert decoded['official_player_not_completed_sum'] is None
    assert decoded['player_counters'][0]['state']=='unavailable_player_counters'
    assert decoded['player_counters'][0]['passes_not_completed'] is None


def test_true_zero_counters_are_explicit_and_actor_failure_withholds_counters():
    p=player(completed=0);p['passes_attempted']=0
    decoded=decode_pass_network(b'',[p])['sides'][0]
    assert decoded['player_counters'][0]['passes_not_completed']==0
    assert decoded['player_counters'][0]['state']=='available_official_player_counters'
    p['canonical_person_id']=None
    assert decode_pass_network(b'',[p])['sides'][0]['player_counters']==[]


def test_unresolved_identity_and_recipient_do_not_become_named_pairs():
    a=player();a['canonical_person_id']=None
    decoded=decode_pass_network(event(),[a,player(1,completed=0)])['sides'][0]
    assert decoded['state']=='unavailable_actor_identity' and decoded['edges']==[]
    decoded=decode_pass_network(event(receiver=4),[player()])['sides'][0]
    assert decoded['missing_actor_slots']==[4] and decoded['edges']==[]


def test_source_width_budgets_duplicate_ids_and_duplicate_slots_fail_closed():
    with pytest.raises(ValueError):decode_pass_network(b'x',[])
    with pytest.raises(ValueError,match='Duplicate'):decode_pass_network(event()+event(),[])
    with pytest.raises(ValueError,match='slot'):decode_pass_network(event(),[player(),player()])
    with pytest.raises(ValueError,match='side'):decode_pass_network(event(side=2),[])


def test_nonpass_events_and_self_links_are_not_named_two_player_combinations():
    decoded=decode_pass_network(event(category=8),[player(completed=0),player(1,completed=0)])
    assert decoded['sides'][0]['official_map_record_count']==0
    assert decoded['sides'][0]['state']=='available'
    assert decode_pass_network(event(receiver=0),[player()])['sides'][0]['edges']==[]


def actual():
    with gzip.open(Path(__file__).parent/'fixtures/retained_pass_networks.json.gz','rt') as f:return json.load(f)


def test_real_forest_and_burnley_maps_match_all80_individual_counters():
    packet=actual();expected={135904:([531,569],[522,565]),136157:([520,559],[512,548])}
    for fixture in packet['fixtures']:
        key=fixture['fixture']['native_match_key']
        decoded=decode_pass_network(bytes.fromhex(fixture['events']),fixture['players'])
        assert [s['official_map_record_count'] for s in decoded['sides']]==expected[key][0]
        assert [s['counter_reconciled_completed_passes'] for s in decoded['sides']]==expected[key][1]
        assert all(s['all_captured_player_counters_match'] and s['captured_player_counter_checks']==20 for s in decoded['sides'])


def test_real_november2_result_conserves_all40_player_counters_and245_named_edges():
    import hashlib
    with gzip.open(Path(__file__).parent/'fixtures/retained_pass_network_136523.json.gz','rt') as f:
        packet=json.load(f)
    raw=bytes.fromhex(packet['events'])
    assert packet['native_match_key']==136523
    assert hashlib.sha256(raw).hexdigest()==packet['event_sha256']
    decoded=decode_pass_network(raw,packet['players'])
    assert decoded['native_event_count']==1800
    for side,attempted,completed,not_completed,edges in zip(decoded['sides'],[446,597],[388,524],[58,73],[126,119]):
        assert side['state']=='available'
        assert len(side['player_counters'])==20 and len(side['edges'])==edges
        assert sum(p['passes_attempted'] for p in side['player_counters'])==attempted
        assert sum(p['passes_completed'] for p in side['player_counters'])==completed
        assert sum(p['passes_not_completed'] for p in side['player_counters'])==not_completed
        assert sum(e['counter_reconciled_completed_passes'] for e in side['edges'])==completed
    away=decoded['sides'][1]
    top=max(away['edges'],key=lambda e:e['counter_reconciled_completed_passes'])
    assert (top['from_name'],top['to_name'],top['counter_reconciled_completed_passes'])==('Taylor Harwood-Bellis','Joshua Quarshie',23)


def captured():
    packet=actual();records=[]
    for f in packet['fixtures']:
        fixture=f['fixture'];decoded=decode_pass_network(bytes.fromhex(f['events']),f['players'])
        for side in decoded['sides']:
            side['team_native_id']=fixture['home_team_id'] if side['side_index']==0 else fixture['away_team_id']
        public={name:fixture[name] for name in ('date',)}
        for side in ('home','away'):public[side+'_team']={'owner':{'name':fixture[side+'_team']}}
        records.append({'fixture':public,'fixture_ref':str(fixture['native_match_key']),
                        'native_match_key':fixture['native_match_key'],'source_id':'test','state':'available',**decoded})
    return {'records':records,'captured_save':packet['captured_save']}


def test_real_repeated_named_pair_baseline_and_explicit_map_metric():
    report=summarize_pass_network(captured(),713)
    assert report['counter_reconciled_fixture_count']==2
    pairs={(p['from_name'],p['to_name']):p for p in report['pairs']}
    assert pairs['Lorenz Assignon','Tom Fellows']['counter_reconciled_completed_passes']==38
    assert pairs['Joshua Quarshie','Taylor Harwood-Bellis']['counter_reconciled_completed_passes']==35
    assert pairs['Alexander Prass','Amine Adli']['counter_reconciled_completed_passes']==34
    assert all(p['matches_observed']==2 for p in report['pairs'])
    assert summarize_pass_network(captured(),713,ranking_basis='official_map_count')['ranking_basis']=='official_map_count'


def test_missing_fixture_source_is_unknown_not_zero_repeat_evidence():
    packet=captured();packet['records'][1].update(state='unavailable_not_retained',sides=[])
    report=summarize_pass_network(packet,713)
    assert report['selected_fixture_count']==2 and report['counter_reconciled_fixture_count']==1
    assert report['pairs']==[]
    assert report['fixtures'][1]['source_state']=='unavailable_not_retained'


def test_duplicate_fixture_aliases_cannot_create_repeat_evidence():
    packet=captured();packet['records'][1]=copy.deepcopy(packet['records'][0])
    with pytest.raises(ValueError,match='Duplicate selected'):summarize_pass_network(packet,713)


def test_pass_availability_uses_own_counter_oracle_not_shot_float_threshold(monkeypatch):
    from fm_live_mcp import live_retained_passes as passes,live_retained_shots as shots,match_data_query
    fixture={'fixture_ref':'f','home_team':{'native_id':688,'database_index':545},'away_team':{'native_id':713,'database_index':570}}
    packet={'_live_capture_epoch':'epoch','capture':{'save':{},'fixtures':[{'fixture':fixture,'native_match_key':7}]},
            'team_totals':{'records':[{'result_key':7,'teams':[{'team_index':545,'team_identity_word':688},{'team_index':570,'team_identity_word':713}]}]},
            'retained_players':[{**p,'fixture_key':7,'person_index_word':p['canonical_person_id'],
                                 'team_index_word':570 if p['side_index'] else 545,
                                 'canonical_team_id':713 if p['side_index'] else 688}
                                for p in [player(),player(1,completed=0),player(side=1,completed=0)]]}
    monkeypatch.setattr(match_data_query,'capture_epoch',lambda *args:'epoch')
    monkeypatch.setattr(passes,'_verify_pass_native',lambda *args:None)
    monkeypatch.setattr(shots,'capture_source',lambda *args:{'state':'available','events':event(),'vectors':[b'',b''],'owner_team_native_id':713})
    monkeypatch.setattr(shots,'decode_attempts',lambda *args:{'side_coverage':[{'state':'unavailable_unreconciled_retained_side','xg_float32_ulp_distance':2}]})
    result=passes.capture_retained_pass_networks(None,'s',['f'],fixture_captures=packet)
    assert result['records'][0]['state']=='available'
    assert result['records'][0]['fixture_shot_oracle'][0]['xg_float32_ulp_distance']==2
    assert all(s['all_captured_player_counters_match'] for s in result['records'][0]['sides'])
    # Identical counters cannot authorize an oracle or actor from another TEAM.
    for field in ('team_identity_word','team_index'):
        foreign_oracle=copy.deepcopy(packet)
        foreign_oracle['team_totals']['records'][0]['teams'][0][field]=999
        with pytest.raises(ValueError,match='canonical fixture TEAM'):
            passes.capture_retained_pass_networks(None,'s',['f'],fixture_captures=foreign_oracle)
    for field in ('team_index_word','canonical_team_id'):
        foreign_actor=copy.deepcopy(packet);foreign_actor['retained_players'][0][field]=999
        rejected=passes.capture_retained_pass_networks(None,'s',['f'],fixture_captures=foreign_actor)
        assert rejected['records'][0]['state']=='unavailable_actor_team_identity'
        assert rejected['records'][0]['sides']==[]


def test_discoverable_report_schema_and_compact_named_output(monkeypatch):
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp import retained_pass_tools as tools
    calls=[]
    monkeypatch.setattr(tools,'capture_retained_pass_networks',lambda *args,**kwargs:(calls.append((args,kwargs)) or captured()))
    async def check():
        mcp=FastMCP('test');tools.register_retained_pass_tools(mcp,None)
        tool,=await mcp.list_tools()
        assert tool.name=='fm_report_live_pass_network' and tool.annotations.readOnlyHint
        schema=tool.inputSchema
        assert {'session_id','fixture_refs','team_native_id'}<=set(schema['required'])
        assert schema['properties']['fixture_refs']['maxItems']==16
        assert schema['properties']['ranking_basis']['default']=='counter_reconciled_completed_passes'
        assert not {'path','sql','source_id'}&schema['properties'].keys()
        result=await mcp.call_tool(tool.name,{'session_id':'s','team_native_id':713,'fixture_refs':['f1','f2']})
        text=''.join(block.text for block in result if hasattr(block,'text')) if isinstance(result,list) else str(result)
        assert 'Lorenz Assignon' in text and 'Tom Fellows' in text
        assert '38' in text and 'route' in text
    asyncio.run(check())
    assert len(calls)==1
