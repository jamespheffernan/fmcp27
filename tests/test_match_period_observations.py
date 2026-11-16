from copy import deepcopy
from pathlib import Path
import gzip
import json
import struct

import pytest

from fm_live_mcp import match_period_observations as periods
from fm_live_mcp.live_retained_shots import decode_attempts
from test_active_match_shot_timeline import sample


SAVE=dict(name='Career',created_date='2025-10-23',created_version=1)
FIXTURE=dict(date='2030-11-02',competition=dict(database_index=7,native_id=11),
             home_team=dict(database_index=10,native_id=688),away_team=dict(database_index=11,native_id=713))


def observation(full=False):
    source,bound,split=sample();source['fixture_identity']=('2030-11-02',11,(10,688),(11,713))
    split.update(state='available',period_source={'simulation_period':'FullTime'if full else 'SecondHalf'},
                 period_markers=[dict(stop_time_slice=t,next_stop_reason=r)for t,r in [(1,'StartOfPeriod'),(10,'EndOfPeriod'),(12,'StartOfPeriod')]])
    if full:
        split['period_markers'].append(dict(stop_time_slice=30,next_stop_reason='EndOfGame'))
        bound.update(current_time_slice=30,buffered_max_time_slice=30)
    value=periods.make_observation(SAVE,FIXTURE,bound,split,source,'epoch-a','2030-11-02T00:00:00Z')
    return value,source,decode_attempts(source['vectors'],source['events'],source['engine_totals'])['shots']


def test_normal_capture_dedup_and_closed_intervals_only(tmp_path):
    store=periods.ObservationStore(tmp_path);value,source,shots=observation()
    first=store.save(value);assert first['state']=='captured'
    assert store.save(value)==dict(state='already_captured',capture_id=first['capture_id'])
    out=periods.link_retained(store,SAVE,FIXTURE,99,source,shots,'epoch-a')
    assert out['state']=='verified_retrospective_continuity'
    assert [p['period']for p in out['periods']]==['FirstHalf']
    assert out['periods'][0]['sides'][0]['shots']==1
    assert out['periods'][0]['sides'][1]['shots']==0
    assert out['unknown_boundary_attempts']==4
    assert out['provenance']['capture_method']=='normal_current_match_query_single_verified_readset'
    # Finalized fingerprints survive a new reader/process; original addresses do not.
    assert periods.link_retained(store,SAVE,FIXTURE,99,source,shots,'epoch-b')['state']=='verified_retrospective_continuity'


def test_closed_second_half_extends_a_previously_linked_observation(tmp_path):
    store=periods.ObservationStore(tmp_path);early,source,shots=observation();store.save(early)
    periods.link_retained(store,SAVE,FIXTURE,99,source,shots,'epoch-a')
    final,source,shots=observation(full=True);store.save(final)
    out=periods.link_retained(store,SAVE,FIXTURE,99,source,shots,'epoch-a')
    assert {p['period']:p['sides'][0]['shots']for p in out['periods']}=={'FirstHalf':1,'SecondHalf':2}
    assert out['unknown_boundary_attempts']==2  # period-end tie and crossing
    assert periods.link_retained(store,SAVE,FIXTURE,99,source,shots,'new-process')['state']=='verified_retrospective_continuity'


def test_no_capture_and_unfinalized_reload_never_become_zero(tmp_path):
    store=periods.ObservationStore(tmp_path);value,source,shots=observation()
    out=periods.link_retained(store,SAVE,FIXTURE,99,source,shots,'epoch-a')
    assert out['periods']is None and out['shot_periods']is None
    store.save(value)
    out=periods.link_retained(store,SAVE,FIXTURE,99,source,shots,'new-process')
    assert out['periods']is None and out['reasons']==['unfinalized_observation_process_or_load_changed']
    other=dict(SAVE,name='Other career')
    assert periods.link_retained(store,other,FIXTURE,99,source,shots,'epoch-a')['periods']is None
    other=deepcopy(FIXTURE);other['away_team']['native_id']=602
    assert periods.link_retained(store,SAVE,other,99,source,shots,'epoch-a')['periods']is None


