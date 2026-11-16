"""Original ordinary base branch and complete reached predicates in owned RAM.

The caller stack/register frame is explicit. This executes BB60..C164 from
the original function, not allocation/materialization or the entire refresh.
"""
from _knowledge_stream_fixture import native_stream_transport
import hashlib
import struct

import pytest
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_INVALID
import unicorn.arm64_const as regs
from _unicorn_pages import map_pages,page_images,page_set

from fm_live_mcp import knowledge_search_base_admission as source
from fm_live_mcp import knowledge_search_context_source as context
from fm_live_mcp import knowledge_club_admission_source as club
from fm_live_mcp import knowledge_club_score_source as score
from fm_live_mcp import knowledge_search_population_source as population
from fm_live_mcp import knowledge_search_retained_union as union
from fm_live_mcp import world
from fm_live_mcp import knowledge_search_fow_source as fow
from fm_live_mcp import knowledge_search_preliminary_source as preliminary
from fm_live_mcp import knowledge_search_association_source as association
from test_knowledge_club_admission_source import memory_fixture as club_fixture, ordinary, foreign, full
from test_knowledge_search_preliminary_source import restore_metadata
import _knowledge_state_native as inherited


def memory_fixture(combined=False):
    m = club_fixture(combined)
    for rva, size, digest in source.NATIVE_GUARDS+context.NATIVE_GUARDS:
        raw = m.disk(rva, size)
        assert hashlib.sha256(raw).hexdigest() == digest
        m.put(m.base+rva, raw)
    m.q(m.base+0x55ad820+0x408, m.base+0xc8cf20)
    m.put(m.base+0x55ad820-0x418, struct.pack('<q', -0x548))
    m.q(m.base+0x55acb30+0x438, m.base+0x12ffe58)
    m.put(m.base+0x55acb30-0x450, struct.pack('<q', -0x438))
    m.listing = m.allocate(0x110)
    m.put(m.listing+0x4c, b'\1')
    m.candidate = m.allocate(8)
    m.q(m.candidate, m.primary)
    m.caller_club, m.caller_context = m.club, 0
    m.q(m.base+0x558a780+0x6d0,m.base+0xca4a50)
    m.q(m.base+0x55908e0+0x6d0,m.base+0xca4e8c)
    m.put(m.base+0x55908e0-0x6e0,struct.pack('<q',-0x208))
    restore_metadata(m)
    return m


def frame(m, show_all=False):
    return source.Frame(m.read, m.base, m.human, show_all=show_all)



def write_known_pages(uc,cells,known,stack):
    """Map the pages of `known` and the stack and write each known page's bytes from `cells`
    (absent cells read as 0), as one mapping per run of adjacent pages and with page images
    reused from the previous call where the cells are unchanged."""
    pages=page_set(known);images=page_images(cells)
    map_pages(uc,pages|set(range(stack,stack+0x10000,4096)))
    for page in pages:uc.mem_write(page,images.get(page,bytes(4096)))

