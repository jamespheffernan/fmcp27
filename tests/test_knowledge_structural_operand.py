"""Finite ownership/visit/byte controls for the collector-local LSE closure."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from fm_live_mcp import knowledge_structural_operand as operand


def fixture():
    base=0x10000000;manager=0x9000;offer=0x5000;other=0x6000;common=0x2000;person_address=0x2388
    identity=(4,50,60);club_identity=(8,80,90);calls=[];failures=[]
    cells={offer+8:b'\x02\0\0\0'}
    def read(a,n):
        calls.append((a,n));return cells[a]
    person=SimpleNamespace(person=SimpleNamespace(address=person_address,identity=identity))
    club=SimpleNamespace(address=0x8000,identity=club_identity)
    class Reader:
        def __init__(self,read,base):self.read=read
        def person(self,address):assert address==person_address;return 0x1000,common,None,identity
        def club(self,address):assert address==club.address;return club_identity
        def ptr(self,address):return {common+0x68:0x3000,base+0x56a67f0:manager+0x18,offer:base+0x1000,other:base+0x1000}[address]
        def bounds(self,address,width,limit):assert address==0x3000;return 0x4000,1
        def pointers(self,address,limit):assert address==manager+0x20;return [offer,other]
        def u8(self,address):assert address==offer+0x8d;return 19
        def predicate(self,address,owner):self.u8(offer+0x8d);return True,'first_offer_vector',0
    transfer=SimpleNamespace(_Reader=Reader,VECTOR_LIMIT=100000,verify_native=lambda *args:None)
    offers=SimpleNamespace(_manager=lambda *args:manager,CLASSES={0x1000:None},_type=lambda *args:'loan')
    journal=SimpleNamespace(poison=lambda error:failures.append(str(error)))
    source=SimpleNamespace(read=read,base=base)
    return source,person,club,transfer,offers,journal,calls,failures,cells


def test_only_visited_typed_owned_offer_adds_exact_four_bytes():
    source,person,club,transfer,offers,journal,calls,failures,cells=fixture();receipts={}
    result=operand.collect(source,person,club,True,transfer,offers,journal,receipts)
    assert calls==[(0x5008,4)] and len(receipts)==1 and not failures
    receipt=next(iter(receipts.values()))
    assert receipt['address']=='0x5008' and receipt['size']==4 and receipt['runtime_kind']=='loan'
    assert receipt['manager_first_vector_slots']==[0]
    assert result['offer_index_ordinal']==0 and 0x6000 not in result['visited']
    assert receipt['native_or_game_write_performed']is False


def test_unknown_family_never_refills_counter():
    source,person,club,transfer,offers,journal,calls,*rest=fixture();receipts={}
    offers.CLASSES={}
    result=operand.collect(source,person,club,True,transfer,offers,journal,receipts)
    assert calls==[] and receipts=={}
    assert result['visited'][0x5000]['state']=='unsupported_offer_family_no_operand_read'


def test_manager_ownership_mismatch_is_fatal_before_counter_read():
    source,person,club,transfer,offers,journal,calls,*rest=fixture()
    offers._manager=lambda *args:0xa000
    with pytest.raises(ValueError,match='BASE manager ownership'):
        operand.collect(source,person,club,True,transfer,offers,journal,{})
    assert calls==[]


def test_type_guard_failure_is_not_an_operand_permission():
    source,person,club,transfer,offers,journal,calls,*rest=fixture()
    def bad(*args):raise ValueError('RTTI changed')
    offers._type=bad
    with pytest.raises(ValueError,match='RTTI changed'):
        operand.collect(source,person,club,True,transfer,offers,journal,{})
    assert calls==[]


def test_changed_counter_and_budget_overrun_poison_capture(monkeypatch):
    source,person,club,transfer,offers,journal,calls,failures,cells=fixture();receipts={}
    operand.collect(source,person,club,True,transfer,offers,journal,receipts)
    cells[0x5008]=b'\x03\0\0\0'
    with pytest.raises(ValueError,match='ownership or bytes changed'):
        operand.collect(source,person,club,True,transfer,offers,journal,receipts)
    assert failures
    monkeypatch.setattr(operand,'MAX_CELLS',0)
    with pytest.raises(ValueError,match='cell budget'):
        operand.collect(source,person,club,True,transfer,offers,journal,{})
    assert len(failures)==2


def test_shadow_predicate_may_not_change_original_result():
    source,person,club,transfer,offers,journal,*rest=fixture()
    with pytest.raises(ValueError,match='changed the pinned predicate result'):
        operand.collect(source,person,club,False,transfer,offers,journal,{})


def test_extension_error_poison_prevents_unavailable_conversion(monkeypatch):
    failures=[];journal=SimpleNamespace(poison=lambda error:failures.append(str(error)),healthy=lambda:None)
    class Observed:
        def _operand(self,name,*args):return True
        def lifetime(self):return ('same',)
    def fail(*args):raise ValueError('structural type mismatch')
    monkeypatch.setattr(operand,'collect',fail)
    Derived=operand.source_type(Observed,None,None,journal,{})
    bound=Derived();bound.subject='subject';bound.owner_club='owner'
    with pytest.raises(ValueError,match='structural type mismatch'):
        bound._operand('transfer_predicate','subject','owner')
    assert failures==['structural type mismatch']


def test_other_context_dependencies_are_not_intercepted(monkeypatch):
    class Observed:
        def _operand(self,name,*args):return 42
    monkeypatch.setattr(operand,'collect',lambda *args:pytest.fail('Unrelated source interception'))
    Derived=operand.source_type(Observed,None,None,None,{})
    assert Derived()._operand('primary2e8')==42
