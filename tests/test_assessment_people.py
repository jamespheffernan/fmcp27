"""Typed canonical identity fixtures; no live report generation or game calls."""
import struct

import pytest

from fm_live_mcp import assessment_people as people, database, players, staff
from test_database import database_memory
from test_players import memory
from test_shortlist_members import member_memory
from test_world import world_memory


def prepare_identity_memory(m):
    """Seed own guards and add a real typed staff/HUMAN/combined assessor helper."""
    for rva, raw in people.NATIVE_SPANS:
        m['put'](m['base'] + rva, raw)

    def add_assessor(kind='staff', index=0, primary_id=77, secondary_id=77, name='Assessor'):
        person_rva, (_, primary_rva, person_offset, type_name) = m['seed_type'](kind)
        if kind == 'player_staff':
            primary, person = m['add_person'](kind, index, primary_id, secondary_id, name)
        else:
            primary = m['allocate'](person_offset + 32)
            person = primary + person_offset
            m['q'](primary, m['base'] + primary_rva)
            m['put'](person, struct.pack('<QIII', m['base'] + person_rva,
                                        index, primary_id, secondary_id))
        data_offset = staff.LAYOUTS[kind][3]
        info = m['allocate'](16)
        native_name = b'N2db16NON_PLAYING_DATAE\0'
        text = m['allocate'](len(native_name) + 1) + 1
        m['put'](text, native_name)
        m['q'](info + 8, text)
        m['put'](m['base'] + staff.NON_PLAYING_RVA - 16, struct.pack('<qQ', 0, info))
        m['q'](primary + data_offset, m['base'] + staff.NON_PLAYING_RVA)
        for slot, adjustment in ((40, 0x150), (41, 0x158), (42, 0x160), (55, 0x1C8)):
            m['q'](m['base'] + players.RVA[2] + slot * 8, 0x8000 + slot * 8)
            m['q'](m['base'] + person_rva + slot * 8, 0x8000 + slot * 8)
            m['put'](m['base'] + person_rva - adjustment, struct.pack('<q', -0x110))
        m['q'](m['base'] + person_rva + 0x658, m['base'] + 0xCA4E78)
        adjustment = data_offset - 8 - person_offset
        m['put'](m['base'] + person_rva - 0x668, struct.pack('<q', adjustment))
        handle = m['allocate'](8)
        m['q'](handle, m['text'](name))
        m['q'](person - 0xF0, handle)
        m['q'](person - 0xE8, 0)
        m['q'](person - 0xE0, 0)
        m['put'](person - 0xB8, struct.pack('<HH', 60, 1980))
        return primary, person

    m['add_assessor'] = add_assessor
    return m


@pytest.fixture
def identity_memory(member_memory):
    return prepare_identity_memory(member_memory)


def binding(m, primary=0x1000, with_index=True, kind=None):
    _, identity = players.decode(m['read'], primary, m['tables'])
    value = {'address': primary, 'identity': identity, 'tables': m['tables']}
    if with_index:
        offset = players.person_offset(m['read'], primary, m['tables'])
        value.update(database_index=struct.unpack('<I', m['read'](primary + offset + 8, 4))[0],
                     world_bound=True)
    if kind:
        value['record_kind'] = kind
    return value


def canonical(m):
    return database.table(m['read'], m['base'], 'people')


def bound(m, value=None, table=None, read=None):
    return people.bound_player(read or m['read'], m['base'], m['tables'],
                               canonical(m) if table is None else table,
                               binding(m) if value is None else value)


def assessor(m, person, read=None, table=None):
    return people.assessor(read or m['read'], m['base'],
                           canonical(m) if table is None else table, person)


@pytest.mark.parametrize('with_index', [False, True])
def test_actual_legacy_and_world_bound_reference_recover_same_person(identity_memory, with_index):
    m = identity_memory
    person, public = bound(m, binding(m, with_index=with_index))
    assert person == 0x1388
    assert public == {'display_name': 'Test Müller', 'native_identity': {
        'database_index': 0, 'native_id': 12345, 'random_id': None}, 'record_kind': 'actual'}
    assert '0x' not in repr(public)