def native(m):
    # Only the captured original branch and original callees execute. Output
    # capacity is owned data; no callee result or program result is stubbed.
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    uc.ctl_set_cpu_model(regs.UC_CPU_ARM64_MAX)
    known = set(m.cells)
    stack, sp = 0x200000000, 0x20000f000
    output = m.allocate(8)
    known.update(range(output, output+8))
    for offset, value in ((0x10,m.caller_context),(0x18,m.caller_club),(0x20,m.human),
                          (0x28,m.team),(0x30,output+8),(0x38,m.listing)):
        m.put(sp+offset, struct.pack('<Q',value))
        known.update(range(sp+offset,sp+offset+8))
    write_known_pages(uc,m.cells,known,stack)
    guards = (inherited.core.NATIVE_GUARDS+inherited.source.EXTRA_GUARDS+
        inherited.transfer.NATIVE_GUARDS+inherited.state.NATIVE_GUARDS+
        source.NATIVE_GUARDS+context.NATIVE_GUARDS+club.NATIVE_GUARDS+score.NATIVE_GUARDS+
        fow.NATIVE_GUARDS+preliminary.NATIVE_GUARDS+association.NATIVE_GUARDS)
    spans = [(m.base+r,m.base+r+n) for r,n,_ in guards]
    spans += [(m.base+r,m.base+r+len(raw)) for r,raw in inherited.source.aggregate.NATIVE_SPANS]
    reads, writes, trace = [], [], []
    stop = m.base+0x208c164
    def code(machine,at,size,user):
        if at==stop:
            machine.emu_stop()
            return
        assert any(a<=at<at+size<=b for a,b in spans), ('uncaptured native code',hex(at-m.base))
        assert all(p in known for p in range(at,at+size))
        trace.append(at-m.base)
    def read(machine,access,at,size,value,user):
        assert all(p in known for p in range(at,at+size)), ('missing native operand',hex(at),size,hex(machine.reg_read(regs.UC_ARM64_REG_PC)-m.base))
        if not stack<=at<stack+0x10000:
            reads.append((at,size))
    def write(machine,access,at,size,value,user):
        assert stack<=at<at+size<=stack+0x10000 or output<=at<at+size<=output+8
        known.update(range(at,at+size))
        writes.append((at,size))
    def invalid(machine,access,at,size,value,user):
        raise AssertionError(('unmapped native operand',hex(at),size,hex(machine.reg_read(regs.UC_ARM64_REG_PC)-m.base)))
    uc.hook_add(UC_HOOK_CODE,code)
    uc.hook_add(UC_HOOK_MEM_READ,read)
    uc.hook_add(UC_HOOK_MEM_WRITE,write)
    uc.hook_add(UC_HOOK_MEM_INVALID,invalid)
    uc.reg_write(regs.UC_ARM64_REG_SP,sp)
    for register,value in ((regs.UC_ARM64_REG_X24,m.candidate),
                           (regs.UC_ARM64_REG_X23,m.candidate+8),
                           (regs.UC_ARM64_REG_X22,output),(regs.UC_ARM64_REG_X28,output)):
        uc.reg_write(register,value)
    uc.emu_start(m.base+0x208bb60,stop,count=100000)
    assert uc.reg_read(regs.UC_ARM64_REG_PC)==stop
    admitted = uc.reg_read(regs.UC_ARM64_REG_X28)==output+8
    if admitted:
        assert int.from_bytes(uc.mem_read(output,8),'little')==m.person
    return admitted, trace, reads


