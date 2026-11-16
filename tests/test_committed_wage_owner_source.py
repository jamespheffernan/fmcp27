"""Owned synthetic inputs only. No current or delivered finance claim."""
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys

import pytest

DEPENDENCY = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmcp-committed-wage-spending-20261108')
SELECTOR_SHA = 'e35b2ea4df6e6f4abf0af5b09ac076957510faa1b05a125b29824f540a0faf18'
try:
    from fm_live_mcp import committed_wage_offer_selection as selector
except ImportError:
    # Candidate-only dependency loading until root integrates both private files.
    path = DEPENDENCY/'fm_live_mcp/committed_wage_offer_selection.py'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == SELECTOR_SHA
    spec = importlib.util.spec_from_file_location('fm_live_mcp.committed_wage_offer_selection', path)
    selector = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = selector
    spec.loader.exec_module(selector)
assert hashlib.sha256(Path(selector.__file__).read_bytes()).hexdigest() == SELECTOR_SHA
from fm_live_mcp import committed_wage_owner_source as core
try:
    from tests.test_committed_wage_offer_selection import Fixture as ParentFixture, NATIVE as SELECTOR_NATIVE, BASE, pack
except ImportError:
    path = DEPENDENCY/'tests/test_committed_wage_offer_selection.py'
    spec = importlib.util.spec_from_file_location('owner_selector_fixture', path)
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    ParentFixture, SELECTOR_NATIVE = fixture_module.Fixture, fixture_module.NATIVE
    BASE, pack = fixture_module.BASE, fixture_module.pack

NATIVE = {int(rva, 0):bytes.fromhex(raw) for rva, raw in json.loads(
    (Path(__file__).parent/'fixtures/committed-wage-owner-native.json').read_text()).items()}


class Fixture(ParentFixture):
    def __init__(self, manager_kind='human_manager'):
        super().__init__()
        for rva, raw in NATIVE.items(): self.put(BASE+rva, raw)
        self.put(BASE+0x88, struct.pack('<QQ',0x55f0,0x4ae8344))
        self.service = self.alloc()
        self.put(BASE+core.FULL_ROOT, pack(self.service))
        self.put(self.service, pack(BASE+core.FULL_TABLE))
        self.put(BASE+core.FULL_TABLE-16, struct.pack('<qQ', 0, BASE+0x55dff18))
        self.put(BASE+0x55dff18+8, pack(BASE+0x53b1011))
        self.put(BASE+0x53b1011, b'17GAME_CLUB_FINANCE\0')
        for slot, getter in ((0x88,0x1fe8af8),(0x138,0x1febc8c)):
            self.put(BASE+core.FULL_TABLE+slot, pack(BASE+getter))
        self.put(self.team+0x28, b'\0');self.put(self.team+0x2f,b'\0')
        person = self.person(manager_kind)
        delta = 0x548 if manager_kind=='human_manager' else 0x208
        self.human = person-0x548 if manager_kind=='human_manager' else None
        self.nonplayer = person-delta
        table = BASE+{'human_manager':0x55ac480,'staff':0x5583660,'player_staff':0x558f568}[manager_kind]
        if manager_kind=='player_staff':
            self.put(self.nonplayer, pack(table))
            full_info = self(BASE+0x558ef38-8,8)
            self.put(table-16, struct.pack('<q',-0x278)+full_info)
        self.put(table-0x20,struct.pack('<q',delta))
        self.put(self.team+0x80,pack(self.nonplayer))
        self.put(BASE+0x55ad820+0x6f0,pack(BASE+0x1300074))
        self.put(BASE+0x55ad820-0x700,struct.pack('<q',-0x548))
        self.date=struct.pack('<I',(2030<<16)|317)
        self.put(BASE+core.world.CURRENT_DATE,self.date)
        self.context=core.Context(123,'owned-save','owned-session',core.PLUGIN_SHA,self.date,
                                 core.CanonicalRef(self.club,0,100,100))
        self.cache([])
        if self.human:
            self.vector(self.human+0x218,[])
            self.vector(self.human+0x200,[])

    def queue_object(self, kind):
        address,table,info,text=self.alloc(),self.alloc(),self.alloc(),self.alloc()
        getter=BASE+0x1004000+kind*16
        if kind==40:
            table,info,text=BASE+0x55e5380,BASE+0x55e5408,BASE+0x53b4d15
            getter=BASE+0x227db10
        self.put(address,pack(table))
        self.put(table-16,struct.pack('<qQ',0,info));self.put(info+8,pack(text))
        self.put(info+0x10,pack(BASE+0x55a44f0))
        self.put(text,(b'29CONTRACT_DETAILS_EDIT_SESSION' if kind==40 else b'18OWNED_QUEUE_SOURCE')+b'\0')
        self.put(table+0x10,pack(getter))
        self.put(getter,struct.pack('<II',0x52800000|(kind<<5),0xd65f03c0))
        return address

    def observe(self, read=None, context=None, lifetime=None):
        return core.observe(read or self,BASE,context or self.context,
                            lifetime=lifetime or (lambda:self.context))


