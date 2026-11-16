"""Actual independent verifier paths on typed synthetic memory, no live capture."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
from types import SimpleNamespace
import pytest
pytest.importorskip('capstone',reason='Independent ARM64 replay requires pinned Capstone5.0.7')
from fm_live_mcp import world
from test_current_contract_concerns_candidate import (concern_memory,agreed_memory,public_assessment_memory,shortlist_public_memory,
    prepared_tactics_memory,bridge,database_memory,memory,team_memory,world_memory,H,PLUGIN,SOURCE)

@pytest.fixture
def verifier_memory(concern_memory,monkeypatch):
    m=concern_memory;monkeypatch.syspath_prepend(str(H))
    spec=importlib.util.spec_from_file_location('independent_concern_verifier_test',H/'verify_recorded_current_contract_concerns.py')
    verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)
    base=m['base'];actor=m['manager']+0x548
    manager_info=struct.unpack('<Q',m['read'](base+0x55ac480-8,8))[0]
    m['put'](base+0x55ad820-16,struct.pack('<qQ',-0x548,manager_info))
    m['put'](actor,struct.pack('<QIII',base+0x55ad820,1,555,555))
    m['vec'](m['headers']['people'],[m['agreed_person'],actor])
    m['vec'](m['team']+0x38,[m['concern_primary']])
    save,identity=world.loaded(m['read'],base)
    context=dict(save=save,world=json.loads(json.dumps(identity)),coach=save['coaches'][0],roster=[m['concern_primary']])
    history=SOURCE.inspect(m['read'],base,m['concern_primary'],'actual',include_stored_name=True)
    row=dict(roster_slot=0,primary_private=m['concern_primary'],primary_vtable_rva='0x5588ee8',concern_history=history)
    packet=dict(plugin_base_private=hex(base),context_before=context,context_after=deepcopy(context),players=[row],
        selected_manager_person=dict(primary_private=m['manager'],person_private=actor,native_identity=dict(database_index=1,native_id=555,random_id=None),record_kind='human_manager'),
        observed_native_ring_entries=3,available_context_owner_count=1,unavailable_context_owner_count=0,nonempty_native_history_owners=1,
        source_before=dict(evidence_sources={'concern-projection-source-spans.json':dict(utf8=(H/'concern-projection-source-spans.json').read_text())}))
    with PLUGIN.open('rb')as native:
        for rva in(0xcb8000,0x129f000,0x12a0000):native.seek(0x5ed4000+rva);m['put'](base+rva,native.read(4096))
    r=SimpleNamespace(read=m['read'],u64=lambda address:struct.unpack('<Q',m['read'](address,8))[0],i64=lambda address:struct.unpack('<q',m['read'](address,8))[0])
    proofs={}
    def original_read(address,size):
        raw=m['read'](address,size)
        if base<=address<base+verifier.VM.TEXT_END:proofs[(address-base,size)]=hashlib.sha256(raw).hexdigest()
        return raw
    domains=verifier.hard.Domains(verifier.VM,base,'concern-context');domains.ret=base+verifier.VM.RET;verifier.VM.Uc=domains.factory
    result=verifier.VM.execute(domains.native_reader(original_read),base,m['agreed_person'],m['club'])
    assert result['state']=='complete_original_concern_context_return'
    packet['original_context_attempt']=dict(owner=history['owner']['native_identity'],owner_name=history['owner']['display_name'],primary_private=m['concern_primary'],person_private=m['agreed_person'],
        current_team_private=m['team'],current_club_private=m['club'],owned_main_contract_private=m['agreed_contract'],result=json.loads(json.dumps(result)),
        reached_original_spans=[dict(rva=hex(rva),size=size,sha256=digest)for(rva,size),digest in sorted(proofs.items())],complete_named_rule_executed=False,game_native_calls=False,UI_or_fulfilment_evaluated=False)
    return m,verifier,packet,r


def test_actual_graph_context_getter_and_original_ring_fragment(verifier_memory):
    m,verifier,packet,r=verifier_memory
    result=verifier.graph(packet,r)
    assert result['entries']==result['nonnull_records']==3 and result['available']==1
    assert result['first_named_nonnull_record']['name']=='Test Müller'
    native=verifier.context_replay(packet,r,result['contexts'])
    assert native['native_contract_private']==m['agreed_contract']
    filtered=verifier.original_open_filter(r,m['base'],result['contexts'][0])
    assert filtered['raw_rule_result_before_cleanup']==1 and filtered['whole_named_rule_executed']is False


@pytest.mark.parametrize('fault',['wrong_owner','wrong_name','wrong_end_date','wrong_category','foreign_contract_owner','canonical_person_slot'])
def test_actual_independent_graph_rejects_inconsistent_projections(verifier_memory,fault):
    m,verifier,packet,r=verifier_memory;packet=deepcopy(packet);history=packet['players'][0]['concern_history']
    if fault=='wrong_owner':history['owner']['native_identity']['native_id']=555
    elif fault=='wrong_name':history['owner']['display_name']='Unrelated Player'
    elif fault=='wrong_end_date':history['records'][0]['record']['stored_end_date']['value']='2030-11-30'
    elif fault=='wrong_category':history['records'][0]['record']['compiled_reason_category_code']=255
    elif fault=='foreign_contract_owner':m['q'](m['agreed_contract']+8,m['manager']+0x548)
    else:
        start=struct.unpack('<Q',m['read'](m['headers']['people'],8))[0];m['q'](start,m['manager']+0x548)
    with pytest.raises(AssertionError):verifier.graph(packet,r)


@pytest.mark.parametrize('mode',['empty','null'])
def test_original_empty_fragment_avoids_float_conversion(verifier_memory,mode):
    m,verifier,packet,r=verifier_memory
    if mode=='empty':m['put'](m['concern_ring'],b'\0')
    else:m['q'](m['agreed_contract']+0x30,0)
    context=dict(contract=m['agreed_contract'],ring=m['concern_ring']if mode=='empty'else 0,count=0,open_count=0)
    result=verifier.original_open_filter(r,m['base'],context)
    assert result['raw_rule_result_before_cleanup']==2 and result['XML_float_parameter_conversion_executed']is False
