"""Canonical typed memory, frozen observed identities and malformed page controls."""
import struct

import pytest

from fm_live_mcp import players, shortlist_members as members, world
from test_database import database_memory
from test_players import memory
from test_world import world_memory


@pytest.fixture
def member_memory(database_memory):
    m = database_memory
    for rva, raw in members.NATIVE_SPANS:
        m['put'](m['base'] + rva, raw)

    def seed_type(kind):
        person_rva, fields = next((rva, f) for rva, f in members._PERSON_TYPES.items() if f[0] == kind)
        _, primary_rva, displacement, name = fields
        for rva, delta in ((primary_rva, 0), (person_rva, -displacement)):
            info = m['allocate'](16)
            # Deliberately unaligned RTTI string pointer.
            text = m['allocate'](len(name) + 2) + 1
            m['put'](text, name + b'\0')
            m['q'](info + 8, text)
            m['put'](m['base'] + rva - 16, struct.pack('<qQ', delta, info))
        if kind in ('actual', 'player_staff'):
            m['q'](m['base'] + person_rva + 0x668, m['base'] + 0xD5C5FC)
            m['put'](m['base'] + person_rva - 0x678, struct.pack('<q', -displacement))
        if kind == 'player_staff':
            for slot, adjustment in ((40, 0x150), (41, 0x158), (42, 0x160), (55, 0x1C8)):
                m['q'](m['base'] + players.RVA[2] + slot * 8, 0x8000 + slot * 8)
                m['q'](m['base'] + players.STAFF_RVA[2] + slot * 8, 0x8000 + slot * 8)
                m['put'](m['base'] + players.STAFF_RVA[2] - adjustment, struct.pack('<q', -0x110))
        return person_rva, fields

    seed_type('actual')
    template = m['read'](0x1000, players.SIZE)

    def add_person(kind='actual', index=0, primary_id=12345, secondary_id=12345, name='Test Müller'):
        person_rva, (_, primary_rva, person_offset, _) = seed_type(kind)
        primary = m['allocate'](max(person_offset + 20, 0x4A0))
        if kind == 'actual':
            m['put'](primary, template)
        elif kind == 'player_staff':
            raw = bytearray(0x4A0)
            raw[:0x278] = template[:0x278]
            raw[0x370:] = template[0x278:]
            m['put'](primary, raw)
            for off, rva in zip((0, 0x140, 0x480), players.STAFF_RVA):
                m['q'](primary + off, m['base'] + rva)
        m['q'](primary, m['base'] + primary_rva)
        person = primary + person_offset
        m['put'](person, struct.pack('<QIII', m['base'] + person_rva, index, primary_id, secondary_id))
        if kind in ('actual', 'player_staff'):
            delta = person_offset - 0x388
            handle = m['allocate'](8)
            m['q'](handle, m['text'](name))
            m['q'](primary + 0x298 + delta, handle)
            m['q'](primary + 0x2A0 + delta, 0)
            m['q'](primary + 0x2A8 + delta, 0)
        return primary, person

    def entry(person):
        address = m['allocate'](0x38)
        m['q'](address, person)
        return address

    listing = m['allocate'](0x108)
    m['vec'](listing + 0x80, [entry(0x1388)])
    m.update(listing=listing, seed_type=seed_type, add_person=add_person, entry=entry)
    return m


def page(m, total=1, offset=0, limit=50, read=None):
    return members.page(read or m['read'], m['base'], m['tables'], m['listing'], total, offset, limit)


def test_actual_binding_is_compatible_with_existing_player_identity(member_memory):
    m = member_memory
    rows = page(m)
    assert rows[0][0] == {'native_entry_index': 0, 'state': 'player', 'display_name': 'Test Müller',
                           'native_identity': {'database_index': 0, 'native_id': 12345, 'random_id': None},
                           'record_kind': 'actual'}
    _, binding = rows[0]
    decoded, identity = players.decode(m['read'], binding['address'], binding['tables'])
    assert binding == {'address': 0x1000, 'identity': identity, 'tables': m['tables'],
                       'world_bound': True, 'database_index': 0, 'record_kind': 'actual'}
    assert decoded['display_name'] == rows[0][0]['display_name']
    assert '0x' not in repr(rows[0][0])


@pytest.mark.parametrize('secondary,public', [(12345, None), (0, 0), (12346, 12346), (0xFFFFFFFF, 0xFFFFFFFF)])
def test_secondary_identity_is_independent(member_memory, secondary, public):
    m = member_memory
    m['put'](0x1398, struct.pack('<I', secondary))
    row, binding = page(m)[0]
    assert row['native_identity']['random_id'] == public
    assert binding['identity'][-1] == secondary


