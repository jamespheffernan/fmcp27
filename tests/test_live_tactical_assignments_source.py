from copy import deepcopy

import pytest

from fm_live_mcp import live_tactical_assignments_source as source, world
from test_live_in_possession_source import context


@pytest.fixture
def two_phase(context):
    memory,base,creator=context['memory'],context['base'],context['creator']
    for rva,raw in source.NATIVE_SPANS:
        memory.put(base+rva,raw)
    mapping=[0,1,2,3,4,6,5,7,9,8,10]
    memory.put(creator+0x7b4,bytes(mapping))
    masks=[1,4,0x200010,0x100010,8,0x200080,0x100080,0x100,0x200,0x2000,0x4000]
    for index,mask in enumerate(masks):
        memory.pack(creator+0x440+index*0x48,'<I',mask)
        memory.pack(creator+0x480+index*0x48,'<Q',1)
    context['mapping']=mapping
    return context


def inspect(c,phase='both'):
    read=world.ReadSet(c['memory'].read)
    result=source.inspect(read,c['base'],c['coach'],phase)
    read.verify()
    return result


def test_permutation_maps_people_independently_in_each_phase(two_phase):
    r=inspect(two_phase)
    assert r['source_state']=='available'
    ip=r['phases']['in_possession']['assignments']
    oop=r['phases']['out_of_possession']['assignments']
    assert [a['person']for a in ip]==[a['person']for a in oop]
    assert [a['position']['position_index']for a in oop]==two_phase['mapping']
    assert ip[5]['position']['name']=='DM(CR)' and oop[5]['position']['name']=='DM(CL)'
    assert oop[9]['position']['name']=='M(L)' and oop[8]['position']['name']=='AM(C)'
    assert oop[9]['phase_map_raw_u8']==8 and oop[9]['phase_map_state']=='stored_index'


def test_unknown_bench_extent_keeps_native_first_eleven_in_both_phases(two_phase):
    two_phase['sheet'].update(role_boundary_state='stored_boundary_unmapped',
                              formation_boundary_state='native_first_11')
    r=inspect(two_phase)
    assert r['source_state']=='available'
    for phase in r['phases'].values():
        assert phase['formation_boundary_state']=='native_first_11'
        assert phase['selection_boundary_state']=='stored_boundary_unmapped'
        assert len(phase['assignments'])==11


def test_all_ff_is_native_identity_fallback(two_phase):
    two_phase['memory'].put(two_phase['creator']+0x7b4,b'\xff'*11)
    rows=inspect(two_phase)['phases']['out_of_possession']['assignments']
    assert [a['phase_slot_index']for a in rows]==list(range(11))
    assert all(a['phase_map_state']=='identity_fallback'for a in rows)


def test_each_u8_mapping_is_bounded_without_reading_invalid_slot(two_phase):
    for value in range(256):
        two_phase['memory'].put(two_phase['creator']+0x7b4,bytes([value]))
        reads=[]
        def read(address,length):
            reads.append((address,length))
            return two_phase['memory'].read(address,length)
        r=source.inspect(read,two_phase['base'],two_phase['coach'],'out_of_possession')
        row=r['phases']['out_of_possession']['assignments'][0]
        if value<=10 or value==255:
            assert row['phase_slot_index']==(0 if value==255 else value)
        else:
            assert row['phase_slot_index']is None and row['position']is None and row['stored_base_role']is None
            assert row['pairing_state']=='unsupported_phase_index'
            assert r['source_state']=='partial'
            # Only11 bounded OOP position records, never creator+440+invalid*48.
            target=two_phase['creator']+0x440+(value if value<128 else value-256)*0x48
            assert (target,4)not in reads


def test_duplicate_target_preserved_not_forced_to_permutation(two_phase):
    two_phase['memory'].put(two_phase['creator']+0x7b4,b'\0'*11)
    r=inspect(two_phase)['phases']['out_of_possession']
    assert r['duplicate_phase_slot_indices']==[0]
    assert len(r['assignments'])==11
    assert all(a['phase_slot_shared']for a in r['assignments'])
    assert all(a['phase_slot_index']==0 for a in r['assignments'])


def test_duplicate_person_stays_ambiguous_across_phases(two_phase):
    two_phase['sheet']['slots'][1]['person']=deepcopy(two_phase['sheet']['slots'][0]['person'])
    r=inspect(two_phase)
    assert r['source_state']=='partial'
    for phase in r['phases'].values():
        assert [a['pairing_state']for a in phase['assignments'][:2]]==['ambiguous_duplicate_person']*2


def test_empty_selection_not_unavailable(two_phase):
    for slot in two_phase['sheet']['slots']:
        slot.update(person=None,state='empty_slot')
    r=inspect(two_phase)
    assert r['source_state']=='partial'
    assert all(p['assignment_count']==11 and p['named_assignment_count']==0 for p in r['phases'].values())
    assert all(a['person']is None for p in r['phases'].values()for a in p['assignments'])


