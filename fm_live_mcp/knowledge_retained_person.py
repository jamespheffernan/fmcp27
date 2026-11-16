"""Private passive replay of the direct CLUB retained-PERSON projector.

This covers ordinary CLUBs and existing canonical PERSONs only. A retained
null is scoped to 15c18a4, never to the full 17bb4c0 selector: its cold, parent
CLUB and special HUMAN paths are not evaluated. No native function, allocator,
generated profile, TEAM alias, name or attribute getter is invoked.
"""
from copy import deepcopy
import hashlib
import struct

from . import assessment_people, database, players, world


SOURCE_LIMIT = 2_000_000  # Passive reader budget, not a native population limit.
NODE_LIMIT = 4096
NATIVE_GUARDS = (
    (0x17BB4C0, 0x808, 'ceaf44b1f88181479f71d0241766f2bc6f1acc530a73ccce5645a08101eb7878'),
    (0x15C18A4, 0x278, '0a979f02b341e88c5988157dbb5df5d397d4f4557f569b59fd1fe573753de0e6'),
    (0x15C1254, 0x100, '84586b709895e10c958a560e2c6524035d8c71f250a53968435daf0f484d03c5'),
    (0x15B6654, 0x68, 'e1d4e862c689024285f94f3fc10d78a84beff8cbb1bdbfd4b0e36902460771a3'),
    (0x15B66BC, 0x48, '216aefcd90604544aa5275275b150814eeb4dcfb66b67de8f0a2233a80976da7'),
    (0x1084CA4, 0x12C, 'b6823950094e48633de8533ebaf0cdd8d9d10ff0a110f74a98b9cfc41b009eac'),
    (0x10AAD10, 20, 'da715ff631e5f639ffda0bad4d79071eaff1d4a0eda4a2ac951adfccf1e85027'),
    (0xCA4A50, 8, 'd3c844a0173107453aa9896cdb7276470625501e7ff067cd764c7a160ece5ca3'),
    (0xCA4E8C, 20, 'c3719ee73c7556f633194a0644fe570347a4a5f1c09cedde41b5f62e753e4fbf'),
)


# Builds whose resolver (0x15C18A4 on the pinned build) drops a resolved PERSON for which the
# PERSON's virtual +0x510 returns true. 27.0.1 added this test after both the ordinal and the UID
# lookup (0x15CAC5C: ldr x8,[x0]; ldr x8,[x8,#0x510]; blr x8; tbnz w8,#0 -> null), and the same
# test inside the selector loop 0x17BBFC8 -> 0x17C64BC; the pinned build returns the PERSON as is.
HIDDEN_PERSON_PREDICATE_BUILDS = frozenset({
    '68adfde2e0588458c1830cb7e688855d9c61237973a7eb7a105af5ac4ed112a4',   # 27.0.1.2503222
})
_RETURNS_FALSE = (bytes.fromhex('00008052c0035fd6'), bytes.fromhex('000080d2c0035fd6'))   # mov w0|x0, #0; ret
_RETURNS_TRUE = bytes.fromhex('20008052c0035fd6')                                        # mov w0, #1; ret


def _pointer(value):
    return assessment_people._address(value)


def _native_hidden(read, base, person):
    """The 27.0.1 resolver's PERSON predicate (virtual +0x510), interpreted only where the method is
    a constant return; any other method is refused rather than guessed. False on the pinned build,
    whose resolver has no such test."""
    from . import address_book
    if address_book.ACTIVE.get('sha256') not in HIDDEN_PERSON_PREDICATE_BUILDS:
        return False
    table = _pointer(players.u64(read(person, 8)))
    method = players.u64(read(table + 0x510, 8))
    if not base <= method < base + (80 << 20):          # the plugin image (80 MiB bound)
        raise ValueError('Retained PERSON +0x510 predicate is outside the plugin')
    code = read(method, 8)
    if code in _RETURNS_FALSE:
        return False
    if code == _RETURNS_TRUE:
        return True
    raise ValueError('Retained PERSON +0x510 predicate is not a constant return; not modelled on this build')


def _optional_pointer(read, address):
    value = players.u64(read(address, 8))
    return _pointer(value) if value else 0


def _bounds(read, address, limit):
    start, end, capacity = struct.unpack('<QQQ', read(address, 24))
    if (start, end, capacity) == (0, 0, 0):
        return 0, 0
    _pointer(start)
    if (end >= 1 << 64 or capacity >= 1 << 64
            or any(value % 8 for value in (end, capacity))
            or not start <= end <= capacity or capacity - start > limit * 8):
        raise ValueError('Invalid retained PERSON vector geometry or reader budget')
    return start, (end - start) // 8