def test_combined_player_has_existing_prefixed_identity_and_canonical_binding(member_memory):
    m = member_memory
    primary, person = m['add_person']('player_staff', 0, 77, 0, 'Combined Player')
    m['vec'](m['headers']['people'], [person])
    m['vec'](m['listing'] + 0x80, [m['entry'](person)])
    row, binding = page(m)[0]
    assert row['record_kind'] == binding['record_kind'] == 'player_staff'
    assert row['native_identity'] == {'database_index': 0, 'native_id': 77, 'random_id': 0}
    assert row['display_name'] == 'Combined Player'
    assert binding['identity'] == ('player_staff', 77, 'Combined Player', '', '2000-02-29', 0)
    assert binding['address'] == primary


@pytest.mark.parametrize('kind', ['staff', 'human_manager', 'virtual'])
def test_known_other_canonical_subtypes_preserve_identity_without_profile_reads(member_memory, kind):
    m = member_memory
    primary, person = m['add_person'](kind, 0, 77, 0)
    m['vec'](m['headers']['people'], [person])
    m['vec'](m['listing'] + 0x80, [m['entry'](person)])
    reads = []

    def bounded(address, size):
        reads.append((address, size))
        return m['read'](address, size)

    row, binding = page(m, read=bounded)[0]
    assert row == {'native_entry_index': 0, 'state': 'unsupported_person_kind', 'display_name': None,
                   'native_identity': {'database_index': 0, 'native_id': 77, 'random_id': 0},
                   'record_kind': kind}
    assert binding is None
    assert all(not (primary <= a < person and n > 8) for a, n in reads)


def test_null_slots_duplicate_players_and_native_indices_are_preserved(member_memory):
    m = member_memory
    null_person = m['entry'](0)
    original = m['entry'](0x1388)
    m['vec'](m['listing'] + 0x80, [0, null_person, original, original, 0])
    rows = page(m, 5)
    assert [r['native_entry_index'] for r, _ in rows] == list(range(5))
    assert [r['state'] for r, _ in rows] == ['null_entry', 'null_person', 'player', 'player', 'null_entry']
    assert all(rows[i][1] is None for i in (0, 1, 4))
    assert rows[2][0]['native_identity'] == rows[3][0]['native_identity']
    assert rows[2][1] == rows[3][1]


def test_page_reads_only_requested_pointer_slice_and_payloads(member_memory):
    m = member_memory
    member = m['entry'](0x1388)
    invalid_unselected = 3
    m['vec'](m['listing'] + 0x80, [invalid_unselected, member, invalid_unselected])
    vector = struct.unpack('<Q', m['read'](m['listing'] + 0x80, 8))[0]
    reads = []

    def bounded(address, size):
        reads.append((address, size))
        if address == 3:
            pytest.fail('Read an unselected entry')
        return m['read'](address, size)

    rows = page(m, 3, 1, 1, bounded)
    assert len(rows) == 1 and rows[0][0]['native_entry_index'] == 1
    assert (vector + 8, 8) in reads
    assert not any(a == vector and n == 24 for a, n in reads)


@pytest.mark.parametrize('zero', [False, True])
def test_empty_and_beyond_end_pages_validate_geometry_without_member_reads(member_memory, zero):
    m = member_memory
    if zero:
        m['put'](m['listing'] + 0x80, bytes(24))
    else:
        m['vec'](m['listing'] + 0x80, [])
    assert page(m, 0, 0) == []
    assert page(m, 0, 999) == []
    m['vec'](m['listing'] + 0x80, [3])
    assert page(m, 1, 1) == []
    assert page(m, 1, 999) == []


@pytest.mark.parametrize('total,offset,limit', [(True, 0, 1), (-1, 0, 1), (100001, 0, 1),
                                               (1, True, 1), (1, -1, 1), (1, 0.0, 1),
                                               (1, 0, True), (1, 0, 0), (1, 0, 101)])
def test_strict_page_bounds(member_memory, total, offset, limit):
    with pytest.raises(ValueError, match='bounds'):
        page(member_memory, total, offset, limit)


@pytest.mark.parametrize('header', [(0, 0, 8), (0x10000, 0xFFFF, 0x10000),
                                     (0x10000, 0x10008, 0x10000), (0x10004, 0x10004, 0x10004),
                                     (0x10000, 0x10000, 0x10000 + 100001 * 8)])
def test_corrupt_geometry_rejects_even_beyond_end(member_memory, header):
    m = member_memory
    m['put'](m['listing'] + 0x80, struct.pack('<QQQ', *header))
    with pytest.raises(ValueError):
        page(m, 0, 999)


def test_total_mismatch_is_stale_source(member_memory):
    with pytest.raises(ValueError, match='count changed'):
        page(member_memory, 0)


@pytest.mark.parametrize('pointer', [1, 0x10004, (1 << 64) - 8])
def test_corrupt_entry_or_person_pointer_rejects(member_memory, pointer):
    m = member_memory
    m['vec'](m['listing'] + 0x80, [pointer])
    with pytest.raises(ValueError):
        page(m)
    m['vec'](m['listing'] + 0x80, [m['entry'](pointer)])
    with pytest.raises(ValueError):
        page(m)