@pytest.mark.parametrize('part',['event_position','event_actor','event_clock','shot_xg','shot_type','extra_prefix_attempt'])
def test_wrong_retained_semantics_rejected(tmp_path,part):
    store=periods.ObservationStore(tmp_path);value,source,shots=observation(full=True);store.save(value)
    source=deepcopy(source);events=bytearray(source['events']);vector=bytearray(source['vectors'][0])
    if part=='event_position':events[24]^=1
    if part=='event_actor':events[39]^=1
    if part=='event_clock':events[50]^=1
    if part=='shot_xg':vector[32]^=1
    if part=='shot_type':vector[44]^=1
    if part=='extra_prefix_attempt':
        e=bytearray(events[:56]);struct.pack_into('<I',e,44,90);events.extend(e)
        v=bytearray(vector[:48]);struct.pack_into('<I',v,36,90);vector.extend(v)
    source.update(events=bytes(events),vectors=[bytes(vector),b''])
    out=periods.link_retained(store,SAVE,FIXTURE,99,source,shots,'epoch-a')
    assert out['periods']is None and 'attempt_event_semantic_prefix_mismatch'in out['reasons']


def test_conflicting_uid_and_period_evidence_not_ranked_as_best(tmp_path):
    store=periods.ObservationStore(tmp_path);a,source,shots=observation(full=True);store.save(a)
    b=deepcopy(a);b['official_match_unique_id']=124
    for interval in b['intervals']:interval['official_match_unique_id']=124
    store.save(b)
    assert periods.link_retained(store,SAVE,FIXTURE,99,source,shots,'epoch-a')['state']=='unavailable_ambiguous_native_match_observations'


def test_corrupt_digest_symlink_and_budget_fail_closed(tmp_path,monkeypatch):
    store=periods.ObservationStore(tmp_path/'store');value,_,_=observation();saved=store.save(value)
    path=store.path(SAVE,FIXTURE);doc=json.loads(path.read_bytes());doc['observations'][saved['capture_id']]['observed_at']+='tampered';path.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='digest'):store.observations(SAVE,FIXTURE)
    path.unlink();path.symlink_to(tmp_path/'absent')
    with pytest.raises(ValueError,match='Invalid host'):store.observations(SAVE,FIXTURE)
    path.unlink();monkeypatch.setattr(periods,'MAX_FIXTURES_PER_CAREER',0)
    store=periods.ObservationStore(tmp_path/'budget')
    other=deepcopy(FIXTURE);other['date']='2030-11-03'
    with pytest.raises(ValueError,match='budget'):store.save(dict(value,fixture=periods.fixture_identity(other)))


def test_authentic_136523_frozen_cross_observation_control(tmp_path):
    value=json.loads(gzip.decompress((Path(__file__).parent/'fixtures/period_observation_136523.json.gz').read_bytes()))
    observation=value['observation'];store=periods.ObservationStore(tmp_path)
    saved=store.save(observation)
    # This explicit fixture is already independently finalized by frozen native
    # cross-observation proof, not a fabricated current/live observation.
    store.finalize(value['save'],value['fixture'],136523,saved['capture_id'],value['retained_semantic_fingerprint'])
    raw=value['retained_source'];source=dict(events=bytes.fromhex(raw['events']['hex']),vectors=[bytes.fromhex(v['hex'])for v in raw['vectors']])
    out=periods.link_retained(store,value['save'],value['fixture'],136523,source,value['retained_shots'],'later-process')
    assert out['state']=='verified_retrospective_continuity'and out['unknown_boundary_attempts']==0
    summary={(p['period'],s['side_index']):s for p in out['periods']for s in p['sides']}
    assert summary['FirstHalf',0]['shots']==7 and summary['SecondHalf',0]['shots']==8
    assert summary['FirstHalf',1]['shots']==6 and summary['SecondHalf',1]['shots']==4
    assert summary['FirstHalf',0]['expected_goals_sum_computed']==pytest.approx(.9236000515520573)
    assert summary['SecondHalf',0]['expected_goals_sum_computed']==pytest.approx(1.7022119499742985)
    assert out['provenance']['capture_method']=='verified_retrospective_authentic_bundle'


