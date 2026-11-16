from unittest.mock import Mock
import struct
import pytest
from fm_live_mcp import current_player_physical as module


def setup(monkeypatch,frontier=100,source_match=4096):
    fixture={'date':'2030-11-11','competition':{'native_id':11},'home_team':{},'away_team':{}}
    binding={'engine':4096,'client':8192,'team_indices':[545,549]}
    context={'bound_active_fixture':fixture,'reason':None}
    bound={'source_match_address':source_match,'current_time_slice':100,
           'official_match_unique_id':77,'playback_address':12288}
    monkeypatch.setattr(module.active_match_source,'inspect_context',Mock(return_value=(context,binding)))
    monkeypatch.setattr(module.active_match_shot_timeline,'_verify_bound',Mock())
    monkeypatch.setattr(module.active_match_playback,'capture',Mock(return_value={
        'state':'bound_playback_cursor','bound_playback':bound}))
    sheet={'source_state':'available','selected_count':1,'duplicate_person_indices':[],
           'team':{'database_index':545},'slots':[{'category':'starting_position',
           'slot_index':0,'person':{'database_index':10,'native_id':123}}]}
    monkeypatch.setattr(module.live_team_sheet_source,'inspect',Mock(return_value=sheet))
    def actor(side,index,native,name):
        return {'side_index':side,'person':{'name':name,'native_identity':{
            'database_index':index,'native_id':native}},'physical':{'condition_percent_computed':87.6543}}
    physical=Mock(return_value={'rows':[actor(0,10,123,'Selected'),
                                      actor(0,11,456,'Not selected'),actor(1,10,123,'Opponent')]})
    monkeypatch.setattr(module.active_player_physical,'inspect',physical)
    memory={a:raw for a,raw in module.FRONTIER_SPANS}
    memory[4096+0x154dc]=struct.pack('<I',frontier)
    memory[16384+8]=struct.pack('<I',545)
    return lambda a,n:memory[a], {'team_address':16384},physical,sheet


@pytest.mark.parametrize('frontier',[99,101,65536])
def test_unsynchronized_or_wrapped_frontier_withholds_all_people_and_numbers(monkeypatch,frontier):
    read,coach,physical,_=setup(monkeypatch,frontier=frontier)
    out=module._inspect(read,0,'2030-11-11',coach)
    assert out['state']=='withheld'
    assert out['players']is None
    physical.assert_not_called()


def test_distinct_native_copy_owners_are_bound_by_official_identity_not_address(monkeypatch):
    read,coach,physical,_=setup(monkeypatch,source_match=4104)
    assert module._inspect(read,0,'2030-11-11',coach)['state']=='available'
    module.active_match_shot_timeline._verify_bound.assert_called_once()


def test_equal_frontiers_only_release_current_manager_selected_identity_intersection(monkeypatch):
    read,coach,_,_=setup(monkeypatch)
    out=module._inspect(read,0,'2030-11-11',coach)
    assert out['state']=='available'
    assert [p['person']['name']for p in out['players']]==['Selected']
    assert out['displayed_time_verified']is False
    assert out['publication_at_exact_display_instant_verified']is False
    assert out['active_XI_verified']is False
    assert out['fixture_eligibility']=='not_evaluated'


def test_ambiguous_or_unknown_selection_does_not_leak_engine_roster(monkeypatch):
    read,coach,_,sheet=setup(monkeypatch)
    sheet['duplicate_person_indices']=[10]
    assert module._inspect(read,0,'2030-11-11',coach)['players']is None
    sheet['duplicate_person_indices']=[];sheet['selected_count']=None
    assert module._inspect(read,0,'2030-11-11',coach)['players']is None


def test_public_tool_discovery_accepts_only_session_and_coach():
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp.player_physical_tools import register_player_physical_tools
    mcp=FastMCP('physical-test')
    register_player_physical_tools(mcp,Mock())
    tools=asyncio.run(mcp.list_tools())
    assert [t.name for t in tools]==['fm_get_current_match_player_physical']
    assert set(tools[0].inputSchema['properties'])=={'session_id','coach_name'}
    assert 'withheld' in tools[0].description
    assert 'exact displayed publication' in tools[0].description


def test_both_changed_attempts_return_structured_withheld_without_rejected_facts(monkeypatch):
    from contextlib import nullcontext
    bridge=Mock()
    bridge.lock=nullcontext()
    bridge._read_scope.side_effect=lambda session, **_kw:nullcontext()
    bridge._player_layout.return_value=(100,)
    original=Mock();original.observed={}
    bridge._world_state.return_value=(original,{'current_date':'2030-11-11'},None)
    monkeypatch.setattr(module,'ReportReadSet',Mock(return_value=original))
    monkeypatch.setattr(module,'_inspect',Mock(return_value={'fixture':{'secret':'rejected'},'players':[1]}))
    original.verify.side_effect=ValueError('Game state changed during read; retry')
    out=module.current_player_physical(bridge,'session')
    assert out['state']=='withheld'
    assert out['reason']=='physical_snapshot_changed_during_read'
    assert out['players']is out['fixture']is out['save']is None
    assert original.verify.call_count==2
    assert bridge._current.call_count==3


def test_non_drift_source_errors_remain_fail_closed(monkeypatch):
    from contextlib import nullcontext
    bridge=Mock();bridge.lock=nullcontext();bridge._read_scope.side_effect=lambda s, **_kw:nullcontext()
    bridge._player_layout.return_value=(100,)
    original=Mock();original.observed={}
    bridge._world_state.return_value=(original,{'current_date':'2030-11-11'},None)
    monkeypatch.setattr(module,'ReportReadSet',Mock(return_value=original))
    monkeypatch.setattr(module,'_inspect',Mock(side_effect=ValueError('canonical identity changed')))
    with pytest.raises(ValueError,match='canonical identity changed'):
        module.current_player_physical(bridge,'session')
    assert bridge._world_state.call_count==1