@pytest.mark.parametrize('fault', ['canonical_slot', 'index', 'primary_id', 'person_type', 'primary_type',
                                  'displacement', 'cast_adjustment', 'cast_getter', 'rtti', 'unknown_type'])
def test_canonical_identity_type_and_cast_mismatches_reject(member_memory, fault):
    m = member_memory
    person_vt = m['base'] + players.RVA[2]
    if fault == 'canonical_slot': m['vec'](m['headers']['people'], [0x1390])
    if fault == 'index': m['put'](0x1390, struct.pack('<I', 1))
    if fault == 'primary_id': m['put'](0x1394, bytes(4))
    if fault == 'person_type': m['q'](0x1388, m['base'] + players.STAFF_RVA[2])
    if fault == 'primary_type': m['q'](0x1000, m['base'] + players.STAFF_RVA[0])
    if fault == 'displacement': m['put'](person_vt - 16, struct.pack('<q', -0x480))
    if fault == 'cast_adjustment': m['put'](person_vt - 0x678, struct.pack('<q', -0x480))
    if fault == 'cast_getter': m['q'](person_vt + 0x668, m['base'] + 0xCA49DC)
    if fault == 'rtti':
        info = struct.unpack('<Q', m['read'](person_vt - 8, 8))[0]
        text = struct.unpack('<Q', m['read'](info + 8, 8))[0]
        m['put'](text, b'X')
    if fault == 'unknown_type': m['q'](0x1388, m['base'] + 0x5500000)
    with pytest.raises(ValueError):
        page(m)


@pytest.mark.parametrize('fault', ['geometry', 'slice', 'entry_person', 'canonical_slot', 'identity'])
def test_late_consumed_changes_reject_before_rows_return(member_memory, fault):
    m = member_memory
    start = struct.unpack('<Q', m['read'](m['listing'] + 0x80, 8))[0]
    entry = struct.unpack('<Q', m['read'](start, 8))[0]
    table_start = struct.unpack('<Q', m['read'](m['headers']['people'], 8))[0]
    seen = 0

    def changing(address, size):
        nonlocal seen
        result = m['read'](address, size)
        if address == 0x1000 and size == players.SIZE:
            seen += 1
            if seen == 2:
                if fault == 'geometry': m['put'](m['listing'] + 0x80 + 8, struct.pack('<Q', start))
                if fault == 'slice': m['q'](start, 0)
                if fault == 'entry_person': m['q'](entry, 0)
                if fault == 'canonical_slot': m['q'](table_start, 0x1390)
                if fault == 'identity': m['put'](0x1398, struct.pack('<I', 54321))
        return result

    with pytest.raises(ValueError, match='changed'):
        page(m, read=changing)


def test_native_guard_mismatch_and_short_reads_reject(member_memory):
    m = member_memory
    rva, raw = members.NATIVE_SPANS[0]
    m['put'](m['base'] + rva, bytes([raw[0] ^ 1]))
    with pytest.raises(ValueError, match='native layout changed'):
        page(m)
    m['put'](m['base'] + rva, raw)
    with pytest.raises(ValueError, match='Incomplete'):
        page(m, read=lambda *_: b'')


# Frozen actual10 identity/name rows from batch18 live-membership.json. These are
# represented in synthetic typed memory here; the unit test is not a live scan.
ACTUAL_TEN = [
    (8162, 12080760, 'Salifou Diarrassouba'), (8520, 13230280, 'Alaeddine Zouhir'),
    (24726, 62175142, 'Đorđe Jovanović'), (39157, 2000056553, 'Javi Villar'),
    (8172, 12087972, 'Nicolas Jackson'), (13331, 28127164, 'Tyler Morton'),
    (31944, 86078360, 'Moisés Caicedo'), (16379, 37084591, 'Micky van de Ven'),
    (35009, 93070271, 'Viktor Gyökeres'), (60187, 2000381365, 'Ayyoub Bouaddi'),
]


def test_actual_ten_frozen_identity_order_and_all_bindings(member_memory):
    m = member_memory
    people = [0] * 60188
    entries = []
    for index, native_id, name in ACTUAL_TEN:
        _, person = m['add_person']('actual', index, native_id, native_id, name)
        people[index] = person
        entries.append(m['entry'](person))
    m['vec'](m['headers']['people'], people)
    m['vec'](m['listing'] + 0x80, entries)
    rows = page(m, 10)
    assert [r['display_name'] for r, _ in rows] == [v[2] for v in ACTUAL_TEN]
    assert [r['native_entry_index'] for r, _ in rows] == list(range(10))
    assert [r['native_identity'] for r, _ in rows] == [
        {'database_index': i, 'native_id': n, 'random_id': None} for i, n, _ in ACTUAL_TEN]
    assert all(binding['world_bound'] for _, binding in rows)
    assert [r for r, _ in page(m, 10, 3, 4)] == [r for r, _ in rows[3:7]]