def test_source_fixture_is_exact_pinned_functions():
    for rva,size,digest in core.SOURCE:
        assert len(NATIVE[rva])==size and hashlib.sha256(NATIVE[rva]).hexdigest()==digest


def test_full_human_empty_sources_are_complete_native_zero_branch():
    f=Fixture(); result=f.observe()
    assert result.state=='native_zero' and result.complete_v138_branch
    assert result.native_return==result.out_amount==0
    assert result.human.address==f.human+0x548
    assert result.first_team==core.CanonicalRef(f.team,0,200,200)
    assert result.queue218.kind40==result.queue200.kind40==()
    assert len(result.selections)==1 and result.selections[0][1].selected==()


@pytest.mark.parametrize('kind',('staff','player_staff'))
def test_nonhuman_owner_is_native_zero_without_queues(kind):
    f=Fixture(kind);result=f.observe()
    assert result.reason=='manager_is_not_human' and result.complete_v138_branch
    assert result.native_return==result.out_amount==0
    assert result.queue218 is result.queue200 is None


@pytest.mark.parametrize('values,reason',(([],'empty_club_team_vector'),([0],'null_first_club_team')))
def test_empty_or_null_first_team_native_zero(values,reason):
    f=Fixture();f.vector(f.club+0x18,values)
    result=f.observe();assert result.reason==reason and result.complete_v138_branch


@pytest.mark.parametrize('offset',(0x200,0x218))
def test_kind40_queue_preserves_null_alias_order_and_withholds_amount(offset):
    f=Fixture();native40=f.queue_object(40);other=f.queue_object(39)
    f.vector(f.human+offset,[0,other,native40,native40])
    result=f.observe(); assert result.state=='unavailable' and not result.complete_v138_branch
    assert result.native_return is result.out_amount is None
    queue=result.queue200 if offset==0x200 else result.queue218
    assert [row.address for row in queue.entries]==[0,other,native40,native40]
    assert [row.native_kind for row in queue.entries]==[None,39,40,40]
    assert queue.kind40==(native40,native40)


def test_checked_non40_queues_can_still_prove_empty_contributions():
    f=Fixture();other=f.queue_object(39);f.vector(f.human+0x218,[other,0,other])
    result=f.observe();assert result.state=='native_zero' and len(result.queue218.entries)==3


def test_nonempty_selected_offer_never_becomes_empty_or_amount():
    f=Fixture();offer=f.offer();f.offers([offer]);f.cache([0,0])
    result=f.observe();assert result.reason=='nonempty_selected_offer_monetary_path_unimplemented'
    assert result.native_return is None and len(result.selections[0][1].selected)==2


def test_missing_team80_is_cold_unknown_not_null_manager_zero():
    f=Fixture();f.put(f.team+0x80,pack(0));result=f.observe()
    assert result.reason=='cold_175e508_manager_selection_unimplemented'
    assert result.native_return is None and not result.complete_v138_branch


@pytest.mark.parametrize('kind,flag',((44,0),(44,1),(0,0),(4,0)))
def test_direct_first_team_special_context_matches_same_human(kind,flag):
    f=Fixture();f.put(f.team+0x28,bytes([kind]));f.put(f.team+0x2f,bytes([flag]))
    result=f.observe();assert result.state=='native_zero' and result.human
    assert len(result.selections)==(0 if kind in (4,44) else 1)