def native_retained(m,entry,index,seen):
    """Original C504..C570 admission + complete1693ADC; stop before copy."""
    slots=m.allocate(8)
    m.q(slots,entry)
    words=m.allocate(16)
    if seen:
        m.q(words+(index//64)*8,1<<(index%64))
    m.q(m.base+0x5733298,words)
    stack,sp=0x200000000,0x20000f000
    m.q(sp+0x18,128)
    m.q(sp+0x28,m.team)
    known=set(m.cells)
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    write_known_pages(uc,m.cells,known,stack)
    guards=source.NATIVE_GUARDS+club.NATIVE_GUARDS
    trace=[]
    stops={m.base+0x208c570:True,m.base+0x208c684:False}
    def code(machine,at,size,user):
        if at in stops:
            machine.emu_stop()
            return
        assert any(m.base+r<=at<at+size<=m.base+r+n for r,n,_ in guards)
        assert all(p in known for p in range(at,at+size))
        trace.append(at-m.base)
    def read(machine,access,at,size,value,user):
        assert all(p in known for p in range(at,at+size)),('missing native union operand',hex(at),size)
    def write(machine,access,at,size,value,user):
        assert stack<=at<at+size<=stack+0x10000
        known.update(range(at,at+size))
    def invalid(machine,access,at,size,value,user):
        raise AssertionError(('unmapped native union operand',hex(at),size))
    uc.hook_add(UC_HOOK_CODE,code)
    uc.hook_add(UC_HOOK_MEM_READ,read)
    uc.hook_add(UC_HOOK_MEM_WRITE,write)
    uc.hook_add(UC_HOOK_MEM_INVALID,invalid)
    uc.reg_write(regs.UC_ARM64_REG_SP,sp)
    uc.reg_write(regs.UC_ARM64_REG_X25,m.human)
    uc.reg_write(regs.UC_ARM64_REG_X26,0)
    uc.reg_write(regs.UC_ARM64_REG_X8,slots)
    uc.emu_start(m.base+0x208c504,m.base+0x208c684,count=100000)
    assert uc.reg_read(regs.UC_ARM64_REG_PC) in stops
    return stops[uc.reg_read(regs.UC_ARM64_REG_PC)],trace


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('scenario',['show_all','club_shortcut','foreign_reject','full_same_club','stored_without_main','no_owner_club'])
def test_native_base_branch_preserves_real_shortcut_order(combined,scenario):
    m = memory_fixture(combined)
    ordinary(m)
    show_all = scenario=='show_all'
    if show_all:
        m.put(m.listing+0x101,b'\1')
    elif scenario=='club_shortcut':
        m.put(m.primary+0x25a,struct.pack('<h',8000))
    elif scenario=='foreign_reject':
        foreign(m)
    elif scenario=='full_same_club':
        full(m)
        row=m.allocate(8)
        m.put(row,struct.pack('<i',0))
        m.vec(m.personal+0xbd8+0x30,[row])
    elif scenario=='stored_without_main':
        m.q(m.common+0x78,0)
        m.q(m.common+0x80,0)
    elif scenario=='no_owner_club':
        m.put(m.owner_contract+0x26,b'\0')
        m.put(m.owner_contract+0xc2,b'\0')
        m.caller_club=0
    actual = frame(m,show_all).admitted(m.person)
    expected,trace,_ = native(m)
    assert actual is expected
    if scenario in ('full_same_club','stored_without_main'):
        assert actual and 0xe58e5c not in trace


def population_fixture(m):
    for rva,raw in population.NATIVE_SPANS:
        assert m.disk(rva,len(raw))==raw
        m.put(m.base+rva,raw)
    # These original HUMAN selector routes are required even in show-all.
    m.q(m.base+0x55ad820+0x230,m.base+0xca4744)
    m.put(m.base+world.TYPES['manager'][0]-0x20,struct.pack('<qq',0x548,0x438))
    m.vec(m.human+0x248,[m.listing])
    m.q(m.listing+0xd0,m.human)
    m.put(m.human+0x42b,b'\0')
    m.put(m.human+0x41f,b'\1')
    for name in population.BASE_VECTORS:
        m.vec(m.base+population.BASE_VECTORS[name],[m.primary])
    for table,offset in ((0x558a780,0x388),(0x55908e0,0x480)):
        m.q(m.base+table+0x6e0,m.base+0xd5c610)
        m.put(m.base+table-0x6f0,struct.pack('<q',-offset))
    restore_metadata(m)
    return world.loaded(m.read,m.base)[0]['coaches'][0]


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('show_all',[False,True])
def test_private_ordinal_page_composes_admission_without_exposing_fields(combined,show_all):
    m=memory_fixture(combined)
    foreign(m)
    m.put(m.listing+0x101,bytes([show_all]))
    coach=population_fixture(m)
    result=population.observe(m.read,m.base,coach,check_current=lambda:('fixture',),apply_native_admission=True)
    assert result['native_base_admission_evaluated'] is True
    assert result['subjects'][0]['native_admitted'] is show_all
    assert result['complete_search_population'] is False
    assert result['manager_knowledge_verified'] is False


def test_retained_discard_consumes_original_alternate_pair_without_third_word():
    m=memory_fixture()
    m.put(m.base+0x56d34e0,b'\0')
    people=club.Reader(m.read,m.base).table('people')
    m.vec(people['root']+0x68,[m.person])
    m.q(people['root']+0x78,0)
    row=m.allocate(8)
    m.put(row,struct.pack('<i',0))
    m.vec(m.personal+0xbd8+0x30,[row])
    m.blocked.append((people['root']+0x78,people['root']+0x80))
    found=union._discarded_people(m.read,m.base,m.human,people)
    result,_,reads,_,_=inherited.execute(m,0x1693adc,[m.personal+0xbd8,m.person],extra=club.NATIVE_GUARDS)
    assert found=={m.person} and result==row
    assert not any(at<people['root']+0x80 and at+n>people['root']+0x78 for at,n in reads)


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('status,want',[(0,True),(0x52,False)])
def test_club_rejection_then_complete_original_fow_branch(combined,status,want):
    from test_knowledge_search_preliminary_source import memory as prepare_preliminary
    m=memory_fixture(combined)
    ordinary(m)
    for rva,size,digest in fow.NATIVE_GUARDS+preliminary.NATIVE_GUARDS+association.NATIVE_GUARDS:
        raw=m.disk(rva,size)
        assert hashlib.sha256(raw).hexdigest()==digest
        m.put(m.base+rva,raw)
    table=int.from_bytes(m.read(m.person,8),'little')
    for negative in (0x300,0x568):
        m.put(table-negative,m.disk(table-m.base-negative,8))
    for slot,target in ((0x2f0,0xcf3c90),(0x558,0xd5c590)):
        m.q(table+slot,m.base+target)
    prepare_preliminary.__wrapped__(m)
    m.service=m.allocate(16)
    m.native_type(m.service,0x55def88)
    m.q(m.base+0x56d2d08,m.service)
    m.q(m.base+0x55def88+0x348,m.base+0x1f9aa0c)
    m.q(m.base+0x55ad820+0x678,m.base+0x1300060)
    m.put(m.base+0x55ad820-0x688,struct.pack('<q',-0x548))
    holder=m.allocate(32)
    contract=m.contract('full_contract',m.human_person,m.national)
    m.q(m.human_common+0x80,holder)
    m.q(holder+0x10,contract)
    m.put(m.base+0x56d4993,b'\1')
    m.caller_context=m.container
    m.put(m.primary+0x266,bytes([status]))
    row=m.allocate(8)
    m.put(row,struct.pack('<i',0))
    m.vec(m.personal+0xbd8+0x30,[row])
    restore_metadata(m)
    bound=frame(m)
    assert bound.club==m.caller_club and bound.context==m.caller_context
    result,trace,_=native(m)
    assert bound.admitted(m.person) is result is want
    assert 0xe58e5c in trace and 0x1f9aa0c in trace and 0x14fb918 in trace


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('show_all',[False,True])
@pytest.mark.parametrize('ordinal',[0,63,64,127])
def test_retained_union_seeds_only_native_admitted_base_rows(combined,show_all,ordinal):
    m=memory_fixture(combined)
    foreign(m)
    m.identity(m.person,ordinal,1001,1002)
    people=[0]*max(2,ordinal+1)
    people[ordinal]=m.person
    people[1]=m.human_person
    m.database('people',people)
    coach=population_fixture(m)
    m.put(m.listing+0x101,bytes([show_all]))
    for rva,raw in union.NATIVE_SPANS:
        assert m.disk(rva,len(raw))==raw
        m.put(m.base+rva,raw)
    retained=m.allocate(0x110)
    m.put(retained+0x4c,b'\3')
    m.q(retained+0xd0,m.human)
    entry=m.allocate(0x38)
    m.q(entry,m.person)
    m.vec(retained+0x80,[entry,entry])
    m.vec(m.human+0x248,[m.listing,retained])
    base=population.observe(m.read,m.base,coach,check_current=lambda:('fixture',),apply_native_admission=True)
    result,next_page=union.observe(m.read,m.base,coach,[base],check_current=lambda:('fixture',))
    expected=['duplicate_base_admitted']*2 if show_all else ['retained_union_addition','duplicate_prior_retained']
    assert [row['state'] for row in result['subjects']]==expected
    assert result['known_base_seed_subjects']==int(show_all)
    assert result['all_union_decisions_resolved'] and next_page is None
    assert not result['complete_search_population'] and not result['manager_knowledge_verified']
    append,trace=native_retained(m,entry,ordinal,seen=show_all)
    assert append is result['subjects'][0]['would_append']
    assert 0x1693adc in trace


@pytest.mark.parametrize('complete',[False,True])
def test_restricted_raw_pointer_presence_does_not_become_admitted_dedup(complete):
    m=memory_fixture()
    foreign(m)
    coach=population_fixture(m)
    for rva,raw in union.NATIVE_SPANS:
        m.put(m.base+rva,raw)
    retained=m.allocate(0x110)
    m.put(retained+0x4c,b'\3')
    m.q(retained+0xd0,m.human)
    entry=m.allocate(0x38)
    m.q(entry,m.person)
    m.vec(retained+0x80,[entry,entry])
    m.vec(m.human+0x248,[m.listing,retained])
    for name in population.BASE_VECTORS:
        m.vec(m.base+population.BASE_VECTORS[name],[m.primary,m.primary])
    frames=[population.observe(m.read,m.base,coach,check_current=lambda:('fixture',),
        source_limit=1,apply_native_admission=True)]
    if complete:
        frames.append(population.observe(m.read,m.base,coach,check_current=lambda:('fixture',),
            source_offset=1,source_limit=1,apply_native_admission=True))
    result,_=union.observe(m.read,m.base,coach,frames,check_current=lambda:('fixture',))
    first='retained_union_addition' if complete else 'base_overlap_unresolved'
    assert [row['state'] for row in result['subjects']]==[first,'duplicate_prior_retained']
    assert result['known_base_seed_subjects']==0
    assert result['all_union_decisions_resolved'] is complete
