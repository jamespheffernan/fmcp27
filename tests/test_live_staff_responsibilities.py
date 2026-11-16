import asyncio
import struct
import pytest
from mcp.server.fastmcp import FastMCP
from fm_live_mcp import live_staff_responsibilities as query, staff_responsibility_tools, world
from fm_live_mcp.bridge import BridgeError
from prepared_tactics_fixture import prepared_tactics_memory
from test_bridge import bridge
from test_club_staff_responsibilities import responsibility_memory
from test_database import database_memory
from test_players import memory
from test_staff import staff_record
from test_teams import team_memory
from test_world import world_memory


@pytest.fixture
def live_staff(prepared_tactics_memory,responsibility_memory,bridge,monkeypatch):
    m = responsibility_memory
    assert m is prepared_tactics_memory
    # Responsibility ordinal lookup uses mode zero; TEAM lookup shares that
    # byte and therefore needs its real fast-vector source in this fixture.
    m['vec'](m['roots']['teams']+0x68,m['team_addresses'])
    m['bridge'],m['closed'] = bridge,[]
    bridge.plugin_identity = ('synthetic_pinned_plugin',)
    class Stream:
        def __init__(self,helper,pid):
            self.pid = pid
        def close(self):
            m['closed'].append(True)
    monkeypatch.setattr(query,'ReadStream',Stream)
    monkeypatch.setattr(bridge,'_player_layout',lambda process:m['tables'])
    monkeypatch.setattr(bridge,'_read_memory',lambda process,a,n:m['read'](a,n))
    monkeypatch.setattr(bridge,'_run',lambda *args:pytest.fail('Unexpected native helper command'))
    _,identity = world.club(m['read'],m['base'],m['club'])
    bridge.club_refs['club'] = dict(address=m['club'],database_index=0,identity=identity,tables=m['tables'])
    return m


@pytest.mark.parametrize('selection',['managed','club_ref'])
def test_real_canonical_stored_report_keeps_effective_scope_unknown(live_staff,selection):
    m = live_staff
    before = dict(m['cells'])
    kwargs = dict(coach_name=' test COACH ') if selection == 'managed' else dict(club_ref='club')
    result = query.get_club_staff_responsibilities(m['bridge'],m['bridge'].session,**kwargs)
    assert result['club']['native_id'] == 688
    assert result['club']['secondary_id'] == int.from_bytes(m['read'](m['club']+0x10,4),'little')
    assert 'random_id' not in result['club']
    assert result['staff_responsibilities']['source_slot_count'] == 1
    row = result['staff_responsibilities']['records'][0]
    assert row['stored_reference']['person']['display_name'] == 'Test Müller'
    assert result['staff_responsibilities']['effective_assignments'] is None
    assert not result['staff_responsibilities']['complete_effective_allocation_verified']
    if selection == 'managed':
        assert result['managed_context']['coach_name'] == 'Test Coach'
    else:
        assert result['managed_context'] is None
    assert result['atomic'] is result['native_calls'] is result['saved_file_fallback'] is False
    assert m['cells'] == before and m['closed'] == [True] and m['bridge']._reader is None


@pytest.mark.parametrize('secondary',[0,688,999])
@pytest.mark.parametrize('selection',['managed','club_ref'])
def test_club_secondary_identity_is_named_and_preserved_without_random_semantics(live_staff,secondary,selection):
    m = live_staff
    m['put'](m['club']+0x10,struct.pack('<I',secondary))
    m['bridge'].club_refs['club']['identity'] = world.club(m['read'],m['base'],m['club'])[1]
    result = query.get_club_staff_responsibilities(m['bridge'],m['bridge'].session,
        **({'club_ref':'club'}if selection=='club_ref'else{}))
    assert result['club']['secondary_id'] == secondary
    assert 'random_id' not in result['club']