@pytest.mark.parametrize('bad',(0,BASE+0x55dfbd8))
def test_missing_or_base_service_is_not_full_service_zero(bad):
    f=Fixture()
    if not bad:f.put(BASE+core.FULL_ROOT,pack(0))
    else:f.put(f.service,pack(bad))
    result=f.observe();assert result.state=='unavailable' and result.native_return is None


@pytest.mark.parametrize('location',('slot39','slot17','owner','person','cast','date','index','rawsecondary'))
def test_typed_owner_near_negatives_reject(location):
    f=Fixture()
    address,raw={
      'slot39':(BASE+core.FULL_TABLE+0x138,pack(BASE+0x2000618)),
      'slot17':(BASE+core.FULL_TABLE+0x88,pack(BASE+0x1ffe470)),
      'owner':(f.team+0x30,pack(f.club+8)),
      'person':(f.human+0x548,pack(BASE+0x55849d8)),
      'cast':(BASE+0x55ad820-0x700,struct.pack('<q',-0x208)),
      'date':(BASE+core.world.CURRENT_DATE,struct.pack('<I',(2030<<16)|318)),
      'index':(f.club+8,struct.pack('<I',1)),
      'rawsecondary':(f.club+16,struct.pack('<I',101)),
    }[location]
    f.put(address,raw)
    with pytest.raises(ValueError):f.observe()


@pytest.mark.parametrize('header',((0,8,8),(4096,4088,4096),(4097,4105,4105),(4096,4096,4096+4097*8)))
def test_queue_bounds_reject(header):
    f=Fixture();f.put(f.human+0x218,struct.pack('<QQQ',*header))
    with pytest.raises(ValueError):f.observe()


def test_unproved_kind_getter_is_unknown_not_native_kind0():
    f=Fixture();obj=f.queue_object(40);f.vector(f.human+0x218,[obj])
    getter=struct.unpack('<Q',f(struct.unpack('<Q',f(obj,8))[0]+0x10,8))[0]
    f.put(getter,bytes.fromhex('00104039c0035fd6'))
    result=f.observe();assert result.state=='unavailable' and result.native_return is None


def test_all_consumed_source_drift_and_lifetime_are_rechecked():
    f=Fixture();target=f.human+0x218;seen=0
    def drift(address,size):
        nonlocal seen
        raw=f(address,size)
        if address==target:
            seen+=1
            if seen>1:return bytes([raw[0]^8])+raw[1:]
        return raw
    with pytest.raises(ValueError):f.observe(read=drift)
    calls=0
    def lifetime():
        nonlocal calls
        calls+=1
        return f.context if calls==1 else replace(f.context,process_id=124)
    with pytest.raises(ValueError):f.observe(lifetime=lifetime)


def test_bool_reference_fields_are_not_native_integer_aliases():
    f=Fixture();bad=replace(f.context,club=replace(f.context.club,index=False))
    with pytest.raises(ValueError):f.observe(context=bad,lifetime=lambda:bad)


@pytest.mark.parametrize('kind,selected',((3,True),(4,False),(7,False),(8,True),
    (21,True),(22,False),(26,False),(27,True),(43,True),(44,False),
    (45,True),(63,True),(64,True),(255,True)))
def test_native_team_kind_branch_boundaries(kind,selected):
    f=Fixture();f.put(f.team+0x28,bytes([kind]));result=f.observe()
    assert result.complete_v138_branch and bool(result.selections)==selected


def test_maximum_queue_uses_bounded_reads_and_preserves_every_null_slot():
    f=Fixture();f.vector(f.human+0x218,[0]*4096);before=dict(f.data)
    result=f.observe()
    assert result.complete_v138_branch and len(result.queue218.entries)==4096
    assert result.queue218.entries[-1].ordinal==4095
    assert max(size for _,size in f.reads)<=16384 and f.data==before


