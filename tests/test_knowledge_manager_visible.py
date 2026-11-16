"""Manager-visible attribute tool: validation, state mapping, registration, scope text."""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from fm_live_mcp import knowledge_manager_visible as km
from fm_live_mcp.bridge import BridgeError


def test_field_ids_default_names_ids_and_errors():
    assert km.field_ids(None)==tuple(range(47))
    assert km.field_ids(['passing','Aerial Reach',46])==(18,0,46)
    for bad in [[],['nonsense'],['Passing','passing'],[47],[-1],[True],['Passing']*48,'Passing',[1.5]]:
        with pytest.raises(BridgeError):km.field_ids(bad)


@pytest.mark.parametrize('refs',[[],'x',[''],[1],['a','a'],['a']*29,None])
def test_player_reference_validation(refs):
    with pytest.raises(BridgeError,match='distinct nonempty player references'):
        km.get_manager_visible_attributes(SimpleNamespace(lock=nullcontext()),'s',refs)


def test_cell_budget_and_coach_name_validation():
    bridge=SimpleNamespace(lock=nullcontext())
    with pytest.raises(BridgeError,match='player-field cells'):
        km.get_manager_visible_attributes(bridge,'s',[str(i) for i in range(15)])
    with pytest.raises(BridgeError,match='coach_name'):
        km.get_manager_visible_attributes(bridge,'s',['a'],['Passing'],'')


def test_capture_failures_become_one_rejection_without_partial_data(monkeypatch):
    bridge=SimpleNamespace(lock=nullcontext())
    def boom(*args):raise ValueError('Field capture journal was poisoned: x')
    monkeypatch.setattr(km,'_capture',boom)
    with pytest.raises(BridgeError,match='no partial result returned'):
        km.get_manager_visible_attributes(bridge,'s',['a'],['Passing'])


def test_unknown_player_reference_is_rejected_before_any_native_work():
    bridge=SimpleNamespace(lock=nullcontext(),player_refs={},_current=lambda sid:SimpleNamespace(pid=1))
    with pytest.raises(BridgeError,match='Unknown or expired player reference'):
        km.get_manager_visible_attributes(bridge,'s',['gone'],['Passing'])


def test_unsupported_record_kind_is_unavailable_with_reason_and_never_reads_the_source(monkeypatch):
    monkeypatch.setattr(km,'_bound_person',lambda *a:(None,'virtual',None,None))
    row=km._subject(None,0,(),None,'ref',{'address':4096})
    assert row['person'] is None and row['reason']=='unsupported_record_kind_compact_or_generated'


def test_unsupported_source_family_is_unavailable_with_reason(monkeypatch):
    monkeypatch.setattr(km,'_bound_person',lambda *a:(None,'actual','N','N'))
    def refuse(*a):raise km.population.SourceUnavailable('family')
    monkeypatch.setattr(km.population,'_base_identity',refuse)
    row=km._subject(None,0,(),None,'ref',{'address':4096})
    assert row['person'] is None and row['reason']=='unsupported_all_actual_source_family'


def test_rejected_reference_is_a_rejection_not_a_guess(monkeypatch):
    def reject(*a):raise ValueError('type/index changed')
    monkeypatch.setattr(km,'_bound_person',reject)
    with pytest.raises(BridgeError,match='Player reference rejected'):km._subject(None,0,(),None,'ref',{'address':4096})


class Healthy:
    def healthy(self):pass


def controlled(result=None,error=None,init_error=None):
    class Bound:
        def __init__(self,*args):
            if init_error:raise init_error
        def permitted(self):
            if error:raise error
            return result
        def verify(self):pass
    return Bound


def field(Bound,journal=None):
    bridge=SimpleNamespace(lock=nullcontext())
    row=dict(person=1,subject_identity=(1,2,3))
    return km._field(bridge,'sid',Bound,journal or Healthy(),row,18,None)


def test_field_results_pass_through_only_the_permitted_shapes(monkeypatch):
    monkeypatch.setattr(km.scope,'collection_stream',lambda *a:nullcontext())
    assert field(controlled({'state':'exact','value':13}))=={'state':'exact','value':13}
    assert field(controlled({'state':'range','minimum':8,'maximum':12}))['maximum']==12


def test_source_failures_become_unavailable_with_a_reason(monkeypatch):
    monkeypatch.setattr(km.scope,'collection_stream',lambda *a:nullcontext())
    unavailable=km.ui_source.core.SourceUnavailable
    got=field(controlled(error=unavailable('Unproved path')))
    assert got=={'state':'unavailable','reason':'unavailable_source','detail':'Unproved path'}
    assert field(controlled(error=ValueError('Invalid native integer operand')))['detail']=='Invalid native integer operand'
    assert field(controlled(init_error=unavailable('Missing node')))['state']=='unavailable'
    with pytest.raises(ValueError):field(controlled(init_error=ValueError('constructor')))


def test_poisoned_journal_rejects_instead_of_returning_a_value(monkeypatch):
    monkeypatch.setattr(km.scope,'collection_stream',lambda *a:nullcontext())
    class Poisoned:
        def healthy(self):raise ValueError('Field capture journal was poisoned: byte')
    with pytest.raises(ValueError,match='poisoned'):field(controlled({'state':'exact','value':1}),Poisoned())


def test_public_shape_reports_scope_firewall_cost_and_context_match():
    before=dict(save=dict(name='S',current_date='2030-12-08'),coach=dict(name='Cesar  Jules',club=dict(name='Newcastle United',short_name='N')))
    raw=dict(before=before,state_counts=dict(exact=1,range=0,unknown=0,unavailable=0),
             journal=dict(forbidden_attribute_intervals=3,authorized_attribute_bytes=1,final_fence_passes=2),
             cost=dict(seconds=1.0),
             subjects=[dict(player_ref='r',record_kind='actual',name='A',display_name='A',native_identity=dict(database_index=1),
                            fields=[dict(native_field_id=18,name='Passing',state='exact',value=13)])])
    out=km._public(raw,'sid')
    assert out['view']=='manager_visible_attributes' and out['default_mode_unchanged'] is True
    assert out['context_matches_oracle_verified_scope'] is True
    assert out['firewall']['unpermitted_attribute_bytes_read'] is False
    assert out['players'][0]['state_counts']['exact']==1
    before['save']['current_date']='2030-12-09'
    assert km._public(raw,'sid')['context_matches_oracle_verified_scope'] is False
    assert 'perceived stars' in out['scope'] and 'unverified' in out['scope']


def test_tool_is_registered_read_only_and_documented():
    import asyncio
    from fm_live_mcp.server import mcp
    tool=next(t for t in asyncio.run(mcp.list_tools()) if t.name=='fm_get_manager_visible_attributes')
    assert tool.annotations.readOnlyHint is True and tool.annotations.destructiveHint is False
    assert set(tool.inputSchema['properties'])=={'session_id','player_refs','fields','coach_name'}
    for phrase in ('exact','range','unknown','unavailable','firewall','0.13 s','stored values'):
        assert phrase in tool.description