@pytest.mark.parametrize('with_index', [False, True])
def test_combined_reference_uses_primary_relation_and_existing_identity(identity_memory, with_index):
    m = identity_memory
    primary, person = m['add_person']('player_staff', 0, 444, 0, 'Combined Player')
    m['vec'](m['headers']['people'], [person])
    value = binding(m, primary, with_index, 'player_staff')
    actual, public = bound(m, value)
    assert actual == person and public['record_kind'] == 'player_staff'
    assert public['native_identity'] == {'database_index': 0, 'native_id': 444, 'random_id': 0}
    assert public['display_name'] == 'Combined Player'


@pytest.mark.parametrize('secondary,public_secondary', [(12345, None), (0, 0), (54321, 54321),
                                                         (0xFFFFFFFF, 0xFFFFFFFF)])
def test_player_native_identity_keeps_independent_secondary(identity_memory, secondary, public_secondary):
    m = identity_memory
    m['put'](0x1398, struct.pack('<I', secondary))
    _, public = bound(m)
    assert public['native_identity']['random_id'] == public_secondary


@pytest.mark.parametrize('kind', ['staff', 'human_manager', 'player_staff'])
@pytest.mark.parametrize('secondary', [77, 0, 88])
def test_named_assessor_is_canonical_without_a_scout_title(identity_memory, kind, secondary):
    m = identity_memory
    primary, person = m['add_assessor'](kind, 0, 77, secondary, 'Hédy Hassine')
    m['vec'](m['headers']['people'], [person])
    result = assessor(m, person)
    assert result == {'state': 'available', 'display_name': 'Hédy Hassine',
                      'native_identity': {'database_index': 0, 'native_id': 77,
                                          'random_id': None if secondary == 77 else secondary},
                      'record_kind': kind}
    assert not any('scout' in key or 'address' in key for key in result)
    if kind == 'player_staff':
        # The native NON_PLAYER cast returns a secondary subobject, not primary.
        assert person - 0x208 == primary + 0x278 and person - 0x208 != primary


def test_null_assessor_is_explicit_and_does_not_read_profiles(identity_memory):
    m = identity_memory
    result = assessor(m, 0, read=lambda *_: pytest.fail('Read for a null assessor'))
    assert result == {'state': 'null_person', 'display_name': None,
                      'native_identity': None, 'record_kind': None}


@pytest.mark.parametrize('kind', ['actual', 'virtual'])
def test_known_unsupported_assessor_type_keeps_identity_without_names(identity_memory, kind):
    m = identity_memory
    _, person = m['add_person'](kind, 0, 88, 0)
    m['vec'](m['headers']['people'], [person])
    result = assessor(m, person)
    assert result == {'state': 'unsupported_person_kind', 'display_name': None,
                      'native_identity': {'database_index': 0, 'native_id': 88, 'random_id': 0},
                      'record_kind': kind}


@pytest.mark.parametrize('change', ['identity', 'index'])
def test_stable_reference_mismatch_has_specific_typed_exception(identity_memory, change):
    m = identity_memory
    value = binding(m)
    if change == 'identity': value['identity'] = (999, *value['identity'][1:])
    else: value['database_index'] = 8
    with pytest.raises(people.StalePlayerReference, match='changed'):
        bound(m, value)


@pytest.mark.parametrize('change', ['identity', 'index'])
def test_transient_change_during_stale_recheck_is_not_typed_stale(identity_memory, change):
    m = identity_memory
    value = binding(m)
    if change == 'identity': value['identity'] = (999, *value['identity'][1:])
    else: value['database_index'] = 8
    count = 0

    def changing(address, size):
        nonlocal count
        raw = m['read'](address, size)
        if address == 0x1000 and size == players.SIZE:
            count += 1
            if count == 2:
                m['q'](m['roots']['people'], 0)
        return raw

    with pytest.raises(ValueError) as error:
        bound(m, value, read=changing)
    assert not isinstance(error.value, people.StalePlayerReference)


@pytest.mark.parametrize('mutation', [
    {'binding_kind': 'stored_virtual_identity_v1'}, {'record_kind': 'virtual'},
    {'record_kind': 'staff'}, {'world_bound': 1}, {'database_index': True},
    {'database_index': -1}, {'database_index': 1 << 32}, {'identity': []},
    {'identity': (12345,)}, {'identity': ('12345', 'Test', 'Müller', '2000-02-29', 12345)},
    {'tables': []}, {'address': None}, {'address': True}, {'address': 0x1004},
])
def test_unsupported_or_malformed_reference_is_ordinary_value_error(identity_memory, mutation):
    m = identity_memory
    value = binding(m)
    value.update(mutation)
    with pytest.raises(ValueError) as error:
        bound(m, value)
    assert not isinstance(error.value, people.StalePlayerReference)


