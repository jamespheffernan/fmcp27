"""Observed native TEAM-settings subtype and full native zero-path controls.
Synthetic objects below are explicit; no current-career or combined wage total
is established by them. Native code is original pinned disk code in owned RAM.
"""
from pathlib import Path
import importlib.util,struct,sys
from dataclasses import replace
import pytest
from fm_live_mcp import committed_wage_owner_source as core
from test_committed_wage_owner_source import Fixture,NATIVE,SELECTOR_NATIVE,BASE,pack
E=Path(__file__).parent
spec=importlib.util.spec_from_file_location('history_native_oracle',E/'_committed_wage_owner_native.py');oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)


def history_object(f):
    address=f.alloc();table=BASE+0x55e6488;info=BASE+0x55e6510;parent=BASE+0x55e55b0
    f.put(address,pack(table));f.put(table-16,struct.pack('<qQ',0,info));f.put(info+8,pack(BASE+0x53b560f));f.put(info+16,pack(parent));f.put(BASE+0x53b560f,b'26TEAM_SETTINGS_EDIT_SESSION\0');f.put(parent+8,pack(BASE+0x53b51b9));f.put(parent+16,pack(BASE+0x55a44f0));f.put(BASE+0x53b51b9,b'N2db25EDIT_SESSION_WITH_HISTORYI19TEAM_SETTINGS_STATEEE\0');f.put(table+16,pack(BASE+0x22d3820));f.put(BASE+0x22d3820,bytes.fromhex('e0028052c0035fd6'))
    return address


def image():return oracle.Image()


def test_disk_native_history_chain_and_literal23_are_exact():
    im=image()
    def ptr(a):return int.from_bytes(im.read(a,8),'little')&((1<<36)-1)
    assert ptr(0x55e6488-8)==0x55e6510 and ptr(0x55e6510+16)==0x55e55b0 and ptr(0x55e55b0+16)==0x55a44f0
    assert ptr(0x55e6510+8)==0x53b560f and im.read(0x53b560f,29)==b'26TEAM_SETTINGS_EDIT_SESSION\0'
    text=b'N2db25EDIT_SESSION_WITH_HISTORYI19TEAM_SETTINGS_STATEEE\0';assert ptr(0x55e55b0+8)==0x53b51b9 and im.read(0x53b51b9,len(text))==text
    assert ptr(0x55e6488+16)==0x22d3820 and im.bounds[0x22d3820]==0x22d3828 and im.read(0x22d3820,8)==bytes.fromhex('e0028052c0035fd6')


@pytest.mark.parametrize('offset',(0x218,0x200))
def test_history23_and_aliases_match_complete_native_v138_zero(offset):
    f=Fixture();a=history_object(f);f.vector(f.human+offset,[a,0,a]);result=f.observe();assert result.state=='native_zero' and result.complete_v138_branch and result.native_return==result.out_amount==0
    queue=result.queue218 if offset==0x218 else result.queue200;assert [e.native_kind for e in queue.entries]==[23,None,23] and queue.kind40==()
    im=image();machine=oracle.Machine(f,NATIVE|SELECTOR_NATIVE|{0x22d3820:im.read(0x22d3820,8)},im);got=machine.run(f);assert got['completed'] and got['return_value']==got['out_amount']==0


def test_old_code_refused_the_same_valid_native_subtype():
    spec=importlib.util.spec_from_file_location('fm_live_mcp.owner_before_history',E/'fixtures/committed-wage-owner-before-history.py');old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
    f=Fixture();f.vector(f.human+0x200,[history_object(f)]);c=f.context;o=old.Context(c.process_id,c.save_identity,c.session_identity,c.plugin_sha256,c.native_date,old.CanonicalRef(c.club.address,c.club.index,c.club.native_id,c.club.secondary));before=old.observe(f,BASE,o,lifetime=lambda:o);after=f.observe()
    assert before.state=='unavailable' and before.reason=='unproved_queue_edit_session_ancestry' and before.out_amount is None
    assert after.state=='native_zero' and after.complete_v138_branch


@pytest.mark.parametrize('target',(0x55e6488-8,0x55e6510+8,0x55e6510+16,0x55e55b0+8,0x55e55b0+16,0x55e6488+16,0x53b560f,0x53b51b9,0x22d3820))
def test_every_newly_bound_history_source_rejects_changed_bytes(target):
    f=Fixture();f.vector(f.human+0x200,[history_object(f)]);f.put(BASE+target,bytes([f(BASE+target,1)[0]^8]))
    with pytest.raises((ValueError,core.UnsupportedSource)):f.observe()


def test_known_history_getter_cannot_drift_to40_or_bypass_its_parent():
    for at,raw in [(0x22d3820,bytes.fromhex('00058052c0035fd6')),(0x55e6510+16,pack(BASE+0x55a44f0))]:
        f=Fixture();f.vector(f.human+0x200,[history_object(f)]);f.put(BASE+at,raw)
        with pytest.raises(ValueError,match='History-backed'):f.observe()


def test_history_subtype_does_not_hide_an_actual_kind40_queue():
    f=Fixture();a=history_object(f);b=f.queue_object(40);f.vector(f.human+0x200,[a,b,a]);result=f.observe();assert result.state=='unavailable' and result.reason=='nonempty_kind40_monetary_helper_unimplemented' and result.queue200.kind40==(b,) and result.out_amount is None and not result.complete_v138_branch


def test_history_parent_changed_by_final_callback_refuses():
    f=Fixture();f.vector(f.human+0x200,[history_object(f)]);calls=0
    def life():
        nonlocal calls
        calls+=1
        if calls==2:f.put(BASE+0x55e55b0+16,pack(BASE+0x55e55b0))
        return f.context
    with pytest.raises(ValueError,match='Game state changed'):f.observe(lifetime=life)
