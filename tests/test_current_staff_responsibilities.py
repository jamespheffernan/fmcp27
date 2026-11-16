"""Original native current delegates, source failures and final byte fences."""
import asyncio
import json
from pathlib import Path
import struct
import pytest
from mcp.server.fastmcp import FastMCP
from fm_live_mcp import current_staff_responsibilities as source
from fm_live_mcp import current_staff_responsibility_tools as tools
from fm_live_mcp import live_current_staff_responsibilities as query,world,players,staff
from fm_live_mcp import bridge as bridge_module,live_staff_responsibilities as stored_query
from fm_live_mcp.bridge import BridgeError
from test_live_staff_responsibilities import live_staff
from prepared_tactics_fixture import prepared_tactics_memory
from test_bridge import bridge
from test_club_staff_responsibilities import responsibility_memory
from test_database import database_memory
from test_players import memory
from test_staff import staff_record
from test_teams import team_memory
from test_world import world_memory

NATIVE = json.loads((Path(__file__).parent/'fixtures/current_staff_responsibility_native_source.json').read_text())


@pytest.fixture
def current_memory(live_staff,monkeypatch):
    m = live_staff
    monkeypatch.setattr(bridge_module,'ReadStream',stored_query.ReadStream)
    for span in NATIVE:m['put'](m['base']+span['rva'],bytes.fromhex(span['raw_hex']))
    base,person,team = m['base'],m['responsibility_person'],m['team']
    contract = m['allocate'](0xD0)
    m['put'](contract,m['read'](m['staff_contract'],32))
    m['q'](contract+0x10,team)
    m['q'](contract+0x18,team)
    m['put'](contract+0x26,b'\x10')
    m['put'](contract+0xC2,b'\x10')
    m['q'](person-0x98,contract)
    person_table = int.from_bytes(m['read'](person,8),'little')
    m['q'](person_table+0x3C0,base+0xCB8C68)
    m['put'](person_table-0x3D0,struct.pack('<q',-0x110))
    m['q'](person_table+0x1B0,base+(0x1300058 if m['staff_kind']=='human_manager' else 0xCA4638))
    m['q'](base+world.TYPES['full_contract'][0]+0x90,base+0x129FFFC)
    m['q'](base+world.TYPES['full_contract'][0]+0x70,base+0x129A4B8)
    m['put'](m['club']+0x163,b'\x10')
    policy = m['allocate'](8)
    m['q'](base+0x56D57D0,policy)
    m['q'](policy,base+0x5690AE0)
    m['q'](base+0x5690AE0+0x30,base+0x1BDBC08)
    guard = m['allocate'](8)
    m['q'](base+0x54B05B0,guard)
    m['q'](guard,123456)
    m['q'](base+world.TYPES['club'][0]+0x150,base+0xE2767C)
    m['q'](base+world.TYPES['club'][0]+0x158,base+0xE27754)
    comp_state,comp_identity = m['allocate'](0x140),m['allocate'](16)
    competition = m['competitions'][0]
    m['q'](competition+0xB0,comp_state)
    m['q'](comp_state+0x138,comp_identity)
    m['put'](comp_identity+12,struct.pack('<I',123))
    m['put'](base+0x56D3518,struct.pack('<I',123))
    m['q'](team+0x50,competition)
    m.update(current_contract=contract,policy=policy,comp_identity=comp_identity)
    return m


def decode(m):return source.decode(m['read'],m['base'],m['club'])


@pytest.mark.parametrize('code',[160,161,170])
def test_complete_original_stored_contract_path_preserves_both_facts(current_memory,code):
    m = current_memory
    m['put'](m['responsibility_row']+4,bytes([code]))
    before = dict(m['cells'])
    result = decode(m)
    assert result['complete_native_current_queries_verified'],result['records'][0]['current_delegate']
    assert not result['complete_UI_population_verified']
    row = result['records'][0]
    assert row['stored_reference']['person']['display_name'] == 'Test Müller'
    assert row['current_delegate'] == {'state':'resolved','person':row['stored_reference']['person']}
    assert row['context_team']['native_type_code'] == 0
    assert result['consumer_flags'] == {'default_candidate_generation':False,'allow_human_delegates':True}
    assert m['cells'] == before


