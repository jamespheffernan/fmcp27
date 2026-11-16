"""Native default policy reconstruction and cold-branch refusal in owned RAM."""
import hashlib
import struct
import pytest
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE,UC_HOOK_MEM_INVALID
import unicorn.arm64_const as regs
from fm_live_mcp import default_training_intensity as source,players,world
from training_source_fixture import training_source_memory,prepared_tactics_memory,team_memory,database_memory,memory,world_memory
from test_individual_training_focus import focus_memory,native_image,member_memory
from test_live_individual_training import live_focus,get,bridge


@pytest.fixture
def default_memory(training_source_memory,focus_memory,native_image):
    m=training_source_memory;assert m is focus_memory;b=m['base'];p=0x1000
    for rva,n,digest in source.NATIVE_GUARDS:
        raw=native_image[0x5ed4000+rva:0x5ed4000+rva+n];assert hashlib.sha256(raw).hexdigest()==digest;m['put'](b+rva,raw)
    m['put'](b+players.RVA[0]-0x20,struct.pack('<q',0x278));m['put'](b+players.RVA[0]-0x18,struct.pack('<q',0x388))
    m['q'](b+players.RVA[2]+0x3c0,b+0xcb8c68);m['put'](b+players.RVA[2]-0x3d0,struct.pack('<q',-0x110))
    contract=m['allocate'](0x200);rva,name=world.TYPES['full_contract'];m['typed_at'](contract,rva,name)
    m['q'](contract+8,p+0x388);m['q'](contract+0x10,m['team']);m['q'](p+0x278+0x78,contract)
    m['q'](b+rva+0x90,b+0x129fffc);m['q'](b+rva+0x98,b+0xd88c8c)
    m['q'](p+0x278+0x48,0);m['q'](p+0x128,m['team']);m['q'](m['team']+0x50,0)
    m['put'](m['team']+0x28,b'\0');m['put'](m['team']+0x2f,b'\0');m['put'](m['club']+0xba,b'\0');m['put'](m['club']+0x163,b'\x10')
    m['put'](p+0x1eb,b'\xff');m['put'](p+0x254,struct.pack('<h',7000));m['put'](m['training_team_node']+0x88,bytes([3,0,1,2,2]))
    m['default_primary']=p;m['default_main']=contract
    return m


def inspect(m,read=None):return source.inspect(read or m['read'],m['base'],m['coach'],m['default_primary'])


def native(m,entry,args,frame=False):
    b=m['base'];cells=m['cells'];known=set(cells);uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM);stack,stop,descriptor=0x200000000,0x300000000,0x200000100
    pages={p&~4095 for p in cells}|set(range(stack,stack+0x10000,4096))|{stop}
    for page in pages:uc.mem_map(page,4096)
    for page in {p&~4095 for p in cells}:uc.mem_write(page,bytes(cells.get(p,0)for p in range(page,page+4096)))
    if frame:
        uc.mem_write(descriptor,struct.pack('<QQQ',m['training_manager'],m['team'],m['default_primary']));known.update(range(descriptor,descriptor+24));args=[descriptor]
    trace=[];reads=[]
    def code(machine,at,n,user):
        if at==stop:machine.emu_stop();return
        assert any(b+rva<=at<b+rva+width for rva,width,_ in source.NATIVE_GUARDS),('unbound original code',hex(at-b))
        assert all(p in known for p in range(at,at+n));trace.append(at-b)
    def load(machine,access,at,n,value,user):
        assert all(p in known for p in range(at,at+n)),('missing original operand',hex(at),n,hex(machine.reg_read(regs.UC_ARM64_REG_PC)-b))
        if not stack<=at<stack+0x10000:reads.append((at,n))
    def store(machine,access,at,n,value,user):
        assert stack<=at and at+n<=stack+0x10000,('native nonstack write',hex(at));known.update(range(at,at+n))
    def invalid(machine,access,at,n,value,user):raise AssertionError(('unmapped original operand',hex(at),n))
    uc.hook_add(UC_HOOK_CODE,code);uc.hook_add(UC_HOOK_MEM_READ,load);uc.hook_add(UC_HOOK_MEM_WRITE,store);uc.hook_add(UC_HOOK_MEM_INVALID,invalid)
    for i,v in enumerate(args):uc.reg_write(getattr(regs,'UC_ARM64_REG_X'+str(i)),v)
    uc.reg_write(regs.UC_ARM64_REG_SP,stack+0xf000);uc.reg_write(regs.UC_ARM64_REG_LR,stop)
    uc.emu_start(b+entry,stop,count=10000);assert uc.reg_read(regs.UC_ARM64_REG_PC)==stop
    raw=uc.reg_read(regs.UC_ARM64_REG_W0 if entry==0x2cf5fbc else regs.UC_ARM64_REG_X0);bits=32 if entry==0x2cf5fbc else 64
    return (raw+(1<<(bits-1)))%(1<<bits)-(1<<(bits-1)),reads,trace


