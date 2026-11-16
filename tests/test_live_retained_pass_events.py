import asyncio
import copy
import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import live_retained_pass_events as passes
from test_live_retained_passes import event, player, actual


def fixture():
    with gzip.open(Path(__file__).parent/'fixtures/retained_pass_network_136523.json.gz','rt') as f:
        packet=json.load(f)
    packet['raw']=bytes.fromhex(packet['events'])
    packet['paths']=[{**p,'raw_xy_pairs':bytes.fromhex(p['raw_xy_pairs'])}for p in packet['paths']]
    return packet


def test_actual1043_pass_points_start_the_path_and_path_ends_say_what_they_are():
    # The fixture stores no pitch geometry; 34 by 52.5 is what the reader returns for a 68 by 105 pitch.
    f=fixture();decoded=passes.decode_pass_attempts(f['raw'],f['players'],f['paths'],
        pitch_geometry={'half_width_native':34.0,'half_length_native':52.5})
    import collections
    ends=[(r,r['field_position']['sampled_path_endpoint'])for r in decoded['attempts']]
    assert all((r['native_event_x'],r['native_event_y'])==(r['native_path_start_x'],r['native_path_start_y'])for r,_ in ends)
    assert all(r['field_position']['ball_release_location']=={'native_x':r['native_event_x'],'native_y':r['native_event_y']}for r,_ in ends)
    assert collections.Counter((r['native_category_code'],e['semantics'])for r,e in ends)=={
        (7,'reception_by_named_recipient'):912,(8,'opponent_won_ball'):58,(9,'opponent_blocked_or_cleared'):9,
        (10,'engine_target_point'):38,(11,'out_of_play'):26}
    assert all((e['analytical_pitch_third'] is None)==(not e['inside_native_pitch_extents'])for _,e in ends)
    assert not any(e['inside_native_pitch_extents']for r,e in ends if r['native_category_code']==11)
    assert collections.Counter(e['analytical_pitch_third']for r,e in ends if r['completed'])=={
        'middle':473,'defensive':243,'attacking':195,None:1}


def test_actual1043_attempts_close_all40_individual_counters_and_native_paths():
    f=fixture();decoded=passes.decode_pass_attempts(f['raw'],f['players'],f['paths'])
    assert hashlib.sha256(f['raw']).hexdigest()==f['event_sha256']
    assert decoded['state']=='available' and len(decoded['attempts'])==1043
    for side,attempted,completed in zip(decoded['side_coverage'],[446,597],[388,524]):
        rows=[r for r in decoded['attempts']if r['side_index']==side['side_index']]
        assert len(rows)==side['attempt_count']==attempted
        assert sum(r['completed'] for r in rows)==side['completed_count']==completed
        assert side['not_completed_count']==attempted-completed
        assert side['all_captured_player_attempt_counters_match'] and side['all_captured_player_completion_counters_match']
    for row in decoded['attempts']:
        assert len(row['native_path_points'])==3
        assert row['origin_destination_state'] in ('not_proved','proved_start_is_pass_location_end_is_linked_event_location') and row['coordinate_units'] is None
        assert row['displayed_time'] is None and row['phase'] is None
        if row['completed']:
            assert row['recipient_person_native_id'] and row['recipient_state']=='canonical_completed_pass_recipient'
        else:
            assert row['specific_failure_reason'] in {'intercepted','blocked','out_of_play','not_completed_other'} and row['recipient_person_native_id'] is None and row['recipient_state']=='not_stored_by_game'
    first=decoded['attempts'][0]
    assert first['person_name']=='Christian Kofane' and first['recipient_name']=='Marlon Gomes'
    assert first['native_path_start_x']==pytest.approx(.5)
    assert first['native_path_end_y']==pytest.approx(-10.690267562866211)


def test_prior80_individual_controls_also_close_attempts_not_only_completions():
    for f in actual()['fixtures']:
        result=passes.decode_pass_attempts(bytes.fromhex(f['events']),f['players'])
        assert result['state']=='available'
        for side in result['side_coverage']:
            assert side['captured_player_counter_checks']==20
            assert side['attempt_count']==sum(p['passes_attempted']for p in f['players']if p['side_index']==side['side_index'])


