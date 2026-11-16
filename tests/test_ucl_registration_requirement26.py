"""Composition semantics and actual existing-adapter publication fences."""
from copy import deepcopy

import pytest

from test_ucl_registration import bridge as canonical_bridge, invoke
from fm_live_mcp import ucl_registration as adapter
from fm_live_mcp.bridge import BridgeError

EXTRA = dict(roster=0x3100, current_club=0x3108, competition=0x3110,
             current_rule=0x3118, medical=0x3120, context=0x3128)


@pytest.fixture
def composed(canonical_bridge, monkeypatch):
    bridge = canonical_bridge
    for at in EXTRA.values():bridge.cells[at] = b'\1'
    for ref,binding in bridge.player_refs.items():
        bridge.cells[binding['address']+19] = b'\1'if ref=='p2'else b'\0'
    calls = []
    def projection(read, base, coach, fixture, decoded, current_date, subjects):
        calls.append(deepcopy(subjects))
        values = {name:read(at,1)[0]for name,at in EXTRA.items()}
        rows = []
        for ref,primary,kind in subjects:
            value = read(primary+19,1)[0]
            native = None if value==2 or kind!='actual'else bool(value)
            rows.append(dict(player_ref=ref, state='unavailable'if native is None else'checked',
                native_requirement26=native, reason='unsupported_test_operator'if native is None else'native_test_clause',
                goalkeeper_position_rating=None if kind!='actual' else 20,
                registration_exemption=True if native else None, full_eligibility_evaluated=False))
        return dict(players=rows, aggregate=dict(state='checked', native_result=True,
            stored_player_slot_count=values['roster'], medical_source=values['medical']),
            fixture_context=dict(state='available'if values['context']else'unavailable',
                reason=None if values['context']else'unsupported_pending_context'),
            current_club_rule_sources=[dict(club=values['current_club'],
                competition=values['competition'], rule=values['current_rule'])])
    monkeypatch.setattr(adapter.requirement26_source,'project',projection)
    return bridge,calls,projection


@pytest.mark.parametrize('value,expected',[(0,None),(1,True),(2,None)])
def test_native26_clause_keeps_true_or_null_coverage_and_first14_skip(composed,value,expected):
    bridge,calls,_ = composed
    bridge.cells[bridge.player_refs['p2']['address']+19] = bytes((value,))
    result = invoke(bridge)
    assert [row['registration_covered_by_current_sources']for row in result['players']]==[True,True,expected]
    assert [row['requirement26']['native_result']for row in result['players']]==[False,None,
        None if value==2 else bool(value)]
    assert result['players'][1]['requirement26']['state']=='not_evaluated_first_requirement14_sufficient'
    assert all([ref for ref,_,_ in call]==['p0','p2']for call in calls)
    assert result['requirement26_aggregate']['stored_player_slot_count']==1
    assert result['requirement26_current_club_rule_sources']==[dict(club=1,competition=1,rule=1)]
    assert result['full_eligibility_evaluated'] is result['current_selection_verified'] is False
    assert all(row['full_eligibility_evaluated'] is False for row in result['players'])
    assert not {'eligible','ineligible','medical_clearance'}&result.keys()


def test_all_first14_sufficient_omits_26_source_and_aggregate(composed):
    bridge,calls,_ = composed
    for binding in bridge.player_refs.values():bridge.cells[binding['address']+17] = b'\1'
    result = invoke(bridge)
    assert calls==[]
    assert result['requirement26_context']['state']=='not_evaluated'
    assert result['requirement26_aggregate'] is None
    assert all(row['requirement26']['state']=='not_evaluated_first_requirement14_sufficient'for row in result['players'])


def test_aliases_preserve_all_rows_and_evaluate_canonical_subject_once(composed):
    bridge,calls,_ = composed
    binding = deepcopy(bridge.player_refs['p2'])
    refs = [f'alias{i}'for i in range(32)]
    bridge.player_refs = {ref:deepcopy(binding)for ref in refs}
    result = invoke(bridge,player_refs=refs)
    assert [row['player_ref']for row in result['players']]==refs
    assert result['count']==32 and result['unique_person_count']==1
    assert len(calls)==2 and all(len(call)==1 and call[0][0]=='alias0'for call in calls)
    assert all(row['requirement26']['native_result'] is True for row in result['players'])


def test_26_only_unsupported_context_preserves_incumbent_context_and_results(composed):
    bridge,_,_ = composed
    bridge.cells[EXTRA['context']] = b'\0'
    result = invoke(bridge)
    assert result['fixture_context']['state']=='available'
    assert result['requirement26_context']['state']=='unavailable'
    assert result['players'][0]['registration']['native_predicate_result'] is True
    assert result['players'][1]['requirement14']['native_requirement14'] is True


@pytest.mark.parametrize('callback',[3,5])
@pytest.mark.parametrize('name',list(EXTRA)+['predicate'])
def test_new_source_mutation_during_rebind_or_after_last_callback_rejects(composed,callback,name):
    bridge,_,_ = composed
    at = bridge.player_refs['p2']['address']+19 if name=='predicate'else EXTRA[name]
    bridge.hooks[callback] = lambda b:b.cells.__setitem__(at,bytes((b.cells[at][0]^1,)))
    with pytest.raises(BridgeError,match='no partial result'):invoke(bridge)
    assert bridge.closed


@pytest.mark.parametrize('name',list(EXTRA))
def test_missing_26_physical_source_rejects_even_with_known_registered_row(composed,name):
    bridge,_,_ = composed
    del bridge.cells[EXTRA[name]]
    with pytest.raises(BridgeError,match='no partial result'):invoke(bridge)
    assert bridge.closed


@pytest.mark.parametrize('fault',['missing_row','reordered_rows','integer_predicate'])
def test_projection_coverage_and_strict_native_predicate_contract(composed,monkeypatch,fault):
    bridge,_,original = composed
    def changed(*args):
        result = original(*args)
        if fault=='missing_row':result['players'].pop()
        elif fault=='reordered_rows':result['players'].reverse()
        else:result['players'][0]['native_requirement26'] = 1
        return result
    monkeypatch.setattr(adapter.requirement26_source,'project',changed)
    with pytest.raises(BridgeError,match='no partial result'):invoke(bridge)


def test_new_source_fences_follow_every_callback(composed):
    bridge,_,_ = composed
    invoke(bridge)
    final = bridge.events.index(('callback',5))
    assert all(event[0] in ('read','close')for event in bridge.events[final+1:])
    for journal in bridge.journals:
        assert {(at,1)for at in EXTRA.values()}<=journal.observed.keys()
    assert bridge.closed