def verify_native(read, base):
    assessment_people._address(base, max(rva + size for rva, size, _ in NATIVE_GUARDS))
    for rva, size, digest in NATIVE_GUARDS:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != digest:
            raise ValueError(f'Retained PERSON native instructions changed at {rva:#x}')


def _owner(read, base, club, expected):
    _pointer(club)
    if (type(expected) is not tuple or len(expected) != 3
            or any(type(value) is not int or not 0 <= value < 1 << 32 for value in expected)
            or expected[1] == 0):
        raise ValueError('Invalid retained CLUB identity binding')
    clubs = database.table(read, base, 'clubs')
    world.typed(read, base, club, 'club')
    raw = read(club, 20)
    identity = struct.unpack('<III', raw[8:20])
    if identity != expected:
        raise ValueError('Retained CLUB identity changed')
    database.club_membership(read, base, clubs, identity[0], club)


def _result(state, reason, selector, context, **fields):
    return {'scope': 'direct_club_retained_projector', 'full_selector_evaluated': False,
            'state': state, 'reason': reason, 'selector': selector,
            'normalized_context': context, **fields}


def _null(reason, selector, context, **fields):
    return _result('native_retained_null', reason, selector, context, **fields)


def _canonical(read, base, people, person):
    primary, offset, public, native_id, secondary = assessment_people._person(
        read, base, people, person)
    return {'person_address': person, 'primary_address': primary, 'person_offset': offset,
            'record_kind': public['record_kind'],
            'identity': (public['native_identity']['database_index'], native_id, secondary)}


def _ordinal(read, base, people, identifier):
    if identifier < 0:
        return 0, 'negative_ordinal'
    root = people['root']
    if not read(base + 0x56D34E0, 1)[0] & 1:
        start, count = _bounds(read, root + 0x68, SOURCE_LIMIT)
        if identifier < count:
            # Native does not fall back when the primary slot itself is null.
            return _optional_pointer(read, start + identifier * 8), 'primary_ordinal'
    if identifier >= people['count']:
        return 0, 'canonical_ordinal_out_of_range'
    return _optional_pointer(read, people['start'] + identifier * 8), 'canonical_ordinal'


def _uid(read, base, people, identifier):
    if identifier == -1:
        return 0, 'minus_one_uid'
    if not people['count']:
        return 0, 'empty_canonical_uid_source'
    root = people['root']
    secondary = bool(read(root + 0x64, 1)[0] & 1)
    if secondary:
        start, count = _bounds(read, root + 0x90, SOURCE_LIMIT)
        local_sort = read(root + 0xA8, 1)[0] == 1
    else:
        start, count, local_sort = people['start'], people['count'], False
    entries = []
    seen = set()
    for index in range(count):
        person = world.pointer(read, start + index * 8)
        binding = _canonical(read, base, people, person)
        uid = struct.unpack('<i', struct.pack('<I', binding['identity'][1]))[0]
        if uid in seen:
            raise ValueError('Ambiguous retained PERSON UID ties')
        seen.add(uid)
        entries.append((uid, person))
    if local_sort:
        entries.sort()  # Exact signed comparator; never write native sort state.
    elif entries != sorted(entries):
        raise ValueError('Unsorted retained PERSON UID source without native sort branch')
    lo, hi = 0, len(entries) - 1
    while lo <= hi:
        middle = (lo + hi) // 2
        uid, person = entries[middle]
        if uid == identifier:
            return person, 'secondary_uid_local_sort' if local_sort else 'uid_binary_search'
        if uid > identifier:
            hi = middle - 1
        else:
            lo = middle + 1
    return 0, 'uid_not_found'


