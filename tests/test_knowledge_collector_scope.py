"""Private collector acceptance must follow every lifetime callback."""
from _knowledge_stream_fixture import native_stream_transport
import subprocess
from types import ModuleType

import pytest

from fm_live_mcp import knowledge_context_score_source as context
from fm_live_mcp import knowledge_passing_state as state
from fm_live_mcp import knowledge_passing_view as view
from fm_live_mcp import knowledge_relation_mask_source as relation
from fm_live_mcp import knowledge_person_selector as selector
from fm_live_mcp import knowledge_person_ui_caller as ui
from test_knowledge_context_score_source import Memory,SyntheticBridge
from test_knowledge_passing_state import memory as state_memory
from test_knowledge_passing_view import memory as view_memory
from test_knowledge_relation_mask_source import memory as relation_memory
from test_knowledge_person_selector import memory as selector_memory
from test_knowledge_person_ui_caller import memory as ui_memory
from test_knowledge_passing_state import full_subject_contract


def collect(module,m,bridge):
    return module.collect(bridge,'synthetic',subject_person=m.person,
        subject_identity=m.person_ref,coach_name='Private Coach')


def fixture(factory):
    m=factory()
    m.put(m.base+0x56d496e,b'\0')
    full_subject_contract(m)
    return m


@pytest.mark.parametrize('module,factory',[(context,Memory),(state,state_memory),
    (view,view_memory),(relation,relation_memory),(selector,selector_memory),(ui,ui_memory)])
def test_last_lifetime_callback_cannot_change_a_consumed_subject_identity(module,factory):
    first=fixture(factory)
    baseline=SyntheticBridge(first)
    assert collect(module,first,baseline)
    final=baseline.lifetimes
    m=fixture(factory)
    bridge=SyntheticBridge(m)
    def change(count):
        if count==final:
            m.identity(m.person,m.person_ref[0],m.person_ref[1]+1,m.person_ref[2])
    bridge.on_current=change
    with pytest.raises(ValueError,match='changed'):
        collect(module,m,bridge)
    assert bridge._reader is None


def test_frozen_old_scope_accepts_stale_identity_but_new_scope_rejects():
    raw=subprocess.run(['git','show','abc3dac9de95f2570bac9fce9bfc27ed12321fdf:fm_live_mcp/knowledge_passing_view.py'],
        capture_output=True,text=True,check=True,timeout=10).stdout
    old=ModuleType('fm_live_mcp._frozen_passing_scope')
    old.__package__='fm_live_mcp'
    exec(compile(raw,'frozen_abc3_passing_view.py','exec'),old.__dict__)
    first=fixture(view_memory)
    baseline=SyntheticBridge(first)
    collect(old,first,baseline)
    m=fixture(view_memory)
    bridge=SyntheticBridge(m)
    def change(count):
        if count==baseline.lifetimes:
            m.identity(m.person,m.person_ref[0],m.person_ref[1]+1,m.person_ref[2])
    bridge.on_current=change
    result=collect(old,m,bridge)
    assert result['subject_identity']==m.person_ref
    assert int.from_bytes(m.read(m.person+0xc,4),'little')==m.person_ref[1]+1
    # The preceding parametrized control runs this same mutation at the new
    # collector's last callback and requires rejection before any return.
