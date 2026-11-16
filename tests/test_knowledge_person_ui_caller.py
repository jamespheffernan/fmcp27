"""Original upstream UI selection and whole Range controls in owned RAM."""
from _knowledge_stream_fixture import native_stream_transport
import hashlib
import struct
import pytest
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
import unicorn.arm64_const as regs
from fm_live_mcp import knowledge_person_ui_caller as ui
from fm_live_mcp import knowledge_retained_person as retained
from test_knowledge_final_relation import memory as inherited_memory
from test_knowledge_passing_state import report,low_K,full_subject_contract
from test_knowledge_context_score_source import SyntheticBridge
from test_knowledge_passing_view import assert_public_shape
from _knowledge_state_native import execute
from _unicorn_pages import map_pages,page_images


def memory():
    m=inherited_memory()
    for rva,n,digest in ui.NATIVE_GUARDS:
        raw=m.disk(rva,n);assert hashlib.sha256(raw).hexdigest()==digest;m.put(m.base+rva,raw)
    return m


def source(m,bridge=None):
    return ui.UiCallerSource(bridge or SyntheticBridge(m),'synthetic',m.person,m.person_ref,'Private Coach',18)


def native_ui_selection(m):
    """Complete original3f9878..3f98b4 slice and reached selectors, no stubs."""
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM);known=set(m.cells);stack=0x200000000
    images=page_images(m.cells)  # same bytes as the per-page bytes(m.cells.get(...)) images
    pages=set(images)|set(range(stack,stack+0x10000,4096))
    map_pages(uc,pages)
    for page in images:uc.mem_write(page,images[page])
    spans=ui.inherited.inherited.view.state.NATIVE_GUARDS+ui.NATIVE_GUARDS
    spans+=ui.inherited.inherited.view.state.inherited.EXTRA_GUARDS
    spans+=ui.inherited.inherited.view.state.inherited.transfer.NATIVE_GUARDS
    spans+=ui.core.NATIVE_GUARDS
    trace=[];reads=[]
    def code(machine,at,n,user):
        if at==m.base+0x3f98b4:machine.emu_stop();return
        assert any(m.base+a<=at<m.base+a+width for a,width,_ in spans),('unbound original code',hex(at-m.base))
        assert all(p in known for p in range(at,at+n));trace.append(at-m.base)
    def read(machine,access,at,n,value,user):
        assert all(p in known for p in range(at,at+n)),('missing original operand',hex(at))
        if not stack<=at<stack+0x10000:reads.append((at,n))
    def write(machine,access,at,n,value,user):
        pc=machine.reg_read(regs.UC_ARM64_REG_PC)-m.base
        ordinary=stack<=at and at+n<=stack+0x10000
        idempotent=pc in (0x12d9f14,0x12da030,0x12da1e0) and n==8 and all(at+i in m.cells for i in range(n)) and value==m.person==int.from_bytes(bytes(m.cells[at+i]for i in range(n)),'little')
        assert ordinary or idempotent,('unexpected owned write',hex(pc),hex(at))
        known.update(range(at,at+n))
    uc.hook_add(UC_HOOK_CODE,code);uc.hook_add(UC_HOOK_MEM_READ,read);uc.hook_add(UC_HOOK_MEM_WRITE,write)
    uc.reg_write(regs.UC_ARM64_REG_X19,m.human);uc.reg_write(regs.UC_ARM64_REG_X22,m.primary)
    uc.reg_write(regs.UC_ARM64_REG_SP,stack+0xf000)
    uc.emu_start(m.base+0x3f9878,m.base+0x3f98b4,count=10000)
    assert uc.reg_read(regs.UC_ARM64_REG_PC)==m.base+0x3f98b4
    return uc.reg_read(regs.UC_ARM64_REG_X21),uc.reg_read(regs.UC_ARM64_REG_X22),reads,trace


