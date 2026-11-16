"""Private native PLAYER-linked promise inventory; lifecycle remains separate.

The caller binds the selected save/coach/roster and rechecks every consumed byte
AFTER its final lifetime/presentation callbacks. This module never calls game
functions, refreshes a promise or expands a player profile. A player's linked
vector is neither a complete manager promise population nor a list exclusively
made by, or exclusively concerning, that player.
"""
import hashlib
import struct

from . import assessment_people, database, players, world

SOURCE = (
    (0x24bfc18, 520, 'b061db146f069a41554081eee1ddb2d26849785616e48952fc4cf130288bd517'),
    (0xd5c5fc, 20, '62e50aff752959cc367e0ab72a4ea1286e80d2e70d5a58cc8796f16a3c89568d'),
    (0x24678b0, 1000, '1c0e0e549ea445b6f8a6401329b692fdc1d87b88dcbea2da4115cfa517c110cd'),
    (0x13342d8, 160, 'e38ff744ddc8dd1d2d14ea9aebb552c4c1d6d37e655bf76ba3bfec54615f30b2'),
)
RULE_NAME = b'38PLAYER_HAS_ACTIVE_PLAYING_TIME_PROMISE\0'
MAX_PROMISES = 256
SCOPE = (
    'Current original PLAYER-linked native promise vector, in physical order with repeated entries retained. '
    'The native PMgm and PMpp PERSON links are separate from the vector owner. Their party roles are not evaluated. '
    'Stored kind, category and linked scalar codes retain unknown meanings. Native endDT can be rewritten '
    'to a resolution date; it is not universally a deadline. Active/ongoing, completion, fulfilment, '
    'success/failure, overdue status, required targets and localized promise wording are not evaluated. '
    'The frontend Promiser display selects PMgm or PMpp based on the viewed PERSON; neither raw link is universally the promiser or subject. '
    'A roster is not the whole club; these vectors are not a complete manager-wide promise population. '
    'No game function, reference-count mutation, refresh, UI or profile generation occurs.'
)


def _pointer(value):
    if type(value) is not int or value < 4096 or value % 8 or value >= 1 << 64:
        raise ValueError('Invalid promise inventory pointer')
    return value


def _u64(read, address):
    return players.u64(read(address, 8))


def verify_native(read, base):
    _pointer(base)
    for rva, size, digest in SOURCE:
        if hashlib.sha256(read(base+rva, size)).hexdigest() != digest:
            raise ValueError(f'Native promise source changed at RVA {rva:#x}')
    if (_u64(read, base+0x55f1b18) != base+0x55ef7c8
            or _u64(read, base+0x55f1b30) != base+0x24bfc18
            or _u64(read, base+0x55ef7d0) != base+0x53bf95f
            or read(base+0x53bf95f, len(RULE_NAME)) != RULE_NAME):
        raise ValueError('Named native promise rule binding changed')
    assessment_people.verify_native(read, base)


def _identity(read, base, people, person):
    if not person:
        return None
    _pointer(person)
    _, _, public, _, _ = assessment_people._person(read, base, people, person)
    return public


def _date(raw, role):
    try:
        value = world.packed_date(raw)
    except ValueError:
        value = None
    packed = int.from_bytes(raw, 'little')
    return {'value': value, 'state': 'stored_native_date' if value else 'unavailable_native_date',
            'raw_hex': raw.hex(), 'stored_year': packed >> 16,
            'stored_day_of_year': packed & 511, 'unmapped_low_word_flags': packed & 0xfe00,
            'role': role}