def test_normal_current_query_persists_after_readset_and_never_leaks_private_source(tmp_path,monkeypatch):
    from contextlib import nullcontext
    from types import MethodType, SimpleNamespace
    from unittest.mock import Mock
    from fm_live_mcp import bridge as bridge_module, current_match_report as current
    source,bound,split=sample();source['fixture_identity']=('2030-11-02',11,(10,688),(11,713))
    split.update(state='available',period_source={'simulation_period':'SecondHalf'},period_markers=[dict(stop_time_slice=t,next_stop_reason=r)for t,r in [(1,'StartOfPeriod'),(10,'EndOfPeriod'),(12,'StartOfPeriod')]])
    # This store-ordering rig has synthetic field bytes, not a runtime image.
    # Actual Mach-O/RTTI publication controls live in RuntimeRig separately.
    bridge=Mock();bridge.lock=nullcontext();bridge._reader=None
    process=SimpleNamespace(pid=7)
    bridge.session='s';bridge.process=process;bridge.world_identity=None
    bridge.plugin_identity=(('synthetic period store context',),bytes(16))
    bridge._current.return_value=process
    bridge._read_scope=MethodType(bridge_module.Bridge._read_scope,bridge)
    stream=Mock();monkeypatch.setattr(bridge_module,'ReadStream',Mock(return_value=stream))
    monkeypatch.setattr(current.players,'verify_runtime',lambda *_:[100])
    read=Mock();bridge._world_state.return_value=(read,dict(SAVE,current_date='2030-11-02'),None)
    bridge._player_layout.return_value=[100];bridge._public_save.return_value=SAVE
    monkeypatch.setattr(current,'_inspect',lambda *a,**k:dict(state='available_fixture_bound',fixture=FIXTURE,_period_capture_candidate=dict(bound=bound,split=split,source=source)))
    monkeypatch.setattr(periods,'process_epoch',lambda _: 'epoch-a')
    store=periods.ObservationStore(tmp_path);original=store.save
    def verified_save(value):
        assert read.verify.call_count==3  # body, original journal, final-context journal
        stream.close.assert_called_once()
        return original(value)
    monkeypatch.setattr(store,'save',verified_save);monkeypatch.setattr(periods,'ObservationStore',lambda:store)
    out=current.current_match_report(bridge,'s',include_tactics=False)
    assert out['host_period_capture']['state']=='captured'
    assert '_period_capture_candidate'not in out and '_host_period_source'not in str(out)
    assert 'source_identity'not in str(out)and 'events'not in str(out)
    def failed(_):raise OSError('disk full')
    monkeypatch.setattr(store,'save',failed)
    out=current.current_match_report(bridge,'s',include_tactics=False)
    assert out['state']=='available_fixture_bound'and out['host_period_capture']==dict(state='not_captured',reason='disk full')


def test_reused_uid_and_interval_with_different_semantics_are_separate(tmp_path):
    store=periods.ObservationStore(tmp_path)
    old,source,shots=observation(full=True)
    first=store.save(old)
    original=periods.link_retained(store,SAVE,FIXTURE,99,source,shots,'epoch-a')
    changed=deepcopy(source)
    events=bytearray(changed['events'])
    struct.pack_into('<f',events,24,123.5)
    changed['events']=bytes(events)
    new=deepcopy(old)
    new['attempt_prefix']=periods.attempt_fingerprints(changed['vectors'],changed['events'],new['fingerprint_cursor'])
    second=store.save(new)
    assert second['state']=='captured' and first['capture_id']!=second['capture_id']
    changed_shots=decode_attempts(changed['vectors'],changed['events'],changed['engine_totals'])['shots']
    result=periods.link_retained(store,SAVE,FIXTURE,99,changed,changed_shots,'epoch-a')
    assert result['state']=='verified_retrospective_continuity'
    assert result['capture_id']==second['capture_id']
    assert original['provenance']['retained_semantic_fingerprint']!=result['provenance']['retained_semantic_fingerprint']
    # Both explicitly finalized alternative source versions retain their own pin.
    assert periods.link_retained(store,SAVE,FIXTURE,99,source,shots,'later')['capture_id']==first['capture_id']
    assert periods.link_retained(store,SAVE,FIXTURE,99,changed,changed_shots,'later')['capture_id']==second['capture_id']


def test_public_historical_tool_has_discoverable_bounded_schema():
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp.match_period_tools import register_match_period_tools
    async def check():
        m=FastMCP('Period evidence');register_match_period_tools(m,None)
        tools=await m.list_tools()
        assert len(tools)==1
        tool=tools[0]
        assert tool.name=='fm_report_retained_match_periods'
        assert set(tool.inputSchema['required'])=={'session_id','fixture_ref'}
        assert set(tool.inputSchema['properties'])=={'session_id','fixture_ref'}
        assert tool.annotations.readOnlyHint is False and tool.outputSchema['type']=='object'
        assert 'host-captured' in tool.description and 'Uncaptured' in tool.description
    asyncio.run(check())


