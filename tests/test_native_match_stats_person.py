"""Synthetic branch/ownership controls plus one coherent genuine identity packet.

The genuine154 fixture contains identity operands only, never33field counters.
"""
import gzip,hashlib,json,struct
from copy import deepcopy
from pathlib import Path

import pytest
from fm_live_mcp import active_match_people as people,database,players,world
from fm_live_mcp import native_match_stats_person as native


class Fixture:
    def __init__(self):
        self.memory={};self.calls=[];self.engine=0x100000;self.side=0x210000
        self.actor=0x300000;self.primary=0x400000;self.person=self.primary+0x388
        self.stats=0x500000;self.index=17;self.uid=2002100357;self.meta=0x8000000
        self.typed(self.engine,0x55FA258,b'10GAME_MATCH');self.q(self.engine+0x20,12345)
        self.q(self.engine+0x15370,0x200000);self.q(self.engine+0x15378,self.side)
        for side,team in [(0x200000,0x220000),(self.side,0x230000)]:
            self.q(side+0xB8,team);self.typed(team,0x55C2E40,b'N2db4TEAME')
            self.put(team+0x38,bytes(24));self.put(side+0x140,bytes(208))
        self.q(self.side+0x140+17*8,self.actor)
        self.typed(self.actor,0x569EE68,b'N7simatch12MATCH_PLAYERE')
        self.q(self.actor+0x280,self.engine);self.q(self.actor+0x288,self.side)
        self.q(self.actor+0x20,self.person);self.u(self.actor+0x48,self.uid)
        self.put(self.actor+0x1E27,b'\x11');self.q(self.actor+0x1880,self.stats)
        self.typed(self.stats,0x55FA800,b'23GAME_MATCH_PLAYER_STATS');self.u(self.stats+0x18,self.index)
        self.typed(self.primary,players.RVA[0],native.ACTUAL_LABEL)
        self.typed(self.person,players.RVA[2],native.ACTUAL_LABEL,-0x388)
        self.put(self.person+8,struct.pack('<III',self.index,self.uid,self.uid))
        self.q(0x56D2D80,0x130000);self.typed(0x130000,0x55A19B8,b'N2db14DATABASE_TABLEINS_6PERSONEEE')
        self.q(0x130000+0x88,0x132000);self.put(0x132000,struct.pack('<QQQ',0x140000,0x1400a0,0x1400a0))
        self.q(0x140000+self.index*8,self.person)
        self.q(0x130068,0x140000);self.q(0x130070,0x1400a0)
        self.q(0x56D2D78,0x700000);self.q(0x700088,0x701000)
        self.q(0x701000,0x702000);self.q(0x701008,0x702008);self.put(0x56D34E0,b'\1')
        self.put(native.GETTER_RVA,native.GETTER_BYTES);self.q(0x55FA810,native.GETTER_RVA)
        for offset,handle,text in [(0x298,0x610000,'Synthetic'),(0x2A0,0x610020,'Youth'),(0x2A8,0x610040,'Synthetic academy player')]:
            self.q(self.primary+offset,handle);data=handle+0x1000;raw=text.encode()
            self.q(handle,data);self.put(data,struct.pack('<I',len(raw))+raw+b'\0')
        for at,raw in people.ACTOR_SLOT_SPANS:self.put(at,raw)
    def put(self,at,raw):self.memory.update((at+i,b) for i,b in enumerate(raw))
    def q(self,at,value):self.put(at,struct.pack('<Q',value))
    def u(self,at,value):self.put(at,struct.pack('<I',value))
    def typed(self,at,table,label,displacement=0):
        info=self.meta;self.meta+=0x100
        self.q(at,table);self.put(table-16,struct.pack('<qQ',displacement,info))
        self.q(info+8,info+0x40);self.put(info+0x40,label+b'\0')
    def read(self,at,size):
        self.calls.append((at,size))
        try:return bytes(self.memory[at+i] for i in range(size))
        except KeyError as error:raise ValueError('Missing synthetic operand') from error
    def inspect(self):
        read=world.ReadSet(self.read);result=people.inspect_canonical(read,0,self.engine,identity_only=True);read.verify();return result


