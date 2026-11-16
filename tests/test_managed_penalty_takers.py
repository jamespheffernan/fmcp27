import struct
import pytest
from fm_live_mcp import managed_penalty_takers as takers, world
from prepared_tactics_fixture import database_memory,memory,prepared_tactics_memory,team_memory,world_memory

@pytest.fixture
def state(prepared_tactics_memory,monkeypatch):
    m=prepared_tactics_memory
    for rva,raw in takers.NATIVE_SPANS:m['put'](m['base']+rva,raw)
    original_table=takers.database.table
    monkeypatch.setattr(takers.database,'table',lambda read,base,kind:{'count':100} if kind=='people' else original_table(read,base,kind))
    monkeypatch.setattr(takers.live_team_sheet_source,'_person',lambda read,base,people,index:{'database_index':index,'native_id':1000+index,'secondary_id':1000+index,'name':'Person '+str(index),'record_kind':'actual'})
    monkeypatch.setattr(takers,'_clubs',lambda read,base,people,index,person:({'on_loan':index==2},'decoded'))
    def vector(values):
        if not values:m['put'](m['tactics_payload']+0x1e0,bytes(24));return
        ptr=m['allocate'](len(values)*4);m['put'](ptr,struct.pack(f'<{len(values)}I',*values));m['put'](m['tactics_payload']+0x1e0,struct.pack('<QQQ',ptr,ptr+len(values)*4,ptr+len(values)*4))
    m['penalty_vector']=vector;vector([1,2]);return m

def inspect(m):
    snapshot=world.ReadSet(m['read']);out=takers.inspect(snapshot,m['base'],m['coach']);snapshot.verify();return out

def test_order_names_and_loan_state_are_not_attribute_rank_or_selection(state):
    out=inspect(state)
    assert [(r['priority'],r['person_index_word'],r['person']['name']) for r in out['ordered_takers']]==[(1,1,'Person 1'),(2,2,'Person 2')]
    assert out['ordered_takers'][1]['clubs']['on_loan'] is True
    assert out['edit_session_override']['state']=='unknown' and out['actual_match_taker_state']=='not_established'
    assert 'address' not in str(out)

def test_empty_sentinel_duplicates_and_unresolved_are_preserved(state):
    state['penalty_vector']([2,0xffffffff,2,0xfffffffe,101]);out=inspect(state)
    assert out['stored_count']==5 and out['duplicate_person_indices']==[2]
    assert [r['state'] for r in out['ordered_takers']]==['identified','unassigned_sentinel','identified','unresolved_person_reference','unresolved_person_reference']
    assert out['ordered_takers'][1]['person'] is None and out['ordered_takers'][4]['unavailable_reason']=='PERSON_index_outside_live_table'
    state['penalty_vector']([]);empty=inspect(state)
    assert empty['source_state']=='available' and empty['ordered_takers']==[] and empty['stored_count']==0

def test_missing_owner_differs_from_empty(state):
    state['vec'](state['tactics_manager']+0x20,[]);out=inspect(state)
    assert out['source_state']=='unavailable' and out['ordered_takers'] is None

@pytest.mark.parametrize('fault',['bounds','alignment','native','owner'])
def test_invalid_source_fails_closed(state,fault):
    m=state
    if fault=='bounds':m['put'](m['tactics_payload']+0x1e0,struct.pack('<QQQ',0x1000,0x2000,0x2000))
    elif fault=='alignment':m['put'](m['tactics_payload']+0x1e0,struct.pack('<QQQ',0x1001,0x1005,0x1005))
    elif fault=='native':m['put'](m['base']+takers.NATIVE_SPANS[0][0],b'\x00')
    else:m['vec'](m['tactics_manager']+0x20,[m['owner_container'],m['owner_container']])
    with pytest.raises(ValueError):inspect(m)

def test_priority_read_drift_rejects_whole_projection(state):
    m=state;start=struct.unpack('<Q',m['read'](m['tactics_payload']+0x1e0,8))[0];changed=False
    def read(address,count):
        nonlocal changed
        raw=m['read'](address,count)
        if address==start and count==8 and not changed:
            changed=True;m['put'](start,struct.pack('<I',9))
        return raw
    snapshot=world.ReadSet(read);takers.inspect(snapshot,m['base'],m['coach'])
    with pytest.raises(ValueError,match='changed'):snapshot.verify()

def test_penalty_tool_is_readonly_and_source_explicit():
    import asyncio
    from fm_live_mcp.server import mcp
    tool=next(t for t in asyncio.run(mcp.list_tools()) if t.name=='fm_get_managed_penalty_takers')
    assert set(tool.inputSchema['properties'])=={'session_id','coach_name'}
    assert tool.annotations.readOnlyHint
    assert 'Pending working-edit overrides are explicitly unknown' in tool.description
