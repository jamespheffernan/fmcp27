"""Genuine captured sources plus labelled altered-source refusal controls."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest
from fm_live_mcp import player_promise_inventory_source as source, world


class Original:
    def __init__(self):
        fixture=Path(__file__).parent/'fixtures/player_promise_inventory148.json.gz'
        with gzip.open(fixture,'rt')as stream:self.packet=json.load(stream)
        journal=self.packet['journal'];regions=journal['regions']
        assert self.packet['state']=='accepted_source_capture_no_lifecycle_verdict'
        assert self.packet['detach']=={'detached':True}
        assert len(regions)==journal['region_count'] and not journal['truncated']
        assert hashlib.sha256(json.dumps(regions,separators=(',',':')).encode()).hexdigest()==journal['sha256']
        self.cells={}
        for row in regions:
            at=int(row['address'],16);raw=bytes.fromhex(row['raw_hex'])
            assert len(raw)==row['size']
            for offset,value in enumerate(raw):
                if at+offset in self.cells:assert self.cells[at+offset]==value
                self.cells[at+offset]=value
        self.base=int(self.packet['plugin_base_private'],16)
        self.manager=self.packet['context_before']['coach']['manager_address']+0x548
    def read(self,address,size):
        try:return bytes(self.cells[address+i]for i in range(size))
        except KeyError as error:raise ValueError('Missing literal captured promise operand')from error
    def write(self,address,raw):
        for offset,value in enumerate(raw):self.cells[address+offset]=value
    def populated(self):return next(row for row in self.packet['players']if row['promises'])
    def inspect(self,row):return source.inspect(self.read,self.base,row['primary'],'actual',selected_view_person=self.manager)


def test_every_genuine_roster_slot_and_all_twenty_two_entries_preserve_roles_and_unknowns():
    old=Original();rows=[old.inspect(row)for row in old.packet['players']]
    assert len(rows)==29
    assert sum(row['native_vector_entry_count']for row in rows)==22
    assert sum(row['state']=='absent_native_vector'for row in rows)==11
    assert sum(row['state']=='observed_native_vector'for row in rows)==18
    actual=[entry for row in rows for entry in row['promises']]
    assert sum(entry['party_A_matches_selected_view']for entry in actual)==18
    assert sum(not entry['party_A_matches_selected_view']for entry in actual)==4
    assert sum(not entry['party_B_matches_vector_owner']for entry in actual)==4
    assert sum(entry['native_end_marker_bit0']for entry in actual)==2
    for projected,captured in zip(rows,old.packet['players'],strict=True):
        for row,original in zip(projected['promises'],captured['promises'],strict=True):
            raw=bytes.fromhex(original['raw60_hex'])
            assert row['native_kind']==original['native_kind']
            assert row['native_category_code']==original['native_PMsc']
            assert row['native_linked_scalar']==original['native_PMsv']
            assert row['native_end_marker_flags']==raw[0x53]
            assert row['stored_start_date']['raw_hex']==original['start_date_raw_hex']
            assert row['stored_end_date']['raw_hex']==original['end_date_raw_hex']
            assert row['stored_end_date']['role']=='stored_end_or_resolution_date'
            assert row['native_party_A']['native_identity']==original['promiser']['native_identity']
            assert row['native_party_B']['native_identity']==original['subject']['native_identity']
            assert row['active']is row['ongoing']is row['fulfilled']is row['overdue']is None
            assert row['native_category_name']is row['kind_name']is None
            assert row['promiser']is row['recipient']is row['subject']is None
            assert row['party_role_state']=='not_evaluated_context_dependent_native_links'
        assert projected['active_count']is None
        assert not projected['complete_manager_population_verified']and not projected['lifecycle_evaluated']


@pytest.mark.parametrize('span',range(len(source.SOURCE)))
def test_each_corrupted_native_binding_is_refused(span):
    old=Original();at=old.base+source.SOURCE[span][0];old.cells[at]^=1
    with pytest.raises(ValueError,match='Native promise source changed'):old.inspect(old.populated())


@pytest.mark.parametrize('rva',[0x55f1b18,0x55f1b30,0x55ef7d0,0x53bf95f])
def test_corrupt_named_rule_rtti_and_handler_refuse(rva):
    old=Original();old.cells[old.base+rva]^=1
    with pytest.raises(ValueError,match='Named native promise rule'):old.inspect(old.populated())


@pytest.mark.parametrize('change',['primary_type','person_slot','getter','person_adjustment','owner_adjustment','subobject_type'])
def test_source_owner_casts_and_canonical_table_reject_unrelated_geometry(change):
    old=Original();row=old.populated();primary=row['primary'];person=primary+0x388;pvt=int.from_bytes(old.read(person,8),'little')
    if change=='primary_type':old.write(primary,struct.pack('<Q',old.base+0x5588ef0))
    elif change=='person_slot':
        root=int.from_bytes(old.read(old.base+0x56d2d80,8),'little');header=int.from_bytes(old.read(root+0x88,8),'little');start=int.from_bytes(old.read(header,8),'little');index=int.from_bytes(old.read(person+8,4),'little');old.write(start+index*8,struct.pack('<Q',person+8))
    elif change=='getter':old.write(pvt+0x668,struct.pack('<Q',old.base+0xd5c600))
    elif change=='person_adjustment':old.write(pvt-0x678,struct.pack('<q',-0x380))
    elif change=='owner_adjustment':old.write(old.base+source.players.RVA[0]-0x20,struct.pack('<q',0x280))
    elif change=='subobject_type':old.write(primary+0x278,struct.pack('<Q',old.base+0x5589a98))
    with pytest.raises(ValueError):old.inspect(row)


@pytest.mark.parametrize('change',['reversed','oversized','misaligned','null_entry','dead_reference','unreadable'])
def test_vector_and_record_failures_never_become_empty(change):
    old=Original();row=old.populated();vector=row['vector'];start,end,capacity=row['vector_header'];promise=row['promises'][0]['address']
    if change=='reversed':old.write(vector+8,struct.pack('<Q',start-8))
    elif change=='oversized':old.write(vector+16,struct.pack('<Q',start+257*8))
    elif change=='misaligned':old.write(vector,struct.pack('<Q',start+4))
    elif change=='null_entry':old.write(start,struct.pack('<Q',0))
    elif change=='dead_reference':old.write(promise,struct.pack('<I',0))
    elif change=='unreadable':old.cells.pop(promise+0x4e)
    with pytest.raises(ValueError):old.inspect(row)


def test_observed_empty_and_absent_source_remain_distinct():
    old=Original();row=old.populated();old.write(row['vector']+8,struct.pack('<Q',row['vector_header'][0]))
    result=old.inspect(row)
    assert result['state']=='observed_empty_native_vector'and result['promises']==[]and result['active_count']is None
    absent=next(row for row in old.packet['players']if not row['vector'])
    result=old.inspect(absent)
    assert result['state']=='absent_native_vector'and result['promises']==[]and result['active_count']is None


def test_repeated_native_entries_are_preserved_not_deduplicated():
    old=Original();row=next(row for row in old.packet['players']if len(row['promises'])==2)
    old.write(row['vector_header'][0]+8,struct.pack('<Q',row['promises'][0]['address']))
    result=old.inspect(row)
    assert result['native_vector_entry_count']==2
    a,b=result['promises'];b=deepcopy(b);b['entry_index']=a['entry_index'];assert a==b


def test_invalid_stored_date_and_unknown_category_never_imply_overdue_or_fulfilled():
    old=Original();row=old.populated();at=row['promises'][0]['address'];old.write(at+0x3c,b'\0'*4);old.write(at+0x56,b'\xff')
    result=old.inspect(row)['promises'][0]
    assert result['stored_end_date']['value']is None
    assert result['stored_end_date']['state']=='unavailable_native_date'
    assert result['native_category_code']==255 and result['native_category_name']is None
    assert result['overdue']is result['fulfilled']is result['active']is None


def test_canonical_player_cannot_be_substituted_as_selected_human_view():
    old=Original();row=old.populated()
    with pytest.raises(ValueError,match='canonical HUMAN'):
        source.inspect(old.read,old.base,row['primary'],'actual',selected_view_person=row['primary']+0x388)


@pytest.mark.parametrize('kind',['player_staff','virtual','non_player',None])
def test_other_record_classes_do_not_inherit_actual_player_offsets(kind):
    old=Original();row=old.populated();result=source.inspect(old.read,old.base,row['primary'],kind)
    assert result['state']=='unsupported_record_kind'and result['promises']is None
    assert result['active_count']is None and result['native_vector_entry_count']is None


def test_all_raw_record_bytes_remain_in_the_callers_final_physical_fence():
    old=Original();row=old.populated();read=world.ReadSet(old.read)
    source.inspect(read,old.base,row['primary'],'actual',selected_view_person=old.manager)
    # Changed end-marker/category cannot leave accepted earlier lifecycle inputs.
    old.cells[row['promises'][0]['address']+0x53]^=1
    with pytest.raises(ValueError,match='Game state changed during read; retry'):read.verify()
