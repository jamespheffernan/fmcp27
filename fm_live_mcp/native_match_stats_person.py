"""Original typed match-statistics PERSON lookup and narrow actor fallback.

This identifies a resident owned original-slot actor. It establishes neither
historical/display-time participation nor current club membership/eligibility.
No native function, generated-name/profile cache or per-person API is invoked.
"""
import struct

# (address, shipped bytes) in one tuple, so the address book re-derives the bytes on a build
# whose getter is the same code up to address fields (the ADRP pages differ on 27.0.1)
GETTER_GUARD = (0x2E8C6D4, bytes.fromhex('e10300aa288c41b81f05003120050054294201d029bd46f9690200b4294540f92a2540a95f0109ebe0010054000080d2c802f837294201d029c146f9690200b42a4201f04a8153392a0200372aad46a96b010acb1f0d8beba2010054480d088b12000014fd7bbfa9fd030091a84401b0000545f9080040f9088140f9020080d200013fd6fd7bc1a8c0035fd6294540f9292940a94a0109ebc00000541f0d8aeb82000054280d088b000140f9c0035fd6000080d2c0035fd6'))
GETTER_RVA, GETTER_BYTES = GETTER_GUARD
IDENTITY_STATE = 'canonical_global_PERSON_via_owned_stats_native_getter'
ACTUAL_LABEL = b'N2db13ACTUAL_PLAYERE'


def _vector(read, address):
    from .active_match_people import _read
    if address < 4096 or address % 8:
        raise ValueError('Invalid native PERSON vector header')
    start, end = struct.unpack('<QQ', _read(read, address, 16))
    if start == end == 0:
        return 0, 0
    if (start < 4096 or start % 8 or end % 8 or not start <= end
            or end - start > 2000000 * 8):
        raise ValueError('Invalid bounded native PERSON vector')
    return start, (end - start) // 8


def resolve_stats_person(read, base, stats):
    """Translate the original getter's literal data-branch order read-only.

    FFFFFFFF returns null before the contextual guard. Other negative indices
    inspect that guard first. The unsupported virtual-service branch returns
    unavailable; its context is never fabricated. Source/type/read failures
    remain fatal. The caller separately checks canonical membership and actor.
    """
    from .active_match_people import _read, _type, _u64
    _type(read, base, stats, 0x55FA800, b'23GAME_MATCH_PLAYER_STATS')
    if _read(read, base + GETTER_RVA, len(GETTER_BYTES)) != GETTER_BYTES:
        raise ValueError('Original stats PERSON getter source changed')
    if _u64(read, base + 0x55FA810) != base + GETTER_RVA:
        raise ValueError('Original stats PERSON virtual getter changed')
    index = struct.unpack('<i', _read(read, stats + 0x18, 4))[0]
    if index == -1:
        return None
    guard = _u64(read, base + 0x56D2D78)
    if not guard:
        return None  # Original contextual virtual-service path is unsupported.
    if guard < 4096 or guard % 8:
        raise ValueError('Invalid native PERSON contextual guard')
    _, guard_count = _vector(read, _u64(read, guard + 0x88))
    if not guard_count:
        return None  # Same contextual virtual-service path, not a table lookup.
    if index < 0:
        return None
    table = _u64(read, base + 0x56D2D80)
    if not table:
        return None
    if table < 4096 or table % 8:
        raise ValueError('Invalid native PERSON table root')
    if not _read(read, base + 0x56D34E0, 1)[0] & 1:
        start, count = _vector(read, table + 0x68)
        if index < count:
            return _u64(read, start + index * 8) or None
    start, count = _vector(read, _u64(read, table + 0x88))
    return (_u64(read, start + index * 8) or None) if index < count else None


def add_global_identities(read, base, engine, result):
    """Extend only unmatched actual-PERSON rows; preserve the TEAM join.

    The original typed-statistics getter must return the owned actor's PERSON.
    UID equality is an additional consistency check, not assignment source proof.
    All reads stay in the caller's shared scope and final physical fence.
    """
    from . import active_match_people as people, database, players, world
    seen = {row['person']['native_identity']['database_index']
            for row in result['rows'] if row['person'] is not None}
    for row in result['rows']:
        if row['person'] is not None or row['identity_state'] != 'unmatched_canonical_roster_pointer':
            continue
        side_index, slot = row['side_index'], row['engine_array_index']
        side = people._u64(read, engine + 0x15370 + side_index * 8)
        actor = people._u64(read, side + 0x140 + slot * 8)
        people._type(read, base, actor, 0x569EE68, b'N7simatch12MATCH_PLAYERE')
        if people._u64(read, actor + 0x280) != engine or people._u64(read, actor + 0x288) != side:
            raise ValueError('Global PERSON actor engine/side changed')
        stats = people._u64(read, actor + 0x1880)
        if not stats:
            continue
        person = people._u64(read, actor + 0x20)
        if not person:
            continue
        table, index, native, secondary = struct.unpack('<QIII', people._read(read, person, 20))
        if table != base + players.RVA[2] or not 0 < native < 0xFFFFFFFF:
            continue
        if people._read(read, actor + 0x1E27, 1)[0] != slot:
            continue
        for rva, raw in people.ACTOR_SLOT_SPANS:
            if people._read(read, base + rva, len(raw)) != raw:
                raise ValueError('Global PERSON original actor-slot source changed')
        resolved = resolve_stats_person(read, base, stats)
        if resolved != person:
            continue
        people_table = database.table(read, base, 'people')
        if index >= people_table['count'] or people._u64(read, people_table['start'] + index * 8) != person:
            continue
        primary = person - 0x388
        people._type(read, base, primary, players.RVA[0], ACTUAL_LABEL)
        displacement, info = struct.unpack('<qQ', people._read(read, table - 16, 16))
        if displacement != -0x388 or info < 4096 or info % 8:
            raise ValueError('Global actual PERSON displacement changed')
        name_pointer = people._u64(read, info + 8)
        if people._read(read, name_pointer, len(ACTUAL_LABEL) + 1) != ACTUAL_LABEL + b'\0':
            raise ValueError('Global actual PERSON type changed')
        if struct.unpack('<I', people._read(read, stats + 0x18, 4))[0] != index:
            continue
        if struct.unpack('<I', people._read(read, actor + 0x48, 4))[0] != native:
            continue
        team = people._u64(read, side + 0xB8)
        world.typed(read, base, team, 'team')
        if primary in world.vector(read, team + 0x38, 256):
            raise ValueError('Established TEAM join and native PERSON fallback disagree')
        if index in seen:
            raise ValueError('Duplicate canonical PERSON across owned actor slots')
        first = players.name_part(read, people._u64(read, primary + 0x298))
        last = players.name_part(read, people._u64(read, primary + 0x2A0))
        common = players.common_name(read, people._u64(read, primary + 0x2A8))
        name = common or ' '.join(part for part in (first, last) if part) or None
        row.update(identity_state=IDENTITY_STATE,
                   person={'name': name, 'name_state': 'stored_direct' if name else 'unavailable',
                           'record_kind': 'actual', 'native_identity': {
                               'database_index': index, 'native_id': native,
                               'random_id': None if native == secondary else secondary}})
        seen.add(index)
    return result