def test_native_club_override_is_independent_of_the_stored_reference(current_memory):
    m = current_memory
    m['q'](m['team']+0x50,0)
    m['put'](m['responsibility_row']+4,b'\xaa')
    # Native override selects the managed HUMAN before reading the stored ref.
    person = m['manager']+0x548
    m['put'](person+8,struct.pack('<I',1))
    m['put'](person+12,struct.pack('<II',456,456))
    table = m['base']+staff.LAYOUTS['human_manager'][1]
    m['q'](m['manager']+8,m['base']+staff.NON_PLAYING_RVA)
    m['q'](table+0x658,m['base']+0xCA4E78)
    m['put'](table-0x668,struct.pack('<q',-0x548))
    for slot,adjustment in ((40,0x150),(41,0x158),(42,0x160),(55,0x1C8)):
        m['q'](table+slot*8,int.from_bytes(m['read'](m['base']+players.RVA[2]+slot*8,8),'little'))
        m['put'](table-adjustment,struct.pack('<q',-0x110))
    m['put'](person-0xB8,struct.pack('<HH',1,1980))
    m['vec'](m['headers']['people'],[m['responsibility_person'],person])
    m['vec'](m['roots']['people']+0x68,[m['responsibility_person'],person])
    row = decode(m)['records'][0]
    assert row['stored_reference']['person']['display_name'] == 'Test Müller'
    assert row['current_delegate']['person']['display_name'] == 'Test Coach'
    assert row['stored_reference']['person'] != row['current_delegate']['person']


def test_basic_contract_kind_callee_runs_as_original_code(current_memory):
    m = current_memory
    table = m['base']+world.TYPES['basic_contract'][0]
    m['q'](m['current_contract'],table)
    m['q'](table+0x90,m['base']+0xD8C3D0)
    m['q'](table+0x70,m['base']+0xD88C6C)
    assert decode(m)['records'][0]['current_delegate']['state'] == 'resolved'


@pytest.mark.parametrize('kind',['unknown_callee','unproved_constructor'])
def test_unsupported_paths_are_unknown_not_unassigned(current_memory,kind):
    m = current_memory
    target = 0x4AEE72C if kind == 'unknown_callee' else 0x22D23E8
    m['q'](m['base']+0x5690AE0+0x30,m['base']+target)
    result = decode(m)
    assert not result['complete_native_current_queries_verified']
    assert result['records'][0]['current_delegate']['state'] == 'unavailable'
    assert result['records'][0]['current_delegate']['person'] is None


def test_instruction_count_includes_original_instructions_before_a_refusal(current_memory):
    m = current_memory
    m['put'](m['responsibility_row']+5,b'\xff')
    m['q'](m['base']+0x5690AE0+0x30,m['base']+0x4AEE72C)
    code = m['read'](m['responsibility_row']+4,1)[0]
    native = source.NativeSource(m['read'],m['base'])
    with pytest.raises(source.NativePathUnavailable):
        native.query(0x17BB4C0,[m['club'],code,0,0,1])
    assert native.executed_instructions>0
    result = decode(m)
    assert result['records'][0]['current_delegate']['state'] == 'unavailable'
    assert result['original_native_code_emulated']
    assert result['original_instruction_count'] == native.executed_instructions


def test_native_mapped_nonstack_write_is_refused_without_mutating_source(current_memory):
    m = current_memory
    native = source.NativeSource(m['read'],m['base'])
    # Guard control only: additionally allow the original UI constructor body
    # so its mapped destination STR reaches the write hook. Production excludes it.
    raw = m['read'](m['base']+0x22D23E8,296)
    native.code.append((m['base']+0x22D23E8,raw,'code'))
    owner,slots,holder,destination = (m['allocate'](n)for n in (0x40,8,0x20,24))
    m['q'](owner+0x38,m['club'])
    m['q'](owner+0x10,slots)
    m['q'](slots,holder)
    m['q'](holder+0x18,destination)
    before = dict(m['cells'])
    with pytest.raises(source.NativePathUnavailable,match='nonstack_write'):
        native.query(0x22D23E8,[owner,0])
    assert m['cells'] == before