def test_fallback_uses_native_getter_canonical_PERSON_and_direct_names():
    f=Fixture();old=people._inspect_canonical_team(f.read,0,f.engine,identity_only=True)
    out=f.inspect();row=out['rows'][43]
    assert old['rows'][43]['person'] is None
    assert row['identity_state']==native.IDENTITY_STATE
    assert row['person']=={'name':'Synthetic academy player','name_state':'stored_direct','record_kind':'actual','native_identity':{'database_index':17,'native_id':f.uid,'random_id':None}}
    assert row['on_pitch'] is None and row['display_time_participation'] is None
    for index in range(52):
        if index!=43:assert out['rows'][index]==old['rows'][index]
    assert {k:v for k,v in out.items() if k!='rows'}=={k:v for k,v in old.items() if k!='rows'}


@pytest.mark.parametrize('flag',[0,1,2,3])
def test_original_flag_routes(flag):
    f=Fixture();f.put(0x56D34E0,bytes([flag]));assert native.resolve_stats_person(f.read,0,f.stats)==f.person


@pytest.mark.parametrize('index',[0xffffffff,0xfffffffe,20,2000000])
def test_signed_and_bounds_null_do_not_gain_identity(index):
    f=Fixture();f.u(f.stats+0x18,index)
    assert f.inspect()['rows'][43]['person'] is None


def test_FFFFFFFF_returns_before_contextual_guard_but_other_negatives_read_guard():
    f=Fixture();f.u(f.stats+0x18,0xffffffff);assert native.resolve_stats_person(f.read,0,f.stats) is None
    assert (0x56D2D78,8) not in f.calls
    f.calls=[];f.u(f.stats+0x18,0xfffffffe);assert native.resolve_stats_person(f.read,0,f.stats) is None
    assert (0x56D2D78,8) in f.calls and (0x56D2D80,8) not in f.calls


@pytest.mark.parametrize('index',[17,0xfffffffe])
@pytest.mark.parametrize('state',['root_absent','guard_empty'])
def test_contextual_virtual_service_is_unavailable_before_negative_index_check(index,state):
    f=Fixture();f.u(f.stats+0x18,index)
    if state=='root_absent':f.q(0x56D2D78,0)
    else:f.q(0x701008,0x702000)
    assert native.resolve_stats_person(f.read,0,f.stats) is None
    assert (0x56D2D80,8) not in f.calls
    assert f.inspect()['rows'][43]['person'] is None


@pytest.mark.parametrize('kind',['source','virtual_slot','guard_alignment','fast_alignment','primary_type','PERSON_displacement','actor_owner','actor_engine','name','native_slot_source'])
def test_source_type_ownership_and_name_errors_stay_fatal(kind):
    f=Fixture()
    if kind=='source':f.put(native.GETTER_RVA,b'\0')
    if kind=='virtual_slot':f.q(0x55FA810,native.GETTER_RVA+4)
    if kind=='guard_alignment':f.q(0x56D2D78,0x700001)
    if kind=='fast_alignment':f.put(0x56D34E0,b'\0');f.q(0x130068,0x140001)
    if kind=='primary_type':f.q(f.primary,0x12345678)
    if kind=='PERSON_displacement':f.put(players.RVA[2]-16,struct.pack('<q',-0x380))
    if kind=='actor_owner':f.q(f.actor+0x288,0x200000)
    if kind=='actor_engine':f.q(f.actor+0x280,0x123000)
    if kind=='name':f.put(0x611044,b'\xff')
    if kind=='native_slot_source':f.put(people.ACTOR_SLOT_SPANS[0][0],b'\0')
    with pytest.raises((ValueError,UnicodeDecodeError)):f.inspect()