@pytest.mark.parametrize('field',('family','name','kind40table','getter','sourcecode','textsection'))
def test_queue_type_or_instruction_mutation_never_creates_a_complete_zero(field):
    f=Fixture();obj=f.queue_object(40);f.vector(f.human+0x218,[obj])
    table=BASE+0x55e5380;info=BASE+0x55e5408
    address,raw={
      'family':(info+0x10,pack(BASE+0x55dff18)),
      'name':(BASE+0x53b4d15,b'X'),
      'kind40table':(obj,pack(table+8)),
      'getter':(BASE+0x227db10,bytes.fromhex('1f2003d5c0035fd6')),
      'sourcecode':(BASE+0x1febc8c,b'\0'),
      'textsection':(BASE+0x88,struct.pack('<Q',0x55f4)),
    }[field]
    f.put(address,raw)
    try:result=f.observe()
    except ValueError:return
    assert result.native_return is None and not result.complete_v138_branch


def test_distinct_queue_storage_is_not_merged_and_aliases_remain_native_inputs():
    f=Fixture();obj=f.queue_object(40)
    f.vector(f.human+0x218,[obj,obj]);f.vector(f.human+0x200,[obj])
    result=f.observe()
    assert result.queue218.kind40==(obj,obj) and result.queue200.kind40==(obj,)
    assert result.native_return is None


def test_known_kind40_getter_cannot_drift_to_a_non40_literal_and_fake_zero():
    f=Fixture();obj=f.queue_object(40);f.vector(f.human+0x218,[obj])
    f.put(BASE+0x227db10,bytes.fromhex('e0048052c0035fd6'))
    with pytest.raises(ValueError,match='kind getter changed'):f.observe()


def test_later_offer_unavailability_preserves_rechecked_queue_inputs_with_incomplete_selection_scope():
    f=Fixture();obj=f.queue_object(40);f.vector(f.human+0x218,[obj])
    f.put(BASE+0x56a49f8,pack(0))
    result=f.observe()
    assert result.state=='unavailable' and result.native_return is None
    assert result.human and result.queue218.kind40==(obj,) and result.queue200.kind40==()
    assert not result.selections_complete and not result.complete_v138_branch


@pytest.mark.parametrize('target',('team_owner','queue_header','person_cast','native_code','club_secondary'))
def test_final_lifetime_callback_byte_mutation_is_rejected_even_with_same_context(target):
    f=Fixture();calls=0
    address,changed={
        'team_owner':(f.team+0x30,pack(f.club+8)),
        'queue_header':(f.human+0x218,pack(0)),
        'person_cast':(BASE+0x55ad820-0x700,struct.pack('<q',-0x208)),
        'native_code':(BASE+0x1febc8c,b'\0'),
        'club_secondary':(f.club+16,struct.pack('<I',101)),
    }[target]
    def lifetime():
        nonlocal calls
        calls+=1
        if calls==2:f.put(address,changed)
        return f.context
    with pytest.raises(ValueError,match='state changed'):f.observe(lifetime=lifetime)
    assert calls==2


@pytest.mark.parametrize('callback_number',(1,2))
@pytest.mark.parametrize('error_type',(RuntimeError,core.UnsupportedSource,selector.UnsupportedSelection))
def test_lifetime_callback_exception_propagates_unchanged(callback_number,error_type):
    f=Fixture();calls=0;sentinel=error_type('owned lifetime read fault')
    def lifetime():
        nonlocal calls
        calls+=1
        if calls==callback_number:raise sentinel
        return f.context
    with pytest.raises(error_type) as raised:f.observe(lifetime=lifetime)
    assert raised.value is sentinel


@pytest.mark.parametrize('mutate',(
    lambda ctx:replace(ctx,process_id=float(ctx.process_id)),
    lambda ctx:replace(ctx,club=replace(ctx.club,index=False)),
    lambda ctx:replace(ctx,club=replace(ctx.club,native_id=float(ctx.club.native_id))),
))
def test_lifetime_context_rejects_cross_type_equality_aliases(mutate):
    f=Fixture();calls=0
    def lifetime():
        nonlocal calls
        calls+=1
        return f.context if calls==1 else mutate(f.context)
    with pytest.raises(ValueError,match='lifetime changed'):f.observe(lifetime=lifetime)


def test_arbitrary_callback_object_cannot_claim_context_equality():
    f=Fixture();calls=0
    class FalseContext:
        def __eq__(self,other):return True
    def lifetime():
        nonlocal calls
        calls+=1
        return f.context if calls==1 else FalseContext()
    with pytest.raises(ValueError,match='lifetime changed'):f.observe(lifetime=lifetime)
