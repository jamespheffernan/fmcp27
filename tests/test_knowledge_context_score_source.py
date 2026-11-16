"""Typed byte fixtures and real private collector calls; no live/game execution."""
from _knowledge_stream_fixture import native_stream_transport
from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import os
import importlib.util
from pathlib import Path
import struct
import threading
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_INVALID
import unicorn.arm64_const as registers

import pytest
from _unicorn_pages import map_pages, page_images

from fm_live_mcp import (bridge as bridge_module, database, knowledge_context_score as core,
    knowledge_context_score_source as source, knowledge_transfer_predicate as transfer,
    players, prepared_tactics_source, world)

import _pinned_build
PLUGIN = _pinned_build.PLUGIN
_PLUGIN_DIGESTS = {}


def plugin_sha256(stream):
    """SHA-256 of the open plugin, hashed once per file identity (device, inode, size, mtime)
    instead of once per Memory: every parametrised case builds a Memory, and hashing the 192 MB
    plugin cost about 0.15 s each time."""
    st = os.fstat(stream.fileno())
    key = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    if key not in _PLUGIN_DIGESTS:
        _PLUGIN_DIGESTS[key] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return _PLUGIN_DIGESTS[key]


class Memory:
    def __init__(self, combined=False):
        self.cells, self.reads, self.tables, self.metadata = {}, [], {}, {}
        self.base, self.next = 0x100000000, 0x100000
        self.blocked, self.on_read = [], None
        self.binary = PLUGIN.open('rb')
        assert plugin_sha256(self.binary) == core.PLUGIN_SHA256
        for rva, size, digest in core.NATIVE_GUARDS + transfer.NATIVE_GUARDS + source.EXTRA_GUARDS:
            raw = self.disk(rva, size)
            assert hashlib.sha256(raw).hexdigest() == digest
            self.put(self.base + rva, raw)
        for rva, raw in prepared_tactics_source.NATIVE_SPANS:
            assert self.disk(rva, len(raw)) == raw
            self.put(self.base + rva, raw)
        for rva, raw in source.aggregate.NATIVE_SPANS:
            assert self.disk(rva, len(raw)) == raw
            self.put(self.base + rva, raw)
        for rva, raw in core.FLOAT_GUARDS:
            assert self.disk(rva, 4) == raw
            self.put(self.base + rva, raw)
        for rva,size in ((0x540420e+18,1),(0x50bda9a,8),(0x539d234+18*2,2),(0x52efdf0,4)):
            self.put(self.base+rva,self.disk(rva,size))
        for table in (players.RVA[0],players.STAFF_RVA[0]):
            self.put(self.base+table-0x20,self.disk(table-0x20,16))
        self.game = self.typed('game', 0xd0)
        self.save = self.typed('save', 0x78)
        self.human = self.typed('manager', 0x600)
        self.human_person, self.human_common = self.human + 0x548, self.human + 0x438
        self.native_type(self.human_person, 0x55ad820)
        self.native_type(self.human_common, 0x55acb30)
        self.team = self.typed('team', 0x180)
        self.club = self.typed('club', 0x200)
        self.other = self.typed('club', 0x200)
        self.nation = self.typed('nation', 0x220)
        self.container = self.typed('national_team_container', 0x600)
        self.national = self.typed('national_team', 0x200)
        self.competition = self.typed('competition', 0x180)
        self.game_club = self.typed('game_club', 16)
        self.q(self.base+0x56d2ce8,self.game_club)
        self.q(self.base+0x55df850+0x168,self.base+0x1fa72c4)
        self.primary = self.allocate(0x600)
        primary_table, person_table, common_table, pd, cd = ((0x558ef38,0x55908e0,0x558fbf0,0x480,0x370) if combined else
                                                         (0x5588ee8,0x558a780,0x5589a90,0x388,0x278))
        self.person, self.common = self.primary + pd, self.primary + cd
        self.native_type(self.primary, primary_table)
        self.native_type(self.person, person_table)
        self.native_type(self.common, common_table)
        if combined:self.native_type(self.primary + 0x278, 0x558f568)
        self.person_ref = (0, 1001, 1002)
        self.identity(self.person, *self.person_ref)
        self.identity(self.human_person, 1, 2001, 2002)
        for name, addresses in [('people',[self.person,self.human_person]),('clubs',[self.club,self.other]),
            ('teams',[self.team,self.national]),('nations',[self.nation]),
            ('national_team_containers',[self.container]),('competitions',[self.competition])]:
            for index,address in enumerate(addresses):
                if name!='people':self.identity(address,index,3000+address//8,4000+address//8)
            self.database(name,addresses)
        self.q(self.team+0x30,self.club); self.q(self.team+0x50,self.competition)
        self.q(self.team+0x80,self.human); self.put(self.team+0x2f,b'\0')
        self.q(self.national+0x30,self.container);self.put(self.national+0x2f,b'\1')
        self.vec(self.club+0x18,[self.team]);self.vec(self.club+0x30,[])
        self.vec(self.other+0x18,[]);self.vec(self.other+0x30,[])
        self.vec(self.container+0x18,[self.national])
        self.q(self.club+0xd8,self.nation);self.q(self.container+0x170,self.nation)
        self.q(self.nation+0x110,self.container);self.q(self.nation+0x118,self.container)
        self.vec(self.club+0x118,[]);self.vec(self.other+0x118,[])
        self.q(self.primary+0x128,self.team)
        self.q(self.common+0xd8,self.other)
        self.q(self.common+0x38,self.nation);self.q(self.human_common+0x38,self.nation)
        self.main = self.contract('trial_contract',self.person,self.team)
        self.owner_contract = self.contract('full_contract',self.human_person,self.team)
        self.q(self.common+0x78,self.main);self.q(self.human_common+0x78,self.owner_contract)
        self.holder=self.allocate(32);self.q(self.holder,self.main);self.q(self.common+0x80,self.holder)
        self.put(self.owner_contract+0x26,b'\2')
        self.put(self.primary+0x25a,struct.pack('<h',8000))
        self.put(self.primary+0x258,struct.pack('<h',5000))
        self.put(self.base+0x56d4993,b'\0');self.put(self.base+0x56d4951,b'\1')
        self.put(self.base+0x56d34e0,b'\1')
        self.q(self.base+0x56d57d0,0)
        self.put(self.human+0x422,b'\1')
        self.personal=self.allocate(0xe00);self.q(self.human+0x388,self.personal)
        self.put(self.personal+0xda4,b'\7')
        self.put(self.base+world.CURRENT_DATE,struct.pack('<HH',317,2030))
        self.q(self.base+world.GAME_ROOT,self.game);self.q(self.base+world.SAVE_ROOT,self.save)
        self.q(self.save+0x28,self.text('Private synthetic career'))
        self.put(self.game+0x38,struct.pack('<II',(2025<<16)|296,2223821))
        self.put(self.game+0xc8,struct.pack('<I',428));self.put(self.save+0x70,struct.pack('<I',(2030<<16)|317))
        user=self.allocate(0x150);info=self.allocate(24);self.q(self.game+0x58,info)
        self.vec(info,[user]);self.q(user+0x148,self.human);self.vec(user+0xc0,[self.human])
        for offset,name in ((0x458,'Private'),(0x460,'Coach')):
            handle=self.allocate(8);self.q(handle,self.text(name));self.q(self.human+offset,handle)
        for address,label in ((self.club,'Private Club'),(self.other,'Other Club')):
            self.q(address+0xc0,self.text(label));self.q(address+0xc8,self.text(label))
        self.fow=self.allocate(0x30);self.native_type(self.fow,0x55f5d80)
        self.record=self.allocate(0x28);self.q(self.record+0x18,self.human_person)
        self.vec(self.fow+0x18,[self.record]);self.q(self.base+0x56a8430,self.fow)
        self.put(self.base+0x56d4980,b'\1');self.put(self.base+0x56d4981,b'\0')
        self.put(self.human+0x3e4,struct.pack('<i',0))
        # Some small vtables neighbor RTTI records within our broad slot seed;
        # restore actual relocated metadata after every class has been seeded.
        for rva,(displacement,info,name,raw) in self.metadata.items():
            self.put(self.base+rva-16,struct.pack('<qQ',displacement,self.base+info))
            self.q(self.base+info+8,self.base+name);self.put(self.base+name,raw)
        self.binary.close()

    def disk(self,rva,size):
        if self.binary.closed:
            with PLUGIN.open('rb') as stream:stream.seek(0x5ed4000+rva);raw=stream.read(size)
        else:
            self.binary.seek(0x5ed4000+rva);raw=self.binary.read(size)
        assert len(raw)==size;return raw

    def put(self,at,raw):
        self.cells.update((at+i,value) for i,value in enumerate(raw))

    def q(self,at,value):
        self.put(at,struct.pack('<Q',value))

    def allocate(self,size):
        at=self.next;self.next+=(size+7)//8*8;self.put(at,bytes(size));return at

    def identity(self,address,index,uid,secondary):
        self.put(address+8,struct.pack('<III',index,uid,secondary))

    def text(self,text):
        raw=text.encode();at=self.allocate(len(raw)+5);self.put(at,struct.pack('<I',len(raw))+raw+b'\0');return at

    def native_type(self,address,rva):
        table=self.base+rva;self.q(address,table)
        displacement,info=struct.unpack('<qQ',self.disk(rva-16,16));info&=0xffffffff
        name=int.from_bytes(self.disk(info+8,8),'little')&0xffffffff
        raw=self.disk(name,256).split(b'\0')[0]+b'\0'
        self.metadata[rva]=(displacement,info,name,raw)
        self.put(table-16,struct.pack('<qQ',displacement,self.base+info))
        self.q(self.base+info+8,self.base+name);self.put(self.base+name,raw)
        for negative in (0x18,0x20,0x1c8,0x230,0x240,0x248,0x3d0,0x3d8,0x3f8,0x408,0x418,0x450,0x678,0x688,0x700,0x1e0):
            self.put(table-negative,self.disk(rva-negative,8))
        for slot in (0x18,0x20,0x30,0x38,0x58,0x70,0x90,0x98,0xa0,0xe8,0xf0,0x138,0x1b0,0x1b8,0x1d0,0x220,0x230,0x238,0x240,
                     0x2e8,0x300,0x3c0,0x3c8,0x3e8,0x3f8,0x408,0x438,0x668,0x678,0x6f0):
            raw=self.disk(rva+slot,8);target=int.from_bytes(raw,'little')&0xffffffff
            if 0x1000<=target<0x5000000:self.q(table+slot,self.base+target)
            else:self.put(table+slot,raw)
        # Restore own metadata after any class-specific negative virtual rows.
        self.put(table-16,struct.pack('<qQ',displacement,self.base+info))

    def typed(self,kind,size):
        at=self.allocate(size);self.native_type(at,world.TYPES[kind][0]);return at

    def contract(self,kind,person,team):
        at=self.typed(kind,0x100);self.q(at+8,person);self.q(at+0x10,team);self.q(at+0x18,team)
        self.put(at+0x44,struct.pack('<HH',318,2030));return at

    def vec(self,at,values):
        start=self.allocate(max(8,len(values)*8))
        for i,value in enumerate(values):self.q(start+i*8,value)
        self.put(at,struct.pack('<QQQ',start,start+8*len(values),start+8*len(values)))
        return start

    def database(self,kind,values):
        root_rva,table_rva,_=database.TABLES[kind]
        root=self.allocate(0x90);self.native_type(root,table_rva)
        header=self.allocate(24);start=self.vec(header,values)
        self.q(root+0x88,header);self.q(self.base+root_rva,root)
        self.tables[kind]=(root,header,start)

    def read(self,at,size):
        self.reads.append((at,size))
        if any(at < end and at+size > start for start,end in self.blocked):
            raise ValueError('Unconsumed synthetic byte was read')
        if self.on_read:self.on_read(at,size)
        return bytes(map(self.cells.__getitem__,range(at,at+size)))  # KeyError on the first missing byte, as before


@dataclass(frozen=True)
class Process:
    pid:int=12345
    version:str=players.VERSION
    bundle_id:str='com.SportsInteractive.FootballManager27'


class SyntheticBridge(bridge_module.Bridge):
    """Only host/process transport is synthetic; world and source reads are real."""
    def __init__(self,memory):
        self.memory=memory;self.lock=threading.RLock();self.process=Process();self.session='synthetic'
        self.helper='synthetic';self._reader=None
        self.plugin_identity=(('synthetic-plugin',),b'pinned-uuid')
        self.world_identity=None;self.lifetimes=0;self.on_current=None

    def _current(self,session):
        assert session==self.session
        self.lifetimes+=1
        if self.on_current:self.on_current(self.lifetimes)
        return self.process

    def _player_layout(self,process):
        return tuple(self.memory.base+rva for rva in players.RVA)

    def _read_memory(self,process,address,size):
        return self.memory.read(address,size)

    @contextmanager
    def _read_scope(self,session):
        self._current(session)
        yield
        self._current(session)


def run(memory,bridge=None):
    return source.collect(bridge or SyntheticBridge(memory),'synthetic',
        subject_person=memory.person,subject_identity=memory.person_ref,
        coach_name='Private Coach',field=18)


@pytest.mark.parametrize('combined',[False,True])
def test_complete_byte_bound_nonfree_K_R_route(combined):
    memory=Memory(combined)
    result=run(memory)
    assert result['score']==90 and result['unavailable_reason'] is None
    assert result['field']==18 and result['fow_owner_record_bound'] is True
    assert result['field_state_or_permission_evaluated'] is False


def copied_K(memory, truncate_association=False, extra_native=(), trace_inputs=False):
    """Execute all actual K/R/callee bytes in local RAM, with NO result stubs."""
    for rva,size,digest in extra_native:
        raw=memory.disk(rva,size);assert hashlib.sha256(raw).hexdigest()==digest
        memory.put(memory.base+rva,raw)
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    known=set(memory.cells);images=page_images(memory.cells);pages=set(images)
    stack,stop=0x200000000,0x300000000
    pages.update(range(stack,stack+0x10000,4096));pages.add(stop)
    map_pages(uc,pages)
    for page in sorted(images):
        uc.mem_write(page,images[page])
    executable=[(memory.base+rva,memory.base+rva+(0x2c4 if truncate_association and rva==0x148a068 else size))
                for rva,size,_ in core.NATIVE_GUARDS+transfer.NATIVE_GUARDS+source.EXTRA_GUARDS]
    executable += [(memory.base+rva,memory.base+rva+len(raw)) for rva,raw in source.aggregate.NATIVE_SPANS]
    executable += [(memory.base+rva,memory.base+rva+size) for rva,size,_ in extra_native]
    native_reads,virtual_calls=[],[]
    def code(machine,address,size,user):
        if address==stop:machine.emu_stop();return
        assert any(start<=address<end for start,end in executable),('uncaptured native callee',hex(address-memory.base))
        word=int.from_bytes(machine.mem_read(address,4),'little')
        if word&0xfffffc1f==0xd63f0000:
            register=getattr(registers,'UC_ARM64_REG_X'+str((word>>5)&31))
            virtual_calls.append((address-memory.base,machine.reg_read(register)-memory.base))
    def read(machine,access,address,size,value,user):
        assert all(at in known for at in range(address,address+size)),('missing copied native input',hex(address),size)
        native_reads.append((machine.reg_read(registers.UC_ARM64_REG_PC)-memory.base,address,size))
    def write(machine,access,address,size,value,user):
        assert stack<=address<stack+0x10000,('copied native nonstack write',hex(address))
        known.update(range(address,address+size))
    def invalid(machine,access,address,size,value,user):
        raise AssertionError(('unmapped copied native input',hex(address),size,hex(machine.reg_read(registers.UC_ARM64_REG_PC)-memory.base)))
    uc.hook_add(UC_HOOK_CODE,code);uc.hook_add(UC_HOOK_MEM_READ,read);uc.hook_add(UC_HOOK_MEM_WRITE,write)
    uc.hook_add(UC_HOOK_MEM_INVALID,invalid)
    uc.reg_write(registers.UC_ARM64_REG_X0,memory.human_person)
    uc.reg_write(registers.UC_ARM64_REG_X1,memory.primary)
    uc.reg_write(registers.UC_ARM64_REG_SP,stack+0xf000);uc.reg_write(registers.UC_ARM64_REG_LR,stop)
    try:
        uc.emu_start(memory.base+0x2386548,stop,count=20000)
    except Exception as error:
        raise AssertionError(('copied K failed at',hex(uc.reg_read(registers.UC_ARM64_REG_PC)-memory.base),str(error))) from error
    assert uc.reg_read(registers.UC_ARM64_REG_PC)==stop
    value=core._signed(uc.reg_read(registers.UC_ARM64_REG_W0),32)
    return (value,native_reads,virtual_calls) if trace_inputs else value


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('scalar',[4999,5000,6499,6500,7999,8000,32767])
@pytest.mark.parametrize('raw_range',[0,2,3,4,5,6,7])
def test_complete_collector_matches_whole_copied_K_without_lower_stubs(combined,scalar,raw_range):
    memory=Memory(combined)
    memory.put(memory.primary+0x25a,struct.pack('<h',scalar))
    memory.put(memory.personal+0xda4,bytes([raw_range]))
    actual=run(memory)
    native=copied_K(memory)
    assert actual['score']==native
    assert native not in (0,100)


def test_old_truncated_association_copy_cannot_complete_actual_caller():
    memory=Memory()
    assert copied_K(memory)==run(memory)['score']==90
    with pytest.raises(AssertionError,match='uncaptured native callee'):
        copied_K(memory,truncate_association=True)


@pytest.mark.parametrize('pointer',[0,1])
def test_transfer_null_and_nonnull_empty_sources_are_distinct(pointer):
    memory=Memory()
    if pointer:
        header=memory.allocate(24);memory.q(memory.common+0x68,header)
    result=run(memory)
    assert result['score']==copied_K(memory)==90


@pytest.mark.parametrize('failure',['subject_id','human_person','human_team','fow_owner','fow_index','fow_flag','fow_bypass','field'])
def test_wrong_identity_owner_or_field_cannot_supply_K(failure):
    memory=Memory();kwargs={}
    if failure=='subject_id':memory.identity(memory.person,0,1234,1002)
    if failure=='human_person':memory.q(memory.human_person,memory.base+players.RVA[2])
    if failure=='human_team':memory.q(memory.team+0x80,memory.human+8)
    if failure=='fow_owner':memory.q(memory.record+0x18,memory.person)
    if failure=='fow_index':memory.put(memory.human+0x3e4,struct.pack('<i',-1))
    if failure=='fow_flag':memory.put(memory.human+0x3fc,b'\x10')
    if failure=='fow_bypass':memory.put(memory.base+0x56d4981,b'\1')
    if failure=='field':kwargs['field']=19
    with pytest.raises((ValueError,bridge_module.BridgeError)):
        source.collect(SyntheticBridge(memory),'synthetic',subject_person=memory.person,
            subject_identity=memory.person_ref,coach_name='Private Coach',**kwargs)


@pytest.mark.parametrize('failure',['national_type','national_kind','national_owner','national_index','national_table'])
def test_checked_national_subset_rejects_wrong_raw_source(failure):
    memory=Memory();memory.q(memory.primary+0x120,memory.national)
    memory.put(memory.national+0xe2,b'\1');memory.put(memory.national+0xb8,struct.pack('<HH',318,2030))
    if failure=='national_type':memory.q(memory.national,memory.base+world.TYPES['team'][0])
    if failure=='national_kind':memory.put(memory.national+0x2f,b'\0')
    if failure=='national_owner':memory.q(memory.national+0x30,memory.club)
    if failure=='national_index':memory.put(memory.national+8,struct.pack('<I',0))
    if failure=='national_table':memory.q(memory.tables['teams'][2]+8,memory.team)
    result=run(memory)
    assert result['score'] is None and result['unavailable_reason']


def test_common_D8_wrong_shape_cannot_become_CLUB():
    memory=Memory();memory.q(memory.common+0xd8,memory.team);memory.q(memory.team+0x50,0)
    memory.blocked.append((memory.team+0x18,memory.team+0x20))
    result=run(memory)
    assert result['score'] is None
    assert 'entity family' in result['unavailable_reason']


def test_raw_field_aliases_cannot_disagree_between_named_operands():
    memory=Memory();bridge=SyntheticBridge(memory)
    with bridge.lock,bridge._read_scope('synthetic'):
        bound=source._Source(bridge,'synthetic',memory.person,memory.person_ref,'Private Coach',18)
        first=bound.operand('common_d8_pointer',bound.subject).value
        assert first==bound.operand('subject238_context',bound.subject).value.address==memory.other
        memory.q(memory.common+0xd8,memory.club)
        with pytest.raises(ValueError,match='changed'):
            bound.operand('subject238_context',bound.subject)


@pytest.mark.parametrize('failure',['scalar','code','fow_record','save_count','date','plugin','process'])
def test_changes_in_final_lifetime_callback_are_rejected_after_callback(failure):
    baseline_memory=Memory();baseline_bridge=SyntheticBridge(baseline_memory)
    assert run(baseline_memory,baseline_bridge)['score']==90
    final_callback=baseline_bridge.lifetimes-1  # Last callback before read-scope exit.
    memory=Memory();bridge=SyntheticBridge(memory)
    def change(count):
        if count!=final_callback:return
        if failure=='scalar':memory.put(memory.primary+0x25a,struct.pack('<h',6500))
        if failure=='code':memory.put(memory.base+0x2386548,b'\0')
        if failure=='fow_record':memory.q(memory.record+0x18,memory.person)
        if failure=='save_count':memory.put(memory.game+0xc8,struct.pack('<I',429))
        if failure=='date':memory.put(memory.base+world.CURRENT_DATE,struct.pack('<HH',318,2030))
        if failure=='plugin':bridge.plugin_identity=(('different-plugin',),b'other-uuid')
        if failure=='process':bridge.process=replace(bridge.process,pid=bridge.process.pid+1)
    bridge.on_current=change
    with pytest.raises((ValueError,bridge_module.BridgeError)):
        run(memory,bridge)


def test_unused_holder_tail_and_unneeded_lower_source_stay_unread():
    memory=Memory()
    memory.blocked.append((memory.holder+8,memory.holder+32))
    # All byte-dependent selector/primary/current-TEAM paths return before
    # these holder slots; known P25A route does not read club-score stores.
    memory.blocked.append((memory.club+0x100,memory.club+0x108))
    assert run(memory)['score']==90


def test_malformed_DOB_and_unproved_relation_fanout_are_unknown_not_zero():
    memory=Memory();memory.put(memory.primary+0x25a,struct.pack('<h',4999));memory.put(memory.team+0x28,b'\1')
    result=run(memory)
    assert result['score'] is None and 'DATE' in result['unavailable_reason']
    memory=Memory();memory.q(memory.primary+0x128,memory.national)
    result=run(memory)
    assert result['score'] is None and '20ee608' in result['unavailable_reason']


def test_nested_range2_now_matches_complete_original_K():
    memory=Memory();memory.put(memory.personal+0xda4,b'\2')
    result=run(memory)
    assert result['score']==copied_K(memory)==90 and result['unavailable_reason']is None


def test_native_range_override_matches_complete_original_K():
    memory=Memory();memory.put(memory.base+0x56d4951,b'\0');memory.put(memory.base+0x56d496e,b'\1')
    result=run(memory)
    assert result['score']==copied_K(memory)==90 and result['unavailable_reason']is None


@pytest.mark.parametrize('failure',['flag','service','selected_competition','projection','override_code'])
def test_override_inputs_are_rechecked_after_final_lifetime_callback(failure):
    def fixture():
        m=Memory();m.put(m.base+0x56d4951,b'\0');m.put(m.base+0x56d496e,b'\1')
        m.q(m.team+0x58,m.competition)
        return m
    baseline=fixture();baseline_bridge=SyntheticBridge(baseline)
    assert run(baseline,baseline_bridge)['score']==90
    assert (baseline.team+0x58,8)in baseline.reads
    final_callback=baseline_bridge.lifetimes-1
    memory=fixture();bridge=SyntheticBridge(memory)
    def change(count):
        if count!=final_callback:return
        if failure=='flag':memory.put(memory.base+0x56d496e,b'\0')
        if failure=='service':memory.q(memory.base+0x56d2ce8,0)
        if failure=='selected_competition':memory.q(memory.team+0x58,0)
        if failure=='projection':memory.q(memory.nation+0x110,0)
        if failure=='override_code':memory.put(memory.base+0x1fa72c4,b'\0')
    bridge.on_current=change
    with pytest.raises(ValueError,match='changed'):run(memory,bridge)


def test_unproved_secondary_path_remains_explicit_unknown():
    memory=Memory();memory.put(memory.base+0x56d4993,b'\1')
    wrapper=memory.allocate(0x18);memory.q(wrapper+0x10,memory.owner_contract)
    memory.q(memory.human_common+0x80,wrapper)
    memory.q(memory.primary+0x120,memory.national)
    memory.put(memory.national+0xe2,b'\1');memory.put(memory.national+0xb8,struct.pack('<HH',318,2030))
    memory.q(memory.common+0x38,0);memory.put(memory.primary+0x25a,struct.pack('<h',5000))
    result=run(memory)
    assert result['score'] is None and '17743b8' in result['unavailable_reason']


def aggregate_memory(combined=False):
    memory=Memory(combined)
    memory.put(memory.primary+0x25a,struct.pack('<h',4999))
    memory.q(memory.primary+0x120,memory.national)
    memory.put(memory.national+0xe2,b'\1');memory.put(memory.national+0xb8,struct.pack('<HH',318,2030))
    memory.put(memory.owner_contract+0x26,b'\x0e')
    memory.vec(memory.club+0x90,[memory.human])
    header=memory.allocate(24);row=memory.allocate(0x28)
    memory.q(row,memory.container);memory.put(row+0x24,b'\x64')
    memory.vec(header,[row]);memory.q(memory.human+0xb0,header)
    memory.knowledge_row=row
    return memory


@pytest.mark.parametrize('combined',[False,True])
def test_native_aggregate_adapter_integrates_in_full_nonfree_K_route(combined):
    memory=aggregate_memory(combined)
    result=run(memory)
    assert result['score']==copied_K(memory)==43
    # First retained100 ends the native helper before the derived pool. No
    # allocator/temporary-vector result is faked in the copied execution.
    assert (memory.knowledge_row+0x24,1) in memory.reads


def test_nested_aggregate_consumed_bytes_rechecked_after_final_callback():
    first=aggregate_memory();baseline=SyntheticBridge(first)
    assert run(first,baseline)['score']==43
    memory=aggregate_memory();bridge=SyntheticBridge(memory)
    def change(count):
        if count==baseline.lifetimes-1:memory.put(memory.knowledge_row+0x24,b'\x63')
    bridge.on_current=change
    with pytest.raises(ValueError,match='changed'):
        run(memory,bridge)


def test_selected_field_metadata_is_checked_without_reading_the_getter_value():
    memory=Memory()
    memory.blocked.append((memory.primary+0x148,memory.primary+0x180))
    assert run(memory)['score']==90
    memory=Memory();memory.put(memory.base+0x540420e+18,b'\x17')
    with pytest.raises(core.SourceUnavailable,match='Passing18 metadata'):
        run(memory)


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('birth_year',[2000,2008,2009,2010])
def test_existing_age_adapter_is_byte_bound_and_matches_full_copied_K(combined,birth_year):
    memory=Memory(combined)
    memory.put(memory.primary+0x25a,struct.pack('<h',4999));memory.put(memory.team+0x28,b'\1')
    memory.put(memory.common+0x58,struct.pack('<HH',200,birth_year))
    memory.put(memory.base+0x56d4951,b'\0');memory.put(memory.base+0x56d496e,b'\0')
    assert run(memory)['score']==copied_K(memory)


def test_default_DOB_returns_before_unread_alternate_age_context():
    memory=Memory();memory.put(memory.primary+0x25a,struct.pack('<h',4999));memory.put(memory.team+0x28,b'\1')
    memory.put(memory.common+0x58,struct.pack('<HH',1,1900))
    memory.blocked.append((memory.base+0x56d57d0,memory.base+0x56d57d0+8))
    assert run(memory)['score']==copied_K(memory)==10


@pytest.mark.parametrize('mode',[1,2])
def test_typed_alternate_age_date_uses_actual_root_bytes(mode):
    memory=Memory();memory.put(memory.primary+0x25a,struct.pack('<h',4999));memory.put(memory.team+0x28,b'\1')
    memory.put(memory.common+0x58,struct.pack('<HH',200,2009));memory.put(memory.base+0x56d4951,bytes([mode]))
    root=memory.allocate(0x200);memory.native_type(root,0x55dd068)
    memory.q(memory.base+0x56d57d0,root);memory.put(root+0x184,struct.pack('<HH',317,2030))
    assert run(memory)['score']==copied_K(memory)==10
    memory.put(root+0x184,struct.pack('<HH',0,2030))
    assert run(memory)['score'] is None


def test_unselected_age_root_is_loaded_but_not_dereferenced():
    memory=Memory();memory.put(memory.primary+0x25a,struct.pack('<h',4999));memory.put(memory.team+0x28,b'\1')
    memory.put(memory.common+0x58,struct.pack('<HH',200,2009));memory.put(memory.base+0x56d4951,b'\0')
    memory.put(memory.base+0x56d496e,b'\0');memory.q(memory.base+0x56d57d0,0)
    assert run(memory)['score']==copied_K(memory)==10
    assert (memory.base+0x56d57d0,8) in memory.reads


def test_HUMAN_main_contract_cast_guard_rejects_real_native_score_divergence():
    memory=Memory()
    assert run(memory)['score']==copied_K(memory)==90
    # Actual cb3724 uses this negative virtual-base row. The historical Source
    # assumed H+438 instead; changing just the row changes actual copied K.
    row=memory.base+0x55ad820-0x3d8
    memory.put(row,struct.pack('<q',-0x548))
    assert copied_K(memory)==80
    old_path=Path('/Volumes/4TB Private/Offloaded/FMCP 27/evidence/knowledge-field-visibility-20261108/context/full-score/implementation-independent/source/frozen-3e5df/knowledge_context_score_source.py')
    assert hashlib.sha256(old_path.read_bytes()).hexdigest()=='3e5df5ba58ab873602b139dbd7dd1894c21921aa4292a1bc303cfe0765b61b3e'
    spec=importlib.util.spec_from_file_location('fm_live_mcp._historical_source_without_3d8',old_path)
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    assert old.collect(SyntheticBridge(memory),'synthetic',subject_person=memory.person,
        subject_identity=memory.person_ref,coach_name='Private Coach',field=18)['score']==90
    with pytest.raises(core.SourceUnavailable,match='HUMAN K subobject displacement'):
        run(memory)
    assert (row,8) in memory.reads


def historical_collect(memory):
    path=Path('/Volumes/4TB Private/Offloaded/FMCP 27/evidence/knowledge-field-visibility-20261108/context/full-score/implementation-independent/source/frozen-3e5df/knowledge_context_score_source.py')
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='3e5df5ba58ab873602b139dbd7dd1894c21921aa4292a1bc303cfe0765b61b3e'
    spec=importlib.util.spec_from_file_location('fm_live_mcp._historical_all_cast_source',path)
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    return old.collect(SyntheticBridge(memory),'synthetic',subject_person=memory.person,
        subject_identity=memory.person_ref,coach_name='Private Coach',field=18)


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('row_offset,mutation',[(0x20,0),(0x18,0x548)])
def test_actual_and_combined_primary_casts_have_old_accept_native_diverge_new_reject(combined,row_offset,mutation):
    memory=Memory(combined)
    if row_offset==0x18:
        # Alternative noncanonical HUMAN-shaped bytes are seeded BEFORE the
        # baseline, exactly as the independent value-changing counterexample.
        memory.q(memory.primary+0x548,memory.base+0x55ad820)
        memory.q(memory.primary+0x4b0,memory.owner_contract)
    assert run(memory)['score']==copied_K(memory)==90
    table=players.STAFF_RVA[0] if combined else players.RVA[0]
    row=memory.base+table-row_offset
    memory.put(row,struct.pack('<q',mutation))
    assert copied_K(memory)==100
    assert historical_collect(memory)['score']==90
    with pytest.raises(core.SourceUnavailable,match='PLAYER primary COMMON/PERSON'):
        run(memory)
    assert any(at<=row and at+size>=row+8 for at,size in memory.reads)


@pytest.mark.parametrize('which',['primary18','DATA450'])
def test_HUMAN_secondary_context_casts_have_native_value_changing_controls(which):
    memory=Memory();memory.put(memory.primary+0x25a,struct.pack('<h',5000))
    memory.put(memory.base+0x56d4993,b'\1')
    wrapper=memory.allocate(0x18);memory.q(wrapper+0x10,memory.owner_contract)
    memory.q(memory.human_common+0x80,wrapper)
    # The changed primary18 route reaches this real PERSON438 null getter.
    # It is copied actual code, not a callback returning a convenient value.
    extra=((0xca47ec,8,'2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'),)
    assert run(memory)['score']==copied_K(memory,extra_native=extra)==60
    row=memory.base+(world.TYPES['manager'][0]-0x18 if which=='primary18' else 0x55acb30-0x450)
    memory.put(row,struct.pack('<q',0x548 if which=='primary18' else 0x110))
    assert copied_K(memory,extra_native=extra)==40
    assert historical_collect(memory)['score']==60
    if which=='primary18':
        with pytest.raises(core.SourceUnavailable,match='HUMAN'):
            run(memory)
    else:
        result=run(memory)
        assert result['score'] is None
        assert 'HUMAN DATA438 owning-primary cast changed' in result['unavailable_reason']
    assert (row,8) in memory.reads


def test_DATA450_guard_is_lazy_on_the_native_disabled_branch():
    memory=Memory();row=memory.base+0x55acb30-0x450
    memory.put(row,struct.pack('<q',0x110))
    memory.blocked.append((row,row+8))
    assert run(memory)['score']==copied_K(memory)==90


@pytest.mark.parametrize('which',['H_PERSON3d8','H_primary18','H_DATA450','actual20','actual18','combined20','combined18'])
def test_native_cast_rows_are_rechecked_after_the_final_callback(which):
    def fixture():
        memory=Memory(which.startswith('combined'))
        if which=='H_DATA450':
            memory.put(memory.base+0x56d4993,b'\1')
            wrapper=memory.allocate(0x18);memory.q(wrapper+0x10,memory.owner_contract)
            memory.q(memory.human_common+0x80,wrapper)
        return memory
    first=fixture();baseline=SyntheticBridge(first)
    assert run(first,baseline)['score']==90
    memory=fixture();bridge=SyntheticBridge(memory)
    rows={'H_PERSON3d8':0x55ad820-0x3d8,
          'H_primary18':world.TYPES['manager'][0]-0x18,
          'H_DATA450':0x55acb30-0x450,
          'actual20':players.RVA[0]-0x20,'actual18':players.RVA[0]-0x18,
          'combined20':players.STAFF_RVA[0]-0x20,'combined18':players.STAFF_RVA[0]-0x18}
    row=memory.base+rows[which]
    def change(count):
        if count==baseline.lifetimes-1:memory.put(row,struct.pack('<q',0))
    bridge.on_current=change
    with pytest.raises(ValueError,match='changed'):
        run(memory,bridge)


def pre_dispatch_collect(memory):
    path=Path('/Volumes/4TB Private/Offloaded/Agent Work/fmcp-knowledge-source-allcasts-20261108/fm_live_mcp/knowledge_context_score_source.py')
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='b1a86e5d1d89d8f419642c79ef9b95c2cbe3e23967a6bf93969b175b66ab7fa4'
    spec=importlib.util.spec_from_file_location('fm_live_mcp._historical_missing_240',path)
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    return old.collect(SyntheticBridge(memory),'synthetic',subject_person=memory.person,
        subject_identity=memory.person_ref,coach_name='Private Coach',field=18)


@pytest.mark.parametrize('which',['owner','actual','combined'])
def test_PERSON240_missing_dispatch_old_accepts_actual_wrong_leaf_new_rejects(which):
    memory=Memory(which=='combined')
    if which=='owner':memory.put(memory.primary+0x25a,struct.pack('<h',4999))
    else:memory.q(memory.common+0xd8,memory.club)
    baseline=40 if which=='owner' else 60
    assert run(memory)['score']==copied_K(memory)==baseline
    table=0x55ad820 if which=='owner' else players.STAFF_RVA[2] if which=='combined' else players.RVA[2]
    row=memory.base+table+0x240
    # Use another existing actual native leaf, never an invented result stub.
    target=0xca4744 if which=='owner' else 0xca474c
    memory.q(row,memory.base+target)
    native,_,calls=copied_K(memory,trace_inputs=True)
    assert (0x23865c8 if which=='owner' else 0x23865b4,target) in calls
    # Owner null changes40→20. Subject's wrong COMMON+D8 getter happens to
    # return the same CLUB in this owned context; numerical coincidence must
    # not excuse a wrong, unrecorded runtime dispatch.
    assert native==(20 if which=='owner' else baseline)
    memory.reads.clear()
    assert pre_dispatch_collect(memory)['score']==baseline
    assert not any(at<=row and at+size>=row+8 for at,size in memory.reads)
    if which=='owner':
        with pytest.raises(ValueError,match='virtual route'):
            run(memory)
    else:
        result=run(memory)
        assert result['score'] is None and 'virtual route' in result['unavailable_reason']
    assert (row,8) in memory.reads


@pytest.mark.parametrize('combined',[False,True])
def test_old_b1_journal_lacks_exact_both240_native_inputs_new_journal_contains_them(combined):
    memory=Memory(combined)
    native,reads,_=copied_K(memory,trace_inputs=True)
    assert native==pre_dispatch_collect(memory)['score']==90
    expected={memory.base+0x55ad820+0x240,
              memory.base+(players.STAFF_RVA[2] if combined else players.RVA[2])+0x240}
    def missing():
        return {address for _,address,size in reads if address in expected
                and not any(at<=address and at+count>=address+size for at,count in memory.reads)}
    assert missing()==expected
    memory.reads.clear()
    assert run(memory)['score']==native
    assert missing()==set()


@pytest.mark.parametrize('which',['owner','actual','combined'])
def test_PERSON240_dispatch_is_rechecked_after_final_callback(which):
    first=Memory(which=='combined');baseline=SyntheticBridge(first)
    assert run(first,baseline)['score']==90
    memory=Memory(which=='combined');bridge=SyntheticBridge(memory)
    table=0x55ad820 if which=='owner' else players.STAFF_RVA[2] if which=='combined' else players.RVA[2]
    def change(count):
        if count==baseline.lifetimes-1:memory.q(memory.base+table+0x240,memory.base+0xca4744)
    bridge.on_current=change
    with pytest.raises(ValueError,match='changed'):run(memory,bridge)


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('route',['early_same_club','R_default','R_range0','R_D8_definition',
                                  'owner_accepted70','secondary','aggregate','age','age_mode1','age_mode2'])
def test_every_reached_native_operand_is_recorded_by_Source(combined,route):
    memory=aggregate_memory(combined) if route=='aggregate' else Memory(combined)
    if route=='early_same_club':memory.q(memory.holder,0)
    elif route=='R_range0':memory.put(memory.personal+0xda4,b'\0')
    elif route=='R_D8_definition':
        memory.q(memory.team+0x50,0)
        team=memory.allocate(0x180);memory.q(team,memory.base+world.TYPES['team'][0])
        memory.identity(team,2,4444,5555);memory.q(team+0x30,memory.other)
        memory.q(team+0x50,memory.competition);memory.vec(memory.other+0x18,[team])
        memory.vec(memory.tables['teams'][1],[memory.team,memory.national,team])
    elif route=='owner_accepted70':
        memory.put(memory.owner_contract+0x26,b'\1');memory.put(memory.owner_contract+0xc2,b'\2')
    elif route=='secondary':
        memory.put(memory.primary+0x25a,struct.pack('<h',5000));memory.put(memory.base+0x56d4993,b'\1')
        wrapper=memory.allocate(0x18);memory.q(wrapper+0x10,memory.owner_contract)
        memory.q(memory.human_common+0x80,wrapper)
    elif route.startswith('age'):
        memory.put(memory.primary+0x25a,struct.pack('<h',4999));memory.put(memory.team+0x28,b'\1')
        memory.put(memory.common+0x58,struct.pack('<HH',200,2010))
        memory.put(memory.base+0x56d4951,b'\0');memory.put(memory.base+0x56d496e,b'\0')
        if route!='age':
            root=memory.allocate(0x200);memory.native_type(root,0x55dd068)
            memory.q(memory.base+0x56d57d0,root);memory.put(root+0x184,struct.pack('<HH',317,2030))
            memory.put(memory.base+0x56d4951,bytes([1 if route=='age_mode1' else 2]))
    result=run(memory)
    native,reads,calls=copied_K(memory,trace_inputs=True)
    assert result['score']==native
    assert calls
    # Code fetch is not a data read. EVERY nonstack native data operand (object
    # field, vtable dispatch, cast row, global or arithmetic constant) on these
    # COMPLETE copied K/R/callee routes must reach the actual Source ReadSet.
    missing=[]
    for pc,address,size in reads:
        if 0x200000000<=address<0x200010000:continue
        if not any(start<=address and start+count>=address+size for start,count in memory.reads):
            missing.append((hex(pc),hex(address-memory.base),size))
    assert not missing,missing
