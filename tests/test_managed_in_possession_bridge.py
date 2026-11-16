"""Owning Bridge checks; source geometry is tested independently."""
from contextlib import contextmanager
from copy import deepcopy
import asyncio

import pytest

from fm_live_mcp import bridge as module, players, server, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge


@pytest.fixture
def sheet(bridge, monkeypatch):
    memory = {0x100:b'selection'}
    snapshot = world.ReadSet(lambda address,length: memory[address][:length])
    coach = {'name':'Cesar Jules','club':{'name':'Newcastle United'},
             'team_address':0x8000,'manager_address':0x9000}
    save = {'name':'Career','current_date':'2030-10-28','coaches':[coach]}
    source = {'team':{'database_index':545,'native_id':688},'source_state':'available',
        'unavailable_reason':None,'role_boundary_state':'unresolved',
        'slots':[{'slot_index':i,'state':'empty' if i>19 else 'selected',
                  'person_index':None if i>19 else i} for i in range(26)]}
    calls = {'opened':0,'closed':0,'inspect':0}
    @contextmanager
    def scope(session):
        assert bridge.lock._is_owned()
        calls['opened']+=1
        try:
            yield
        finally:
            calls['closed']+=1
    def inspect(read,base,selected):
        assert bridge.lock._is_owned() and read is snapshot
        assert base == 0x100000 and selected is coach
        calls['inspect']+=1
        read(0x100,9)
        return deepcopy(source)
    monkeypatch.setattr(bridge,'_read_scope',scope)
    monkeypatch.setattr(bridge,'_player_layout',lambda process:tuple(0x100000+r for r in players.RVA))
    monkeypatch.setattr(bridge,'_world_state',lambda process,tables:(snapshot,save,('save',)))
    monkeypatch.setattr(module.live_in_possession_source,'inspect',inspect)
    return dict(memory=memory,snapshot=snapshot,coach=coach,save=save,source=source,calls=calls,inspect=inspect)


def test_scope_and_complete_order_preserved_without_new_refs(bridge,sheet):
    bridge.player_refs['old']={'identity':'keep'}
    result=bridge.get_managed_in_possession_positions(bridge.session)
    assert result['slots']==sheet['source']['slots']
    assert result['role_boundary_state']=='unresolved'
    assert result['coach']=='Cesar Jules' and result['club']==sheet['coach']['club']
    assert 'manager_address' not in result and 'team_address' not in result
    assert sheet['calls']=={'opened':1,'closed':1,'inspect':1}
    assert bridge.player_refs=={'old':{'identity':'keep'}} and bridge.team_refs=={}


def test_unavailable_is_not_empty_selection(bridge,sheet):
    sheet['source'].update(source_state='unavailable',unavailable_reason='existing_edit_session_missing',
                           slots=None,role_boundary_state='source_unavailable')
    result=bridge.get_managed_in_possession_positions(bridge.session)
    assert result['slots'] is None and result['unavailable_reason']=='existing_edit_session_missing'


def test_duplicates_and_empty_positions_not_compacted(bridge,sheet):
    sheet['source']['slots'][1]['person_index']=0
    result=bridge.get_managed_in_possession_positions(bridge.session)
    assert [s['slot_index'] for s in result['slots']]==list(range(26))
    assert [s['person_index'] for s in result['slots'][:2]]==[0,0]
    assert len(result['slots'])==26 and result['slots'][25]['state']=='empty'


@pytest.mark.parametrize('failure',['source','mutation','process'])
def test_failure_rejects_entire_selection_and_closes_scope(bridge,sheet,monkeypatch,failure):
    if failure=='process':
        current=bridge._current
        calls=[]
        def changed(session):
            calls.append(session)
            if len(calls)==2:
                raise BridgeError('process changed')
            return current(session)
        monkeypatch.setattr(bridge,'_current',changed)
    else:
        def inspect(*args):
            result=sheet['inspect'](*args)
            if failure=='source':
                raise ValueError('invalid typed session')
            sheet['memory'][0x100]=b'changed!!'
            return result
        monkeypatch.setattr(module.live_in_possession_source,'inspect',inspect)
    with pytest.raises(BridgeError,match='no partial read'):
        bridge.get_managed_in_possession_positions(bridge.session)
    assert sheet['calls']['opened']==sheet['calls']['closed']==1
    assert bridge.player_refs=={} and bridge.team_refs=={}


def test_coach_selection_is_mandatory_before_source(bridge,sheet):
    sheet['save']['coaches'].append({**sheet['coach'],'name':'Other'})
    with pytest.raises(BridgeError,match='Select one active coach'):
        bridge.get_managed_in_possession_positions(bridge.session)
    assert sheet['calls']['inspect']==0
    assert bridge.get_managed_in_possession_positions(bridge.session,'  CESAR Jules ')['coach']=='Cesar Jules'


@pytest.mark.parametrize('name',['',[],1,'x'*257,'Unknown'])
def test_invalid_coach_does_not_read_source(bridge,sheet,name):
    with pytest.raises(BridgeError):
        bridge.get_managed_in_possession_positions(bridge.session,name)
    assert sheet['calls']['inspect']==0


def test_public_tool_readonly_schema_and_forwarding(monkeypatch):
    tool=next(t for t in asyncio.run(server.mcp.list_tools()) if t.name=='fm_get_managed_in_possession_positions')
    assert set(tool.inputSchema['properties'])=={'session_id','coach_name'}
    assert tool.inputSchema['required']==['session_id']
    assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
    assert not tool.annotations.openWorldHint
    calls=[]
    monkeypatch.setattr(server.bridge,'get_managed_in_possession_positions',lambda *args:calls.append(args) or {'state':'test'})
    assert server.fm_get_managed_in_possession_positions('session','Coach')=={'state':'test'}
    assert calls==[('session','Coach')]


def test_invalid_session_rejected_before_source(bridge,sheet):
    with pytest.raises(BridgeError):
        bridge.get_managed_in_possession_positions('invalid')
    assert sheet['calls']['inspect']==0


def test_status_advertises_in_possession_assignments(bridge):
    assert bridge.status()['capabilities']['managed_in_possession_positions'] is True


def test_public_tool_invalid_session_error():
    from mcp.server.fastmcp.exceptions import ToolError
    with pytest.raises(ToolError,match='session|Attach|attach'):
        asyncio.run(server.mcp.call_tool('fm_get_managed_in_possession_positions',{'session_id':'invalid'}))
