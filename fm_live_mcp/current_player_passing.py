"""Typed resident PLAYER passing counters, without a native clock association.

Caller owns the current fixture/incarnation, runtime/ReadSet and final epoch
checks. This module neither attaches nor publishes a host observation. Native
unsigned byte counters are observations, not cursor/halftime totals, appearances,
complete squad membership or evidence of current on-pitch participation.
"""
import struct

from . import active_match_people as people

# Native UI passes percentage selector; literal byte loads consume no clock.
# MATCH_PLAYER+1880 assignment, original-slot setup and canonical actor guards
# are independently pinned by ACTOR_SLOT_SPANS in the caller's same ReadSet.
SOURCE_SPANS = (
    (0x266644, bytes.fromhex('69888a5249afa9721f01096b2158005408e84239885a003409ec4239aa020014')),
)


def inspect(read, base, engine, *, expected_match_unique_id):
    """Read only BA/BB after same-side PERSON and concrete stats reconciliation.

    No native clock is accepted or derived. A null or mismatched source remains
    unavailable; stored0 is an actual unsigned byte0. No sum claims a side total.
    Caller must recheck every consumed byte after its last lifetime callback.
    """
    if type(expected_match_unique_id) is not int or not 0 < expected_match_unique_id < 1 << 64:
        raise ValueError('A checked nonzero official match unique ID is required')
    people._type(read, base, engine, 0x55FA258, b'10GAME_MATCH')
    if people._u64(read, engine + 0x20) != expected_match_unique_id:
        raise ValueError('PLAYER passing official match identity changed')
    for offset, raw in (*SOURCE_SPANS, *people.ACTOR_SLOT_SPANS):
        if people._read(read, base + offset, len(raw)) != raw:
            raise ValueError('PLAYER passing native source changed')
    actors = people.inspect_canonical(read, base, engine, identity_only=True)
    rows = []
    identities = set()
    for actor in actors['rows']:
        side_index, index = actor['side_index'], actor['engine_array_index']
        identity = actor['person']
        row = {'side_index': side_index, 'engine_array_index': index,
               'identity_state': actor['identity_state'], 'person': identity,
               'state': 'unavailable_identity', 'passes_attempted': None,
               'passes_completed': None, 'pass_completion_percentage_computed': None}
        if identity is not None:
            key = side_index, identity['native_identity']['database_index']
            if key in identities:
                raise ValueError('Duplicate canonical PLAYER passing identity')
            identities.add(key)
            side = people._u64(read, engine + 0x15370 + side_index * 8)
            player = people._u64(read, side + 0x140 + index * 8)
            people._type(read, base, player, 0x569EE68, b'N7simatch12MATCH_PLAYERE')
            if (people._u64(read, player + 0x280) != engine
                    or people._u64(read, player + 0x288) != side):
                raise ValueError('PLAYER passing owner changed')
            if people._read(read, player + 0x1E27, 1)[0] != index:
                raise ValueError('PLAYER passing original roster slot changed')
            stats = people._u64(read, player + 0x1880)
            row['state'] = 'unavailable_stats'
            if stats:
                people._type(read, base, stats, 0x55FA800, b'23GAME_MATCH_PLAYER_STATS')
                ordinal = struct.unpack('<I', people._read(read, stats + 0x18, 4))[0]
                row['state'] = 'unavailable_stats_person_mismatch'
                if ordinal == identity['native_identity']['database_index']:
                    attempted, completed = people._read(read, stats + 0xBA, 2)
                    if completed > attempted:
                        raise ValueError('PLAYER passing completed exceeds attempted')
                    row.update(state='available_native_counter_observation',
                               passes_attempted=attempted, passes_completed=completed,
                               pass_completion_percentage_computed=100 * completed / attempted if attempted else None)
        rows.append(row)
    available = sum(row['state'] == 'available_native_counter_observation' for row in rows)
    return {'state': 'available' if available == len(rows) else 'available_partial' if available else 'unavailable',
            'source': 'typed_owned_resident_GAME_MATCH_PLAYER_STATS',
            'official_match_unique_id': expected_match_unique_id,
            'rows': rows,
            'coverage': {'resident_slots': len(rows), 'available_counter_rows': available,
                         'unavailable_rows': len(rows) - available,
                         'complete_on_pitch_population_verified': False},
            'counter_units': 'unsigned native stored byte0..255',
            'native_timestamp_association': False,
            'displayed_time_verified': False,
            'counter_publication_fence_verified': False,
            'atomic_snapshot_verified': False,
            'participation_verified': False,
            'complete_side_total_verified': False,
            'scope': 'Resident counter bytes requiring caller recheck. No native tick, displayed minute, '
                     'halftime, completion, live-versus-replay or on-pitch claim.'}