@pytest.mark.parametrize('condition,band,expected',[(0,0,-2),(5049,0,-2),(5050,1,0),(6549,1,0),(6550,2,1),(7549,2,1),(7550,3,2),(8549,3,2),(8550,4,2),(10000,4,2)])
def test_actual_source_matches_complete_original_training_TEAM_and_default(default_memory,condition,band,expected):
    m=default_memory;m['put'](0x1254,struct.pack('<h',condition));consumed=[]
    def read(a,n):consumed.append((a,n));return m['read'](a,n)
    actual=inspect(m,read);assert actual['native_code']==expected and actual['condition_band']==band
    selected,team_reads,_=native(m,0x2c98dbc,[m['training_manager'],0x1000]);assert selected==m['team']
    value,policy_reads,trace=native(m,0x2cf5fbc,[],True);assert value==expected
    assert all(any(a<=p<a+n for a,n in consumed)for at,width in team_reads+policy_reads for p in range(at,at+width))
    assert 0x3a1f240 not in trace and 0x3a1f248 not in trace
    assert actual['applied_intensity']is None and actual['workload']is None
    assert all(not(a<0x118d and a+n>0x1148)for a,n in consumed)


def test_all_signed_condition_words_match_original_rounding_and_band(native_image):
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM);uc.mem_map(0x2cf6000,4096);uc.mem_write(0x2cf6000,native_image[0x5ed4000+0x2cf6000:0x5ed4000+0x2cf7000])
    for raw in range(-32768,32768):
        uc.reg_write(regs.UC_ARM64_REG_W19,raw&0xffffffff);uc.reg_write(regs.UC_ARM64_REG_X0,0x100000000)
        uc.emu_start(0x2cf6060,0x2cf60b0,count=32)
        assert uc.reg_read(regs.UC_ARM64_REG_X8)-0x100000000==source.condition_band(raw)


@pytest.mark.parametrize('raw',[0,1,2,3,127,128,254,255])
def test_native_policy_values_above_two_resolve_to_no_pitch_or_gym(default_memory,raw):
    m=default_memory;m['put'](m['training_team_node']+0x8a,bytes([raw]));actual=inspect(m)
    value,_,_=native(m,0x2cf5fbc,[],True);assert value==(raw if raw<3 else -2)==actual['native_code']


@pytest.mark.parametrize('fault,reason',[('national','unsupported_national_training_context'),('mode','unsupported_training_assignment_mode'),('manager','training_manager_missing'),('owner','direct_policy_missing_native_fallback_unsupported'),('missing_team','direct_policy_missing_native_fallback_unsupported'),('foreign_stored','training_team_source_outside_verified_direct_branch'),('event','training_team_source_outside_verified_direct_branch')])
def test_unsupported_contexts_never_become_native_absence_or_a_default(default_memory,fault,reason):
    m=default_memory
    if fault=='national':m['put'](m['team']+0x2f,b'\1')
    elif fault=='mode':m['put'](m['training_source_gate'],b'\0')
    elif fault=='manager':m['q'](m['training_source_root'],0)
    elif fault=='owner':m['vec'](m['training_manager']+0x38,[])
    elif fault=='missing_team':
        owner=m['training_owner'];m['q'](owner+0x48,owner+0x50);m['q'](owner+0x50,0);m['q'](owner+0x58,0)
    elif fault=='foreign_stored':m['q'](0x1128,0)
    else:
        event=m['allocate'](0x50);m['q'](0x1278+0x48,event);m['put'](event+0x4b,b'\1')
    actual=inspect(m);assert actual['state']=='unavailable' and actual['reason']==reason and actual['native_code']is None


def test_explicit_setting_does_not_resolve_or_read_manager(default_memory):
    m=default_memory;m['put'](0x11eb,b'\0')
    def read(a,n):
        assert a!=m['training_source_root'];return m['read'](a,n)
    assert inspect(m,read)['state']=='not_requested'


def test_policy_change_during_final_source_recheck_rejects(default_memory):
    m=default_memory;at=m['training_team_node']+0x8a;seen=0
    def read(a,n):
        nonlocal seen
        if a<=at<a+n:
            seen+=1
            if seen==2:m['put'](at,b'\2')
        return m['read'](a,n)
    with pytest.raises(ValueError,match='changed'):inspect(m,read)


@pytest.mark.parametrize('kind',['basic_contract','loan_contract','trial_contract'])
def test_known_alternate_contracts_are_unavailable_without_breaking_batch(default_memory,kind):
    m=default_memory;at=m['default_main'];rva,name=world.TYPES[kind];m['typed_at'](at,rva,name)
    assert inspect(m)['state']=='unavailable'


def test_opt_in_public_adapter_keeps_default_resolution_separate(default_memory,live_focus):
    m=default_memory;assert m is live_focus
    ordinary=get(m);assert 'default_intensity_resolution'not in ordinary['players'][0]
    actual=get(m,include_default_resolution=True);row=actual['players'][0]
    assert row['club_training_intensity']['state']=='native_default_resolution_requested'
    assert row['club_training_intensity']['applied_intensity']is None
    assert row['default_intensity_resolution']['native_code']==1
    assert row['default_intensity_resolution']['english_definition_name']=='Normal Intensity'
    assert row['default_intensity_resolution']['applied_intensity']is None
    assert actual['field_sources']['default_intensity_resolution']=='reconstructed_existing_native_default_policy'


@pytest.mark.parametrize('value',[None,0,1,'true'])
def test_direct_adapter_rejects_non_Boolean_opt_in(live_focus,value):
    from fm_live_mcp.bridge import BridgeError
    with pytest.raises(BridgeError,match='Boolean'):get(live_focus,include_default_resolution=value)


def test_public_optional_schema_can_request_default_resolution(live_focus):
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp.individual_training_tools import register_individual_training_tools
    mcp=FastMCP('training default');register_individual_training_tools(mcp,live_focus['bridge'])
    tool,=asyncio.run(mcp.list_tools())
    option=tool.inputSchema['properties']['include_default_resolution']
    assert option['type']=='boolean' and option['default']is False
