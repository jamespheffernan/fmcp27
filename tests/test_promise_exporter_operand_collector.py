"""Exporter raw-operand controls only. Never attach to a process."""
import importlib.util
from pathlib import Path
import struct
import pytest

PATH=Path(__file__).resolve().parents[1]/'evidence/social-promises-20261109/collect_promise_exporter_operands.py'
SPEC=importlib.util.spec_from_file_location('social_exporter_operand_collector',PATH)
SOURCE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(SOURCE)

@pytest.fixture
def source_memory():
    base,primary,promise,manager,context,team=0x100000000,0x300000000,0x500000000,0x400000548,0x600000000,0x700000000
    cells={};reads=[]
    def put(address,raw):cells.update({address+i:b for i,b in enumerate(raw)})
    def q(address,value):put(address,struct.pack('<Q',value))
    def read(address,size):
        reads.append((address,size))
        try:return bytes(cells[address+i]for i in range(size))
        except KeyError as error:raise ValueError('Uncaptured source operand')from error
    identity={'native_id':123,'person_index':42}
    owner={'primary':primary,'owner':{'native_identity':identity}}
    entry={'address':promise,'native_kind':1,'native_party_B':{'address':primary+0x388,'native_identity':identity}}
    raw=bytearray(96);struct.pack_into('<I',raw,0,1);struct.pack_into('<QQQQ',raw,0x10,0,manager,primary+0x388,context);struct.pack_into('<h',raw,0x4e,1);put(promise,raw)
    q(primary+0x388,base+SOURCE.players.RVA[2]);put(primary+0x394,struct.pack('<I',123))
    person_table=base+SOURCE.players.RVA[2]
    q(person_table+0x6e0,base+0xd5c610);put(person_table-0x6f0,struct.pack('<q',-0x388))
    q(primary,base+SOURCE.players.RVA[0]);table=base+SOURCE.players.RVA[0]
    put(table-0x20,struct.pack('<q',0x278));q(primary+0x278,base+0x5589a90)
    q(table+0x2e8,base+0xcffffc);q(table+0x300,base+0xcfff70);q(primary+0x2f8,0)
    put(context+0x2f,b'\0');q(context+0x30,team)
    return dict(base=base,primary=primary,promise=promise,manager=manager,context=context,team=team,owner=owner,entry=entry,read=read,put=put,q=q,reads=reads,cells=cells,person_table=person_table,table=table)

def inspect(m):return SOURCE.capture_exporter_operands(m['read'],m['base'],m['owner'],m['entry'],m['manager'])

def test_actual_four_byte_code_getter_and_neutral_unknown_flags(source_memory):
    m=source_memory;result=inspect(m)
    assert result['loan_predicate_getters']=={'0x2e8':'0xcffffc','0x300':'0xcfff70'}
    assert result['original_person_cast_rva']=='0xd5c610'and result['person_cast_displacement']==-0x388
    assert result['native_PMlo']is result['native_PMto']is None
    assert result['lifecycle_evaluated']is result['exporter_executed']is result['game_native_calls']is False
    assert result['extra_contracts_private']==0 and result['context_team_private']==m['team']

@pytest.mark.parametrize('fault',['target','party_A','party_B','kind','row_kind','owner_identity','virtual','person_type','cast','cast_two_aligned','cast_displacement','primary_type','normalized_delta','normalized_type','loan_getter','lifetime','context','missing_cast_operand'])
def test_changed_source_or_owner_refuses_without_flags(source_memory,fault):
    m=source_memory
    if fault=='target':m['q'](m['promise']+0x10,0x800000000)
    elif fault=='party_A':m['q'](m['promise']+0x18,0x800000000)
    elif fault=='party_B':m['q'](m['promise']+0x20,0x800000000)
    elif fault=='kind':m['put'](m['promise']+0x4e,struct.pack('<h',2))
    elif fault=='row_kind':m['entry']['native_kind']=2
    elif fault=='owner_identity':m['entry']['native_party_B']['native_identity']={'native_id':999}
    elif fault=='virtual':m['put'](m['primary']+0x394,b'\xff'*4)
    elif fault=='person_type':m['q'](m['primary']+0x388,m['base']+0x55ad820)
    elif fault=='cast':m['q'](m['person_table']+0x6e0,m['base']+0xd5c5fc)
    elif fault=='cast_two_aligned':m['q'](m['person_table']+0x6e0,m['base']+0xd5c612)
    elif fault=='cast_displacement':m['put'](m['person_table']-0x6f0,struct.pack('<q',-0x548))
    elif fault=='primary_type':m['q'](m['primary'],m['base']+0x55ad2d8)
    elif fault=='normalized_delta':m['put'](m['table']-0x20,struct.pack('<q',0))
    elif fault=='normalized_type':m['q'](m['primary']+0x278,m['base']+0x5589a98)
    elif fault=='loan_getter':m['q'](m['table']+0x2e8,m['base']+0xcfff70)
    elif fault=='lifetime':m['put'](m['promise'],b'\0'*4)
    elif fault=='context':m['q'](m['promise']+0x28,0)
    else:del m['cells'][m['person_table']-0x6f0]
    with pytest.raises(ValueError):inspect(m)