def test_missing_required_reference_fields_reject(identity_memory):
    m = identity_memory
    for key in ('address', 'identity', 'tables'):
        value = binding(m)
        del value[key]
        with pytest.raises(ValueError) as error:
            bound(m, value)
        assert not isinstance(error.value, people.StalePlayerReference)


@pytest.mark.parametrize('fault', ['canonical_slot', 'current_index', 'current_primary_id', 'person_type',
                                  'primary_type', 'displacement', 'cast_getter', 'cast_adjustment', 'rtti'])
def test_corrupt_or_changing_current_player_is_never_typed_stale(identity_memory, fault):
    m = identity_memory
    value = binding(m)
    table = m['base'] + players.RVA[2]
    if fault == 'canonical_slot': m['vec'](m['headers']['people'], [0x1390])
    if fault == 'current_index': m['put'](0x1390, struct.pack('<I', 7))
    if fault == 'current_primary_id': m['put'](0x1394, bytes(4))
    if fault == 'person_type': m['q'](0x1388, m['base'] + 0x5500000)
    if fault == 'primary_type': m['q'](0x1000, m['base'] + players.STAFF_RVA[0])
    if fault == 'displacement': m['put'](table - 16, struct.pack('<q', -0x480))
    if fault == 'cast_getter': m['q'](table + 0x668, m['base'] + 0xCA49DC)
    if fault == 'cast_adjustment': m['put'](table - 0x678, struct.pack('<q', -0x480))
    if fault == 'rtti':
        info = struct.unpack('<Q', m['read'](table - 8, 8))[0]
        text = struct.unpack('<Q', m['read'](info + 8, 8))[0]
        m['put'](text, b'X')
    with pytest.raises(ValueError) as error:
        bound(m, value)
    assert not isinstance(error.value, people.StalePlayerReference)


@pytest.mark.parametrize('field', ['root', 'header', 'start', 'count', 'identity'])
def test_supplied_people_descriptor_must_match_current_table(identity_memory, field):
    m = identity_memory
    info = canonical(m)
    info[field] = () if field == 'identity' else info[field] + 8
    with pytest.raises(ValueError, match='table changed'):
        bound(m, table=info)


@pytest.mark.parametrize('fault', ['slot', 'id', 'unknown_type', 'primary_type', 'cast_getter', 'cast_adjustment'])
def test_assessor_canonical_type_and_cast_failures_reject(identity_memory, fault):
    m = identity_memory
    primary, person = m['add_assessor']()
    m['vec'](m['headers']['people'], [person])
    vt = m['base'] + staff.LAYOUTS['staff'][1]
    if fault == 'slot': m['vec'](m['headers']['people'], [person + 8])
    if fault == 'id': m['put'](person + 12, bytes(4))
    if fault == 'unknown_type': m['q'](person, m['base'] + 0x5500000)
    if fault == 'primary_type': m['q'](primary, m['base'] + players.RVA[0])
    if fault == 'cast_getter': m['q'](vt + 0x658, m['base'] + 0xCA49C0)
    if fault == 'cast_adjustment': m['put'](vt - 0x668, struct.pack('<q', -0x480))
    with pytest.raises(ValueError):
        assessor(m, person)


def test_local_rechecks_detect_assessor_identity_mutation(identity_memory):
    m = identity_memory
    primary, person = m['add_assessor']()
    m['vec'](m['headers']['people'], [person])
    seen = 0

    def changing(address, size):
        nonlocal seen
        raw = m['read'](address, size)
        if address == primary and size == 0x208 + 32:
            seen += 1
            if seen == 2:
                m['put'](person + 16, struct.pack('<I', 99))
        return raw

    with pytest.raises(ValueError, match='changed'):
        assessor(m, person, read=changing)