@pytest.mark.parametrize('mutation',['final_current','public_save','second_layout','save_identity','club_identity','native_source','person_identity'])
@pytest.mark.parametrize('selection',['managed','club_ref'])
def test_post_projection_callbacks_cannot_publish_stale_staff_facts(live_staff,monkeypatch,mutation,selection):
    m,bridge = live_staff,live_staff['bridge']
    if mutation == 'final_current':
        original,calls = bridge._current,[]
        def current(session):
            calls.append(1)
            if len(calls) == 3:m['put'](m['responsibility_row']+4,b'\xa1')
            return original(session)
        monkeypatch.setattr(bridge,'_current',current)
    elif mutation == 'second_layout':
        original,calls = bridge._player_layout,[]
        def layout(process):
            calls.append(1)
            if len(calls) == 2:bridge.plugin_identity = ('changed_plugin',)
            return original(process)
        monkeypatch.setattr(bridge,'_player_layout',layout)
    elif mutation == 'save_identity':
        original,calls = bridge._world_state,[]
        def loaded(process,tables):
            result = original(process,tables)
            calls.append(1)
            return (result[0],result[1],('changed',)) if len(calls) == 2 else result
        monkeypatch.setattr(bridge,'_world_state',loaded)
    else:
        original = bridge._public_save
        def public(save):
            if mutation == 'public_save':m['q'](m['club']+0xB0,0)
            elif mutation == 'club_identity':m['put'](m['club']+12,struct.pack('<I',999))
            elif mutation == 'native_source':m['put'](m['base']+query.club_staff_responsibilities.NATIVE_SPANS[0][0],bytes(4))
            else:m['put'](m['responsibility_person']+12,struct.pack('<I',777))
            return original(save)
        monkeypatch.setattr(bridge,'_public_save',public)
    with pytest.raises(BridgeError,match='rejected'):
        query.get_club_staff_responsibilities(bridge,bridge.session,
            **({'club_ref':'club'} if selection == 'club_ref' else {}))
    assert m['closed'] == [True] and bridge._reader is None


@pytest.mark.parametrize('fault',['unknown_club','unknown_coach','missing_native_byte','reader_close'])
def test_source_and_selection_failures_close_without_publishing(live_staff,monkeypatch,fault):
    m,bridge = live_staff,live_staff['bridge']
    kwargs = {}
    if fault == 'unknown_club':kwargs['club_ref'] = 'expired'
    elif fault == 'unknown_coach':kwargs['coach_name'] = 'Missing Coach'
    elif fault == 'missing_native_byte':
        del m['cells'][m['base']+query.club_staff_responsibilities.NATIVE_SPANS[0][0]]
    else:
        original = query.ReadStream.close
        def close(reader):
            original(reader)
            raise query.ReaderError('Synthetic close failure')
        monkeypatch.setattr(query.ReadStream,'close',close)
    with pytest.raises(BridgeError):
        query.get_club_staff_responsibilities(bridge,bridge.session,**kwargs)
    assert m['closed'] == [True] and bridge._reader is None


@pytest.mark.parametrize('arguments',[{'session_id':''},{'session_id':True},{'coach_name':''},{'coach_name':True},
    {'club_ref':''},{'club_ref':True},{'club_ref':'club','coach_name':'Test Coach'}])
def test_bad_selectors_fail_before_a_native_reader_is_created(live_staff,arguments):
    m = live_staff
    with pytest.raises(BridgeError):
        query.get_club_staff_responsibilities(m['bridge'],**{'session_id':m['bridge'].session,**arguments})
    assert not m['closed'] and m['bridge']._reader is None


def test_schema_declares_the_stored_read_only_scope_and_native_unknowns():
    mcp = FastMCP('staff-responsibility-contract')
    staff_responsibility_tools.register_staff_responsibility_tools(mcp,object())
    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == 1 and tools[0].name == 'fm_get_club_staff_responsibilities'
    assert tools[0].annotations.readOnlyHint is True and tools[0].annotations.destructiveHint is False
    assert tools[0].inputSchema['required'] == ['session_id']
    assert set(tools[0].inputSchema['properties']) == {'session_id','coach_name','club_ref'}
    assert 'not verified effective delegation' in tools[0].description
    assert 'Preserve template placeholders' in tools[0].description