def inspect(read, base, primary, kind, *, selected_view_person=None):
    """Read one actual PLAYER's exact linked vector; caller owns outer fences."""
    verify_native(read, base)
    if kind != 'actual':
        return {'state': 'unsupported_record_kind', 'owner': None, 'promises': None,
                'native_vector_entry_count': None, 'active_count': None,
                'complete_manager_population_verified': False, 'lifecycle_evaluated': False, 'scope': SCOPE}
    primary = _pointer(primary)
    if _u64(read, primary) != base+players.RVA[0]:
        raise ValueError('Promise inventory primary PLAYER type changed')
    people = database.table(read, base, 'people')
    owner_person = primary+0x388
    found, offset, owner, _, _ = assessment_people._person(read, base, people, owner_person)
    if found != primary or offset != 0x388 or owner['record_kind'] != 'actual':
        raise ValueError('Promise inventory canonical owner changed')
    selected = None
    if selected_view_person is not None:
        selected = _identity(read, base, people, _pointer(selected_view_person))
        if selected['record_kind'] != 'human_manager':
            raise ValueError('Selected promise view must be a canonical HUMAN manager')
    person_table = _pointer(_u64(read, owner_person))
    # Code pointers may be4-byte aligned; exact equality pins this real getter.
    if (_u64(read, person_table+0x668) != base+0xd5c5fc
            or struct.unpack('<q', read(person_table-0x678, 8))[0] != -0x388
            or struct.unpack('<q', read(base+players.RVA[0]-0x20, 8))[0] != 0x278):
        raise ValueError('Native promise PERSON/PLAYER owner route changed')
    normalized = primary+0x278
    if (_u64(read, normalized) != base+0x5589a90
            or struct.unpack('<q', read(base+0x5589a90-16, 8))[0] != -0x278):
        raise ValueError('Native promise normalized subobject changed')
    vector = _u64(read, normalized+0xa8)
    result = {'state': 'absent_native_vector' if not vector else 'observed_native_vector',
              'owner': owner, 'selected_view_person': selected, 'promises': [],
              'native_vector_entry_count': 0, 'active_count': None,
              'complete_manager_population_verified': False,
              'lifecycle_evaluated': False, 'scope': SCOPE}
    if not vector:
        return result
    vector = _pointer(vector)
    start, end, capacity = struct.unpack('<QQQ', read(vector, 24))
    if (any(value % 8 for value in (start, end, capacity))
            or not 0 <= start <= end <= capacity < 1 << 64
            or capacity-start > MAX_PROMISES*8
            or (start < 4096 and (start or end or capacity))):
        raise ValueError('Native promise vector geometry rejected')
    rows = []
    for ordinal, at in enumerate(range(start, end, 8)):
        promise = _pointer(_u64(read, at))
        raw = read(promise, 0x60)
        if len(raw) != 0x60:
            raise ValueError('Incomplete native promise record')
        reference_count = struct.unpack_from('<I', raw)[0]
        if not 0 < reference_count < 1 << 30:
            raise ValueError('Native promise reference lifetime rejected')
        party_A, party_B = struct.unpack_from('<QQ', raw, 0x18)
        rows.append({'entry_index': ordinal,
            'native_kind': struct.unpack_from('<h', raw, 0x4e)[0],
            'kind_name': None, 'kind_name_state': 'unmapped_native_kind',
            'native_party_A': _identity(read, base, people, party_A),
            'native_party_B': _identity(read, base, people, party_B),
            'party_A_matches_selected_view': None if selected_view_person is None else party_A == selected_view_person,
            'party_B_matches_vector_owner': party_B == owner_person,
            'party_A_matches_vector_owner': party_A == owner_person,
            'promiser': None, 'recipient': None, 'subject': None,
            'party_role_state': 'not_evaluated_context_dependent_native_links',
            'stored_start_date': _date(raw[0x38:0x3c], 'stored_start_date'),
            'stored_end_date': _date(raw[0x3c:0x40], 'stored_end_or_resolution_date'),
            'native_end_marker_flags': raw[0x53],
            'native_end_marker_bit0': bool(raw[0x53] & 1),
            'native_category_code': raw[0x56], 'native_category_name': None,
            'native_linked_scalar': struct.unpack_from('<i', raw, 0x44)[0],
            'linked_scalar_meaning': 'not_evaluated_for_this_kind',
            'active': None, 'ongoing': None, 'fulfilled': None, 'overdue': None,
            'lifecycle_state': 'not_evaluated'})
    result.update(state='observed_empty_native_vector' if not rows else 'observed_native_vector',
                  promises=rows, native_vector_entry_count=len(rows))
    return result
