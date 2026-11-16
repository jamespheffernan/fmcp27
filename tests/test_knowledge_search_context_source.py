"""Original context slice and complete reached getters in owned RAM only."""
from _knowledge_stream_fixture import native_stream_transport
import hashlib
import struct

import pytest
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE,UC_HOOK_MEM_INVALID
import unicorn.arm64_const as regs
from _unicorn_pages import map_pages,page_images

from fm_live_mcp import knowledge_search_context_source as source
from test_knowledge_context_score_source import Memory
from test_knowledge_search_preliminary_source import restore_metadata,identity


@pytest.fixture
def memory():
    m=Memory()
    for rva,n,digest in source.NATIVE_GUARDS:
        raw=m.disk(rva,n);assert hashlib.sha256(raw).hexdigest()==digest;m.put(m.base+rva,raw)
    m.q(m.base+0x55ad820+0x408,m.base+0xc8cf20)
    m.put(m.base+0x55ad820-0x418,struct.pack('<q',-0x548))
    m.q(m.base+0x55acb30+0x438,m.base+0x12ffe58)
    m.put(m.base+0x55acb30-0x450,struct.pack('<q',-0x438))
    m.secondary_holder=m.allocate(32)
    m.secondary_contract=m.contract('full_contract',m.human_person,m.national)
    m.q(m.human_common+0x80,m.secondary_holder);m.q(m.secondary_holder+0x10,m.secondary_contract)
    m.put(m.base+0x56d4993,b'\1');m.put(m.container+0xb9,b'\0');m.put(m.club+0xb9,b'\0')
    m.alternate=m.typed('national_team_container',0x600);m.identity(m.alternate,1,6001,6002)
    m.database('national_team_containers',[m.container,m.alternate]);m.q(m.nation+0x118,m.alternate)
    restore_metadata(m)
    return m


def evaluate(m,**kwargs):
    return source.evaluate(m.read,m.base,m.human,identity(m,m.human_person),
                           check_current=kwargs.pop('check_current',lambda:('process','save','build')),**kwargs)


def native(m):
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM);known=set(m.cells)
    stack=0x200000000;stop=m.base+0x208b400
    images=page_images(m.cells)  # the same bytes for the same pages (known is set(m.cells) here)
    map_pages(uc,set(images)|set(range(stack,stack+0x10000,4096)))
    for page in images:uc.mem_write(page,images[page])
    reads=[];instructions=[];writes=[]
    def code(machine,at,n,user):
        if at==stop:machine.emu_stop();return
        assert any(m.base+r<=at and at+n<=m.base+r+size for r,size,_ in source.NATIVE_GUARDS)
        assert all(p in known for p in range(at,at+n))
        instructions.append(at-m.base)
    def read(machine,access,at,n,value,user):
        assert all(p in known for p in range(at,at+n)),('missing original native operand',hex(at),n)
        if not stack<=at<stack+0x10000:reads.append((at,n))
    def write(machine,access,at,n,value,user):
        assert stack<=at and at+n<=stack+0x10000
        known.update(range(at,at+n));writes.append((at,n))
    def invalid(machine,access,at,n,value,user):raise AssertionError(('unmapped original native operand',hex(at),n))
    uc.hook_add(UC_HOOK_CODE,code);uc.hook_add(UC_HOOK_MEM_READ,read);uc.hook_add(UC_HOOK_MEM_WRITE,write);uc.hook_add(UC_HOOK_MEM_INVALID,invalid)
    uc.reg_write(regs.UC_ARM64_REG_X22,m.human_person);uc.reg_write(regs.UC_ARM64_REG_SP,stack+0xf000)
    uc.emu_start(m.base+0x208b3a8,stop,count=1000)
    assert uc.reg_read(regs.UC_ARM64_REG_PC)==stop
    return uc.reg_read(regs.UC_ARM64_REG_X20),reads,instructions,writes


def test_existing_secondary_contract_matches_original_context_and_both_getters(memory):
    m=memory;actual=evaluate(m);expected,reads,instructions,writes=native(m)
    assert actual['context']==expected==m.container
    assert actual['context_identity']==identity(m,m.container)
    assert {0x208b3a8,0xc8cf20,0x12ffe58}<=set(instructions)
    assert (m.secondary_contract+0x10,8)in reads and writes
    assert set(actual)=={'scope','context','context_identity','complete_search_population_evaluated','field_visibility_evaluated','non_atomic'}


def test_every_mode_byte_preserves_only_one_enabled_and_does_not_substitute_primary_club(memory):
    m=memory
    for raw in range(256):
        m.put(m.base+0x56d4993,bytes([raw]))
        assert evaluate(m)['context']==native(m)[0]==(m.container if raw==1 else 0)


@pytest.mark.parametrize('national',[False,True])
def test_all_owner_discriminator_bytes_use_nonzero_not_low_bit(memory,national):
    m=memory;team=m.national if national else m.team;owner=m.container if national else m.club
    m.q(m.secondary_contract+0x10,team)
    for raw in range(256):
        m.put(owner+0xb9,bytes([raw]))
        assert evaluate(m)['context']==native(m)[0]==(m.alternate if raw else m.container)


@pytest.mark.parametrize('target',['holder','contract','team','owner','nation','projection'])
def test_null_native_sources_remain_null_without_projection_fallback(memory,target):
    m=memory
    address={'holder':m.human_common+0x80,'contract':m.secondary_holder+0x10,
             'team':m.secondary_contract+0x10,'owner':m.national+0x30,
             'nation':m.container+0x170,'projection':m.nation+0x118}[target]
    if target=='projection':m.put(m.container+0xb9,b'\2')
    m.q(address,0)
    actual=evaluate(m)
    assert actual['context']==native(m)[0]==0 and actual['context_identity']is None


@pytest.mark.parametrize('fault',['owner','contract_owner','team_backlink','nation_type','context_type','source','person_route','data_route','adjustment','callback'])
def test_unproved_or_changed_source_is_unavailable(memory,fault):
    m=memory
    if fault=='owner':m.identity(m.human_person,1,9999,9998)
    if fault=='contract_owner':m.q(m.secondary_contract+8,m.person)
    if fault=='team_backlink':m.vec(m.container+0x18,[])
    if fault=='nation_type':m.q(m.nation,0)
    if fault=='context_type':m.q(m.container,0)
    if fault=='source':m.put(m.base+0x208b3a8,b'\0')
    if fault=='person_route':m.q(m.base+0x55ad820+0x408,m.base+0xc8cf20+4)
    if fault=='data_route':m.q(m.base+0x55acb30+0x438,m.base+0x12ffe58+4)
    if fault=='adjustment':m.put(m.base+0x55acb30-0x450,struct.pack('<q',-0x440))
    kwargs={}
    if fault=='callback':kwargs['check_current']=None
    owner_identity=(1,2001,2002)
    with pytest.raises(ValueError):source.evaluate(m.read,m.base,m.human,owner_identity,check_current=kwargs.get('check_current',lambda:('process','save','build')))


def test_final_lifetime_callback_cannot_change_a_consumed_selector(memory):
    m=memory;calls=[]
    def lifetime():
        calls.append(1)
        if len(calls)==2:m.put(m.base+0x56d4993,b'\0')
        return ('process','save','build')
    with pytest.raises(ValueError,match='changed'):evaluate(m,check_current=lifetime)


def test_missing_reached_native_operand_is_not_filled_from_disk(memory):
    m=memory;del m.cells[m.secondary_contract+0x10]
    with pytest.raises((AssertionError,KeyError)):native(m)
