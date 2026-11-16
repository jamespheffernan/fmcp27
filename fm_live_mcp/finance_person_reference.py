"""Bounded read-only native ID-pair lookup used by retained finance clauses.

Native1096BD0 may sort or remap. Those branches remain explicit unsupported
states; exact matches use its stable binary-search and identity predicates.
"""
import hashlib
import struct

from . import database, players, world


SOURCE = ((0x1096BD0, 448, 'ab0463b2159a3c7cb38826193520d947bc27d08997fafc82e775842dc4d89cdb'),)


def context(read, base):
    for rva, size, digest in SOURCE:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != digest:
            raise ValueError('Native finance PERSON-reference source changed')
    people = database.table(read, base, 'people')
    if not people['count']:
        return {'people': people, 'state': 'native_empty_person_header'}
    flag = read(people['root'] + 0x64, 1)[0]
    if not flag & 1:
        return {'people': people, 'start': people['start'], 'count': people['count'],
                'state': 'native_header_binary_search', 'native_table_flag': flag}
    sort = read(people['root'] + 0xA8, 1)[0]
    if sort == 1:
        return {'people': people, 'state': 'native_reference_sort_required',
                'native_table_flag': flag, 'native_shadow_sort_flag': sort}
    start, end, capacity = struct.unpack('<QQQ', read(people['root'] + 0x90, 24))
    if start == end == capacity == 0:
        count = 0
    else:
        if (start < 4096 or any(p % 8 for p in (start, end, capacity))
                or not start <= end <= capacity or capacity - start > 2000000 * 8):
            raise ValueError('Malformed native finance PERSON shadow index')
        count = (end - start) // 8
    return {'people': people, 'start': start, 'count': count, 'state': 'native_shadow_binary_search',
            'native_table_flag': flag, 'native_shadow_sort_flag': sort}


def lookup(read, context, native_id, secondary):
    """Return an exact native match, never a guessed index or absent-person claim."""
    if type(native_id) is not int or type(secondary) is not int or not 0 <= native_id <= 0xFFFFFFFF or not 0 <= secondary <= 0xFFFFFFFF:
        raise ValueError('Invalid native finance PERSON reference pair')
    if not 1 <= native_id <= 0x7FFFFFFF:
        return {'state': 'native_primary_reference_not_positive'}
    if context['state'] in ('native_reference_sort_required', 'native_empty_person_header'):
        return {'state': context['state']}
    low, high, probes = 0, context['count'] - 1, 0
    while low <= high:
        probes += 1
        if probes > 32:
            raise ValueError('Native finance PERSON lookup exceeded its bounded index')
        middle = (low + high) // 2
        person = world.pointer(read, context['start'] + middle * 8)
        raw = read(person, 20)
        current = struct.unpack_from('<i', raw, 12)[0]
        if current > native_id:
            high = middle - 1
        elif current < native_id:
            low = middle + 1
        else:
            native_secondary = struct.unpack_from('<I', raw, 16)[0]
            effective_secondary = native_secondary or native_id
            if secondary not in (0, effective_secondary):
                return {'state': 'native_reference_remap_not_evaluated' if secondary <= 0x7FFFFFFF else
                                 'native_reference_not_resolved', 'binary_search_probes': probes}
            return {'state': 'matched_native_reference', 'person_address': person,
                    'database_index': struct.unpack_from('<I', raw, 8)[0],
                    'native_id': native_id, 'secondary_id': native_secondary,
                    'binary_search_probes': probes, 'index_source': context['state']}
    return {'state': 'native_reference_remap_not_evaluated' if 1 <= secondary <= 0x7FFFFFFF else
                     'native_reference_not_resolved', 'binary_search_probes': probes}


def playing_identity(read, base, context, match):
    if match['state'] != 'matched_native_reference':
        return {'state': match['state']}
    person = match['person_address']
    table = world.pointer(read, person)
    if table == base + players.RVA[2]:
        offset, kind, expected = 0x388, 'player', b'N2db13ACTUAL_PLAYERE'
        primary_table = base + players.RVA[0]
    elif table == base + players.STAFF_RVA[2]:
        offset, kind, expected = 0x480, 'player_staff', b'N2db28ACTUAL_PLAYER_AND_NON_PLAYERE'
        primary_table = base + players.STAFF_RVA[0]
    else:
        return {'state': 'native_person_not_supported_playing_type'}
    for vtable, displacement in ((table, -offset), (primary_table, 0)):
        raw = read(vtable - 16, 16)
        if struct.unpack_from('<q', raw)[0] != displacement:
            raise ValueError('Finance bound PERSON displacement changed')
        info = players.u64(raw, 8)
        name = players.u64(read(info + 8, 8))
        if read(name, len(expected) + 1) != expected + b'\0':
            raise ValueError('Finance bound PERSON runtime type changed')
    primary = person - offset
    database.player_membership(read, base, context['people'], match['database_index'], primary)
    decoded, _ = players.decode(read, primary, tuple(base + rva for rva in players.RVA))
    identity = struct.unpack('<III', read(person + 8, 12))
    if identity != (match['database_index'], match['native_id'], match['secondary_id']):
        raise ValueError('Finance bound PERSON identity changed')
    return {'state': 'canonical_playing_person', 'name': decoded['name'], 'display_name': decoded['display_name'],
            'record_kind': kind, 'database_index': match['database_index'],
            'native_id': match['native_id'], 'secondary_id': match['secondary_id'],
            'binary_search_probes': match['binary_search_probes'], 'index_source': match['index_source']}