@pytest.mark.parametrize('case',['none','club_first','club_null_assessor','alternate_reverse','alternate_range','alternate_negative','alternate_assessor'])
def test_upstream_original_UI_selection_and_whole_Range(case):
    m=memory();low_K(m);expected=0
    if case=='club_first':
        expected=report(m,40,m.human_person);m.vec(m.human+0x110,[expected]);m.vec(m.human+0x128,[report(m,100)])
    elif case=='club_null_assessor':
        m.vec(m.human+0x110,[report(m,100)]);expected=report(m,40);m.vec(m.human+0x128,[expected])
    elif case=='alternate_reverse':
        a=report(m,40);expected=report(m,100);m.vec(m.human+0x128,[a,expected])
    elif case in ('alternate_range','alternate_negative','alternate_assessor'):
        expected=report(m,128 if case=='alternate_negative'else 40,m.human_person if case=='alternate_assessor'else 0);m.vec(m.human+0x128,[expected])
    m.reads.clear();s=source(m);assert (s.ui_report() or 0)==expected;s.verify()
    consumed={p for at,n in m.reads for p in range(at,at+n)}
    row,assessor,reads,trace=native_ui_selection(m)
    assert row==expected and assessor==(int.from_bytes(m.read(row+8,8),'little')if row else 0)
    assert all(p in consumed for at,n in reads for p in range(at,at+n)),[(hex(at),n)for at,n in reads if not all(p in consumed for p in range(at,at+n))]
    assert 0x12d9e40 in trace
    assert (0x12da3d0 in trace)==(case!='club_first')
    m.reads.clear();actual=ui.collect(SyntheticBridge(m),'synthetic',subject_person=m.person,subject_identity=m.person_ref,coach_name='Private Coach');assert_public_shape(actual)
    output=m.allocate(8);_,raw,_,_,_=execute(m,0x2386eac,[m.record,output,m.primary,18,assessor,row,1],score_pointer=output,output_width=3,
        extra=ui.inherited.inherited.NATIVE_GUARDS+ui.inherited.NATIVE_GUARDS+retained.NATIVE_GUARDS+ui.inherited.inherited.view.NATIVE_GUARDS)
    low,high,_=struct.unpack('bbb',raw)
    state=actual['value']['state']
    assert actual['value']==({'state':'unknown'}if low==-1 and high==-1 else {'state':'exact','value':low}if state=='exact'else {'state':'range','minimum':low,'maximum':high})
    assert state==('unknown'if case in('none','alternate_negative')else'exact'if case=='alternate_reverse'else'range')


def test_UI_selects_report_before_own_context_H_early_return():
    m=memory();full_subject_contract(m);m.vec(m.human+0x128,[report(m,100)]);m.blocked=[(m.human+0x128,m.human+0x140)]
    with pytest.raises(ValueError):source(m).permitted()


def test_UI_unknown_never_reads_hidden_attribute_for_all_stored_bytes():
    m=memory();low_K(m);m.blocked=[(m.primary+0x148,m.primary+0x18d)];expected=None
    for raw in range(256):
        m.put(m.primary+0x15e,bytes([raw]));actual=ui.collect(SyntheticBridge(m),'synthetic',subject_person=m.person,subject_identity=m.person_ref,coach_name='Private Coach')
        assert actual['value']=={'state':'unknown'};assert_public_shape(actual)
        if expected is None:expected=actual
        assert actual==expected


def test_UI_report_lifetime_change_rejects():
    m=memory();low_K(m);row=report(m,40);m.vec(m.human+0x128,[row]);b=SyntheticBridge(m);s=source(m,b);assert s.permitted()['state']=='range'
    b.on_current=lambda _:m.put(row+0x3f,b'\x64')
    with pytest.raises(ValueError,match='changed'):s.verify()


def test_UI_code_drift_rejects_before_report_selection():
    m=memory();m.put(m.base+0x3f9878,bytes(4))
    with pytest.raises(ValueError,match='caller changed'):source(m)


@pytest.mark.parametrize('offset',[0x110,0x128])
def test_UI_used_range_does_not_confuse_unused_capacity_with_record_count(offset):
    m=memory();low_K(m);row=report(m,40,m.human_person if offset==0x110 else 0)
    storage=m.allocate(6316*8);m.q(storage,row);m.put(m.human+offset,struct.pack('<QQQ',storage,storage+8,storage+6316*8))
    s=source(m);assert s.ui_report()==row;assert s.permitted()['state']=='range';s.verify()
    native,_,_,_=native_ui_selection(m);assert native==row
