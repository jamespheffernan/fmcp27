"""Synthetic canonical ownership and stored-reference safety controls."""
import json
from pathlib import Path
import struct

import pytest
from fm_live_mcp import assessment_people, club_staff_responsibilities as source, database, staff, world
from test_database import database_memory
from test_players import memory
from test_staff import staff_record
from test_world import world_memory

NATIVE = json.loads((Path(__file__).parent/'fixtures/staff_responsibility_native_source.json').read_text())


@pytest.fixture
def responsibility_memory(staff_record):
    m = staff_record
    for span in NATIVE:
        m['put'](m['base']+span['rva'],bytes.fromhex(span['raw_hex']))
    for rva,raw in assessment_people.NATIVE_SPANS:
        m['put'](m['base']+rva,raw)
    layout = staff.LAYOUTS[m['staff_kind']]
    table = m['base']+layout[1]
    m['q'](table+0x658,m['base']+0xCA4E78)
    m['put'](table-0x668,struct.pack('<q',layout[3]-8-layout[2]))
    person = 0x1000+layout[2]
    # The older shared fixture allocates only the canonical table's0x90-byte
    # prefix; this feature also tests its auxiliary ID-index flags at+0xA8.
    root = m['allocate'](0xB0)
    m['put'](root,m['read'](m['roots']['people'],0x90))
    m['q'](m['base']+database.TABLES['people'][0],root)
    m['roots']['people'] = root
    m['vec'](m['roots']['people']+0x68,[person])
    m['put'](m['base']+0x56D34E0,b'\0')
    m['put'](m['roots']['people']+0x64,b'\0')
    secondary,vector,row = (m['allocate'](n) for n in (0x50,24,16))
    m['q'](m['club']+0xB0,secondary)
    m['q'](secondary+0x48,vector)
    m['put'](row,struct.pack('<iBb3xB',0,160,0,1))
    m['vec'](vector,[row])
    m.update(responsibility_secondary=secondary,responsibility_vector=vector,
        responsibility_row=row,responsibility_person=person)
    return m


def decode(m):
    return source.decode(m['read'],m['base'],m['club'])


def test_named_stored_reference_keeps_outer_effective_assignment_unknown(responsibility_memory):
    m = responsibility_memory
    result = decode(m)
    assert result['state'] == 'available_own_stored_records'
    assert result['source_slot_count'] == 1 and result['null_slot_count'] == 0
    row = result['records'][0]
    assert row['responsibility_code'] == 160 and row['team_type_code'] == 0
    assert row['description_template'].startswith('Handles team training in general')
    assert row['stored_reference']['person']['display_name'] == 'Test Müller'
    assert row['stored_reference']['person']['record_kind'] == m['staff_kind']
    assert row['stored_reference']['encoding'] == 'PERSON_table_index'
    assert result['effective_assignments'] is None
    assert not result['complete_effective_allocation_verified']


def test_missing_source_and_observed_empty_remain_distinct(responsibility_memory):
    m = responsibility_memory
    m['q'](m['responsibility_secondary']+0x48,0)
    missing = decode(m)
    assert missing['state'] == 'unavailable' and missing['records'] is None
    assert 'fallback_not_evaluated' in missing['reason']
    m['q'](m['responsibility_secondary']+0x48,m['responsibility_vector'])
    m['put'](m['responsibility_vector'],bytes(24))
    empty = decode(m)
    assert empty['state'] == 'available_own_stored_records'
    assert empty['records'] == [] and empty['source_slot_count'] == 0


def test_duplicate_and_null_slots_are_not_deduplicated_or_hidden(responsibility_memory):
    m = responsibility_memory
    m['vec'](m['responsibility_vector'],[m['responsibility_row'],0,m['responsibility_row']])
    result = decode(m)
    assert result['source_slot_count'] == 3 and result['null_slot_count'] == 1
    assert result['records'][1]['state'] == 'null_slot'
    assert [r['slot'] for r in result['records']] == [0,1,2]
    assert result['records'][0]['stored_reference'] == result['records'][2]['stored_reference']