@pytest.mark.parametrize('kind',['stats_absent','PERSON_null','UID_mismatch','stats_PERSON_mismatch','global_membership_mismatch','native_zero','native_FFFFFFFF','original_slot_mismatch','unsupported_PERSON','absent_owner'])
def test_inconsistent_or_unsupported_rows_remain_unknown(kind):
    f=Fixture()
    if kind=='stats_absent':f.q(f.actor+0x1880,0)
    if kind=='PERSON_null':f.q(f.actor+0x20,0)
    if kind=='UID_mismatch':f.u(f.actor+0x48,1)
    if kind=='stats_PERSON_mismatch':f.u(f.stats+0x18,16);f.q(0x140000+16*8,0)
    if kind=='global_membership_mismatch':f.q(0x140000+17*8,f.person+8)
    if kind=='native_zero':f.u(f.person+12,0)
    if kind=='native_FFFFFFFF':f.u(f.person+12,0xffffffff)
    if kind=='original_slot_mismatch':f.put(f.actor+0x1e27,b'\x12')
    if kind=='unsupported_PERSON':f.q(f.person,players.STAFF_RVA[2])
    if kind=='absent_owner':f.q(f.actor+0x288,0)
    assert f.inspect()['rows'][43]['person'] is None


def test_existing_TEAM_identity_never_uses_new_getter_or_stats(monkeypatch):
    f=Fixture();f.put(0x230038,struct.pack('<QQQ',0x710000,0x710008,0x710008));f.q(0x710000,f.primary)
    before=people._inspect_canonical_team(f.read,0,f.engine,identity_only=True)
    f.calls=[];assert f.inspect()==before
    assert (f.actor+0x1880,8) not in f.calls and (native.GETTER_RVA,len(native.GETTER_BYTES)) not in f.calls


@pytest.mark.parametrize('at',[0x2e8c6d4,0x55fa810,0x56d34e0,0x701008,0x140000+17*8,0x400388,0x300000+0x20,0x300000+0x1880])
def test_final_callback_changes_reject(at):
    f=Fixture();read=world.ReadSet(f.read);people.inspect_canonical(read,0,f.engine,identity_only=True)
    f.put(at,bytes([f.memory[at]^1]))
    with pytest.raises(ValueError,match='Game state changed'):read.verify()


class Genuine:
    def __init__(self):
        raw=gzip.decompress((Path(__file__).parent/'fixtures/current_actor_global_PERSON_native154.json.gz').read_bytes())
        assert hashlib.sha256(raw).hexdigest()=='159be13668896f23a4863e3e579aa39a2c9582e2bc6b69aa6165cb2ffd16e342'
        self.packet=json.loads(raw);self.memory={}
        for row in self.packet['raw_consumed_byte_journal']['regions']:
            at=int(row['address'],16)
            for i,v in enumerate(bytes.fromhex(row['rawhex'])):
                assert at+i not in self.memory or self.memory[at+i]==v;self.memory[at+i]=v
        self.base=int(self.packet['plugin']['base_private'],16);self.engine=self.packet['context_before']['private']['engine']
    def read(self,at,size):
        try:return bytes(self.memory[at+i] for i in range(size))
        except KeyError as error:raise ValueError('Missing genuine captured operand') from error


def test_coherent_genuine_identity_packet_adds_only_two_names_and_preserves_nine_unknowns():
    f=Genuine();read=world.ReadSet(f.read);result=people.inspect_canonical(read,f.base,f.engine,identity_only=True);read.verify()
    old=people._inspect_canonical_team(f.read,f.base,f.engine,identity_only=True)
    assert old==f.packet['baseline']
    assert sum(r['person'] is not None for r in result['rows'])==43
    for i,row in enumerate(result['rows']):
        if i not in (43,45):assert row==old['rows'][i]
        else:
            expected=deepcopy(f.packet['candidate']['rows'][i]);expected.pop('global_fallback_state');expected.pop('current_TEAM_roster_member');expected['identity_state']=native.IDENTITY_STATE
            assert row==expected
    assert result['rows'][43]['person']['name']=='Rhys Godwin'
    assert result['rows'][45]['person']['name']=='José Luis Montero'
    assert len([r for r in result['rows'] if r['person'] is None])==9
    assert not any('shot' in k or 'passing' in k for r in result['rows'] for k in r)


