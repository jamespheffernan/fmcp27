from copy import deepcopy
import pytest
from fm_live_mcp import current_cup_history as source
from fm_live_mcp.bridge import BridgeError
from test_assessment_public import (public_assessment_memory, bridge, shortlist_public_memory,
                                    prepared_tactics_memory, database_memory, memory,
                                    team_memory, world_memory)


@pytest.fixture
def cup_world(public_assessment_memory, bridge, monkeypatch):
    m=public_assessment_memory
    ref=m['assessment_player_ref'];primary=bridge.player_refs[ref]['address']
    m['q'](primary+0x128,0)
    bridge.competition_refs['cup']={'address':0x999000}
    calls=[]
    def collect(read,base,comp,indices):
        assert comp['address']==0x999000
        assert len(indices)==1
        index,=indices
        # PERSON database index, never the bound PERSON address.
        assert index<10000
        calls.append(index)
        return ({'source_state':'available','native_season_code':2030,'phase':None},
                {index:{'state':'present','stored_appearance_counter_raw_u8':0,
                        '_team_index':42,'native_other_team_cup_history_condition':None}})
    monkeypatch.setattr(source,'collect_current',collect)
    return m,ref,calls


def test_real_bound_identity_duplicates_and_zero_preserved(bridge,cup_world):
    _,ref,calls=cup_world
    result=bridge.get_current_player_cup_history(bridge.session,'cup',[ref,ref])
    assert len(calls)==1
    assert result['players'][0]==result['players'][1]
    assert result['players'][0]['native_identity']['native_id']==12345
    assert result['players'][0]['history']['stored_appearance_counter_raw_u8']==0
    assert '_team_index' not in str(result)
    assert result['fixture_eligibility']=='not_evaluated'
    assert result['historical_kickoff_verdict']=='not_evaluated'


def test_stale_and_mismatched_refs_reject(bridge,cup_world):
    _,ref,_=cup_world
    with pytest.raises(BridgeError,match='competition reference'):
        bridge.get_current_player_cup_history(bridge.session,'missing',[ref])
    with pytest.raises(BridgeError,match='player reference'):
        bridge.get_current_player_cup_history(bridge.session,'cup',['missing'])
    with pytest.raises(BridgeError,match='fixture reference'):
        bridge.get_current_player_cup_history(bridge.session,'cup',[ref],'missing')
    with pytest.raises(BridgeError,match='at most32'):
        bridge.get_current_player_cup_history(bridge.session,'cup',[ref]*33)


def test_unavailable_is_not_zero(bridge,cup_world,monkeypatch):
    _,ref,_=cup_world
    monkeypatch.setattr(source,'collect_current',lambda *a:({'source_state':'unavailable'},None))
    result=bridge.get_current_player_cup_history(bridge.session,'cup',[ref])
    assert result['players'][0]['history'] is None


def test_late_current_source_drift_rejects_all(bridge,cup_world,monkeypatch):
    m,ref,_=cup_world
    original=source.collect_current
    primary=bridge.player_refs[ref]['address']
    def collect(*args):
        read=args[0]
        read(primary+0x128,8)
        result=original(*args)
        m['q'](primary+0x128,0x123000)
        return result
    monkeypatch.setattr(source,'collect_current',collect)
    with pytest.raises(BridgeError,match='changed during read'):
        bridge.get_current_player_cup_history(bridge.session,'cup',[ref])