def test_nonzero_extra_contract_pointer_is_retained_without_inferred_flag(source_memory):
    m=source_memory;m['q'](m['primary']+0x2f8,0x800000000)
    result=inspect(m)
    assert result['extra_contracts_private']==0x800000000 and result['native_PMlo']is None

def test_native_virtual_context_does_not_consume_unused_team_operand(source_memory):
    m=source_memory;m['put'](m['context']+0x2f,b'\x01')
    for i in range(8):del m['cells'][m['context']+0x30+i]
    result=inspect(m)
    assert result['context_virtual_byte']==1 and result['context_team_private']is None
    assert(m['context']+0x30,8)not in m['reads']

def test_source_pins_embed_uncommitted_collector_without_relabeling_frozen_head():
    import _pinned_build
    _pinned_build.require_steam_language_template()
    pin=SOURCE.pins();literal=pin['additional_evidence_sources'][PATH.name]
    assert literal['utf8']==PATH.read_text()and literal['sha256']==pin['collector_sha256']
    assert len(pin['head'])==40 and int(pin['head'],16)>0

@pytest.mark.parametrize('raises',[False,True])
def test_stream_exit_closes_without_post_fence_process_callback(monkeypatch,raises):
    from types import SimpleNamespace
    calls=[]
    class Reader:
        def __init__(self,helper,pid):calls.append(('open',helper,pid))
        def close(self):calls.append(('close',))
    bridge=SimpleNamespace(_reader=None,helper='unused')
    bridge._current=lambda sid:calls.append(('current',sid))or SimpleNamespace(pid=42)
    monkeypatch.setattr(SOURCE,'ReadStream',Reader)
    def body():
        with SOURCE.collection_stream(bridge,'synthetic-session'):
            assert bridge._reader is not None
            calls.append(('final-fence',))
            if raises:raise RuntimeError('synthetic interruption')
    if raises:
        with pytest.raises(RuntimeError):body()
    else:body()
    assert calls==[('current','synthetic-session'),('open','unused',42),('final-fence',),('close',)]
    assert bridge._reader is None

@pytest.mark.parametrize('unsupported_first',[False,True])
def test_unsupported_roster_companion_preserves_actual_kind1_candidate(unsupported_first):
    actual={'state':'captured_native_vector','promises':[{'native_kind':7},{'native_kind':1}]}
    companion={'state':'unsupported_primary_kind','primary':0x800000000}
    rows=[companion,actual]if unsupported_first else[actual,companion]
    assert SOURCE.first_kind1_candidate(rows)==(actual,actual['promises'][1])

@pytest.mark.parametrize('rows',[
    [{'state':'unsupported_primary_kind'}],
    [{'state':'captured_native_vector','promises':[{'native_kind':7}]}, {'state':'unsupported_primary_kind'}],
    [{'state':'captured_native_vector'}],
    [{'state':'unsupported_primary_kind','promises':[{'native_kind':1}]}],
    [{'state':'unknown_owner_state','promises':[]}],
])
def test_absent_candidate_or_malformed_owner_rows_refuse(rows):
    with pytest.raises(ValueError):SOURCE.first_kind1_candidate(rows)

def test_unsupported_companion_schema_runs_actual_recorded_verifier_chain(monkeypatch):
    import gzip,json
    from copy import deepcopy
    h=PATH.parent
    monkeypatch.syspath_prepend(str(h))
    import verify_recorded_definitions as definitions
    import verify_recorded_inventory as inventory
    import verify_recorded_status as status
    fixture=Path(__file__).resolve().parent/'fixtures/promise_status_original_7e85cb7.json.gz'
    packet=json.loads(gzip.decompress(fixture.read_bytes()))
    journal=inventory.Journal(packet)
    # Synthetic branch control: keep the genuine selected promise and native
    # predicate source intact; change an unrelated empty owner slot's primary
    # type and transport state to the unsupported branch. This is no live result.
    index=next(i for i,row in enumerate(packet['players'])if not row['promises'])
    former=packet['players'][index];base=int(packet['plugin_base_private'],16)
    packet['players'][index]={'roster_slot':former['roster_slot'],'primary':former['primary'],
        'state':'unsupported_primary_kind','primary_vtable_rva':0x5588ef0,'promises':[]}
    for offset,value in enumerate(struct.pack('<Q',base+0x5588ef0)):journal.cells[former['primary']+offset]=value
    old=deepcopy(packet);del old['players'][index]['promises']
    with pytest.raises(KeyError,match='promises'):definitions.verify(old,journal)
    with pytest.raises(KeyError,match='promises'):status.replay(old,journal)
    checked=definitions.verify(packet,journal)
    assert checked['inventory']['promises']==packet['native_promise_entries']==22
    replay=status.replay(packet,journal)
    assert replay['state']=='complete_original_status_predicate_return'and replay['native_return']==6