def test_optional_compact_pass_witness_and_failure_do_not_block_shots(tmp_path,monkeypatch):
    from fm_live_mcp import retained_pass_periods
    value,source,shots=observation(full=True)
    expected=retained_pass_periods.pass_event_fingerprint(source['events'],value['fingerprint_cursor'])
    assert value['pass_event_fingerprint']==expected
    assert set(expected)=={'schema','semantic_sha256','event_count','cutoff_exclusive'}
    legacy=deepcopy(value);legacy.pop('pass_event_fingerprint');legacy.pop('pass_period_report_fingerprint')
    store=periods.ObservationStore(tmp_path)
    store.save(legacy)
    rich=store.save(value)
    assert rich['state']=='captured'
    result=periods.link_retained(store,SAVE,FIXTURE,99,source,shots,'epoch-a')
    assert result['capture_id']==rich['capture_id']
    monkeypatch.setattr(retained_pass_periods,'pass_event_fingerprint',lambda *args:(_ for _ in ()).throw(ValueError('unsupported optional pass source')))
    partial,_,_=observation(full=True)
    assert 'pass_event_fingerprint'not in partial
    assert periods.validate_observation(partial)


@pytest.mark.parametrize('change',[{'semantic_sha256':'g'*64},{'event_count':True},
    {'cutoff_exclusive':999},{'schema':True},{'extra':1}])
def test_invalid_optional_pass_fingerprint_rejected(change):
    value,_,_=observation(full=True)
    value['pass_event_fingerprint'].update(change)
    with pytest.raises(ValueError,match='pass continuity'):
        periods.validate_observation(value)


def test_reused_uid_identical_shots_but_changed_passes_selects_matching_capture(tmp_path):
    from fm_live_mcp.retained_pass_periods import pass_event_fingerprint,pass_period_report_fingerprint
    store=periods.ObservationStore(tmp_path)
    original,source,shots=observation(full=True)
    store.save(original)
    event=bytearray(56)
    struct.pack_into('<H',event,34,2);struct.pack_into('<H',event,50,3)
    struct.pack_into('<I',event,44,999);event[42]=7
    changed=deepcopy(source);changed['events']+=bytes(event)
    newer=deepcopy(original)
    newer['pass_event_fingerprint']=pass_event_fingerprint(changed['events'],newer['fingerprint_cursor'])
    newer['pass_period_report_fingerprint']=pass_period_report_fingerprint(changed['events'],newer['fingerprint_cursor'])
    saved=store.save(newer)
    assert saved['state']=='captured'
    result=periods.link_retained(store,SAVE,FIXTURE,99,changed,shots,'epoch-a')
    assert result['capture_id']==saved['capture_id']
    assert result['state']=='verified_retrospective_continuity'


def test_strict_pass_mismatch_does_not_erase_independent_shot_period_link(tmp_path):
    from fm_live_mcp.retained_pass_periods import pass_event_fingerprint,pass_period_report_fingerprint
    value,source,shots=observation(full=True)
    event=bytearray(56);event[42]=7
    struct.pack_into('<I',event,44,999);struct.pack_into('<H',event,34,2);struct.pack_into('<H',event,50,3)
    source['events']+=bytes(event)
    value['pass_event_fingerprint']=pass_event_fingerprint(source['events'],30)
    value['pass_period_report_fingerprint']=pass_period_report_fingerprint(source['events'],30)
    store=periods.ObservationStore(tmp_path);saved=store.save(value)
    changed=deepcopy(source);events=bytearray(changed['events']);events[-56+48]^=4;changed['events']=bytes(events)
    out=periods.link_retained(store,SAVE,FIXTURE,99,changed,shots,'epoch-a')
    assert out['state']=='verified_retrospective_continuity'
    assert out['capture_id']==saved['capture_id']
    assert out['metric_family_continuity']['passes']=={'strict_full_flags':'mismatch','period_network_fields':'matched'}
    assert store.observations(SAVE,FIXTURE)['observations'][saved['capture_id']]['pass_event_fingerprint']==value['pass_event_fingerprint']


@pytest.mark.parametrize('change',[{'report_policy':'other'},{'native_flags_mask':4},
    {'native_flags_mask':True},{'semantic_sha256':'f'*63},{'cutoff_exclusive':65536}])
def test_invalid_report_specific_witness_rejected(change):
    value,_,_=observation(full=True)
    value['pass_period_report_fingerprint'].update(change)
    with pytest.raises(ValueError,match='report-specific'):
        periods.validate_observation(value)