def test_native_family_includes_unseen6_and_excludes_unlabelled_mask8():
    raw=event(category=6)+event(category=7,identity=2)+event(category=10,flags=8,identity=3)
    p=player();p['passes_attempted']=2
    decoded=passes.decode_pass_attempts(raw,[p,player(1,completed=0)])
    # Recipient has one attempted counter but no event; must fail this side closed.
    assert decoded['side_coverage'][0]['state']=='unavailable_attempt_counter_reconciliation'
    recipient=player(1,completed=0);recipient['passes_attempted']=0
    decoded=passes.decode_pass_attempts(raw,[p,recipient])
    assert [r['native_category_code']for r in decoded['attempts']]==[6,7]
    assert decoded['side_coverage'][0]['excluded_unlabelled_mask8_count']==1
    assert decoded['attempts'][0]['completed'] is False


def test_equal_team_attempts_with_wrong_individuals_are_not_sufficient():
    f=fixture();players=copy.deepcopy(f['players'])
    own=[p for p in players if p['side_index']==0]
    own[0]['passes_attempted']+=1;own[1]['passes_attempted']-=1
    result=passes.decode_pass_attempts(f['raw'],players,f['paths'])
    assert result['state']=='partial'
    assert result['side_coverage'][0]['attempt_count'] is None
    assert not any(r['side_index']==0 for r in result['attempts'])
    assert result['side_coverage'][1]['attempt_count']==597


def test_duplicate_missing_actor_bad_sides_and_wrong_path_binding_fail_closed():
    f=fixture()
    with pytest.raises(ValueError,match='Duplicate'):passes.decode_pass_attempts(f['raw'][:56]*2,f['players'])
    with pytest.raises(ValueError,match='side'):passes.decode_pass_attempts(event(category=8,side=2),[])
    paths=copy.deepcopy(f['paths']);paths[0]['event_id']+=1
    with pytest.raises(ValueError,match='path identity'):passes.decode_pass_attempts(f['raw'],f['players'],paths)
    paths=copy.deepcopy(f['paths']);paths[0]['raw_xy_pairs']=b'bad'
    with pytest.raises(ValueError,match='path identity'):passes.decode_pass_attempts(f['raw'],f['players'],paths)
    paths=copy.deepcopy(f['paths']);paths[0]['raw_xy_pairs']=struct.pack('<ff',float('nan'),0)
    with pytest.raises(ValueError,match='Nonfinite'):passes.decode_pass_attempts(f['raw'],f['players'],paths)
    players=copy.deepcopy(f['players']);players[0]['canonical_person_id']=None
    result=passes.decode_pass_attempts(f['raw'],players)
    assert result['side_coverage'][players[0]['side_index']]['attempt_count'] is None


def test_true_zero_is_only_after_zero_individual_counter_closure():
    p=player(completed=0);p['passes_attempted']=0
    result=passes.decode_pass_attempts(b'',[p])
    assert result['side_coverage'][0]['attempt_count']==0
    assert result['side_coverage'][1]['attempt_count'] is None
    p['passes_attempted']=None
    assert passes.decode_pass_attempts(b'',[p])['side_coverage'][0]['attempt_count'] is None


def mock_capture(monkeypatch):
    from fm_live_mcp import live_retained_shots as shots,match_data_query
    f=fixture();fixture_row={'fixture_ref':'f','home_team':{'native_id':688,'database_index':545},'away_team':{'native_id':713,'database_index':570}}
    teams=[{'team_index':545,'team_identity_word':688},{'team_index':570,'team_identity_word':713}]
    packet={'_live_capture_epoch':'epoch','capture':{'save':{},'fixtures':[{'fixture':fixture_row,'native_match_key':136523}]},
            'team_totals':{'records':[{'result_key':136523,'teams':teams}]},
            'retained_players':[{**p,'fixture_key':136523,'person_index_word':p['canonical_person_id'],
                                 'team_index_word':545 if p['side_index']==0 else 570,
                                 'canonical_team_id':688 if p['side_index']==0 else 713}for p in f['players']]}
    source={'state':'available','events':f['raw']}
    monkeypatch.setattr(match_data_query,'capture_epoch',lambda *a:'epoch')
    monkeypatch.setattr(passes,'_verify_pass_native',lambda *a:None)
    monkeypatch.setattr(passes,'_verify_attempt_native',lambda *a:None)
    monkeypatch.setattr(passes,'_capture_paths',lambda *a:f['paths'])
    monkeypatch.setattr(shots,'capture_source',lambda *a:source)
    return packet,source