def test_native_null_is_separate_from_an_unsupported_path(current_memory):
    m = current_memory
    m['put'](m['responsibility_row'],struct.pack('<i',-1))
    result = decode(m)
    row = result['records'][0]
    assert row['stored_reference']['state'] == 'negative_native_index'
    assert row['current_delegate'] == {'state':'native_returned_none','person':None}
    assert result['complete_native_current_queries_verified']


def test_external_stack_alias_is_refused_instead_of_becoming_an_accepted_empty_delegate(current_memory,monkeypatch):
    m = current_memory
    normal = decode(m)['records'][0]['current_delegate']
    collision = source.STACK+0xEFA0
    m['q'](m['club']+0xB0,collision-0x48)
    m['q'](collision,m['responsibility_vector'])
    before = dict(m['cells'])
    with pytest.raises(source.NativePathUnavailable,match='private'):
        decode(m)
    # A direct native query cannot hide the same source pointer in saved regs.
    native = source.NativeSource(m['read'],m['base'])
    with pytest.raises(source.NativePathUnavailable,match='private'):
        native.query(0x17BB4C0,[m['club'],160,m['team'],0,1])
    monkeypatch.setattr(source,'STACK',0x310000000000)
    assert decode(m)['records'][0]['current_delegate'] == normal
    assert m['cells'] == before


def test_computed_external_vector_alias_cannot_read_a_private_frame(current_memory,monkeypatch):
    m = current_memory
    # Neither outside endpoint points inside the stack. The indexed midpoint
    # aliases saved X20 during original native-ID bisection. Value scanning
    # alone cannot detect this source-derived access.
    native = source.NativeSource(m['read'],m['base'])
    root = m['roots']['people']
    m['put'](root+0x64,b'\0')
    header = int.from_bytes(m['read'](root+0x88,8),'little')
    start = source.STACK-0x20000
    middle = source.STACK+0xEFE0
    end = 2*middle-start+16
    m['put'](header,struct.pack('<QQQ',start,end,end))
    m['q'](middle,m['responsibility_person'])
    with pytest.raises(source.NativePathUnavailable,match='private'):
        native.query(0x1084CA4,[root,12345])
    monkeypatch.setattr(source,'STACK',0x310000000000)
    returned,_ = native.query(0x1084CA4,[root,12345])
    assert returned == m['responsibility_person']


def test_private_stop_callee_is_unknown_instead_of_an_accepted_canonical_person(current_memory):
    m = current_memory
    m['put'](m['responsibility_row']+5,b'\xff')
    person = m['responsibility_person']
    table = int.from_bytes(m['read'](person,8),'little')
    m['q'](m['base']+0x56D57D0,person)
    m['q'](table+0x30,source.STOP)
    result = decode(m)
    assert result['records'][0]['current_delegate']['state'] == 'unavailable'
    assert not result['complete_native_current_queries_verified']


def test_stop_monitor_requires_an_observed_balanced_ret_even_if_callee_filter_is_bypassed(current_memory,monkeypatch):
    m = current_memory
    person = m['responsibility_person']
    table = int.from_bytes(m['read'](person,8),'little')
    m['q'](m['base']+0x56D57D0,person)
    m['q'](table+0x30,source.STOP)
    native = source.NativeSource(m['read'],m['base'])
    # Independent termination-fence control: deliberately bypass both prior
    # defenses to ensure BLR-to-STOP still cannot be accepted as a return.
    native.code.append((source.STOP,bytes.fromhex('1f2003d5'),'code'))
    original = source._private_overlap
    monkeypatch.setattr(source,'_private_overlap',lambda at,n:
        False if at==source.STOP and n==1 else original(at,n))
    with pytest.raises(source.NativePathUnavailable,match='without_native_ret'):
        native.query(0x17BB4C0,[m['club'],160,0,0,1])


def test_stop_entry_cannot_complete_without_executing_a_native_return(current_memory):
    m = current_memory
    native = source.NativeSource(m['read'],m['base'])
    with pytest.raises(source.NativePathUnavailable,match='without_native_ret'):
        native.query(source.STOP-m['base'],[m['responsibility_person']])


