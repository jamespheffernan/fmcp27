"""Original per-actor constructor windows, not full commentary construction."""
import hashlib,struct
import pytest
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn.arm64_const import UC_ARM64_REG_X19,UC_ARM64_REG_X20,UC_ARM64_REG_X22,UC_ARM64_REG_SP,UC_ARM64_REG_PC
from fm_live_mcp import playback_event_actor_identity as identity
from test_frame_attack_direction import PLUGIN

BASE,INFO,TABLE,EVENT,OUTPUT,STACK=0x100000000,0x30000000,0x31000000,0x32000000,0x33000000,0x80000000


@pytest.fixture(scope='module')
def original():
    with PLUGIN.open('rb') as f:
        assert hashlib.file_digest(f,'sha256').hexdigest()=='774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
        for at,raw in identity.NATIVE_SPANS:f.seek(0x5ED4000+at);assert f.read(len(raw))==raw
    return identity.NATIVE_SPANS


@pytest.mark.parametrize('field',range(6))
@pytest.mark.parametrize('side,slot',[(0,0),(0,25),(1,0),(1,25),(2,0),(0,26)])
def test_original_actor_uid_window_uses_original_slot_and_same_setup_table(original,field,side,slot):
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    for page in {BASE+(at&~4095) for at,_ in original}|{INFO,INFO+4096,TABLE,EVENT,OUTPUT,STACK}:uc.mem_map(page,4096)
    for at,raw in original:uc.mem_write(BASE+at,raw)
    uc.mem_write(INFO+0x1B,b'\x03\x1d')
    uc.mem_write(INFO+0x1058,struct.pack('<Q',TABLE))
    expected=123456+field
    uc.mem_write(TABLE+48*((3 if side==0 else 29)+slot),struct.pack('<I',expected))
    uc.mem_write(EVENT+field*2,bytes([slot,side]))
    read_addresses=[]
    def rd(machine,kind,address,size,value,extra):
        assert (INFO<=address and address+size<=INFO+0x1060) or (EVENT<=address and address+size<=EVENT+12) or (TABLE<=address and address+size<=TABLE+4096) or (STACK<=address and address+size<=STACK+4096)
        read_addresses.append((address,size))
    def wr(machine,kind,address,size,value,extra):assert OUTPUT+field*4==address and size==4
    uc.hook_add(UC_HOOK_MEM_READ,rd);uc.hook_add(UC_HOOK_MEM_WRITE,wr)
    for reg,value in [(UC_ARM64_REG_X19,OUTPUT),(UC_ARM64_REG_X20,EVENT),(UC_ARM64_REG_X22,INFO),(UC_ARM64_REG_SP,STACK+0xF00)]:uc.reg_write(reg,value)
    start=0x73E494+field*0x5C;stop=start+(0x60 if field==5 else 0x5C)
    uc.emu_start(BASE+start,BASE+stop,count=40);assert uc.reg_read(UC_ARM64_REG_PC)==BASE+stop
    actual=struct.unpack('<I',uc.mem_read(OUTPUT+field*4,4))[0]
    assert actual==(expected if side<2 and slot<26 else 0xFFFFFFFF)
    if side<2 and slot<26:assert (TABLE+48*((3 if side==0 else 29)+slot),4) in read_addresses
    else:assert not any(TABLE<=address<TABLE+4096 for address,_ in read_addresses)


def actor(side,uid,person):return {'side_index':side,'engine_playback_uid':uid,'canonical_person_id':person,'person_name':str(person)}


def test_same_uid_on_other_side_never_cross_joins_and_unknowns_stay_null():
    row={'player_ids_raw':[10,10,0,0xFFFFFFFF,30,10],'player_teams_bits_raw':2}
    result=identity.project([row],[actor(0,10,100),actor(1,10,200),actor(1,30,300)])
    people=result['rows'][0]['event_players']
    assert [p['canonical_person_id'] for p in people]==[100,200,None,None,None,100]
    assert all(p['on_pitch'] is p['participation_role'] is None for p in people)
    assert result['historical_on_pitch_verified'] is result['substitution_actor_roles_verified'] is False


def test_ambiguous_actor_and_malformed_fields_refuse():
    with pytest.raises(ValueError):identity.project([],[actor(0,10,100),actor(0,10,101)])
    with pytest.raises(ValueError):identity.project([],[actor(0,10,100),actor(1,20,100)])
    with pytest.raises(ValueError):identity.project([{'player_ids_raw':[1],'player_teams_bits_raw':0}],[])
    with pytest.raises(ValueError):identity.project([{'player_ids_raw':[0]*6,'player_teams_bits_raw':True}],[])


@pytest.mark.parametrize('at,raw',identity.NATIVE_SPANS)
def test_native_constructor_guard_refuses_drift(original,at,raw):
    memory={base:code for base,code in original}
    identity.verify_native(lambda address,size:memory[address-BASE],BASE)
    memory[at]=bytes([raw[0]^1])+raw[1:]
    with pytest.raises(ValueError):identity.verify_native(lambda address,size:memory[address-BASE],BASE)


def test_capture_reconciles_owner_original_uid_and_preserves_mismatch(original):
    from test_frame_attack_direction import Source
    obj=Source.__new__(Source);obj.values={};obj.reads=[]
    for at,raw in original:obj.put(BASE+at,raw)
    playback=INFO-0x28
    obj.put(playback+0x1418+0x898,struct.pack('<Q',INFO))
    obj.put(INFO+0x1B,b'\x03\x1d');obj.put(INFO+0x1058,struct.pack('<Q',TABLE))
    obj.put(TABLE+48*3,struct.pack('<I',10));obj.put(TABLE+48*29,struct.pack('<I',20))
    actors=[actor(0,10,100)|{'stored_player_slot':0},actor(1,30,200)|{'stored_player_slot':0}]
    row={'player_ids_raw':[10,30,0,0xFFFFFFFF,10,30],'player_teams_bits_raw':0b100010}
    bound={'playback_address':playback,'official_match_unique_id':123}
    captured=identity.capture(obj.read,BASE,bound,[row],actors)
    assert [p['canonical_person_id'] for p in captured['rows'][0]['event_players']]==[100,None,None,None,100,None]
    assert captured['unresolved_canonical_actor_setup']==[{'side_index':1,'stored_player_slot':0,'reason':'native_MATCH_INFO_and_MATCH_PLAYER_uid_disagree'}]
    assert identity.verify_capture(obj.read,BASE,bound,captured)['native_actor_uid_setup_physically_reselected'] is True
    obj.put(TABLE+48*3,struct.pack('<I',11))
    with pytest.raises(ValueError,match='setup changed'):identity.verify_capture(obj.read,BASE,bound,captured)
    obj.put(playback+0x1418+0x898,struct.pack('<Q',INFO+8))
    with pytest.raises(ValueError,match='owner changed'):identity.capture(obj.read,BASE,bound,[row],actors)