def test_native_guards_and_short_reads(identity_memory):
    m = identity_memory
    value = binding(m)
    for rva, raw in people.NATIVE_SPANS:
        m['put'](m['base'] + rva, bytes([raw[0] ^ 1]))
        with pytest.raises(ValueError, match='native layout changed'):
            bound(m, value)
        m['put'](m['base'] + rva, raw)
    with pytest.raises(ValueError, match='Incomplete'):
        bound(m, value, read=lambda *_: b'')


@pytest.mark.parametrize('invalid', [None, True, -1, 1, 0x1004, (1 << 64) - 8])
def test_invalid_assessor_pointer_rejects(identity_memory, invalid):
    with pytest.raises(ValueError):
        assessor(identity_memory, invalid)


# Frozen batch20 canonical pairs; constructed typed memory does not replace live acceptance.
FROZEN_PAIRS = [
    (8172, 12087972, 'Nicolas Jackson', 5140, 4001503, 'Peter Clark'),
    (13331, 28127164, 'Tyler Morton', 15118, 29232984, 'Hédy Hassine'),
    (31944, 86078360, 'Moisés Caicedo', 5140, 4001503, 'Peter Clark'),
    (35009, 93070271, 'Viktor Gyökeres', 5905, 5202443, 'Jack Ross'),
    (39157, 2000056553, 'Javi Villar', 5140, 4001503, 'Peter Clark'),
    (60187, 2000381365, 'Ayyoub Bouaddi', 34987, 93054676, 'Kyle Macaulay'),
]


def test_all_six_frozen_pair_identities_remain_independent(identity_memory):
    m = identity_memory
    slots = [0] * 60188
    references, assessors = [], {}
    for index, native_id, name, assessor_index, assessor_id, assessor_name in FROZEN_PAIRS:
        primary, person = m['add_person']('actual', index, native_id, native_id, name)
        slots[index] = person
        references.append((person, binding(m, primary)))
        if assessor_index not in assessors:
            _, assessors[assessor_index] = m['add_assessor']('staff', assessor_index, assessor_id,
                                                          assessor_id, assessor_name)
            slots[assessor_index] = assessors[assessor_index]
    m['vec'](m['headers']['people'], slots)
    for expected, reference in zip(FROZEN_PAIRS, references):
        person, public = bound(m, reference[1])
        assert person == reference[0] and public['display_name'] == expected[2]
        assert public['native_identity']['database_index'] == expected[0]
        report_author = assessor(m, assessors[expected[3]])
        assert report_author['state'] == 'available' and report_author['display_name'] == expected[5]
        assert report_author['native_identity'] == {'database_index': expected[3],
                                                   'native_id': expected[4], 'random_id': None}


@pytest.mark.parametrize('saved_primary,secondary', [(0, 12345), (-1, 12345),
                                                     (1 << 32, 12345), (12345, -1),
                                                     (12345, 1 << 32)])
def test_malformed_saved_identity_words_are_not_confirmed_stale(identity_memory, saved_primary, secondary):
    m = identity_memory
    value = binding(m)
    value['identity'] = (saved_primary, *value['identity'][1:-1], secondary)
    with pytest.raises(ValueError) as error:
        bound(m, value)
    assert not isinstance(error.value, people.StalePlayerReference)


def test_passed_layout_mismatch_rejects_before_read(identity_memory):
    m = identity_memory
    invalid = (m['tables'][0] + 8, *m['tables'][1:])
    with pytest.raises(ValueError, match='layout changed'):
        people.bound_player(lambda *_: pytest.fail('Read for invalid layout'), m['base'], invalid,
                            canonical(m), binding(m))


def test_virtual_subject_and_non_table_cached_profile_reject(identity_memory):
    m = identity_memory
    primary, person = m['add_person']('virtual', 0, 77, 77)
    m['vec'](m['headers']['people'], [person])
    value = {'address': primary, 'identity': (77, 'Name', '', '2000-01-01', 77), 'tables': m['tables']}
    with pytest.raises(ValueError) as error:
        bound(m, value)
    assert not isinstance(error.value, people.StalePlayerReference)
    # Cached actual profiles have native PERSON index -1, not a canonical table slot.
    value = binding(m, 0x1000)
    m['put'](0x1390, struct.pack('<I', 0xFFFFFFFF))
    with pytest.raises(ValueError) as error:
        bound(m, value)
    assert not isinstance(error.value, people.StalePlayerReference)