def test_native_data_guard_is_not_an_executable_function(current_memory):
    m = current_memory
    native = source.NativeSource(m['read'],m['base'])
    with pytest.raises(source.NativePathUnavailable,match='callee_not_supported'):
        native.query(0x539E968,[m['responsibility_person']])


def test_missing_physical_operand_aborts_instead_of_becoming_unavailable(current_memory):
    m = current_memory
    del m['cells'][m['policy']]
    with pytest.raises((ValueError,KeyError)):decode(m)


@pytest.mark.parametrize('span',range(len(source.NATIVE_SPANS)))
def test_every_native_body_table_and_consumer_guard_is_required(current_memory,span):
    m = current_memory
    at = m['base']+source.NATIVE_SPANS[span][0]
    m['put'](at,bytes([m['read'](at,1)[0]^1]))
    with pytest.raises(ValueError):decode(m)


def test_full_outer_function_terminal_instruction_is_guarded(current_memory,monkeypatch):
    m = current_memory
    # LC_FUNCTION_STARTS ends this body at17BBCC8. The prior2052-byte
    # guard stopped before the final BL instruction at17BBCC4.
    at = m['base']+0x17BBCC4
    m['put'](at,bytes([m['read'](at,1)[0]^1]))
    old = tuple((rva,2052,'64201f4fa33758c5f50023630ea6adb760970ae51112a608937efbc1953da2ec',kind)
        if rva==0x17BB4C0 else(rva,size,digest,kind)for rva,size,digest,kind in source.NATIVE_SPANS)
    with monkeypatch.context() as before:
        before.setattr(source,'NATIVE_SPANS',old)
        assert decode(m)['complete_native_current_queries_verified']
    with pytest.raises(ValueError,match='native source changed'):decode(m)


def test_missing_empty_duplicate_null_and_budget_remain_distinct(current_memory):
    m = current_memory
    m['q'](m['responsibility_secondary']+0x48,0)
    assert decode(m)['state'] == 'unavailable'
    m['q'](m['responsibility_secondary']+0x48,m['responsibility_vector'])
    m['vec'](m['responsibility_vector'],[])
    empty = decode(m)
    assert empty['records'] == [] and not empty['original_native_code_emulated']
    m['vec'](m['responsibility_vector'],[m['responsibility_row'],0,m['responsibility_row']])
    result = decode(m)
    assert result['records'][1]['current_delegate']['state'] == 'null_stored_slot'
    assert result['records'][0]['current_delegate'] == result['records'][2]['current_delegate']
    m['vec'](m['responsibility_vector'],[m['responsibility_row']]*(source.SLOT_LIMIT+1))
    result = decode(m)
    assert result['records'] is None and result['reason'] == 'native_query_slot_budget_exceeded'
    assert not result['original_native_code_emulated']


def test_oversized_source_refuses_before_any_stored_person_profile_is_resolved(current_memory):
    m = current_memory
    m['vec'](m['responsibility_vector'],[m['responsibility_row']]*(source.SLOT_LIMIT+1))
    del m['cells'][m['responsibility_person']]
    result = decode(m)
    assert result['reason'] == 'native_query_slot_budget_exceeded' and result['records'] is None


@pytest.mark.parametrize('selection',['managed','club_ref'])
def test_public_current_adapter_uses_real_projection_and_closes(current_memory,selection):
    m = current_memory
    result = query.get_club_current_staff_responsibilities(m['bridge'],m['bridge'].session,
        **({'club_ref':'club'}if selection == 'club_ref' else {}))
    assert result['current_staff_responsibilities']['records'][0]['current_delegate']['state'] == 'resolved'
    assert result['original_native_code_emulated'] and not result['native_calls']
    assert result['club']['secondary_id'] == 688 and 'random_id' not in result['club']
    assert m['closed'] == [True] and m['bridge']._reader is None