def test_genuine_actor_API_preserves_original_same_TEAM_contract_and_unresolved_aliases():
    f=Genuine();read=world.ReadSet(f.read)
    out=people.inspect_actor_bindings(read,f.base,f.engine,expected_match_unique_id=f.packet['context_before']['official_match_unique_id']);read.verify()
    assert len(out['players'])==38
    assert all(r['identity_state']=='canonical_PERSON_table_same_team_and_typed_stats' for r in out['players'])
    for slot in (17,19,20,21,22,23,24,25):assert not any(r['side_index']==1 and r['stored_player_slot']==slot for r in out['players'])


@pytest.mark.parametrize('case,index,flag,fast_count,slow_count,expected',[
    ('fast0',0,0,20,20,0x410000),('fast17',17,0,20,20,0x400388),
    ('slow0',0,1,20,20,0x410000),('slow17',17,1,20,20,0x400388),
    ('fast_bounds_to_slow',17,0,17,20,0x400388),
    ('FFFFFFFF',0xffffffff,1,20,20,None),('negative',0xfffffffe,1,20,20,None),
    ('bounds',20,1,20,20,None),('slow_empty',0,1,20,0,None),
])
def test_nine_original_ARM_getter_controls_match_readonly_candidate(case,index,flag,fast_count,slow_count,expected):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_MEM_READ
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_LR,UC_ARM64_REG_SP
    f=Fixture();f.u(f.stats+0x18,index);f.put(0x56d34e0,bytes([flag]))
    f.q(0x140000,0x410000);f.q(0x130070,0x140000+fast_count*8)
    f.q(0x132008,0x140000+slow_count*8)
    captured=Genuine();original=captured.read(captured.base+native.GETTER_RVA,184)
    assert hashlib.sha256(original).hexdigest()=='a529c0ed653892f9c419f9c45c382d3bf3e875097bf31b80c0a0c739176132d0'
    assert original==native.GETTER_BYTES
    vm=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    for page in sorted({at//4096*4096 for at in f.memory}|{0x9000000,0x9001000}):
        vm.mem_map(page,4096);vm.mem_write(page,bytes(f.memory.get(page+i,0) for i in range(4096)))
    vm.mem_write(native.GETTER_RVA,original)
    vm.reg_write(UC_ARM64_REG_X0,f.stats);vm.reg_write(UC_ARM64_REG_LR,0x9000000);vm.reg_write(UC_ARM64_REG_SP,0x9001ff0)
    reads=[];vm.hook_add(UC_HOOK_MEM_READ,lambda uc,access,at,size,value,user:reads.append((at,size)))
    vm.emu_start(native.GETTER_RVA,0x9000000,count=100)
    assert (vm.reg_read(UC_ARM64_REG_X0) or None)==expected
    assert native.resolve_stats_person(f.read,0,f.stats)==expected
    if index==0xffffffff:assert (0x56d2d78,8) not in reads
    elif index==0xfffffffe:assert (0x56d2d78,8) in reads and (0x56d2d80,8) not in reads


@pytest.mark.parametrize('at',[0x2e8c6d4,0x55fa810,0x56d34e0,0x140000+17*8])
def test_missing_required_runtime_source_or_operand_is_fatal(at):
    f=Fixture();del f.memory[at]
    with pytest.raises(ValueError,match='Missing synthetic operand'):f.inspect()


def test_duplicate_canonical_PERSON_across_owned_original_slots_refuses():
    f=Fixture();second=0x720000;f.q(f.side+0x140+18*8,second)
    f.typed(second,0x569ee68,b'N7simatch12MATCH_PLAYERE')
    for offset,value in [(0x280,f.engine),(0x288,f.side),(0x20,f.person),(0x1880,f.stats)]:f.q(second+offset,value)
    f.u(second+0x48,f.uid);f.put(second+0x1e27,b'\x12')
    with pytest.raises(ValueError,match='Duplicate canonical PERSON'):f.inspect()


def test_new_identity_route_never_calls_rich_profile_or_virtual_GENERATED_name(monkeypatch):
    from fm_live_mcp import virtual_identity
    f=Fixture()
    def forbidden(*a,**k):raise AssertionError('Generated/profile API is forbidden')
    monkeypatch.setattr(players,'decode',forbidden);monkeypatch.setattr(virtual_identity,'inspect',forbidden)
    assert f.inspect()['rows'][43]['person']['name']=='Synthetic academy player'