@pytest.mark.parametrize('mode',[0,2,255])
def test_non_one_modes_use_native_id_without_reinterpreting_as_ordinal(responsibility_memory,mode):
    m = responsibility_memory
    native_id = struct.unpack('<i',m['read'](m['responsibility_person']+12,4))[0]
    m['put'](m['responsibility_row'],struct.pack('<iBb3xB',native_id,160,0,mode))
    row = decode(m)['records'][0]
    assert row['stored_reference']['encoding'] == 'PERSON_native_id'
    assert row['stored_reference']['person']['display_name'] == 'Test Müller'


def test_dirty_native_id_index_is_unknown_and_never_sorted(responsibility_memory):
    m = responsibility_memory
    m['put'](m['roots']['people']+0x64,b'\1')
    m['put'](m['roots']['people']+0xA8,b'\1')
    m['put'](m['responsibility_row'],struct.pack('<iBb3xB',123456,160,0,0))
    row = decode(m)['records'][0]
    assert row['stored_reference']['state'] == 'native_id_lookup_requires_sort'
    assert row['stored_reference']['person'] is None
    assert m['read'](m['roots']['people']+0xA8,1) == b'\1'


def test_clean_auxiliary_native_id_index_still_rechecks_canonical_membership(responsibility_memory):
    m = responsibility_memory
    person = m['responsibility_person']
    native_id = struct.unpack('<i',m['read'](person+12,4))[0]
    m['put'](m['roots']['people']+0x64,b'\1')
    m['put'](m['roots']['people']+0xA8,b'\0')
    m['vec'](m['roots']['people']+0x90,[person])
    m['put'](m['responsibility_row'],struct.pack('<iBb3xB',native_id,160,0,0))
    assert decode(m)['records'][0]['stored_reference']['person']['display_name'] == 'Test Müller'
    m['vec'](m['headers']['people'],[m['manager']])
    with pytest.raises(ValueError,match='canonical slot changed'):
        decode(m)


@pytest.mark.parametrize('span',range(len(source.NATIVE_SPANS)))
def test_each_native_body_or_description_table_change_rejects(responsibility_memory,span):
    m = responsibility_memory
    rva,size,_ = source.NATIVE_SPANS[span]
    at = m['base']+rva+size-1
    m['put'](at,bytes([m['read'](at,1)[0]^1]))
    with pytest.raises(ValueError,match='native source changed'):
        decode(m)


@pytest.mark.parametrize('value,mode,state',[(-1,0,'native_unassigned_id'),(-1,1,'negative_native_index'),(-2,1,'negative_native_index'),(999999,1,'native_reference_not_found')])
def test_null_and_unavailable_references_keep_the_native_reason(responsibility_memory,value,mode,state):
    m = responsibility_memory
    m['put'](m['responsibility_row'],struct.pack('<iBb3xB',value,255,-128,mode))
    row = decode(m)['records'][0]
    assert row['description_template'] is row['description_resource_key'] is None
    assert row['team_type_code'] == -128
    assert row['stored_reference']['state'] == state
    assert row['stored_reference']['person'] is None


@pytest.mark.parametrize('fault',['club_membership','club_rtti','row_alignment','reversed_vector','unaligned_end','budget','person_index','native_guard'])
def test_corrupt_ownership_geometry_and_native_binding_reject(responsibility_memory,fault):
    m = responsibility_memory
    if fault == 'club_membership':m['vec'](m['headers']['clubs'],[m['manager']])
    elif fault == 'club_rtti':m['q'](m['club'],0)
    elif fault == 'row_alignment':m['vec'](m['responsibility_vector'],[m['responsibility_row']+1])
    elif fault == 'person_index':m['put'](m['responsibility_person']+8,struct.pack('<I',2))
    elif fault == 'native_guard':m['put'](m['base']+source.NATIVE_SPANS[0][0],bytes(4))
    else:
        start = m['allocate'](8)
        end = start-8 if fault == 'reversed_vector' else start+1 if fault == 'unaligned_end' else start+(source.SLOT_LIMIT+1)*8
        m['put'](m['responsibility_vector'],struct.pack('<QQQ',start,end,max(start,end)))
    with pytest.raises((ValueError,KeyError)):
        decode(m)


def test_late_source_mutation_is_caught_by_the_callers_final_readset(responsibility_memory):
    m = responsibility_memory
    snapshot = world.ReadSet(m['read'])
    source.decode(snapshot,m['base'],m['club'])
    m['put'](m['responsibility_row']+4,b'\xa1')
    with pytest.raises(ValueError,match='Game state changed'):
        snapshot.verify()