def test_source_pinned_pages_preserve_every_row_once_and_reject_mutations(monkeypatch):
    packet,source=mock_capture(monkeypatch)
    first=passes.capture_retained_pass_attempts(None,'s','f',fixture_captures=packet,limit=500)
    assert first['total_count']==1043 and first['next_offset']==500
    assert first['pass_field_summary']['sides'][1]['attempted']==597
    assert first['pass_field_summary']['sides'][1]['not_completed']==73
    rows=list(first['attempts'])
    for offset in (500,1000):
        page=passes.capture_retained_pass_attempts(None,'s','f',fixture_captures=packet,limit=500,offset=offset,expected_source_id=first['source_id'])
        assert page['pass_field_summary']==first['pass_field_summary']
        rows.extend(page['attempts'])
    assert len(rows)==len({r['event_id']for r in rows})==1043 and page['next_offset'] is None
    with pytest.raises(ValueError,match='first page'):passes.capture_retained_pass_attempts(None,'s','f',offset=500,fixture_captures=packet)
    with pytest.raises(ValueError,match='source changed'):passes.capture_retained_pass_attempts(None,'s','f',expected_source_id='0'*64,fixture_captures=packet)
    old=copy.deepcopy(packet);old['_live_capture_epoch']='old'
    with pytest.raises(ValueError,match='epoch'):passes.capture_retained_pass_attempts(None,'s','f',fixture_captures=old)
    wrong=copy.deepcopy(packet);wrong['retained_players'][0]['canonical_team_id']=999
    assert passes.capture_retained_pass_attempts(None,'s','f',fixture_captures=wrong)['state']=='unavailable_actor_team_identity'
    source['state']='unavailable_not_retained'
    result=passes.capture_retained_pass_attempts(None,'s','f',fixture_captures=packet)
    assert result['total_count'] is None and result['attempts']==[]
    assert len(result['side_coverage'])==2
    assert all(s['attempt_count'] is None for s in result['side_coverage'])


def test_native_path_change_and_reload_between_reads_reject_whole_page(monkeypatch):
    from fm_live_mcp import live_retained_shots as shots,match_data_query
    packet,source=mock_capture(monkeypatch)
    first=passes.capture_retained_pass_attempts(None,'s','f',fixture_captures=packet)
    f=fixture();f['paths'][0]['raw_xy_pairs']=struct.pack('<ff',1,2)
    monkeypatch.setattr(passes,'_capture_paths',lambda *a:f['paths'])
    with pytest.raises(ValueError,match='source changed'):
        passes.capture_retained_pass_attempts(None,'s','f',expected_source_id=first['source_id'],fixture_captures=packet)
    calls=[]
    monkeypatch.setattr(shots,'capture_source',lambda *a:(calls.append(1) or (source if len(calls)==1 else {'state':'unavailable_not_retained'})))
    with pytest.raises(ValueError,match='source changed'):
        passes.capture_retained_pass_attempts(None,'s','f',fixture_captures=packet)
    monkeypatch.setattr(shots,'capture_source',lambda *a:source)
    epochs=iter(['epoch','reloaded'])
    monkeypatch.setattr(match_data_query,'capture_epoch',lambda *a:next(epochs))
    with pytest.raises(ValueError,match='source changed'):
        passes.capture_retained_pass_attempts(None,'s','f',fixture_captures=packet)


def test_paged_tool_schema_and_dispatch_are_bounded(monkeypatch):
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp import retained_pass_event_tools as tools
    calls=[]
    monkeypatch.setattr(tools,'capture_retained_pass_attempts',lambda *a,**kw:(calls.append((a,kw))or {'state':'available','attempts':[]}))
    async def check():
        mcp=FastMCP('test');tools.register_retained_pass_event_tools(mcp,None)
        tool,=await mcp.list_tools()
        assert tool.name=='fm_get_retained_pass_events' and tool.annotations.readOnlyHint
        assert tool.inputSchema['properties']['limit']['maximum']==500
        assert not {'path','sql','fixture_refs'}&tool.inputSchema['properties'].keys()
        await mcp.call_tool(tool.name,{'session_id':'s','fixture_ref':'f','limit':20})
        assert calls[0][1]['limit']==20
    asyncio.run(check())