def test_absent_session_unavailable_not_empty(two_phase):
    two_phase['sheet'].update(source_state='unavailable',unavailable_reason='missing',slots=None)
    r=inspect(two_phase)
    assert r['source_state']=='unavailable'
    assert all(p['assignments']is None and p['assignment_count']is None for p in r['phases'].values())


def test_missing_creator_preserves_selection_for_each_phase(two_phase):
    two_phase['memory'].pack(0x20000,'<Q',0)
    r=inspect(two_phase)
    assert r['source_state']=='partial'
    assert all(p['assignments']is None and len(p['ordered_selection'])==11 for p in r['phases'].values())


def test_unknown_oop_labels_are_explicit(two_phase):
    two_phase['memory'].pack(two_phase['creator']+0x440,'<I',0xffffffff)
    two_phase['memory'].pack(two_phase['creator']+0x480,'<Q',0)
    r=inspect(two_phase)
    assert r['phases']['in_possession']['source_state']=='available'
    row=r['phases']['out_of_possession']['assignments'][0]
    assert row['position']['name']is None and row['stored_base_role']['compiled_english_name']is None
    assert r['source_state']=='partial'


def test_ip_only_view_unchanged_and_never_reads_oop(two_phase):
    reads=[]
    def read(address,length):
        reads.append((address,length))
        return two_phase['memory'].read(address,length)
    old=source.ip.inspect(read,two_phase['base'],two_phase['coach'])
    r=source.inspect(read,two_phase['base'],two_phase['coach'],'in_possession')
    phase=r['phases']['in_possession'];phase=deepcopy(phase)
    phase.pop('phase_mapping_state');phase['out_of_possession_pairing_state']='not_established'
    assert phase==old
    creator=two_phase['creator']
    assert not any(creator+0x440<=address<creator+0x750 or address==creator+0x7b4 for address,_ in reads)


def test_single_phase_response_is_narrowed(two_phase):
    for phase in source.PHASES:
        assert list(inspect(two_phase,phase)['phases'])==[phase]


@pytest.mark.parametrize('phase',['all','defence','',True,None,[],{}])
def test_invalid_phase_rejected_before_source(two_phase,phase):
    with pytest.raises(ValueError,match='Select'):inspect(two_phase,phase)


def test_each_oop_native_guard_required(two_phase):
    for rva,raw in source.NATIVE_SPANS:
        two_phase['memory'].put(two_phase['base']+rva,bytes([raw[0]^1]))
        with pytest.raises(ValueError):inspect(two_phase)
        two_phase['memory'].put(two_phase['base']+rva,raw)


def test_changed_phase_map_detected_before_publish(two_phase):
    read=world.ReadSet(two_phase['memory'].read)
    source.inspect(read,two_phase['base'],two_phase['coach'])
    two_phase['memory'].put(two_phase['creator']+0x7b4,b'X')
    with pytest.raises(ValueError):read.verify()


def test_short_map_rejected(two_phase):
    def read(address,length):
        raw=two_phase['memory'].read(address,length)
        return raw[:-1]if address==two_phase['creator']+0x7b4 else raw
    with pytest.raises(ValueError,match='Incomplete'):source.inspect(read,two_phase['base'],two_phase['coach'])


def test_working_selected_creator_owns_both_positions_and_map(two_phase):
    memory,creator=two_phase['memory'],two_phase['creator']
    other=0xA0000
    memory.put(other,memory.read(creator,0x7c0))
    memory.put(other+0x7b4,b'\xff'*11)
    memory.pack(two_phase['payload']+0x1000,'<QQQ',0x20000,0x20010,0x20010)
    memory.pack(0x20000,'<QQ',creator,other)
    memory.put(two_phase['payload']+0x1018,b'\x01')
    # A bad map in an unselected creator is neither used nor repaired.
    memory.put(creator+0x7b4,b'\x80'*11)
    result=inspect(two_phase)
    assert result['selected_creator_index']==1
    assert result['phases']['out_of_possession']['assignments'][5]['phase_slot_index']==5
    assert result['phases']['out_of_possession']['assignments'][5]['position']['name']=='DM(CR)'
    assert result['phases']['out_of_possession']['assignments'][9]['position']['name']=='AM(C)'


def test_same_slot_fallback_still_uses_distinct_oop_fields(two_phase):
    two_phase['memory'].put(two_phase['creator']+0x7b4,b'\xff'*11)
    result=inspect(two_phase)
    assert result['phases']['in_possession']['assignments'][9]['position']['name']=='AM(L)'
    assert result['phases']['out_of_possession']['assignments'][9]['position']['name']=='AM(C)'