@pytest.mark.parametrize('secondary',[0,688,999])
@pytest.mark.parametrize('selection',['managed','club_ref'])
def test_current_club_secondary_identity_is_preserved(current_memory,secondary,selection):
    m = current_memory
    m['put'](m['club']+0x10,struct.pack('<I',secondary))
    m['bridge'].club_refs['club']['identity'] = world.club(m['read'],m['base'],m['club'])[1]
    result = query.get_club_current_staff_responsibilities(m['bridge'],m['bridge'].session,
        **({'club_ref':'club'}if selection=='club_ref'else{}))
    assert result['club']['secondary_id'] == secondary and 'random_id' not in result['club']


@pytest.mark.parametrize('callback',['final_current','public_save'])
def test_last_lifetime_or_public_callback_cannot_publish_a_stale_native_delegate(current_memory,monkeypatch,callback):
    m,bridge = current_memory,current_memory['bridge']
    if callback == 'final_current':
        original,calls = bridge._current,[]
        def current(session):
            calls.append(1)
            if len(calls) == 3:m['put'](m['current_contract']+0x26,b'\x00')
            return original(session)
        monkeypatch.setattr(bridge,'_current',current)
    else:
        original = bridge._public_save
        def public(save):
            m['put'](m['current_contract']+0x26,b'\x00')
            return original(save)
        monkeypatch.setattr(bridge,'_public_save',public)
    with pytest.raises(BridgeError):
        query.get_club_current_staff_responsibilities(bridge,bridge.session)
    assert m['closed'] == [True] and bridge._reader is None


def test_current_tool_contract_retains_scope_and_unknowns():
    mcp = FastMCP('current-staff-responsibility-contract')
    tools.register_current_staff_responsibility_tools(mcp,object())
    tool = asyncio.run(mcp.list_tools())[0]
    assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
    assert tool.inputSchema['required'] == ['session_id']
    assert 'stored references separately from current delegates' in tool.description
    assert 'default candidate generation disabled' in tool.description


@pytest.mark.parametrize('late_callback',[3,4,5])
def test_canonical_scope_callbacks_all_precede_current_delegate_fences(current_memory,monkeypatch,late_callback):
    m,bridge = current_memory,current_memory['bridge']
    original,calls = bridge._current,[]
    def current(session):
        calls.append(1)
        if len(calls)==late_callback:m['put'](m['current_contract']+0x26,b'\0')
        return original(session)
    monkeypatch.setattr(bridge,'_current',current)
    with pytest.raises(BridgeError):query.get_club_current_staff_responsibilities(bridge,bridge.session)
    assert len(calls)==5 and m['closed']==[True] and bridge._reader is None


def test_final_current_callback_cannot_expire_club_ref_after_its_rebinding(current_memory,monkeypatch):
    m,bridge = current_memory,current_memory['bridge']
    original,calls = bridge._current,[]
    def current(session):
        calls.append(1)
        if len(calls)==5:bridge.club_refs.pop('club')
        return original(session)
    monkeypatch.setattr(bridge,'_current',current)
    with pytest.raises(BridgeError,match='source binding changed'):
        query.get_club_current_staff_responsibilities(bridge,bridge.session,club_ref='club')
    assert m['closed']==[True] and bridge._reader is None


def test_no_lifetime_or_public_callback_runs_after_the_final_two_fences(current_memory,monkeypatch):
    m,bridge = current_memory,current_memory['bridge']
    events = []
    original_current,original_public = bridge._current,bridge._public_save
    original_verify,original_close = world.ReadSet.verify,bridge_module.ReadStream.close
    def current(session):
        events.append('current')
        return original_current(session)
    def public(save):
        events.append('public')
        return original_public(save)
    def verify(snapshot):
        events.append('fence')
        return original_verify(snapshot)
    def close(reader):
        events.append('close')
        return original_close(reader)
    monkeypatch.setattr(bridge,'_current',current)
    monkeypatch.setattr(bridge,'_public_save',public)
    monkeypatch.setattr(world.ReadSet,'verify',verify)
    monkeypatch.setattr(bridge_module.ReadStream,'close',close)
    query.get_club_current_staff_responsibilities(bridge,bridge.session)
    assert events.count('current')==5 and events.count('public')==1
    assert events[-3:]==['fence','fence','close']