def test_native_failure_codes_decode_to_outcomes_and_never_become_tactical_causes():
    f=fixture();result=passes.decode_pass_attempts(f['raw'],f['players'],f['paths'])
    for side in result['side_coverage']:
        for p in side['player_counters']:
            assert sum(p['incomplete_native_category_counts'].values())==p['passes_not_completed']
            assert p['specific_failure_reasons_state']=='not_decoded'
    for row in result['attempts']:
        assert row['tactical_cause'] is None and (row['specific_failure_reason'] is None if row['completed'] else row['specific_failure_reason'] in {'intercepted','blocked','out_of_play','not_completed_other'})
        assert row['native_outcome_symbol']==('CBE_END_PASS_COMPLETED'if row['completed']else None)
        assert row['field_position'] is None


def test_lille_real945_attempts_close43_players_with_honest_failure_and_field_scope():
    import collections
    with gzip.open(Path(__file__).parent/'fixtures/retained_pass_network_136941.json.gz','rt')as f:
        packet=json.load(f)
    raw=bytes.fromhex(packet['events']);assert hashlib.sha256(raw).hexdigest()==packet['event_sha256']
    result=passes.decode_pass_attempts(raw,packet['players'],pitch_geometry=packet['pitch_geometry'])
    assert result['state']=='available'and len(result['attempts'])==945
    assert [s['attempt_count']for s in result['side_coverage']]==[452,493]
    assert [s['completed_count']for s in result['side_coverage']]==[404,429]
    assert sum(s['captured_player_counter_checks']for s in result['side_coverage'])==43
    failures=collections.Counter(r['native_category_code']for r in result['attempts']if not r['completed'])
    assert dict(failures)=={8:51,9:6,10:31,11:24}
    away=result['side_coverage'][1]['player_counters'];maximum=max(p['passes_not_completed']for p in away)
    leaders={p['person_name']for p in away if p['passes_not_completed']==maximum}
    assert maximum==8 and leaders=={'Alberto Costa','Chema Andrés','Luiz Henrique','Jay Robinson'}
    assert all(r['field_position']['location_semantics']=='official_pass_map_event_location; pass_origin_proved'for r in result['attempts'])
    assert all(r['field_position']['intended_destination'] is None for r in result['attempts'])
    assert all(r['specific_failure_reason'] in {'intercepted','blocked','out_of_play','not_completed_other'} for r in result['attempts'] if not r['completed'])
    away_summary=result['pass_field_summary']['sides'][1]
    assert away_summary['classified_location_count']==493
    cells={(c['pitch_third'],c['lateral_channel']):c for c in away_summary['zones']}
    assert (cells['middle','outer']['attempted'],cells['middle','outer']['not_completed'])==(181,27)
    assert (cells['attacking','outer']['attempted'],cells['attacking','outer']['not_completed'])==(73,17)
    assert result['pass_field_summary']['sides'][0]['unclassified_location']['attempted']==1


def test_geometry_is_part_of_pagination_source_identity(monkeypatch):
    packet,source=mock_capture(monkeypatch)
    first=passes.capture_retained_pass_attempts(None,'s','f',fixture_captures=packet)
    source['pitch_geometry']={'half_width_native':34,'half_length_native':52.5}
    with pytest.raises(ValueError,match='source changed'):
        passes.capture_retained_pass_attempts(None,'s','f',expected_source_id=first['source_id'],fixture_captures=packet)


def test_category7_without_official_completion_closure_cannot_be_a_completed_row():
    # The older network ignores category7 with an invalid recipient; attempt
    # closure alone must not accidentally promote that event to completion.
    p=player(completed=0);p['passes_attempted']=1
    result=passes.decode_pass_attempts(event(receiver=255),[p])
    assert result['side_coverage'][0]['state']!='available'
    assert result['side_coverage'][0]['attempt_count'] is None and result['attempts']==[]