def _cast(read, base, binding):
    kind = binding['record_kind']
    if kind == 'virtual':
        return {'projection_state': 'unsupported_person_cast', 'non_player_address': None}
    person, primary = binding['person_address'], binding['primary_address']
    table = players.u64(read(person, 8))
    target = 0xCA4A50 if kind == 'actual' else 0xCA4E8C
    if players.u64(read(table + 0x6D0, 8)) != base + target:
        raise ValueError('Retained PERSON virtual6d0 route changed')
    if kind == 'actual':
        return {'projection_state': 'native_null', 'non_player_address': 0}
    delta = struct.unpack('<q', read(table - 0x6E0, 8))[0]
    expected = {'player_staff': -0x208, 'staff': -0x208, 'human_manager': -0x548}[kind]
    if delta != expected:
        raise ValueError('Retained PERSON virtual6d0 adjustment changed')
    projection = _pointer(person + delta)
    if kind == 'player_staff':
        # Combined's NON_PLAYER is a secondary base, not the full primary.
        if (projection != primary + 0x278
                or players.u64(read(projection, 8)) != base + 0x558F568):
            raise ValueError('Retained combined NON_PLAYER relation changed')
        displacement, info = struct.unpack('<qQ', read(base + 0x558F568 - 16, 16))
        if displacement != -0x278 or info != players.u64(read(base + 0x558EF38 - 8, 8)):
            raise ValueError('Retained combined NON_PLAYER type changed')
    elif projection != primary:
        raise ValueError('Retained NON_PLAYER primary relation changed')
    return {'projection_state': 'existing_non_player', 'non_player_address': projection}


def resolve(read, base, club, club_identity, selector, context, *, check_current):
    """Resolve an existing direct retained node and its typed warm6d0 projection.

    ``club_identity`` is the exact (canonical ordinal, native UID, raw secondary)
    tuple. ``context`` is a native byte, not an asserted TEAM identity. The caller
    must have separately proved this CLUB/context is the intended selector input
    and must supply a current process/save/build lifetime callback. Addresses and
    raw IDs in the result are private source bindings, never public references.
    """
    if not callable(check_current):
        raise ValueError('Retained PERSON needs a process/save/build lifetime check')
    if any(type(value) is not int or not 0 <= value <= 255 for value in (selector, context)):
        raise ValueError('Retained PERSON selector and context must be native bytes')
    before = deepcopy(check_current())
    if type(before) is not tuple or not before:
        raise ValueError('Invalid retained PERSON lifetime identity')
    snapshot = world.ReadSet(read)
    verify_native(snapshot, base)
    _owner(snapshot, base, club, club_identity)
    requires_team = (113 <= selector <= 115 or
                     (138 <= selector <= 190 and
                      bool((1 << (selector - 138)) & 0x001C00670CC7F0FF)))
    normalized = context if requires_team else 255
    result = _resolve(snapshot, base, club, selector, normalized, requires_team)
    snapshot.verify()
    if check_current() != before:
        raise ValueError('Retained PERSON process/save/build lifetime changed')
    snapshot.verify()
    return result


def _resolve(read, base, club, selector, context, requires_team):
    if selector == 0 or (requires_team and context == 255):
        return _null('selector_context_rejected', selector, context)
    if read(club + 0xBA, 1)[0] != 0:
        return _result('unproved_cold_selection', 'special_club_route', selector, context)
    auxiliary = world.pointer(read, club + 0xB0)
    container = _optional_pointer(read, auxiliary + 0x48)
    if not container:
        return _result('unproved_cold_selection', 'no_retained_container', selector, context)
    start, count = _bounds(read, container, NODE_LIMIT)
    for index in range(count):
        # Retained identifier rows are plain packed records with a32-bit
        # first word. They are not polymorphic8-byte-aligned PERSON objects.
        node = players.u64(read(start + index * 8, 8))
        if node < 4096 or node % 4 or node + 10 >= 1 << 64:
            raise ValueError('Invalid packed retained PERSON node pointer')
        raw = read(node, 10)
        if raw[4] != selector or raw[5] != context:
            continue
        identifier = struct.unpack_from('<i', raw)[0]
        people = database.table(read, base, 'people')
        person, route = (_ordinal(read, base, people, identifier) if raw[9] == 1
                         else _uid(read, base, people, identifier))
        if not person:
            return _null(route, selector, context, node_index=index)
        if _native_hidden(read, base, person):
            return _null(f'{route}_native_hidden_person', selector, context, node_index=index)
        binding = _canonical(read, base, people, person)
        if raw[9] == 1 and binding['identity'][0] != identifier:
            raise ValueError('Retained PERSON ordinal backlink changed')
        if raw[9] != 1 and binding['identity'][1] != identifier & 0xFFFFFFFF:
            raise ValueError('Retained PERSON UID changed')
        return _result('person', route, selector, context, node_index=index,
                       **binding, **_cast(read, base, binding))
    return _result('unproved_cold_selection', 'no_matching_retained_node', selector, context)
